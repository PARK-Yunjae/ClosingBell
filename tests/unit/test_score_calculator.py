"""점수 산출 테스트"""

import pytest
from datetime import date
from typing import List

from src.domain.score_calculator import (
    calculate_cci_value_score,
    calculate_cci_slope_score,
    calculate_ma20_slope_score,
    calculate_candle_score,
    calculate_change_score,
    calculate_total_score,
    ScoreCalculator,
)
from src.domain.models import DailyPrice, ScoreDetail
from src.config.constants import (
    SCORE_MAX,
    SCORE_MIN,
    CCI_OPTIMAL,
    CHANGE_OPTIMAL_MIN,
    CHANGE_OPTIMAL_MAX,
)


class TestCCIValueScore:
    """CCI 값 점수 테스트"""
    
    def test_optimal_cci_max_score(self):
        """CCI 180 근처에서 최고점 (10점)"""
        score = calculate_cci_value_score(180)
        assert score == SCORE_MAX
    
    def test_cci_175_high_score(self):
        """CCI 175~185 구간에서 높은 점수"""
        score = calculate_cci_value_score(175)
        assert score >= 9.0
        
        score = calculate_cci_value_score(185)
        assert score >= 9.0
    
    def test_cci_far_from_optimal_lower_score(self):
        """CCI가 180에서 멀수록 낮은 점수"""
        score_180 = calculate_cci_value_score(180)
        score_140 = calculate_cci_value_score(140)
        score_100 = calculate_cci_value_score(100)
        
        assert score_180 > score_140 > score_100
    
    def test_extreme_high_cci_penalty(self):
        """CCI 400 이상에서 강한 감점"""
        score = calculate_cci_value_score(450)
        assert score <= 2.0
    
    def test_negative_cci_low_score(self):
        """음수 CCI에서 낮은 점수"""
        score = calculate_cci_value_score(-50)
        assert score <= 3.0


class TestCCISlopeScore:
    """CCI 기울기 점수 테스트"""
    
    def test_strong_uptrend_max_score(self):
        """강한 상승세에서 최고점"""
        score = calculate_cci_slope_score(slope=20, current_cci=150)
        assert score >= 9.0
    
    def test_flat_trend_middle_score(self):
        """횡보에서 중간 점수"""
        score = calculate_cci_slope_score(slope=1, current_cci=150)
        assert 4.0 <= score <= 6.0
    
    def test_downtrend_low_score(self):
        """하락세에서 낮은 점수"""
        score = calculate_cci_slope_score(slope=-10, current_cci=150)
        assert score <= 4.0
    
    def test_high_cci_downtrend_extra_penalty(self):
        """CCI 200 이상에서 하락 시 추가 감점"""
        # 일반 구간에서 하락
        score_normal = calculate_cci_slope_score(slope=-5, current_cci=150)
        # 고점에서 하락 (추가 감점)
        score_high = calculate_cci_slope_score(slope=-5, current_cci=220)
        
        assert score_high <= score_normal


class TestMA20SlopeScore:
    """MA20 기울기 점수 테스트"""
    
    def test_strong_uptrend_max_score(self):
        """강한 상승세 (2% 이상)에서 최고점"""
        score = calculate_ma20_slope_score(2.5)
        assert score >= 9.0
    
    def test_moderate_uptrend_good_score(self):
        """적당한 상승세 (1%)에서 좋은 점수"""
        score = calculate_ma20_slope_score(1.0)
        assert score >= 7.0
    
    def test_flat_middle_score(self):
        """횡보에서 중간 점수"""
        score = calculate_ma20_slope_score(0.0)
        assert 4.0 <= score <= 6.0
    
    def test_downtrend_low_score(self):
        """하락세에서 낮은 점수"""
        score = calculate_ma20_slope_score(-2.0)
        assert score <= 3.0


class TestCandleScore:
    """양봉 품질 점수 테스트"""
    
    def test_ideal_candle_max_score(self):
        """이상적인 양봉 (윗꼬리 짧음 + MA20 위 적당히)"""
        score = calculate_candle_score(
            is_bullish=True,
            upper_wick_ratio=0.05,  # 5% 윗꼬리
            ma20_position=2.0,      # MA20 위 2%
        )
        assert score >= 9.0
    
    def test_bearish_candle_low_score(self):
        """음봉에서 낮은 점수"""
        score = calculate_candle_score(
            is_bullish=False,
            upper_wick_ratio=0.3,
            ma20_position=2.0,
        )
        assert score <= 4.0
    
    def test_long_upper_wick_penalty(self):
        """긴 윗꼬리에서 감점"""
        score_short = calculate_candle_score(True, 0.1, 2.0)
        score_long = calculate_candle_score(True, 0.5, 2.0)
        
        assert score_short > score_long
    
    def test_far_above_ma20_penalty(self):
        """MA20 대비 너무 높으면 감점 (과열)"""
        score_moderate = calculate_candle_score(True, 0.1, 2.0)
        score_overheat = calculate_candle_score(True, 0.1, 8.0)
        
        assert score_moderate > score_overheat


class TestChangeScore:
    """상승률 점수 테스트"""
    
    def test_optimal_change_max_score(self):
        """10~15% 상승에서 최고점"""
        score = calculate_change_score(12.0)
        assert score == SCORE_MAX
    
    def test_moderate_change_good_score(self):
        """5~10% 상승에서 좋은 점수"""
        score = calculate_change_score(7.0)
        assert score >= 8.0
    
    def test_too_low_change_penalty(self):
        """1% 미만 상승에서 감점"""
        score = calculate_change_score(0.5)
        assert score <= 3.0
    
    def test_too_high_change_penalty(self):
        """30% 이상 상승에서 감점 (추격 위험)"""
        score = calculate_change_score(35.0)
        assert score <= 2.0
    
    def test_negative_change_low_score(self):
        """하락 시 낮은 점수"""
        score = calculate_change_score(-5.0)
        assert score <= 2.0


class TestTotalScore:
    """총점 계산 테스트"""
    
    def test_total_score_calculation(self, sample_score_detail):
        """총점이 개별 점수의 가중합과 일치"""
        weights = {
            'cci_value': 1.0,
            'cci_slope': 1.0,
            'ma20_slope': 1.0,
            'candle': 1.0,
            'change': 1.0,
        }
        
        expected = (
            sample_score_detail.cci_value * weights['cci_value'] +
            sample_score_detail.cci_slope * weights['cci_slope'] +
            sample_score_detail.ma20_slope * weights['ma20_slope'] +
            sample_score_detail.candle * weights['candle'] +
            sample_score_detail.change * weights['change']
        )
        
        total = calculate_total_score(sample_score_detail, weights)
        assert abs(total - expected) < 0.01
    
    def test_total_score_with_different_weights(self, sample_score_detail):
        """가중치 변경 시 총점 변화"""
        weights_equal = {'cci_value': 1.0, 'cci_slope': 1.0, 'ma20_slope': 1.0, 'candle': 1.0, 'change': 1.0}
        weights_cci_heavy = {'cci_value': 3.0, 'cci_slope': 2.0, 'ma20_slope': 1.0, 'candle': 1.0, 'change': 1.0}
        
        total_equal = calculate_total_score(sample_score_detail, weights_equal)
        total_heavy = calculate_total_score(sample_score_detail, weights_cci_heavy)
        
        # CCI 점수가 높으면 가중치 높을 때 총점도 높아야 함
        if sample_score_detail.cci_value > 5:
            assert total_heavy > total_equal
    
    def test_max_possible_score(self):
        """만점 계산 (50점)"""
        perfect_detail = ScoreDetail(
            cci_value=10.0,
            cci_slope=10.0,
            ma20_slope=10.0,
            candle=10.0,
            change=10.0,
            raw_cci=180.0,
            raw_ma20=50000,
        )
        weights = {'cci_value': 1.0, 'cci_slope': 1.0, 'ma20_slope': 1.0, 'candle': 1.0, 'change': 1.0}
        
        total = calculate_total_score(perfect_detail, weights)
        assert total == 50.0
