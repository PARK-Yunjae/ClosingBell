"""기술 지표 계산 테스트"""

import pytest
from datetime import date
from typing import List

from src.domain.indicators import (
    calculate_cci,
    calculate_ma,
    calculate_cci_slope,
    calculate_ma20_slope,
    analyze_candle,
)
from src.domain.models import DailyPrice
from src.config.constants import CCI_PERIOD, MA20_PERIOD


class TestCCI:
    """CCI 계산 테스트"""
    
    def test_cci_calculation_with_sample_data(self, sample_daily_prices):
        """샘플 데이터로 CCI 계산"""
        # CCI 계산에 최소 14일 데이터 필요
        cci_values = calculate_cci(sample_daily_prices)
        
        assert cci_values is not None
        assert len(cci_values) > 0
        # 최신 값 확인
        cci = cci_values[-1]
        assert isinstance(cci, float)
        # CCI는 일반적으로 -300 ~ +300 범위
        assert -500 < cci < 500
    
    def test_cci_insufficient_data(self):
        """데이터 부족 시 빈 리스트 반환"""
        # 14일 미만 데이터
        prices = [
            DailyPrice(
                date=date(2026, 1, i + 1),
                open=10000, high=10100, low=9900, close=10050,
                volume=1000000, trading_value=10050000000.0
            )
            for i in range(10)
        ]
        
        cci_values = calculate_cci(prices)
        assert cci_values == []
    
    def test_cci_uptrend_positive(self, sample_daily_prices):
        """상승 추세에서 CCI가 양수"""
        cci_values = calculate_cci(sample_daily_prices)
        # 상승 추세 데이터이므로 최신 CCI가 양수여야 함
        assert cci_values[-1] > 0


class TestMA20:
    """MA20 계산 테스트"""
    
    def test_ma20_calculation(self, sample_daily_prices):
        """MA20 계산"""
        ma_values = calculate_ma(sample_daily_prices)
        
        assert ma_values is not None
        assert len(ma_values) > 0
        ma20 = ma_values[-1]
        assert isinstance(ma20, float)
        assert ma20 > 0
    
    def test_ma20_insufficient_data(self):
        """데이터 부족 시 빈 리스트 반환"""
        prices = [
            DailyPrice(
                date=date(2026, 1, i + 1),
                open=10000, high=10100, low=9900, close=10050,
                volume=1000000, trading_value=10050000000.0
            )
            for i in range(15)  # 20일 미만
        ]
        
        ma_values = calculate_ma(prices)
        assert ma_values == []
    
    def test_ma20_average_correct(self, sample_daily_prices):
        """MA20이 최근 20일 종가 평균과 일치"""
        ma_values = calculate_ma(sample_daily_prices)
        ma20 = ma_values[-1]
        
        # 수동 계산
        recent_20 = sample_daily_prices[-20:]
        expected_ma20 = sum(p.close for p in recent_20) / 20
        
        assert abs(ma20 - expected_ma20) < 0.01


class TestSlopes:
    """기울기 계산 테스트"""
    
    def test_cci_slope_uptrend(self, sample_daily_prices):
        """상승 추세에서 CCI 기울기가 양수"""
        cci_values = calculate_cci(sample_daily_prices)
        slope = calculate_cci_slope(cci_values, period=5)
        # 상승 추세이므로 기울기가 양수
        assert slope > 0
    
    def test_ma20_slope_uptrend(self, sample_daily_prices):
        """상승 추세에서 MA20 기울기가 양수"""
        ma_values = calculate_ma(sample_daily_prices)
        slope = calculate_ma20_slope(ma_values, period=7)
        assert slope > 0
    
    def test_ma20_slope_downtrend(self, sample_downtrend_prices):
        """하락 추세에서 MA20 기울기가 음수"""
        ma_values = calculate_ma(sample_downtrend_prices)
        slope = calculate_ma20_slope(ma_values, period=7)
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
        analysis = analyze_candle(candle, ma20=10000)
        assert analysis.is_bullish is True
    
    def test_bearish_candle(self):
        """음봉 판별"""
        candle = DailyPrice(
            date=date(2026, 1, 1),
            open=10150, high=10200, low=9900, close=10000,
            volume=1000000, trading_value=10000000000.0
        )
        analysis = analyze_candle(candle, ma20=10000)
        assert analysis.is_bullish is False
    
    def test_upper_wick_ratio_calculation(self):
        """윗꼬리 비율 계산"""
        # 양봉: open=100, close=150, high=170, low=90
        # 몸통 = 50
        # 윗꼬리 = 170 - 150 = 20
        # 비율 = 20 / 50 = 0.4
        candle = DailyPrice(
            date=date(2026, 1, 1),
            open=100, high=170, low=90, close=150,
            volume=1000, trading_value=150000.0
        )
        analysis = analyze_candle(candle, ma20=140)
        assert abs(analysis.upper_wick_ratio - 0.4) < 0.01
    
    def test_upper_wick_ratio_no_wick(self):
        """윗꼬리가 없는 경우"""
        # close == high인 경우
        candle = DailyPrice(
            date=date(2026, 1, 1),
            open=100, high=150, low=90, close=150,
            volume=1000, trading_value=150000.0
        )
        analysis = analyze_candle(candle, ma20=140)
        assert analysis.upper_wick_ratio == 0.0
