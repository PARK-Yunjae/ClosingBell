"""기술 지표 계산 테스트"""

import pytest
from datetime import date
from typing import List

from src.domain.indicators import (
    calculate_cci,
    calculate_ma20,
    calculate_cci_slope,
    calculate_ma20_slope,
    calculate_upper_wick_ratio,
    is_bullish_candle,
)
from src.domain.models import DailyPrice
from src.config.constants import CCI_PERIOD, MA20_PERIOD


class TestCCI:
    """CCI 계산 테스트"""
    
    def test_cci_calculation_with_sample_data(self, sample_daily_prices):
        """샘플 데이터로 CCI 계산"""
        # CCI 계산에 최소 14일 데이터 필요
        cci = calculate_cci(sample_daily_prices)
        
        assert cci is not None
        assert isinstance(cci, float)
        # CCI는 일반적으로 -300 ~ +300 범위
        assert -500 < cci < 500
    
    def test_cci_insufficient_data(self):
        """데이터 부족 시 None 반환"""
        # 14일 미만 데이터
        prices = [
            DailyPrice(
                date=date(2026, 1, i + 1),
                open=10000, high=10100, low=9900, close=10050,
                volume=1000000, trading_value=10050000000.0
            )
            for i in range(10)
        ]
        
        cci = calculate_cci(prices)
        assert cci is None
    
    def test_cci_uptrend_positive(self, sample_daily_prices):
        """상승 추세에서 CCI가 양수"""
        cci = calculate_cci(sample_daily_prices)
        # 상승 추세 데이터이므로 CCI가 양수여야 함
        assert cci > 0


class TestMA20:
    """MA20 계산 테스트"""
    
    def test_ma20_calculation(self, sample_daily_prices):
        """MA20 계산"""
        ma20 = calculate_ma20(sample_daily_prices)
        
        assert ma20 is not None
        assert isinstance(ma20, float)
        assert ma20 > 0
    
    def test_ma20_insufficient_data(self):
        """데이터 부족 시 None 반환"""
        prices = [
            DailyPrice(
                date=date(2026, 1, i + 1),
                open=10000, high=10100, low=9900, close=10050,
                volume=1000000, trading_value=10050000000.0
            )
            for i in range(15)  # 20일 미만
        ]
        
        ma20 = calculate_ma20(prices)
        assert ma20 is None
    
    def test_ma20_average_correct(self, sample_daily_prices):
        """MA20이 최근 20일 종가 평균과 일치"""
        ma20 = calculate_ma20(sample_daily_prices)
        
        # 수동 계산
        recent_20 = sample_daily_prices[-20:]
        expected_ma20 = sum(p.close for p in recent_20) / 20
        
        assert abs(ma20 - expected_ma20) < 0.01


class TestSlopes:
    """기울기 계산 테스트"""
    
    def test_cci_slope_uptrend(self, sample_daily_prices):
        """상승 추세에서 CCI 기울기가 양수"""
        slope = calculate_cci_slope(sample_daily_prices, days=5)
        # 상승 추세이므로 기울기가 양수
        assert slope > 0
    
    def test_ma20_slope_uptrend(self, sample_daily_prices):
        """상승 추세에서 MA20 기울기가 양수"""
        slope = calculate_ma20_slope(sample_daily_prices, days=7)
        assert slope > 0
    
    def test_ma20_slope_downtrend(self, sample_downtrend_prices):
        """하락 추세에서 MA20 기울기가 음수"""
        slope = calculate_ma20_slope(sample_downtrend_prices, days=7)
        assert slope < 0


class TestCandleAnalysis:
    """캔들 분석 테스트"""
    
    def test_bullish_candle(self):
        """양봉 판별"""
        candle = DailyPrice(
            date=date(2026, 1, 1),
            open=10000, high=10200, low=9900, close=10150,
            volume=1000000, trading_value=10150000000.0
        )
        assert is_bullish_candle(candle) is True
    
    def test_bearish_candle(self):
        """음봉 판별"""
        candle = DailyPrice(
            date=date(2026, 1, 1),
            open=10150, high=10200, low=9900, close=10000,
            volume=1000000, trading_value=10000000000.0
        )
        assert is_bullish_candle(candle) is False
    
    def test_upper_wick_ratio_calculation(self):
        """윗꼬리 비율 계산"""
        # 양봉: open=100, close=150, high=170, low=90
        # 전체 범위 = 170 - 90 = 80
        # 윗꼬리 = 170 - 150 = 20
        # 비율 = 20 / 80 = 0.25
        candle = DailyPrice(
            date=date(2026, 1, 1),
            open=100, high=170, low=90, close=150,
            volume=1000, trading_value=150000.0
        )
        ratio = calculate_upper_wick_ratio(candle)
        assert abs(ratio - 0.25) < 0.01
    
    def test_upper_wick_ratio_no_wick(self):
        """윗꼬리가 없는 경우"""
        # close == high인 경우
        candle = DailyPrice(
            date=date(2026, 1, 1),
            open=100, high=150, low=90, close=150,
            volume=1000, trading_value=150000.0
        )
        ratio = calculate_upper_wick_ratio(candle)
        assert ratio == 0.0
