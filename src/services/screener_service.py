"""
스크리닝 서비스 v5.3

책임:
- 스크리닝 플로우 제어
- 유니버스 조회 → 데이터 수집 → 점수 계산 → 저장 → 알림
- 최소한의 하드필터 (데이터부족, 하락종목만 제외)
- 나머지 조건은 모두 점수로 반영 (소프트 필터)
- K값 돌파 시그널 통합 (v5.3)
"""

import os
import time
import logging
from datetime import date
from typing import List, Optional, Dict

from src.config.settings import settings
from src.config.constants import TOP_N_COUNT, MIN_DAILY_DATA_COUNT
from src.utils.stock_filters import filter_universe_stocks
from src.domain.models import StockData, ScreeningResult, ScreeningStatus
from src.domain.score_calculator import (
    ScoreCalculatorV5,
    StockScoreV5,
    format_discord_embed,
)
from src.adapters.kis_client import get_kis_client, KISClient
from src.adapters.discord_notifier import get_discord_notifier, DiscordNotifier
from src.infrastructure.repository import (
    get_screening_repository,
    ScreeningRepository,
)
from src.infrastructure.database import init_database

logger = logging.getLogger(__name__)


class ScreenerService:
    """스크리닝 서비스 v5.3 (종가매매 + K값 돌파)"""
    
    def __init__(
        self,
        kis_client: Optional[KISClient] = None,
        discord_notifier: Optional[DiscordNotifier] = None,
        screening_repo: Optional[ScreeningRepository] = None,
    ):
        self.kis_client = kis_client or get_kis_client()
        self.discord_notifier = discord_notifier or get_discord_notifier()
        self.screening_repo = screening_repo or get_screening_repository()
        self.calculator = ScoreCalculatorV5()
        
        logger.info("ScreenerService v5.3 초기화")
    
    def run_screening(
        self,
        screen_time: str = "15:00",
        save_to_db: bool = True,
        send_alert: bool = True,
        is_preview: bool = False,
    ) -> Dict:
        """스크리닝 실행"""
        start_time = time.time()
        screen_date = date.today()
        
        logger.info(f"스크리닝 시작: {screen_date} {screen_time}")
        
        try:
            # 1. 유니버스 조회
            stocks = self._get_universe()
            if not stocks:
                return self._empty_result(screen_date, screen_time, start_time, 
                                         is_preview, "유니버스 비어있음")
            
            logger.info(f"유니버스: {len(stocks)}개")
            
            # 2. 데이터 수집 (최소 하드필터만)
            stock_data_list = self._collect_data(stocks)
            if not stock_data_list:
                return self._empty_result(screen_date, screen_time, start_time,
                                         is_preview, "수집된 종목 없음")
            
            logger.info(f"데이터 수집: {len(stock_data_list)}개")
            
            # 3. 점수 계산
            scores = self.calculator.calculate_scores(stock_data_list)
            top_n = self.calculator.select_top_n(scores, TOP_N_COUNT)
            
            execution_time = time.time() - start_time
            
            result = {
                "screen_date": screen_date,
                "screen_time": screen_time,
                "total_count": len(scores),
                "top_n": top_n,
                "all_scores": scores,
                "execution_time_sec": execution_time,
                "status": "SUCCESS",
                "is_preview": is_preview,
                "error_message": None,
            }
            
            # 4. DB 저장
            if save_to_db and not is_preview:
                self._save_result(result)
            
            # 5. 알림 발송
            if send_alert:
                self._send_alert(result, is_preview)
            
            # 6. 콘솔 출력
            self._print_results(top_n)
            
            logger.info(f"스크리닝 완료: {execution_time:.1f}초")
            return result
            
        except Exception as e:
            logger.error(f"스크리닝 에러: {e}")
            import traceback
            traceback.print_exc()
            
            if send_alert:
                try:
                    self.discord_notifier.send_error_alert(e, "스크리닝 에러")
                except:
                    pass
            
            return self._empty_result(screen_date, screen_time, start_time,
                                     is_preview, str(e))
    
    def _get_universe(self) -> List:
        """유니버스 조회"""
        condition_name = os.getenv("CONDITION_NAME", "TV200")
        min_candidates = int(os.getenv("MIN_CANDIDATES", "30"))
        
        stocks = []
        
        try:
            # 조건검색
            stocks_raw = self.kis_client.get_condition_universe(
                condition_name=condition_name,
                limit=500,
            )
            
            if stocks_raw:
                stocks, _ = filter_universe_stocks(stocks_raw, log_details=True)
                logger.info(f"조건검색 결과: {len(stocks)}개")
        except Exception as e:
            logger.error(f"조건검색 실패: {e}")
        
        # Fallback
        if len(stocks) < min_candidates:
            logger.warning(f"종목 부족 ({len(stocks)}개), fallback 실행")
            try:
                fallback = self.kis_client.get_top_trading_value_stocks(
                    min_trading_value=settings.screening.min_trading_value,
                    limit=200,
                )
                if fallback:
                    filtered, _ = filter_universe_stocks(fallback, log_details=True)
                    existing = {s.code for s in stocks}
                    for s in filtered:
                        if s.code not in existing:
                            stocks.append(s)
                    logger.info(f"Fallback 후: {len(stocks)}개")
            except Exception as e:
                logger.error(f"Fallback 실패: {e}")
        
        return stocks
    
    def _collect_data(self, stocks: List) -> List[StockData]:
        """데이터 수집 (최소 하드필터)"""
        stock_data_list = []
        
        for i, stock in enumerate(stocks):
            try:
                daily_prices = self.kis_client.get_daily_prices(
                    stock.code,
                    count=MIN_DAILY_DATA_COUNT + 10,
                )
                
                if len(daily_prices) < MIN_DAILY_DATA_COUNT:
                    continue
                
                today = daily_prices[-1]
                yesterday = daily_prices[-2]
                change_rate = ((today.close - yesterday.close) / yesterday.close) * 100
                
                # 하락종목 제외 (종가매매는 상승종목 대상)
                if change_rate < 0:
                    continue
                
                # 거래대금 계산 (여러 소스에서 시도)
                trading_value = 0.0
                
                # 1차: 일봉 데이터에서
                if today.trading_value > 0:
                    trading_value = today.trading_value / 100_000_000
                
                # 2차: 현재가 API에서
                if trading_value <= 0:
                    try:
                        current_data = self.kis_client.get_current_price(stock.code)
                        if current_data and current_data.trading_value > 0:
                            trading_value = current_data.trading_value / 100_000_000
                    except Exception as e:
                        logger.debug(f"현재가 조회 실패: {stock.code} - {e}")
                
                # 3차: 조건검색 결과에서
                if trading_value <= 0 and hasattr(stock, 'trading_value') and stock.trading_value > 0:
                    trading_value = stock.trading_value
                
                # 4차: 거래량 × 종가로 추정
                if trading_value <= 0 and today.volume > 0:
                    trading_value = (today.volume * today.close) / 100_000_000
                
                stock_data = StockData(
                    code=stock.code,
                    name=stock.name,
                    daily_prices=daily_prices,
                    current_price=today.close,
                    trading_value=trading_value,
                )
                stock_data_list.append(stock_data)
                
                if (i + 1) % 20 == 0:
                    logger.info(f"진행: {i + 1}/{len(stocks)}")
                    
            except Exception as e:
                logger.debug(f"수집 실패: {stock.code} - {e}")
        
        return stock_data_list
    
    def _empty_result(self, screen_date, screen_time, start_time, 
                      is_preview, error_msg) -> Dict:
        """빈 결과"""
        return {
            "screen_date": screen_date,
            "screen_time": screen_time,
            "total_count": 0,
            "top_n": [],
            "all_scores": [],
            "execution_time_sec": time.time() - start_time,
            "status": "FAILED",
            "is_preview": is_preview,
            "error_message": error_msg,
        }
    
    def _save_result(self, result: Dict):
        """DB 저장"""
        try:
            from src.domain.models import StockScore, ScoreDetail
            
            # v5 → 레거시 변환
            legacy_scores = []
            for s in result["all_scores"]:
                d = s.score_detail
                legacy = StockScore(
                    stock_code=s.stock_code,
                    stock_name=s.stock_name,
                    current_price=s.current_price,
                    change_rate=s.change_rate,
                    trading_value=s.trading_value,
                    score_detail=ScoreDetail(
                        cci_value=d.cci_score / 1.5,
                        cci_slope=d.distance_score / 1.5,
                        ma20_slope=d.ma20_3day_bonus * 3.33,
                        candle=d.candle_score / 1.5,
                        change=d.change_score / 1.5,
                        raw_cci=d.raw_cci,
                        raw_ma20=d.raw_ma20,
                    ),
                    score_total=s.score_total,
                    rank=s.rank,
                )
                legacy_scores.append(legacy)
            
            legacy_result = ScreeningResult(
                screen_date=result["screen_date"],
                screen_time=result["screen_time"],
                total_count=result["total_count"],
                top3=legacy_scores[:5],
                all_items=legacy_scores,
                execution_time_sec=result["execution_time_sec"],
                status=ScreeningStatus.SUCCESS,
            )
            
            screening_id = self.screening_repo.save_screening(legacy_result)
            logger.info(f"DB 저장: ID={screening_id}")
        except Exception as e:
            logger.error(f"DB 저장 실패: {e}")
    
    def _send_alert(self, result: Dict, is_preview: bool):
        """알림 발송 (종가매매 + K값 돌파)"""
        try:
            top_n = result["top_n"]
            
            # 1. 종가매매 TOP5 발송
            if not top_n:
                self.discord_notifier.send_message("📊 종가매매: 적합한 종목 없음")
            else:
                title = "[프리뷰] 종가매매 TOP5" if is_preview else "🔔 종가매매 TOP5"
                embed = format_discord_embed(top_n, title=title)
                
                success = self.discord_notifier.send_embed(embed)
                if success:
                    logger.info("종가매매 Discord 발송 완료")
                else:
                    logger.warning("종가매매 Discord 발송 실패")
            
            # 2. K값 돌파 TOP3 발송
            try:
                k_signals = self._get_k_signals(result.get("all_scores", []))
                
                if k_signals:
                    from src.domain.k_breakout import format_k_signal_embed
                    
                    k_title = "[프리뷰] K값 돌파 TOP3" if is_preview else "🚀 K값 돌파 TOP3"
                    k_embed = format_k_signal_embed(k_signals[:3], title=k_title)
                    
                    k_success = self.discord_notifier.send_embed(k_embed)
                    if k_success:
                        logger.info(f"K값 돌파 Discord 발송 완료 ({len(k_signals)}개)")
                    else:
                        logger.warning("K값 돌파 Discord 발송 실패")
                else:
                    logger.info("K값 돌파 시그널 없음")
                    
            except Exception as e:
                logger.warning(f"K값 돌파 알림 에러: {e}")
                
        except Exception as e:
            logger.error(f"알림 에러: {e}")
    
    def _get_k_signals(self, all_scores: List) -> List:
        """K값 돌파 시그널 조회 및 DB 저장"""
        try:
            from src.domain.k_breakout import KBreakoutStrategy, KBreakoutConfig
            from src.infrastructure.repository import get_k_signal_repository
            
            config = KBreakoutConfig(
                k=0.3,
                stop_loss_pct=-2.0,
                take_profit_pct=5.0,
                min_trading_value=200.0,
                min_volume_ratio=2.0,
                max_signals=5,
            )
            strategy = KBreakoutStrategy(config)
            
            # 지수 데이터 조회 시도
            try:
                index_data = self.kis_client.get_index_price("0001")
                if index_data:
                    strategy.set_index_data(
                        index_change=getattr(index_data, 'change_rate', 0),
                        index_close=getattr(index_data, 'close', 0),
                        index_ma5=getattr(index_data, 'ma5', 0),
                        index_ma20=getattr(index_data, 'ma20', 0),
                    )
            except Exception as e:
                logger.debug(f"K값 지수 조회 실패: {e}")
                strategy.config.require_index_above_ma5 = False
            
            # 스크리닝된 종목들에서 K값 시그널 체크
            signals = []
            
            for score in all_scores:
                try:
                    # StockScoreV5에서 데이터 추출
                    stock_code = score.stock_code
                    stock_name = score.stock_name
                    
                    # 일봉 데이터 재조회 (open, high, low 필요)
                    daily_prices = self.kis_client.get_daily_prices(stock_code, count=25)
                    
                    if len(daily_prices) < 2:
                        continue
                    
                    signal = strategy.scan_from_daily_prices(
                        stock_code=stock_code,
                        stock_name=stock_name,
                        daily_prices=daily_prices,
                        current_price=score.current_price,
                    )
                    
                    if signal:
                        # ClosingBell 점수 추가
                        signal.score = max(signal.score, score.score_total)
                        signals.append(signal)
                        
                except Exception as e:
                    logger.debug(f"K값 체크 실패 {score.stock_code}: {e}")
                    continue
            
            # 점수순 정렬
            signals.sort(key=lambda x: x.score, reverse=True)
            signals = signals[:5]
            
            # DB 저장
            if signals:
                try:
                    k_repo = get_k_signal_repository()
                    signal_dicts = []
                    
                    for i, sig in enumerate(signals):
                        sig_dict = {
                            'stock_code': sig.stock_code,
                            'stock_name': sig.stock_name,
                            'signal_date': sig.signal_date,
                            'signal_time': sig.signal_time,
                            'current_price': sig.current_price,
                            'open_price': sig.open_price,
                            'breakout_price': sig.breakout_price,
                            'prev_high': sig.prev_high,
                            'prev_low': sig.prev_low,
                            'prev_close': sig.prev_close,
                            'k_value': sig.k_value,
                            'range_value': sig.range_value,
                            'prev_change_pct': sig.prev_change_pct,
                            'volume_ratio': sig.volume_ratio,
                            'trading_value': sig.trading_value,
                            'stop_loss_pct': sig.stop_loss_pct,
                            'take_profit_pct': sig.take_profit_pct,
                            'stop_loss_price': sig.stop_loss_price,
                            'take_profit_price': sig.take_profit_price,
                            'index_change': sig.index_change,
                            'index_above_ma5': sig.index_above_ma5,
                            'score': sig.score,
                            'confidence': sig.confidence,
                            'rank': i + 1,
                        }
                        signal_dicts.append(sig_dict)
                    
                    k_repo.save_signals(signal_dicts)
                    logger.info(f"K값 시그널 {len(signal_dicts)}개 DB 저장 완료")
                    
                except Exception as e:
                    logger.warning(f"K값 시그널 DB 저장 실패: {e}")
            
            return signals[:5]
            
        except Exception as e:
            logger.error(f"K값 시그널 조회 에러: {e}")
            return []
    
    def _print_results(self, top_n: List[StockScoreV5]):
        """콘솔 출력"""
        print("\n" + "=" * 60)
        print("🔔 종가매매 TOP5 (v5.3)")
        print("=" * 60)
        
        if not top_n:
            print("적합한 종목 없음")
            return
        
        for s in top_n:
            d = s.score_detail
            st = s.sell_strategy
            grade_emoji = {"S": "🏆", "A": "🥇", "B": "🥈", "C": "🥉", "D": "⚠️"}
            
            print(f"\n#{s.rank} {s.stock_name} ({s.stock_code})")
            print(f"   {s.score_total:.1f}점 {grade_emoji[s.grade.value]}{s.grade.value}")
            print(f"   현재가: {s.current_price:,}원 ({s.change_rate:+.1f}%)")
            print(f"   CCI: {d.raw_cci:.0f} | 이격도: {d.raw_distance:.1f}%")
            print(f"   거래량: {d.raw_volume_ratio:.1f}배 | 연속: {d.raw_consec_days}일")
            print(f"   매도: 시초 {st.open_sell_ratio}% / 목표 +{st.target_profit}%")
        
        print("\n" + "=" * 60)


# 편의 함수
def run_screening(
    screen_time: str = "15:00",
    save_to_db: bool = True,
    send_alert: bool = True,
    is_preview: bool = False,
) -> Dict:
    """스크리닝 실행"""
    service = ScreenerService()
    return service.run_screening(screen_time, save_to_db, send_alert, is_preview)


def run_main_screening() -> Dict:
    """15:00 메인 스크리닝"""
    return run_screening(
        screen_time="15:00",
        save_to_db=True,
        send_alert=True,
        is_preview=False,
    )


def run_preview_screening() -> Dict:
    """12:30 프리뷰 스크리닝"""
    return run_screening(
        screen_time="12:30",
        save_to_db=False,
        send_alert=True,
        is_preview=True,
    )


if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )
    
    try:
        init_database()
    except:
        pass
    
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"
    
    if mode == "main":
        result = run_main_screening()
    elif mode == "preview":
        result = run_preview_screening()
    else:
        result = run_screening(save_to_db=False, send_alert=False)
    
    print(f"\n상태: {result['status']}")
    print(f"분석: {result['total_count']}개")
    print(f"시간: {result['execution_time_sec']:.1f}초")
