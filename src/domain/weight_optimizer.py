"""
가중치 최적화 모듈

책임:
- 지표별 상관관계 분석
- 최적 가중치 계산
- 가중치 범위 검증
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
import math

from src.config.constants import (
    WEIGHT_MIN,
    WEIGHT_MAX,
    WEIGHT_DEFAULT,
    WEIGHT_CHANGE_MAX,
    MIN_LEARNING_SAMPLES,
)

logger = logging.getLogger(__name__)


@dataclass
class CorrelationResult:
    """상관관계 분석 결과"""
    indicator_name: str
    correlation: float  # -1.0 ~ 1.0
    sample_count: int
    p_value: Optional[float] = None  # 유의수준


@dataclass
class WeightOptimizationResult:
    """가중치 최적화 결과"""
    old_weights: Dict[str, float]
    new_weights: Dict[str, float]
    changes: Dict[str, float]  # 변경폭
    correlations: Dict[str, float]
    reason: str  # 최적화 사유


def calculate_mean(values: List[float]) -> float:
    """평균 계산"""
    if not values:
        return 0.0
    return sum(values) / len(values)


def calculate_std(values: List[float], mean: Optional[float] = None) -> float:
    """표준편차 계산"""
    if len(values) < 2:
        return 0.0
    
    if mean is None:
        mean = calculate_mean(values)
    
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)


def calculate_pearson_correlation(x_values: List[float], y_values: List[float]) -> float:
    """피어슨 상관계수 계산
    
    Args:
        x_values: X 변수 값들 (지표 점수)
        y_values: Y 변수 값들 (익일 수익률)
        
    Returns:
        상관계수 (-1.0 ~ 1.0)
    """
    if len(x_values) != len(y_values) or len(x_values) < 3:
        return 0.0
    
    n = len(x_values)
    
    # 평균
    x_mean = calculate_mean(x_values)
    y_mean = calculate_mean(y_values)
    
    # 표준편차
    x_std = calculate_std(x_values, x_mean)
    y_std = calculate_std(y_values, y_mean)
    
    # 표준편차가 0이면 상관관계 계산 불가
    if x_std == 0 or y_std == 0:
        return 0.0
    
    # 공분산
    covariance = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values)) / (n - 1)
    
    # 상관계수
    correlation = covariance / (x_std * y_std)
    
    # 범위 제한 (-1 ~ 1)
    return max(-1.0, min(1.0, correlation))


def analyze_correlation(
    indicator_scores: Dict[str, List[float]],
    next_day_returns: List[float],
) -> Dict[str, CorrelationResult]:
    """지표별 상관관계 분석
    
    Args:
        indicator_scores: 지표별 점수 리스트
            {'cci_value': [8.0, 7.5, ...], 'cci_slope': [...], ...}
        next_day_returns: 익일 시초가 수익률 리스트
            [2.5, -1.2, 3.1, ...]
            
    Returns:
        지표별 상관관계 결과
    """
    results = {}
    
    for indicator_name, scores in indicator_scores.items():
        if len(scores) != len(next_day_returns):
            logger.warning(
                f"데이터 길이 불일치: {indicator_name} ({len(scores)}) != "
                f"returns ({len(next_day_returns)})"
            )
            continue
        
        correlation = calculate_pearson_correlation(scores, next_day_returns)
        
        results[indicator_name] = CorrelationResult(
            indicator_name=indicator_name,
            correlation=correlation,
            sample_count=len(scores),
        )
        
        logger.debug(
            f"상관관계 분석: {indicator_name} = {correlation:.4f} "
            f"(n={len(scores)})"
        )
    
    return results


def calculate_optimal_weights(
    correlations: Dict[str, CorrelationResult],
    current_weights: Dict[str, float],
    learning_rate: float = 0.1,
) -> WeightOptimizationResult:
    """최적 가중치 계산
    
    상관관계가 높은 지표는 가중치 증가, 낮은 지표는 감소
    
    Args:
        correlations: 지표별 상관관계 결과
        current_weights: 현재 가중치
        learning_rate: 학습률 (0.0 ~ 1.0)
        
    Returns:
        가중치 최적화 결과
    """
    new_weights = current_weights.copy()
    changes = {}
    
    # 상관관계 정규화 (전체 합이 1이 되도록)
    corr_values = [r.correlation for r in correlations.values()]
    corr_sum = sum(abs(c) for c in corr_values) if corr_values else 1.0
    
    for indicator_name, corr_result in correlations.items():
        if indicator_name not in current_weights:
            continue
        
        current_weight = current_weights[indicator_name]
        
        # 상관관계 기반 조정
        # 양의 상관관계: 가중치 증가
        # 음의 상관관계: 가중치 감소
        normalized_corr = corr_result.correlation / corr_sum if corr_sum > 0 else 0
        
        # 변경폭 계산 (learning_rate 적용)
        delta = normalized_corr * learning_rate * WEIGHT_CHANGE_MAX * 5
        
        # 최대 변경폭 제한
        delta = max(-WEIGHT_CHANGE_MAX, min(WEIGHT_CHANGE_MAX, delta))
        
        # 새 가중치 계산
        new_weight = current_weight + delta
        
        # 가중치 범위 검증
        new_weight = validate_weight(new_weight)
        
        new_weights[indicator_name] = new_weight
        changes[indicator_name] = new_weight - current_weight
        
        logger.debug(
            f"가중치 조정: {indicator_name} "
            f"{current_weight:.2f} -> {new_weight:.2f} "
            f"(delta={delta:+.4f}, corr={corr_result.correlation:.4f})"
        )
    
    # 결과 생성
    corr_dict = {name: r.correlation for name, r in correlations.items()}
    
    return WeightOptimizationResult(
        old_weights=current_weights,
        new_weights=new_weights,
        changes=changes,
        correlations=corr_dict,
        reason=_generate_optimization_reason(correlations, changes),
    )


def validate_weight(weight: float) -> float:
    """가중치 범위 검증
    
    Args:
        weight: 검증할 가중치
        
    Returns:
        범위 내로 조정된 가중치 (WEIGHT_MIN ~ WEIGHT_MAX)
    """
    return max(WEIGHT_MIN, min(WEIGHT_MAX, weight))


def validate_weights(weights: Dict[str, float]) -> Dict[str, float]:
    """전체 가중치 범위 검증
    
    Args:
        weights: 검증할 가중치 딕셔너리
        
    Returns:
        범위 내로 조정된 가중치 딕셔너리
    """
    return {name: validate_weight(w) for name, w in weights.items()}


def should_optimize(sample_count: int) -> bool:
    """가중치 최적화 실행 여부 판단
    
    Args:
        sample_count: 학습 샘플 수
        
    Returns:
        최적화 실행 여부
    """
    return sample_count >= MIN_LEARNING_SAMPLES


def _generate_optimization_reason(
    correlations: Dict[str, CorrelationResult],
    changes: Dict[str, float],
) -> str:
    """최적화 사유 생성"""
    if not changes:
        return "변경 없음"
    
    # 가장 많이 변경된 지표 찾기
    max_change_name = max(changes.keys(), key=lambda k: abs(changes[k]))
    max_change = changes[max_change_name]
    
    # 상관관계가 가장 높은/낮은 지표
    if correlations:
        best_corr = max(correlations.values(), key=lambda r: r.correlation)
        worst_corr = min(correlations.values(), key=lambda r: r.correlation)
        
        return (
            f"최고 상관: {best_corr.indicator_name}({best_corr.correlation:+.3f}), "
            f"최저 상관: {worst_corr.indicator_name}({worst_corr.correlation:+.3f}), "
            f"최대 변경: {max_change_name}({max_change:+.3f})"
        )
    
    return f"최대 변경: {max_change_name}({max_change:+.3f})"


def get_default_weights() -> Dict[str, float]:
    """기본 가중치 반환"""
    return {
        'cci_value': WEIGHT_DEFAULT,
        'cci_slope': WEIGHT_DEFAULT,
        'ma20_slope': WEIGHT_DEFAULT,
        'candle': WEIGHT_DEFAULT,
        'change': WEIGHT_DEFAULT,
    }


if __name__ == "__main__":
    # 테스트
    logging.basicConfig(level=logging.DEBUG)
    
    # 샘플 데이터
    indicator_scores = {
        'cci_value': [7.0, 8.0, 6.5, 7.5, 8.5, 7.0, 9.0, 6.0, 8.0, 7.5] * 3,
        'cci_slope': [6.0, 7.0, 5.5, 6.5, 7.5, 6.0, 8.0, 5.0, 7.0, 6.5] * 3,
        'ma20_slope': [5.0, 6.0, 4.5, 5.5, 6.5, 5.0, 7.0, 4.0, 6.0, 5.5] * 3,
        'candle': [8.0, 9.0, 7.5, 8.5, 9.5, 8.0, 10.0, 7.0, 9.0, 8.5] * 3,
        'change': [7.0, 8.0, 6.5, 7.5, 8.5, 7.0, 9.0, 6.0, 8.0, 7.5] * 3,
    }
    
    # 익일 수익률 (점수와 양의 상관관계가 있도록)
    next_day_returns = [2.5, 3.0, 1.5, 2.0, 3.5, 2.0, 4.0, 1.0, 3.0, 2.5] * 3
    
    # 상관관계 분석
    print("\n=== 상관관계 분석 ===")
    correlations = analyze_correlation(indicator_scores, next_day_returns)
    for name, result in correlations.items():
        print(f"{name}: {result.correlation:.4f} (n={result.sample_count})")
    
    # 가중치 최적화
    print("\n=== 가중치 최적화 ===")
    current_weights = get_default_weights()
    optimization = calculate_optimal_weights(correlations, current_weights)
    
    print(f"사유: {optimization.reason}")
    print("\n변경 내역:")
    for name in current_weights:
        old = optimization.old_weights[name]
        new = optimization.new_weights[name]
        change = optimization.changes.get(name, 0)
        print(f"  {name}: {old:.2f} -> {new:.2f} ({change:+.4f})")
