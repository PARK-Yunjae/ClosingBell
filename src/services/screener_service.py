"""
스크리닝 오케스트레이션 서비스

책임:
- 스크리닝 플로우 제어
- 필터링 → 분석 → 점수 산출 → 저장 → 알림 순서 관리
- 에러 처리 및 부분 실패 핸들링
- 실행 시간 측정
- 조건검색 기반 유니버스 지원 (2차 필터 적용)
- fallback 정책 (조건검색 실패/부족 시 자동 대체)

의존성:
- adapters.kis_client
- domain.score_calculator
- infrastructure.repository
- adapters.discord_notifier
- utils.stock_filters
"""

import os
import time
import logging
from datetime import date
from typing import List, Optional

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
from src.domain.score_calculator import ScoreCalculator
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


class ScreenerService:
    """스크리닝 서비스"""
    
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
    
    def run_screening(
        self,
        screen_time: str = "15:00",
        save_to_db: bool = True,
        send_alert: bool = True,
        is_preview: bool = False,
    ) -> ScreeningResult:
        """스크리닝 실행
        
        Args:
            screen_time: 스크리닝 시각 ("15:00" or "12:30")
            save_to_db: DB 저장 여부 (12:30 프리뷰는 False)
            send_alert: 알림 발송 여부
            is_preview: 프리뷰 모드 여부
            
        Returns:
            스크리닝 결과
        """
        start_time = time.time()
        screen_date = date.today()
        
        logger.info(f"스크리닝 시작: {screen_date} {screen_time} (프리뷰: {is_preview})")
        
        try:
            # 1. 현재 가중치 로드
            weights = self._load_weights()
            logger.info(f"가중치 로드 완료: {weights.to_dict()}")
            
            # 2. 거래대금 300억+ 종목 조회
            stocks = self._get_filtered_stocks()
            if not stocks:
                return self._create_empty_result(
                    screen_date, screen_time, start_time, weights, is_preview
                )
            
            # 3. 각 종목 일봉 데이터 수집 및 StockData 생성
            stock_data_list = self._collect_stock_data(stocks)
            logger.info(f"일봉 데이터 수집 완료: {len(stock_data_list)}개 종목")
            
            if not stock_data_list:
                return self._create_empty_result(
                    screen_date, screen_time, start_time, weights, is_preview
                )
            
            # 4. 점수 산출
            calculator = ScoreCalculator(weights)
            scores = calculator.calculate_scores(stock_data_list)
            
            # 5. TOP 3 선정
            top3 = calculator.select_top_n(scores, TOP_N_COUNT)
            logger.info(f"TOP {TOP_N_COUNT} 선정 완료")
            
            # 결과 생성
            execution_time = time.time() - start_time
            result = ScreeningResult(
                screen_date=screen_date,
                screen_time=screen_time,
                total_count=len(scores),
                top3=top3,
                all_items=scores,
                execution_time_sec=execution_time,
                status=ScreeningStatus.SUCCESS,
                weights_used=weights,
                is_preview=is_preview,
            )
            
            # 6. DB 저장 (프리뷰는 저장 안 함)
            if save_to_db and not is_preview:
                self._save_result(result)
            
            # 7. 알림 발송
            if send_alert:
                self._send_alert(result, is_preview)
            
            logger.info(f"스크리닝 완료: {execution_time:.1f}초 소요")
            return result
            
        except Exception as e:
            logger.error(f"스크리닝 에러: {e}")
            
            execution_time = time.time() - start_time
            result = ScreeningResult(
                screen_date=screen_date,
                screen_time=screen_time,
                total_count=0,
                top3=[],
                all_items=[],
                execution_time_sec=execution_time,
                status=ScreeningStatus.FAILED,
                error_message=str(e),
                is_preview=is_preview,
            )
            
            # 에러 알림
            if send_alert:
                self.discord_notifier.send_error_alert(e, "스크리닝 실행 중 에러")
            
            return result
    
    def run_preview_screening(self) -> ScreeningResult:
        """12:30 프리뷰 스크리닝 실행"""
        return self.run_screening(
            screen_time="12:30",
            save_to_db=False,
            send_alert=True,
            is_preview=True,
        )
    
    def run_main_screening(self) -> ScreeningResult:
        """15:00 메인 스크리닝 실행"""
        return self.run_screening(
            screen_time="15:00",
            save_to_db=True,
            send_alert=True,
            is_preview=False,
        )
    
    def _load_weights(self) -> Weights:
        """가중치 로드"""
        try:
            return self.weight_repo.get_weights()
        except Exception as e:
            logger.warning(f"가중치 로드 실패, 기본값 사용: {e}")
            return Weights()
    
    def _get_filtered_stocks(self) -> List:
        """
        유니버스 종목 조회 (조건검색 우선 + fallback 정책)
        
        우선순위:
        1. 조건검색(psearch) 기반 유니버스 -> 2차 필터 적용
        2. fallback: volume_rank API
        3. fallback: 주요 종목 리스트 스캔
        """
        # 환경변수에서 설정 읽기
        universe_source = os.getenv("UNIVERSE_SOURCE", "condition_search")
        condition_name = os.getenv("CONDITION_NAME", "TV200")
        min_candidates = int(os.getenv("MIN_CANDIDATES", "30"))
        fallback_enabled = os.getenv("FALLBACK_ENABLED", "true").lower() == "true"
        
        min_value = settings.screening.min_trading_value
        stocks = []
        filter_result = None
        
        # ============================================================
        # 1. 조건검색 기반 유니버스 (우선)
        # ============================================================
        if universe_source == "condition_search":
            logger.info(f"조건검색 유니버스 조회: {condition_name}")
            
            try:
                stocks_raw = self.kis_client.get_condition_universe(
                    condition_name=condition_name,
                    limit=500,
                )
                
                if stocks_raw:
                    logger.info(f"조건검색 raw 결과: {len(stocks_raw)}개")
                    
                    # 2차 필터 적용
                    stocks, filter_result = filter_universe_stocks(
                        stocks_raw,
                        log_details=True,
                    )
                    
                    logger.info(f"2차 필터 후: {len(stocks)}개")
                else:
                    logger.warning("조건검색 결과가 비어있습니다")
                    
            except Exception as e:
                logger.error(f"조건검색 조회 실패: {e}")
        
        # ============================================================
        # 2. Fallback 정책
        # ============================================================
        if fallback_enabled and len(stocks) < min_candidates:
            logger.warning(
                f"유니버스 부족 ({len(stocks)}개 < {min_candidates}개), "
                f"fallback 실행..."
            )
            
            # 2-1. volume_rank API fallback
            if len(stocks) < min_candidates:
                logger.info("Fallback 1: volume_rank API 조회")
                try:
                    fallback_stocks = self.kis_client.get_top_trading_value_stocks(
                        min_trading_value=min_value,
                        limit=200,
                    )
                    
                    if fallback_stocks:
                        # 2차 필터 적용
                        filtered_fallback, fb_result = filter_universe_stocks(
                            fallback_stocks,
                            log_details=True,
                        )
                        
                        # 기존 종목과 병합 (중복 제거)
                        existing_codes = {s.code for s in stocks}
                        for stock in filtered_fallback:
                            if stock.code not in existing_codes:
                                stocks.append(stock)
                                existing_codes.add(stock.code)
                        
                        logger.info(f"Fallback 후 총: {len(stocks)}개")
                        
                except Exception as e:
                    logger.error(f"volume_rank fallback 실패: {e}")
        
        # 최종 결과 로깅
        if stocks:
            logger.info(f"최종 유니버스: {len(stocks)}개 종목")
            if filter_result:
                logger.info(str(filter_result))
        else:
            logger.warning("유니버스가 비어있습니다!")
        
        return stocks
    
    def _collect_stock_data(self, stocks) -> List[StockData]:
        """종목별 일봉 데이터 수집"""
        stock_data_list = []
        failed_count = 0
        
        for i, stock_info in enumerate(stocks):
            try:
                # 일봉 데이터 조회
                prices = self.kis_client.get_daily_prices(
                    stock_info.code,
                    count=MIN_DAILY_DATA_COUNT + 5,  # 여유분
                )
                
                if len(prices) < MIN_DAILY_DATA_COUNT:
                    logger.warning(f"데이터 부족: {stock_info.name} ({len(prices)}일)")
                    continue
                
                # 현재가 조회
                current = self.kis_client.get_current_price(stock_info.code)
                
                # 거래대금 (억원)
                trading_value = current.trading_value / 100_000_000
                
                stock_data = StockData(
                    code=stock_info.code,
                    name=stock_info.name,
                    daily_prices=prices,
                    current_price=current.price,
                    trading_value=trading_value,
                )
                stock_data_list.append(stock_data)
                
                # 진행률 로깅 (10개마다)
                if (i + 1) % 10 == 0:
                    logger.info(f"데이터 수집 진행: {i + 1}/{len(stocks)}")
                    
            except ScreenerError as e:
                logger.warning(f"종목 데이터 수집 실패: {stock_info.name} - {e}")
                failed_count += 1
                continue
            except Exception as e:
                logger.warning(f"종목 데이터 수집 에러: {stock_info.name} - {e}")
                failed_count += 1
                continue
        
        if failed_count > 0:
            logger.warning(f"데이터 수집 실패 종목: {failed_count}개")
        
        return stock_data_list
    
    def _create_empty_result(
        self,
        screen_date: date,
        screen_time: str,
        start_time: float,
        weights: Weights,
        is_preview: bool,
    ) -> ScreeningResult:
        """빈 결과 생성"""
        execution_time = time.time() - start_time
        return ScreeningResult(
            screen_date=screen_date,
            screen_time=screen_time,
            total_count=0,
            top3=[],
            all_items=[],
            execution_time_sec=execution_time,
            status=ScreeningStatus.SUCCESS,
            error_message="필터링된 종목이 없습니다",
            weights_used=weights,
            is_preview=is_preview,
        )
    
    def _save_result(self, result: ScreeningResult):
        """결과 DB 저장"""
        try:
            screening_id = self.screening_repo.save_screening(result)
            logger.info(f"스크리닝 결과 저장 완료: ID={screening_id}")
        except Exception as e:
            logger.error(f"DB 저장 실패: {e}")
            # 저장 실패해도 알림은 발송
    
    def _send_alert(self, result: ScreeningResult, is_preview: bool):
        """알림 발송 (Discord)"""
        try:
            discord_result = self.discord_notifier.send_screening_result(
                result,
                is_preview=is_preview,
            )
            if discord_result.success:
                logger.info("Discord 알림 발송 성공")
            else:
                logger.warning(f"Discord 알림 발송 실패: {discord_result.error_message}")
        except Exception as e:
            logger.error(f"Discord 알림 발송 에러: {e}")


# 편의 함수
def run_screening(
    screen_time: str = "15:00",
    save_to_db: bool = True,
    send_alert: bool = True,
    is_preview: bool = False,
) -> ScreeningResult:
    """스크리닝 실행 유틸리티 함수"""
    service = ScreenerService()
    return service.run_screening(screen_time, save_to_db, send_alert, is_preview)


def run_main_screening() -> ScreeningResult:
    """15:00 메인 스크리닝"""
    service = ScreenerService()
    return service.run_main_screening()


def run_preview_screening() -> ScreeningResult:
    """12:30 프리뷰 스크리닝"""
    service = ScreenerService()
    return service.run_preview_screening()


if __name__ == "__main__":
    # 테스트 실행
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )
    
    # DB 초기화
    init_database()
    
    # 인자로 모드 선택
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"
    
    if mode == "main":
        print("=== 메인 스크리닝 (15:00) ===")
        result = run_main_screening()
    elif mode == "preview":
        print("=== 프리뷰 스크리닝 (12:30) ===")
        result = run_preview_screening()
    else:
        print("=== 테스트 스크리닝 (알림 없음) ===")
        result = run_screening(
            screen_time="15:00",
            save_to_db=False,
            send_alert=False,
            is_preview=False,
        )
    
    print(f"\n=== 결과 ===")
    print(f"상태: {result.status.value}")
    print(f"분석 종목: {result.total_count}개")
    print(f"실행 시간: {result.execution_time_sec:.1f}초")
    
    if result.top3:
        print(f"\n=== TOP {len(result.top3)} ===")
        for stock in result.top3:
            print(f"{stock.rank}. {stock.stock_name} ({stock.stock_code})")
            print(f"   현재가: {stock.current_price:,}원 ({stock.change_rate:+.2f}%)")
            print(f"   점수: {stock.score_total:.1f}점")
    else:
        print("\n적합한 종목이 없습니다.")
    
    if result.error_message:
        print(f"\n에러: {result.error_message}")
