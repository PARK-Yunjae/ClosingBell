"""
스크리닝 오케스트레이션 서비스 v5.0

🎯 핵심 변경사항:
- 하드 필터 최소화 (TV200 조건검색이 1차 필터)
- 점수제 중심으로 전환 (소프트 필터)
- 과열/위험 조건은 점수 감점으로 처리
- 등급 및 매도전략 포함
"""

import os
import time
import logging
from datetime import date
from typing import List, Optional, Dict

from src.config.settings import settings
from src.config.constants import (
    TOP_N_COUNT,
    MIN_DAILY_DATA_COUNT,
)
from src.utils.stock_filters import (
    filter_universe_stocks,
)
from src.domain.models import (
    StockData,
    Weights,
    ScreeningResult,
    ScreeningStatus,
    ScreenerError,
)
# v5 점수 계산기 임포트
from src.domain.score_calculator_v5 import (
    ScoreCalculatorV5,
    StockScoreV5,
    format_discord_embed,
    format_score_display,
    format_simple_display,
)
from src.adapters.kis_client import get_kis_client, KISClient
from src.adapters.discord_notifier import get_discord_notifier, DiscordNotifier
from src.infrastructure.repository import (
    get_screening_repository,
    get_weight_repository,
    ScreeningRepository,
    WeightRepository,
)
from src.infrastructure.database import init_database

logger = logging.getLogger(__name__)


class ScreenerServiceV5:
    """스크리닝 서비스 v5 - 소프트 필터 방식"""
    
    def __init__(
        self,
        kis_client: Optional[KISClient] = None,
        discord_notifier: Optional[DiscordNotifier] = None,
        screening_repo: Optional[ScreeningRepository] = None,
        weight_repo: Optional[WeightRepository] = None,
    ):
        self.kis_client = kis_client or get_kis_client()
        self.discord_notifier = discord_notifier or get_discord_notifier()
        self.screening_repo = screening_repo or get_screening_repository()
        self.weight_repo = weight_repo or get_weight_repository()
        
        # v5 점수 계산기
        self.calculator = ScoreCalculatorV5()
        
        logger.info("ScreenerService v5.0 초기화 (소프트 필터 방식)")
    
    def run_screening(
        self,
        screen_time: str = "15:00",
        save_to_db: bool = True,
        send_alert: bool = True,
        is_preview: bool = False,
    ) -> Dict:
        """스크리닝 실행 - v5
        
        Returns:
            결과 딕셔너리 (v5 점수 포함)
        """
        start_time = time.time()
        screen_date = date.today()
        
        logger.info(f"스크리닝 시작: {screen_date} {screen_time} (프리뷰: {is_preview})")
        
        try:
            # 1. 유니버스 조회 (TV200 조건검색)
            stocks = self._get_filtered_stocks()
            if not stocks:
                return self._create_empty_result(
                    screen_date, screen_time, start_time, is_preview,
                    "유니버스가 비어있습니다"
                )
            
            logger.info(f"유니버스 조회 완료: {len(stocks)}개 종목")
            
            # 2. 일봉 데이터 수집 (최소한의 하드필터만 적용)
            stock_data_list = self._collect_stock_data_minimal(stocks)
            
            if not stock_data_list:
                return self._create_empty_result(
                    screen_date, screen_time, start_time, is_preview,
                    "데이터 수집 후 종목이 없습니다"
                )
            
            logger.info(f"데이터 수집 완료: {len(stock_data_list)}개 종목")
            
            # 3. v5 점수 계산 (소프트 필터)
            v5_scores = self.calculator.calculate_scores(stock_data_list)
            
            # 4. TOP N 선정
            top_n = self.calculator.select_top_n(v5_scores, TOP_N_COUNT)
            
            execution_time = time.time() - start_time
            
            # 5. 결과 생성
            result = {
                "screen_date": screen_date,
                "screen_time": screen_time,
                "total_count": len(v5_scores),
                "top_n": top_n,
                "all_scores": v5_scores,
                "execution_time_sec": execution_time,
                "status": "SUCCESS",
                "is_preview": is_preview,
                "error_message": None,
            }
            
            # 6. DB 저장 (레거시 형식으로 변환)
            if save_to_db and not is_preview:
                self._save_result_legacy(result)
            
            # 7. 알림 발송 (v5 포맷)
            if send_alert:
                self._send_alert_v5(result, is_preview)
            
            # 8. 콘솔 출력
            self._print_results(top_n)
            
            logger.info(f"스크리닝 완료: {execution_time:.1f}초 소요")
            return result
            
        except Exception as e:
            logger.error(f"스크리닝 에러: {e}")
            import traceback
            traceback.print_exc()
            
            execution_time = time.time() - start_time
            
            # 에러 알림
            if send_alert:
                try:
                    self.discord_notifier.send_error_alert(e, "스크리닝 실행 중 에러")
                except:
                    pass
            
            return self._create_empty_result(
                screen_date, screen_time, start_time, is_preview,
                str(e)
            )
    
    def _get_filtered_stocks(self) -> List:
        """유니버스 종목 조회 (TV200 조건검색 기반)"""
        universe_source = os.getenv("UNIVERSE_SOURCE", "condition_search")
        condition_name = os.getenv("CONDITION_NAME", "TV200")
        min_candidates = int(os.getenv("MIN_CANDIDATES", "30"))
        fallback_enabled = os.getenv("FALLBACK_ENABLED", "true").lower() == "true"
        
        min_value = settings.screening.min_trading_value
        stocks = []
        filter_result = None
        
        # 1. 조건검색 기반 유니버스
        if universe_source == "condition_search":
            logger.info(f"조건검색 유니버스 조회: {condition_name}")
            
            try:
                stocks_raw = self.kis_client.get_condition_universe(
                    condition_name=condition_name,
                    limit=500,
                )
                
                if stocks_raw:
                    logger.info(f"조건검색 raw 결과: {len(stocks_raw)}개")
                    
                    # ETF/인버스 등 제외 필터만 적용
                    stocks, filter_result = filter_universe_stocks(
                        stocks_raw,
                        log_details=True,
                    )
                    
                    logger.info(f"2차 필터 후: {len(stocks)}개")
                else:
                    logger.warning("조건검색 결과가 비어있습니다")
                    
            except Exception as e:
                logger.error(f"조건검색 조회 실패: {e}")
        
        # 2. Fallback
        if fallback_enabled and len(stocks) < min_candidates:
            logger.warning(f"유니버스 부족 ({len(stocks)}개), fallback 실행...")
            
            try:
                fallback_stocks = self.kis_client.get_top_trading_value_stocks(
                    min_trading_value=min_value,
                    limit=200,
                )
                
                if fallback_stocks:
                    filtered_fallback, _ = filter_universe_stocks(
                        fallback_stocks,
                        log_details=True,
                    )
                    
                    existing_codes = {s.code for s in stocks}
                    for stock in filtered_fallback:
                        if stock.code not in existing_codes:
                            stocks.append(stock)
                            existing_codes.add(stock.code)
                    
                    logger.info(f"Fallback 후 총: {len(stocks)}개")
                    
            except Exception as e:
                logger.error(f"Fallback 실패: {e}")
        
        return stocks
    
    def _collect_stock_data_minimal(self, stocks: List) -> List[StockData]:
        """
        종목별 일봉 데이터 수집 - 최소한의 하드필터만 적용
        
        🔥 v5 핵심: 과열/위험 조건은 하드필터가 아닌 점수 감점으로 처리
        
        하드필터 (제외):
        - 데이터 부족 (20일 미만)
        - 하락 종목 (등락률 < 0)
        
        소프트필터 (점수 감점으로 처리):
        - CCI 과열 (200+) → 점수 감점
        - 등락률 과대 (15%+) → 점수 감점
        - 이격도 과대 (15%+) → 점수 감점
        - 연속양봉 과다 (5일+) → 점수 감점
        - CCI 하락중 → 보너스 미지급
        - MA20 하락 → 보너스 미지급
        - 고가=종가 → 보너스 미지급
        """
        stock_data_list = []
        filtered_count = {
            "데이터부족": 0,
            "하락종목": 0,
        }
        failed_count = 0
        
        for i, stock in enumerate(stocks):
            try:
                # 일봉 데이터 조회
                daily_prices = self.kis_client.get_daily_prices(
                    stock.code,
                    count=MIN_DAILY_DATA_COUNT + 10
                )
                
                # 하드필터 1: 데이터 부족
                if len(daily_prices) < MIN_DAILY_DATA_COUNT:
                    logger.debug(f"데이터 부족: {stock.name} ({len(daily_prices)}일)")
                    filtered_count["데이터부족"] += 1
                    continue
                
                # 당일 등락률 계산
                today = daily_prices[-1]
                yesterday = daily_prices[-2]
                change_rate = ((today.close - yesterday.close) / yesterday.close) * 100
                
                # 하드필터 2: 하락 종목 (종가매매는 상승 종목 대상)
                if change_rate < 0:
                    logger.debug(f"하락종목 제외: {stock.name} ({change_rate:.1f}%)")
                    filtered_count["하락종목"] += 1
                    continue
                
                # ⚠️ v5: 여기서 다른 하드필터는 적용하지 않음!
                # 과열, 이격도 과대 등은 모두 점수로 처리
                
                # 거래대금 계산
                trading_value = today.trading_value / 100_000_000  # 원 -> 억원
                
                if trading_value <= 0:
                    try:
                        current_price_data = self.kis_client.get_current_price(stock.code)
                        trading_value = current_price_data.trading_value / 100_000_000
                    except:
                        pass
                
                if trading_value <= 0 and hasattr(stock, 'trading_value') and stock.trading_value > 0:
                    trading_value = stock.trading_value
                
                # StockData 생성
                stock_data = StockData(
                    code=stock.code,
                    name=stock.name,
                    daily_prices=daily_prices,
                    current_price=today.close,
                    trading_value=trading_value,
                )
                stock_data_list.append(stock_data)
                
                # 진행률 로깅
                if (i + 1) % 10 == 0:
                    logger.info(f"데이터 수집 진행: {i + 1}/{len(stocks)}")
                    
            except Exception as e:
                logger.warning(f"종목 데이터 수집 실패: {stock.code} - {e}")
                failed_count += 1
                continue
        
        # 필터링 로그
        total_filtered = sum(filtered_count.values())
        logger.info(f"=== 데이터 수집 결과 ===")
        logger.info(f"  입력: {len(stocks)}개")
        logger.info(f"  데이터부족: {filtered_count['데이터부족']}개")
        logger.info(f"  하락종목: {filtered_count['하락종목']}개")
        logger.info(f"  수집실패: {failed_count}개")
        logger.info(f"  최종: {len(stock_data_list)}개 → 점수 계산 대상")
        
        return stock_data_list
    
    def _create_empty_result(
        self,
        screen_date: date,
        screen_time: str,
        start_time: float,
        is_preview: bool,
        error_message: str,
    ) -> Dict:
        """빈 결과 생성"""
        return {
            "screen_date": screen_date,
            "screen_time": screen_time,
            "total_count": 0,
            "top_n": [],
            "all_scores": [],
            "execution_time_sec": time.time() - start_time,
            "status": "FAILED" if error_message else "SUCCESS",
            "is_preview": is_preview,
            "error_message": error_message,
        }
    
    def _save_result_legacy(self, result: Dict):
        """결과 DB 저장 (레거시 형식)"""
        try:
            # v5 점수를 레거시 형식으로 변환
            legacy_scores = [s.to_legacy_score() for s in result["all_scores"]]
            
            legacy_result = ScreeningResult(
                screen_date=result["screen_date"],
                screen_time=result["screen_time"],
                total_count=result["total_count"],
                top3=[s.to_legacy_score() for s in result["top_n"]],
                all_items=legacy_scores,
                execution_time_sec=result["execution_time_sec"],
                status=ScreeningStatus.SUCCESS,
                is_preview=result["is_preview"],
            )
            
            screening_id = self.screening_repo.save_screening(legacy_result)
            logger.info(f"스크리닝 결과 저장 완료: ID={screening_id}")
        except Exception as e:
            logger.error(f"DB 저장 실패: {e}")
    
    def _send_alert_v5(self, result: Dict, is_preview: bool):
        """v5 형식 Discord 알림 발송"""
        try:
            top_n = result["top_n"]
            
            if not top_n:
                # 종목 없음 알림
                self.discord_notifier.send_message(
                    content="📊 종가매매 스크리닝 결과: 적합한 종목이 없습니다.",
                )
                return
            
            # v5 Discord Embed 생성
            title = "[프리뷰] 종가매매 TOP5" if is_preview else "🔔 종가매매 TOP5"
            embed = format_discord_embed(top_n, title=title)
            
            # Discord 전송
            success = self.discord_notifier.send_embed(embed)
            
            if success:
                logger.info("Discord 알림 발송 성공 (v5 형식)")
            else:
                logger.warning("Discord 알림 발송 실패")
                
        except Exception as e:
            logger.error(f"Discord 알림 발송 에러: {e}")
    
    def _print_results(self, top_n: List[StockScoreV5]):
        """결과 콘솔 출력"""
        print("\n" + "=" * 70)
        print("🔔 종가매매 TOP5 (v5.0 점수제)")
        print("=" * 70)
        
        if not top_n:
            print("적합한 종목이 없습니다.")
            return
        
        for i, score in enumerate(top_n, 1):
            print(f"\n{format_score_display(score, i)}")
            print("-" * 50)
        
        # 등급 설명
        print("\n" + "=" * 70)
        print("📋 등급별 매도전략")
        print("-" * 70)
        print("🏆 S등급 (85점+): 시초 30% + 목표 +4% 홀딩 | 손절 -3% | 신뢰도: 매우 높음")
        print("🥇 A등급 (75-84): 시초 40% + 목표 +3% 홀딩 | 손절 -2.5% | 신뢰도: 높음")
        print("🥈 B등급 (65-74): 시초 50% + 목표 +2.5% 홀딩 | 손절 -2% | 신뢰도: 중상")
        print("🥉 C등급 (55-64): 시초 70% + 목표 +2% (보수적) | 손절 -1.5% | 신뢰도: 중간")
        print("⚠️ D등급 (<55): 시초가 전량 매도 권장 | 손절 -1% | 신뢰도: 낮음")
        print("=" * 70)


# ============================================================
# 편의 함수
# ============================================================

def run_screening_v5(
    screen_time: str = "15:00",
    save_to_db: bool = True,
    send_alert: bool = True,
    is_preview: bool = False,
) -> Dict:
    """v5 스크리닝 실행"""
    service = ScreenerServiceV5()
    return service.run_screening(screen_time, save_to_db, send_alert, is_preview)


def run_main_screening_v5() -> Dict:
    """15:00 메인 스크리닝 (v5)"""
    service = ScreenerServiceV5()
    return service.run_screening(
        screen_time="15:00",
        save_to_db=True,
        send_alert=True,
        is_preview=False,
    )


def run_preview_screening_v5() -> Dict:
    """12:30 프리뷰 스크리닝 (v5)"""
    service = ScreenerServiceV5()
    return service.run_screening(
        screen_time="12:30",
        save_to_db=False,
        send_alert=True,
        is_preview=True,
    )


# ============================================================
# 레거시 호환
# ============================================================

ScreenerService = ScreenerServiceV5
run_screening = run_screening_v5
run_main_screening = run_main_screening_v5
run_preview_screening = run_preview_screening_v5


if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )
    
    # DB 초기화
    try:
        init_database()
    except:
        pass
    
    # 인자로 모드 선택
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"
    
    if mode == "main":
        print("=== 메인 스크리닝 (15:00) v5 ===")
        result = run_main_screening_v5()
    elif mode == "preview":
        print("=== 프리뷰 스크리닝 (12:30) v5 ===")
        result = run_preview_screening_v5()
    else:
        print("=== 테스트 스크리닝 (알림 없음) v5 ===")
        result = run_screening_v5(
            screen_time="15:00",
            save_to_db=False,
            send_alert=False,
            is_preview=False,
        )
    
    print(f"\n=== 실행 결과 ===")
    print(f"상태: {result['status']}")
    print(f"분석 종목: {result['total_count']}개")
    print(f"실행 시간: {result['execution_time_sec']:.1f}초")
    
    if result.get("error_message"):
        print(f"에러: {result['error_message']}")
