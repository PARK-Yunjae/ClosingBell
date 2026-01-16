"""
학습 서비스 v5.3
================

익일 결과를 분석하여 가중치를 자동 조정합니다.

[종가매매]
- 각 지표(CCI, 등락률, 이격도 등)와 gap_rate 상관관계 분석
- 상관관계 높은 지표 가중치 증가

[K값 전략]
- 필터 조건별 승률 분석
- 최적 파라미터 탐색

사용:
    from src.services.learner_service import run_daily_learning
    run_daily_learning()
"""

import logging
import statistics
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from src.infrastructure.repository import get_repository

logger = logging.getLogger(__name__)


class LearnerService:
    """학습 서비스 (종가매매 + K값)"""
    
    def __init__(self):
        self.repo = get_repository()
        
        # 학습 설정
        self.min_samples = 20           # 최소 샘플 수
        self.learning_rate = 0.1        # 가중치 조정 비율
        self.correlation_threshold = 0.05  # 의미있는 상관관계 임계값
    
    # =========================================
    # 종가매매 학습
    # =========================================
    
    def analyze_closing_correlations(self, days: int = 30) -> Dict[str, float]:
        """종가매매 지표별 상관관계 분석
        
        Args:
            days: 분석 기간
            
        Returns:
            지표별 상관관계 딕셔너리
        """
        # 스크리닝 결과 + 익일 결과 조인 조회
        data = self.repo.get_screening_with_next_day(days=days)
        
        if len(data) < self.min_samples:
            logger.warning(f"샘플 부족: {len(data)}개 (최소 {self.min_samples}개 필요)")
            return {}
        
        logger.info(f"📊 상관관계 분석: {len(data)}개 샘플")
        
        # 지표별 상관관계 계산
        indicators = [
            'score_cci_value',
            'score_cci_slope', 
            'score_ma20_slope',
            'score_candle',
            'score_change',
        ]
        
        correlations = {}
        gap_rates = [d.get('gap_rate', 0) or 0 for d in data]
        
        for indicator in indicators:
            values = [d.get(indicator, 0) or 0 for d in data]
            
            if len(values) < 2 or len(set(values)) < 2:
                continue
            
            try:
                corr = self._calculate_correlation(values, gap_rates)
                correlations[indicator] = corr
                logger.info(f"  {indicator}: {corr:+.3f}")
            except Exception as e:
                logger.warning(f"  {indicator} 계산 실패: {e}")
        
        return correlations
    
    def update_closing_weights(self, correlations: Dict[str, float]) -> Dict[str, float]:
        """상관관계 기반 가중치 업데이트
        
        Args:
            correlations: 지표별 상관관계
            
        Returns:
            업데이트된 가중치
        """
        if not correlations:
            logger.info("업데이트할 상관관계 없음")
            return {}
        
        # 현재 가중치 조회
        current_weights = self.repo.get_current_weights() or {}
        updated = {}
        
        for indicator, corr in correlations.items():
            # 지표명 매핑 (score_xxx -> xxx)
            weight_key = indicator.replace('score_', '')
            
            if weight_key not in current_weights:
                continue
            
            old_weight = current_weights[weight_key]
            
            # 상관관계에 따른 가중치 조정
            if abs(corr) > self.correlation_threshold:
                # 양의 상관관계 → 가중치 증가
                # 음의 상관관계 → 가중치 감소
                adjustment = corr * self.learning_rate * old_weight
                new_weight = old_weight + adjustment
                
                # 범위 제한 (0.5 ~ 3.0)
                new_weight = max(0.5, min(3.0, new_weight))
                
                if abs(new_weight - old_weight) > 0.01:
                    self.repo.weight.update_weight(
                        indicator=weight_key,
                        new_weight=round(new_weight, 2),
                        reason=f"상관관계 {corr:+.3f}",
                        correlation=corr,
                        sample_size=self.min_samples,
                    )
                    updated[weight_key] = new_weight
                    logger.info(f"  {weight_key}: {old_weight:.2f} → {new_weight:.2f}")
        
        return updated
    
    # =========================================
    # K값 전략 학습
    # =========================================
    
    def analyze_k_performance(self, days: int = 30) -> Dict:
        """K값 전략 성과 분석
        
        Args:
            days: 분석 기간
            
        Returns:
            성과 통계
        """
        # K값 시그널의 익일 결과 조회
        results = self.repo.get_k_signal_results(days=days)
        
        if not results:
            logger.info("K값 시그널 결과 없음")
            return {}
        
        # 승률 계산
        total = len(results)
        wins = sum(1 for r in results if (r.get('gap_rate') or 0) > 0)
        win_rate = wins / total * 100 if total > 0 else 0
        
        # 평균 수익률
        avg_gap = sum(r.get('gap_rate', 0) or 0 for r in results) / total
        avg_high = sum(r.get('high_change_rate', 0) or 0 for r in results) / total
        
        stats = {
            'total': total,
            'wins': wins,
            'win_rate': win_rate,
            'avg_gap': avg_gap,
            'avg_high': avg_high,
        }
        
        logger.info(f"📊 K값 성과: 승률 {win_rate:.1f}% ({wins}/{total}), 평균갭 {avg_gap:+.2f}%")
        
        return stats
    
    def optimize_k_params(self, days: int = 30) -> Dict:
        """K값 파라미터 최적화 제안
        
        현재는 통계만 제공, 자동 조정은 위험할 수 있음
        """
        results = self.repo.get_k_signal_results(days=days)
        
        if len(results) < self.min_samples:
            return {}
        
        # 구간별 승률 분석
        analysis = {
            'volume_ratio': self._analyze_by_range(results, 'volume_ratio', [1.5, 2.0, 2.5, 3.0, 4.0]),
            'trading_value': self._analyze_by_range(results, 'trading_value', [50, 100, 150, 200, 300]),
            'prev_change': self._analyze_by_range(results, 'prev_change_rate', [0, 2, 4, 6, 8, 10]),
        }
        
        return analysis
    
    def _analyze_by_range(
        self, 
        results: List[Dict], 
        field: str, 
        ranges: List[float]
    ) -> Dict:
        """구간별 승률 분석"""
        analysis = {}
        
        for i in range(len(ranges) - 1):
            low, high = ranges[i], ranges[i + 1]
            filtered = [r for r in results if low <= (r.get(field) or 0) < high]
            
            if filtered:
                wins = sum(1 for r in filtered if (r.get('gap_rate') or 0) > 0)
                win_rate = wins / len(filtered) * 100
                analysis[f"{low}-{high}"] = {
                    'count': len(filtered),
                    'win_rate': round(win_rate, 1),
                }
        
        return analysis
    
    # =========================================
    # 유틸리티
    # =========================================
    
    def _calculate_correlation(self, x: List[float], y: List[float]) -> float:
        """피어슨 상관계수 계산"""
        n = len(x)
        if n < 2:
            return 0.0
        
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        
        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        
        std_x = (sum((xi - mean_x) ** 2 for xi in x) / n) ** 0.5
        std_y = (sum((yi - mean_y) ** 2 for yi in y) / n) ** 0.5
        
        if std_x == 0 or std_y == 0:
            return 0.0
        
        return numerator / (n * std_x * std_y)
    
    def get_learning_stats(self, days: int = 30) -> Dict:
        """학습 통계 조회 (Streamlit용)
        
        Returns:
            {
                'closing': {'win_rate': float, 'total': int, ...},
                'k_value': {'win_rate': float, 'total': int, ...},
                'weights': {'cci_value': float, ...},
                'weight_history': [...]
            }
        """
        # 종가매매 통계
        closing_results = self.repo.get_next_day_results(days=days)
        closing_stats = self._calc_stats(closing_results)
        
        # K값 통계
        k_stats = self.analyze_k_performance(days=days)
        
        # 현재 가중치
        weights = self.repo.get_current_weights() or {}
        
        # 가중치 변경 이력
        weight_history = self.repo.weight.get_weight_history(days=days)
        
        return {
            'closing': closing_stats,
            'k_value': k_stats,
            'weights': weights,
            'weight_history': weight_history,
        }
    
    def _calc_stats(self, results: List[Dict]) -> Dict:
        """승률 통계 계산"""
        if not results:
            return {'total': 0, 'wins': 0, 'win_rate': 0, 'avg_gap': 0}
        
        total = len(results)
        wins = sum(1 for r in results if (r.get('gap_rate') or 0) > 0)
        avg_gap = sum(r.get('gap_rate', 0) or 0 for r in results) / total
        
        return {
            'total': total,
            'wins': wins,
            'win_rate': round(wins / total * 100, 1) if total > 0 else 0,
            'avg_gap': round(avg_gap, 2),
        }


def run_daily_learning() -> Dict:
    """일일 학습 실행 (스케줄러용)
    
    Returns:
        학습 결과 요약
    """
    logger.info("=" * 50)
    logger.info("🧠 일일 학습 시작")
    logger.info("=" * 50)
    
    learner = LearnerService()
    result = {'closing': {}, 'k_value': {}}
    
    # 1. 종가매매 상관관계 분석 & 가중치 업데이트
    logger.info("\n[1/2] 종가매매 학습")
    try:
        correlations = learner.analyze_closing_correlations(days=30)
        updated = learner.update_closing_weights(correlations)
        result['closing'] = {
            'correlations': correlations,
            'updated_weights': updated,
        }
    except Exception as e:
        logger.error(f"종가매매 학습 실패: {e}")
    
    # 2. K값 성과 분석
    logger.info("\n[2/2] K값 전략 분석")
    try:
        k_stats = learner.analyze_k_performance(days=30)
        k_analysis = learner.optimize_k_params(days=30)
        result['k_value'] = {
            'stats': k_stats,
            'analysis': k_analysis,
        }
    except Exception as e:
        logger.error(f"K값 분석 실패: {e}")
    
    logger.info("=" * 50)
    logger.info("🧠 일일 학습 완료")
    logger.info("=" * 50)
    
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_daily_learning()
