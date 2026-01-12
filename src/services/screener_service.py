"""
스크리닝 서비스 v5.1

책임:
- 스크리닝 플로우 제어
- 유니버스 조회 → 데이터 수집 → 점수 계산 → 저장 → 알림
- 최소한의 하드필터 (데이터부족, 하락종목만 제외)
- 나머지 조건은 모두 점수로 반영 (소프트 필터)
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
    """스크리닝 서비스 v5.1"""
    
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
        
        logger.info("ScreenerService v5.1 초기화")
    
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
        """알림 발송"""
        try:
            top_n = result["top_n"]
            
            if not top_n:
                self.discord_notifier.send_message("📊 종가매매: 적합한 종목 없음")
                return
            
            title = "[프리뷰] 종가매매 TOP5" if is_preview else "🔔 종가매매 TOP5"
            embed = format_discord_embed(top_n, title=title)
            
            success = self.discord_notifier.send_embed(embed)
            if success:
                logger.info("Discord 발송 완료")
            else:
                logger.warning("Discord 발송 실패")
        except Exception as e:
            logger.error(f"알림 에러: {e}")
    
    def _print_results(self, top_n: List[StockScoreV5]):
        """콘솔 출력"""
        print("\n" + "=" * 60)
        print("🔔 종가매매 TOP5 (v5.1)")
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
