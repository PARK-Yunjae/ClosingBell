"""
학습 서비스 모듈

책임:
- 익일 결과 수집
- 성과 분석
- 가중치 최적화
- 일일 학습 프로세스
"""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from src.adapters.kis_client import get_kis_client
from src.infrastructure.repository import get_repository
from src.domain.weight_optimizer import (
    analyze_correlation,
    calculate_optimal_weights,
    should_optimize,
    get_default_weights,
    WeightOptimizationResult,
    CorrelationResult,
)
from src.config.constants import MIN_LEARNING_SAMPLES

logger = logging.getLogger(__name__)


@dataclass
class NextDayResult:
    """익일 결과 데이터"""
    stock_code: str
    stock_name: str
    screen_date: date
    screen_rank: int
    screen_score: float
    
    # 익일 가격 정보
    next_open: int  # 익일 시가
    next_close: int  # 익일 종가
    next_high: int
    next_low: int
    next_volume: int
    next_trading_value: float
    
    # 계산된 지표
    gap_rate: float  # 갭 상승률 (전일 종가 대비 익일 시가)
    day_return: float  # 당일 수익률 (익일 시가 대비 종가)
    volatility: float  # 변동성 (고가-저가)/시가


@dataclass 
class PerformanceStats:
    """성과 통계"""
    sample_count: int
    win_rate: float  # 익일 시초가 상승 비율
    avg_gap_rate: float  # 평균 갭 상승률
    avg_day_return: float  # 평균 당일 수익률
    max_gap_rate: float  # 최대 갭 상승률
    min_gap_rate: float  # 최소 갭 상승률
    avg_volatility: float  # 평균 변동성
    
    # TOP1만의 성과
    top1_win_rate: float
    top1_avg_gap_rate: float


@dataclass
class LearningReport:
    """학습 결과 리포트"""
    learning_date: date
    sample_count: int
    performance: PerformanceStats
    correlations: Dict[str, float]
    weight_changed: bool
    optimization_result: Optional[WeightOptimizationResult]
    message: str


class LearnerService:
    """학습 서비스"""
    
    def __init__(self):
        self.kis_client = get_kis_client()
        self.repository = get_repository()
    
    def collect_next_day_results(self, target_date: Optional[date] = None) -> List[NextDayResult]:
        """전일 스크리닝 종목의 익일 결과 수집
        
        Args:
            target_date: 수집 대상일 (None이면 전일)
            
        Returns:
            익일 결과 리스트
        """
        if target_date is None:
            target_date = date.today() - timedelta(days=1)
        
        logger.info(f"익일 결과 수집 시작: {target_date}")
        
        # 해당 날짜의 스크리닝 결과 조회
        screening_results = self.repository.get_screening_results_by_date(target_date)
        
        if not screening_results:
            logger.warning(f"{target_date} 스크리닝 결과 없음")
            return []
        
        results = []
        for sr in screening_results:
            try:
                # 익일 일봉 데이터 조회
                daily_prices = self.kis_client.get_daily_prices(sr.stock_code, count=2)
                
                if len(daily_prices) < 2:
                    logger.warning(f"일봉 데이터 부족: {sr.stock_name}")
                    continue
                
                # 전일 데이터 (스크리닝 당일)
                prev_day = daily_prices[-2]
                # 익일 데이터
                next_day = daily_prices[-1]
                
                # 갭 상승률 계산
                gap_rate = ((next_day.open - prev_day.close) / prev_day.close) * 100
                
                # 당일 수익률 계산
                day_return = ((next_day.close - next_day.open) / next_day.open) * 100
                
                # 변동성 계산
                volatility = ((next_day.high - next_day.low) / next_day.open) * 100
                
                result = NextDayResult(
                    stock_code=sr.stock_code,
                    stock_name=sr.stock_name,
                    screen_date=target_date,
                    screen_rank=sr.rank,
                    screen_score=sr.score_total,
                    next_open=next_day.open,
                    next_close=next_day.close,
                    next_high=next_day.high,
                    next_low=next_day.low,
                    next_volume=next_day.volume,
                    next_trading_value=next_day.trading_value,
                    gap_rate=gap_rate,
                    day_return=day_return,
                    volatility=volatility,
                )
                
                results.append(result)
                
                # DB에 저장
                self._save_next_day_result(result)
                
            except Exception as e:
                logger.warning(f"익일 결과 수집 실패: {sr.stock_name} - {e}")
                continue
        
        logger.info(f"익일 결과 수집 완료: {len(results)}개")
        return results
    
    def _save_next_day_result(self, result: NextDayResult):
        """익일 결과 DB 저장"""
        try:
            self.repository.save_next_day_result(
                stock_code=result.stock_code,
                screen_date=result.screen_date,
                gap_rate=result.gap_rate,
                day_return=result.day_return,
                volatility=result.volatility,
                next_open=result.next_open,
                next_close=result.next_close,
                next_high=result.next_high,
                next_low=result.next_low,
            )
        except Exception as e:
            logger.error(f"익일 결과 저장 실패: {e}")
    
    def analyze_performance(self, days: int = 30) -> PerformanceStats:
        """최근 N일간의 스크리닝 성과 분석
        
        Args:
            days: 분석 기간 (일)
            
        Returns:
            성과 통계
        """
        logger.info(f"성과 분석 시작: 최근 {days}일")
        
        # DB에서 익일 결과 조회
        results = self.repository.get_next_day_results(days=days)
        
        if not results:
            logger.warning("분석할 데이터 없음")
            return PerformanceStats(
                sample_count=0,
                win_rate=0.0,
                avg_gap_rate=0.0,
                avg_day_return=0.0,
                max_gap_rate=0.0,
                min_gap_rate=0.0,
                avg_volatility=0.0,
                top1_win_rate=0.0,
                top1_avg_gap_rate=0.0,
            )
        
        # 전체 통계
        gap_rates = [r['gap_rate'] for r in results if r.get('gap_rate') is not None]
        day_returns = [r['day_return'] for r in results if r.get('day_return') is not None]
        volatilities = [r['volatility'] for r in results if r.get('volatility') is not None]
        
        win_count = sum(1 for g in gap_rates if g > 0)
        
        # TOP1 통계
        top1_results = [r for r in results if r.get('screen_rank') == 1]
        top1_gaps = [r['gap_rate'] for r in top1_results if r.get('gap_rate') is not None]
        top1_wins = sum(1 for g in top1_gaps if g > 0)
        
        stats = PerformanceStats(
            sample_count=len(results),
            win_rate=(win_count / len(gap_rates) * 100) if gap_rates else 0.0,
            avg_gap_rate=sum(gap_rates) / len(gap_rates) if gap_rates else 0.0,
            avg_day_return=sum(day_returns) / len(day_returns) if day_returns else 0.0,
            max_gap_rate=max(gap_rates) if gap_rates else 0.0,
            min_gap_rate=min(gap_rates) if gap_rates else 0.0,
            avg_volatility=sum(volatilities) / len(volatilities) if volatilities else 0.0,
            top1_win_rate=(top1_wins / len(top1_gaps) * 100) if top1_gaps else 0.0,
            top1_avg_gap_rate=sum(top1_gaps) / len(top1_gaps) if top1_gaps else 0.0,
        )
        
        logger.info(
            f"성과 분석 완료: 샘플 {stats.sample_count}개, "
            f"승률 {stats.win_rate:.1f}%, 평균 갭 {stats.avg_gap_rate:+.2f}%"
        )
        
        return stats
    
    def _get_correlation_data(self, days: int = 30) -> Tuple[Dict[str, List[float]], List[float]]:
        """상관관계 분석용 데이터 준비
        
        Returns:
            (지표별 점수 딕셔너리, 익일 갭 수익률 리스트)
        """
        # DB에서 스크리닝 결과와 익일 결과 조인하여 조회
        data = self.repository.get_screening_with_next_day(days=days)
        
        indicator_scores = {
            'cci_value': [],
            'cci_slope': [],
            'ma20_slope': [],
            'candle': [],
            'change': [],
        }
        next_day_returns = []
        
        for row in data:
            indicator_scores['cci_value'].append(row.get('score_cci_value', 0))
            indicator_scores['cci_slope'].append(row.get('score_cci_slope', 0))
            indicator_scores['ma20_slope'].append(row.get('score_ma20_slope', 0))
            indicator_scores['candle'].append(row.get('score_candle', 0))
            indicator_scores['change'].append(row.get('score_change', 0))
            next_day_returns.append(row.get('gap_rate', 0))
        
        return indicator_scores, next_day_returns
    
    def optimize_weights(self) -> Optional[WeightOptimizationResult]:
        """가중치 최적화 실행
        
        30일 이상 데이터가 있을 때만 실행
        
        Returns:
            최적화 결과 (데이터 부족 시 None)
        """
        logger.info("가중치 최적화 시작")
        
        # 상관관계 분석용 데이터 준비
        indicator_scores, next_day_returns = self._get_correlation_data(days=60)
        
        sample_count = len(next_day_returns)
        
        if not should_optimize(sample_count):
            logger.info(
                f"학습 데이터 부족: {sample_count}개 "
                f"(최소 {MIN_LEARNING_SAMPLES}개 필요)"
            )
            return None
        
        # 상관관계 분석
        correlations = analyze_correlation(indicator_scores, next_day_returns)
        
        # 현재 가중치 로드
        current_weights = self.repository.get_current_weights()
        if not current_weights:
            current_weights = get_default_weights()
        
        # 최적 가중치 계산
        optimization = calculate_optimal_weights(correlations, current_weights)
        
        # 가중치 변경이 있으면 저장
        if any(abs(c) > 0.001 for c in optimization.changes.values()):
            self._save_weight_update(optimization)
            logger.info(f"가중치 업데이트 완료: {optimization.reason}")
        else:
            logger.info("가중치 변경 없음")
        
        return optimization
    
    def _save_weight_update(self, optimization: WeightOptimizationResult):
        """가중치 업데이트 저장"""
        try:
            # weight_config 테이블 업데이트
            self.repository.update_weights(optimization.new_weights)
            
            # weight_history 테이블에 이력 저장
            self.repository.save_weight_history(
                weights=optimization.new_weights,
                correlations=optimization.correlations,
                reason=optimization.reason,
            )
        except Exception as e:
            logger.error(f"가중치 저장 실패: {e}")
    
    def run_daily_learning(self) -> LearningReport:
        """일일 학습 프로세스 실행
        
        16:30에 스케줄러에서 호출
        
        Returns:
            학습 결과 리포트
        """
        logger.info("=" * 60)
        logger.info("일일 학습 프로세스 시작")
        logger.info("=" * 60)
        
        learning_date = date.today()
        
        # 1. 전일 스크리닝 종목의 익일 결과 수집
        next_day_results = self.collect_next_day_results()
        
        # 2. 성과 분석
        performance = self.analyze_performance(days=30)
        
        # 3. 가중치 최적화 (30일 이상 데이터 있을 때)
        optimization_result = None
        weight_changed = False
        
        if performance.sample_count >= MIN_LEARNING_SAMPLES:
            optimization_result = self.optimize_weights()
            weight_changed = (
                optimization_result is not None and 
                any(abs(c) > 0.001 for c in optimization_result.changes.values())
            )
        
        # 상관관계 정보
        correlations = {}
        if optimization_result:
            correlations = optimization_result.correlations
        
        # 리포트 생성
        message = self._generate_learning_message(
            performance, optimization_result, weight_changed
        )
        
        report = LearningReport(
            learning_date=learning_date,
            sample_count=performance.sample_count,
            performance=performance,
            correlations=correlations,
            weight_changed=weight_changed,
            optimization_result=optimization_result,
            message=message,
        )
        
        logger.info(message)
        logger.info("=" * 60)
        logger.info("일일 학습 프로세스 완료")
        logger.info("=" * 60)
        
        return report
    
    def _generate_learning_message(
        self,
        performance: PerformanceStats,
        optimization: Optional[WeightOptimizationResult],
        weight_changed: bool,
    ) -> str:
        """학습 결과 메시지 생성"""
        lines = [
            "📚 일일 학습 결과",
            "",
            f"📊 성과 분석 (최근 30일)",
            f"  • 샘플 수: {performance.sample_count}개",
            f"  • 승률: {performance.win_rate:.1f}%",
            f"  • 평균 갭 상승률: {performance.avg_gap_rate:+.2f}%",
            f"  • TOP1 승률: {performance.top1_win_rate:.1f}%",
            f"  • TOP1 평균 갭: {performance.top1_avg_gap_rate:+.2f}%",
        ]
        
        if optimization:
            lines.extend([
                "",
                "📈 상관관계 분석",
            ])
            for name, corr in optimization.correlations.items():
                lines.append(f"  • {name}: {corr:+.4f}")
        
        if weight_changed and optimization:
            lines.extend([
                "",
                "⚖️ 가중치 변경",
            ])
            for name, change in optimization.changes.items():
                if abs(change) > 0.001:
                    old = optimization.old_weights[name]
                    new = optimization.new_weights[name]
                    lines.append(f"  • {name}: {old:.2f} → {new:.2f} ({change:+.3f})")
        elif not weight_changed:
            lines.extend([
                "",
                "⚖️ 가중치 변경 없음",
            ])
        
        return "\n".join(lines)


# 싱글톤 인스턴스
_learner_service: Optional[LearnerService] = None


def get_learner_service() -> LearnerService:
    """Learner 서비스 인스턴스 반환"""
    global _learner_service
    if _learner_service is None:
        _learner_service = LearnerService()
    return _learner_service


def run_daily_learning() -> LearningReport:
    """일일 학습 실행 (스케줄러용)"""
    service = get_learner_service()
    return service.run_daily_learning()


if __name__ == "__main__":
    # 테스트
    logging.basicConfig(level=logging.INFO)
    
    service = LearnerService()
    
    # 성과 분석 테스트
    print("\n=== 성과 분석 ===")
    stats = service.analyze_performance(days=30)
    print(f"샘플: {stats.sample_count}개")
    print(f"승률: {stats.win_rate:.1f}%")
    print(f"평균 갭: {stats.avg_gap_rate:+.2f}%")
