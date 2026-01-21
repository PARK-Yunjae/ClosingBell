"""
스크리닝 서비스 v6.2

책임:
- 스크리닝 플로우 제어
- 유니버스 조회 → 데이터 수집 → 점수 계산 → 저장 → 알림
- 최소한의 하드필터 (데이터부족, 하락종목만 제외)
- 나머지 조건은 모두 점수로 반영 (소프트 필터)
- 글로벌 지표 필터 (나스닥/환율)

v6.2 변경사항:
- CCI 하드 필터 추가 (250 이상 TOP5 제외)
- 대기업 TOP5 별도 표시 (점수 가산 없음)

v6.0 변경사항:
- TOP5 결과를 closing_top5_history 테이블에도 저장
- 대시보드에서 20일 추적 데이터 표시 지원

v5.4 변경사항:
- K값 전략 제거
- 글로벌 지표 점수 조정 (나스닥/환율)
- 연속양봉 4일 이상 감점 강화
- CCI 150~170 최적 구간
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


# ============================================================
# v6.2 설정값
# ============================================================

# CCI 하드 필터: 이 값 이상이면 TOP5에서 제외
CCI_HARD_LIMIT = 250

# 시가총액 분류 기준 (라벨 표시용, 점수 가산 없음)
# (최소, 최대, 미사용, 라벨)
MARKET_CAP_TIERS = [
    (100000, float('inf'), 0, "mega"),    # 10조+
    (30000, 100000, 0, "large"),          # 3조~10조
    (10000, 30000, 0, "mid"),             # 1조~3조
    (3000, 10000, 0, "small"),            # 3천억~1조
    (0, 3000, 0, "micro"),                # 3천억 미만
]

# 대기업 기준 시가총액 (1조원 = 10000억)
LARGE_CAP_THRESHOLD = 10000


def get_market_cap_label(market_cap: float) -> str:
    """시가총액 라벨 반환 (점수 가산 없음)
    
    Returns:
        라벨 문자열 (mega/large/mid/small/micro/unknown)
    """
    if market_cap is None or market_cap <= 0:
        return "unknown"
    
    for min_cap, max_cap, _, label in MARKET_CAP_TIERS:
        if min_cap <= market_cap < max_cap:
            return label
    return "unknown"


def filter_by_cci(scores: list, limit: int = CCI_HARD_LIMIT) -> tuple:
    """CCI 과열 종목 필터링
    
    Returns:
        (filtered_scores, filtered_out_count)
    """
    filtered = []
    filtered_out = 0
    
    for s in scores:
        cci = s.score_detail.raw_cci
        if cci is not None and cci > limit:
            filtered_out += 1
            logger.debug(f"CCI 필터: {s.stock_name} CCI={cci:.0f} (>{limit})")
        else:
            filtered.append(s)
    
    if filtered_out > 0:
        logger.info(f"CCI 하드필터: {filtered_out}개 제외 (CCI > {limit})")
    
    return filtered, filtered_out


class ScreenerService:
    """스크리닝 서비스 v5.4 (글로벌 지표 필터 통합)"""
    
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
        
        logger.info("ScreenerService v5.4 초기화")
    
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
            # 0. 글로벌 지표 조회 (v5.4)
            global_adjustment = 0
            global_info = ""
            try:
                from src.data.index_monitor import get_global_indicators
                global_ind = get_global_indicators()
                global_adjustment = global_ind.get_score_adjustment()
                
                if global_ind.nasdaq_change is not None:
                    global_info = f"나스닥 {global_ind.nasdaq_change:+.1f}%({global_ind.nasdaq_trend})"
                    if global_ind.usdkrw_change is not None:
                        global_info += f" / 환율 {global_ind.usdkrw_change:+.1f}%({global_ind.fx_trend})"
                    
                    if global_adjustment != 0:
                        global_info += f" → 점수 {global_adjustment:+d}점"
                    
                    logger.info(f"글로벌 지표: {global_info}")
            except Exception as e:
                logger.warning(f"글로벌 지표 조회 실패: {e}")
            
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
            
            # 3-1. 글로벌 지표 점수 조정 (v5.4)
            if global_adjustment != 0:
                for score in scores:
                    score.score_total = min(100, score.score_total + global_adjustment)
                    # grade/sell_strategy는 score_total 기반 property로 자동 계산됨
                logger.info(f"글로벌 점수 조정: {global_adjustment:+d}점 적용")
            
            # ================================================
            # v6.2: CCI 하드 필터 적용
            # ================================================
            scores_filtered, cci_filtered_count = filter_by_cci(scores, CCI_HARD_LIMIT)
            
            # ================================================
            # v6.2: 시가총액 정보 로드 (점수 가산 없음, 대기업 표시용)
            # ================================================
            market_cap_info = self._load_market_cap_info(scores_filtered)
            
            # TOP5 선정 (필터링된 목록에서)
            top_n = self.calculator.select_top_n(scores_filtered, TOP_N_COUNT)
            
            # v6.2: 대기업 TOP5 별도 추출
            large_cap_top5 = [s for s in scores_filtered 
                            if getattr(s, '_market_cap', 0) >= LARGE_CAP_THRESHOLD][:TOP_N_COUNT]
            
            execution_time = time.time() - start_time
            
            result = {
                "screen_date": screen_date,
                "screen_time": screen_time,
                "total_count": len(scores),
                "filtered_count": len(scores_filtered),  # v6.2
                "cci_filtered_out": cci_filtered_count,  # v6.2
                "top_n": top_n,
                "large_cap_top5": large_cap_top5,  # v6.2: 대기업 TOP5
                "all_scores": scores_filtered,  # 필터링된 목록
                "execution_time_sec": execution_time,
                "status": "SUCCESS",
                "is_preview": is_preview,
                "error_message": None,
                "global_info": global_info,  # v5.4
                "market_cap_info": market_cap_info,  # v6.2
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
    
    def _load_market_cap_info(self, scores: list) -> dict:
        """v6.2: 시가총액 정보 로드 (점수 가산 없음, 대기업 표시용)
        
        Returns:
            통계 정보 dict
        """
        stats = {"mega": 0, "large": 0, "mid": 0, "small": 0, "micro": 0, "unknown": 0}
        
        try:
            import sqlite3
            
            db_path = os.path.join(os.path.dirname(__file__), '../../data/screener.db')
            if not os.path.exists(db_path):
                db_path = 'data/screener.db'
            
            market_caps = {}
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT stock_code, market_cap FROM nomad_candidates WHERE market_cap > 0")
                for code, cap in cursor.fetchall():
                    market_caps[code] = cap
                conn.close()
            except Exception as e:
                logger.warning(f"시가총액 DB 조회 실패: {e}")
            
            # 시가총액 정보만 저장 (점수 가산 없음)
            for score in scores:
                market_cap = market_caps.get(score.stock_code, 0)
                label = get_market_cap_label(market_cap)
                
                # 시가총액 정보 저장 (대기업 필터용)
                score._market_cap = market_cap
                score._market_cap_label = label
                stats[label] += 1
            
            logger.info(f"시가총액 정보 로드: {stats}")
            return stats
            
        except Exception as e:
            logger.warning(f"시가총액 정보 로드 실패: {e}")
            return stats
    
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
        """DB 저장 (기존 테이블 + v6.0 TOP5 테이블)"""
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
            
            # ================================================
            # v6.0: closing_top5_history 테이블에도 저장
            # ================================================
            self._save_top5_history(result)
            
        except Exception as e:
            logger.error(f"DB 저장 실패: {e}")
    
    def _save_top5_history(self, result: Dict):
        """v6.0: TOP5를 closing_top5_history에 저장"""
        try:
            from src.infrastructure.repository import get_top5_history_repository
            
            top5_repo = get_top5_history_repository()
            top_n = result.get("top_n", [])
            screen_date = result["screen_date"]
            
            if not top_n:
                logger.info("TOP5 비어있음 - 저장 스킵")
                return
            
            for score in top_n:
                d = score.score_detail
                
                history_data = {
                    'screen_date': screen_date.isoformat(),
                    'rank': score.rank,
                    'stock_code': score.stock_code,
                    'stock_name': score.stock_name,
                    'screen_price': score.current_price,
                    'screen_score': score.score_total,
                    'grade': score.grade.value,
                    'cci': d.raw_cci,
                    'rsi': getattr(d, 'raw_rsi', None),
                    'change_rate': score.change_rate,
                    'disparity_20': d.raw_distance,
                    'consecutive_up': d.raw_consec_days,
                    'volume_ratio_5': d.raw_volume_ratio,
                    'data_source': 'realtime',
                }
                
                history_id = top5_repo.upsert(history_data)
                logger.debug(f"TOP5 저장: #{score.rank} {score.stock_name} (id={history_id})")
            
            logger.info(f"v6.0 TOP5 저장 완료: {len(top_n)}개")
            
        except Exception as e:
            logger.error(f"v6.0 TOP5 저장 실패: {e}")
    
    def _send_alert(self, result: Dict, is_preview: bool):
        """알림 발송 (종가매매 TOP5) v6.2"""
        try:
            top_n = result["top_n"]
            cci_filtered = result.get("cci_filtered_out", 0)
            large_cap_top5 = result.get("large_cap_top5", [])
            
            # 종가매매 TOP5 발송
            if not top_n:
                self.discord_notifier.send_message("📊 종가매매: 적합한 종목 없음")
            else:
                # v6.2: 필터링 정보 추가
                title = "[프리뷰] 종가매매 TOP5" if is_preview else "🔔 종가매매 TOP5"
                if cci_filtered > 0:
                    title += f" (CCI과열 {cci_filtered}개 제외)"
                
                embed = format_discord_embed(top_n, title=title)
                
                success = self.discord_notifier.send_embed(embed)
                if success:
                    logger.info("종가매매 Discord 발송 완료")
                else:
                    logger.warning("종가매매 Discord 발송 실패")
                
                # v6.2: 대기업 TOP5 별도 발송 (있는 경우)
                if large_cap_top5 and not is_preview:
                    self._send_large_cap_alert(large_cap_top5)
                
        except Exception as e:
            logger.error(f"알림 에러: {e}")
    
    def _send_large_cap_alert(self, large_cap_stocks: list):
        """v6.2: 대기업 TOP5 별도 알림"""
        try:
            if not large_cap_stocks:
                return
            
            # 간단한 텍스트 형식으로 발송
            lines = ["🏢 **대기업 TOP5** (시총 1조+)\n"]
            for i, s in enumerate(large_cap_stocks[:5], 1):
                market_cap = getattr(s, '_market_cap', 0)
                cap_str = f"{market_cap/10000:.1f}조" if market_cap >= 10000 else f"{market_cap:.0f}억"
                lines.append(f"#{i} {s.stock_name} | {s.score_total:.1f}점 | 시총 {cap_str}")
            
            self.discord_notifier.send_message("\n".join(lines))
            logger.info("대기업 TOP5 알림 발송 완료")
            
        except Exception as e:
            logger.warning(f"대기업 알림 실패: {e}")
                
        except Exception as e:
            logger.error(f"알림 에러: {e}")
    
    def _print_results(self, top_n: List[StockScoreV5]):
        """콘솔 출력 v6.2"""
        print("\n" + "=" * 60)
        print("🔔 종가매매 TOP5 (v6.2)")
        print("=" * 60)
        
        if not top_n:
            print("적합한 종목 없음")
            return
        
        for s in top_n:
            d = s.score_detail
            st = s.sell_strategy
            grade_emoji = {"S": "🏆", "A": "🥇", "B": "🥈", "C": "🥉", "D": "⚠️"}
            
            # v6.2: 시가총액 정보 추가
            market_cap = getattr(s, '_market_cap', 0)
            cap_str = ""
            if market_cap > 0:
                if market_cap >= 10000:
                    cap_str = f" | 시총 {market_cap/10000:.1f}조"
                else:
                    cap_str = f" | 시총 {market_cap:.0f}억"
            
            print(f"\n#{s.rank} {s.stock_name} ({s.stock_code}){cap_str}")
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
