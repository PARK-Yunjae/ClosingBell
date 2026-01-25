"""
기술 지표 계산기

책임:
- CCI(14일) 계산
- 이동평균선(MA20) 계산
- 기울기 계산
- 캔들 패턴 분석

의존성:
- 없음 (순수 계산 로직)
"""

from typing import List, Optional
from dataclasses import dataclass

from src.domain.models import DailyPrice
from src.config.constants import (
    CCI_PERIOD,
    MA20_PERIOD,
    CCI_SLOPE_PERIOD,
    MA20_SLOPE_PERIOD,
)


@dataclass
class CandleAnalysis:
    """캔들 분석 결과"""
    is_bullish: bool            # 양봉 여부
    body_size: int              # 몸통 크기
    upper_wick_ratio: float     # 윗꼬리 비율 (몸통 대비)
    lower_wick_ratio: float     # 아랫꼬리 비율
    ma20_position: float        # MA20 대비 위치 (%)
    is_above_ma20: bool         # MA20 위 안착 여부


def calculate_typical_price(price: DailyPrice) -> float:
    """Typical Price 계산 (고가 + 저가 + 종가) / 3"""
    return (price.high + price.low + price.close) / 3


def calculate_mean_deviation(
    typical_prices: List[float],
    mean: float,
) -> float:
    """평균 편차 계산"""
    if not typical_prices:
        return 0.0
    deviations = [abs(tp - mean) for tp in typical_prices]
    return sum(deviations) / len(deviations)


def calculate_cci(
    prices: List[DailyPrice],
    period: int = CCI_PERIOD,
) -> List[float]:
    """CCI(Commodity Channel Index) 계산
    
    CCI = (TP - SMA(TP)) / (0.015 × Mean Deviation)
    - TP: Typical Price = (High + Low + Close) / 3
    - SMA: 단순이동평균
    - Mean Deviation: 평균 편차
    
    Args:
        prices: 일봉 데이터 리스트 (오래된 순)
        period: CCI 계산 기간 (기본 14일)
        
    Returns:
        CCI 값 리스트 (prices 길이 - period + 1)
    """
    if len(prices) < period:
        return []
    
    # Typical Price 계산
    typical_prices = [calculate_typical_price(p) for p in prices]
    
    cci_values = []
    for i in range(period - 1, len(prices)):
        # 현재 윈도우의 TP들
        window_tps = typical_prices[i - period + 1:i + 1]
        
        # SMA 계산
        sma = sum(window_tps) / period
        
        # Mean Deviation 계산
        mean_dev = calculate_mean_deviation(window_tps, sma)
        
        # CCI 계산
        if mean_dev == 0:
            cci = 0.0
        else:
            cci = (typical_prices[i] - sma) / (0.015 * mean_dev)
        
        cci_values.append(cci)
    
    return cci_values


def calculate_ma(
    prices: List[DailyPrice],
    period: int = MA20_PERIOD,
) -> List[float]:
    """이동평균선(MA) 계산
    
    Args:
        prices: 일봉 데이터 리스트 (오래된 순)
        period: MA 기간 (기본 20일)
        
    Returns:
        MA 값 리스트 (prices 길이 - period + 1)
    """
    if len(prices) < period:
        return []
    
    close_prices = [p.close for p in prices]
    
    ma_values = []
    for i in range(period - 1, len(prices)):
        window = close_prices[i - period + 1:i + 1]
        ma = sum(window) / period
        ma_values.append(ma)
    
    return ma_values


def calculate_slope(
    values: List[float],
    period: int = 5,
) -> float:
    """기울기 계산 (선형 회귀 기반)
    
    최근 N일의 값으로 기울기를 계산
    
    Args:
        values: 값 리스트 (오래된 순)
        period: 기울기 계산 기간
        
    Returns:
        기울기 값 (양수: 상승, 음수: 하락)
    """
    if len(values) < period:
        return 0.0
    
    recent = values[-period:]
    n = len(recent)
    
    # 선형 회귀 기울기 계산
    # slope = Σ((x - x̄)(y - ȳ)) / Σ((x - x̄)²)
    x_values = list(range(n))
    x_mean = sum(x_values) / n
    y_mean = sum(recent) / n
    
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, recent))
    denominator = sum((x - x_mean) ** 2 for x in x_values)
    
    if denominator == 0:
        return 0.0
    
    return numerator / denominator


def calculate_slope_percentage(
    values: List[float],
    period: int = 7,
) -> float:
    """기울기를 백분율로 계산
    
    시작점 대비 끝점의 변화율
    
    Args:
        values: 값 리스트 (오래된 순)
        period: 계산 기간
        
    Returns:
        백분율 변화 (%)
    """
    if len(values) < period:
        return 0.0
    
    recent = values[-period:]
    start = recent[0]
    end = recent[-1]
    
    if start == 0:
        return 0.0
    
    return ((end - start) / start) * 100


def calculate_cci_slope(
    cci_values: List[float],
    period: int = CCI_SLOPE_PERIOD,
) -> float:
    """CCI 기울기 계산 (절대값 기반)
    
    Args:
        cci_values: CCI 값 리스트
        period: 기울기 계산 기간 (기본 5일)
        
    Returns:
        기울기 값 (일일 변화량)
    """
    return calculate_slope(cci_values, period)


def calculate_ma20_slope(
    ma_values: List[float],
    period: int = MA20_SLOPE_PERIOD,
) -> float:
    """MA20 기울기 계산 (백분율 기반)
    
    Args:
        ma_values: MA 값 리스트
        period: 기울기 계산 기간 (기본 7일)
        
    Returns:
        백분율 변화 (%)
    """
    return calculate_slope_percentage(ma_values, period)


def analyze_candle(
    price: DailyPrice,
    ma20: float,
) -> CandleAnalysis:
    """캔들 패턴 분석
    
    Args:
        price: 당일 캔들
        ma20: 당일 MA20 값
        
    Returns:
        캔들 분석 결과
    """
    is_bullish = price.is_bullish
    body_size = price.body_size
    
    # 윗꼬리 비율
    if body_size == 0:
        upper_wick_ratio = 1.0 if price.upper_wick > 0 else 0.0
        lower_wick_ratio = 1.0 if price.lower_wick > 0 else 0.0
    else:
        upper_wick_ratio = price.upper_wick / body_size
        lower_wick_ratio = price.lower_wick / body_size
    
    # MA20 대비 위치
    if ma20 == 0:
        ma20_position = 0.0
        is_above_ma20 = False
    else:
        ma20_position = ((price.close - ma20) / ma20) * 100
        is_above_ma20 = price.close > ma20
    
    return CandleAnalysis(
        is_bullish=is_bullish,
        body_size=body_size,
        upper_wick_ratio=upper_wick_ratio,
        lower_wick_ratio=lower_wick_ratio,
        ma20_position=ma20_position,
        is_above_ma20=is_above_ma20,
    )


def check_continuous_rise(
    values: List[float],
    period: int = 5,
) -> bool:
    """연속 상승 여부 확인
    
    Args:
        values: 값 리스트
        period: 확인 기간
        
    Returns:
        연속 상승 여부
    """
    if len(values) < period:
        return False
    
    recent = values[-period:]
    for i in range(1, len(recent)):
        if recent[i] <= recent[i - 1]:
            return False
    return True


def count_rising_days(
    values: List[float],
    period: int = 5,
) -> int:
    """상승 일수 카운트
    
    Args:
        values: 값 리스트
        period: 확인 기간
        
    Returns:
        상승한 일수
    """
    if len(values) < period:
        return 0
    
    recent = values[-period:]
    count = 0
    for i in range(1, len(recent)):
        if recent[i] > recent[i - 1]:
            count += 1
    return count


# ============================================================
# 통합 지표 계산 함수
# ============================================================

@dataclass
class IndicatorResult:
    """지표 계산 결과"""
    cci: float              # 최신 CCI 값
    cci_slope: float        # CCI 기울기
    ma20: float             # 최신 MA20 값
    ma20_slope: float       # MA20 기울기 (%)
    candle: CandleAnalysis  # 캔들 분석
    
    # 전체 값 (분석용)
    cci_values: List[float]
    ma20_values: List[float]


def calculate_all_indicators(
    prices: List[DailyPrice],
) -> Optional[IndicatorResult]:
    """모든 지표 계산
    
    Args:
        prices: 일봉 데이터 (오래된 순, 최소 20일)
        
    Returns:
        지표 계산 결과 또는 None (데이터 부족 시)
    """
    if len(prices) < MA20_PERIOD:
        return None
    
    # CCI 계산
    cci_values = calculate_cci(prices, CCI_PERIOD)
    if not cci_values:
        return None
    
    # MA20 계산
    ma20_values = calculate_ma(prices, MA20_PERIOD)
    if not ma20_values:
        return None
    
    # 기울기 계산
    cci_slope = calculate_cci_slope(cci_values, CCI_SLOPE_PERIOD)
    ma20_slope = calculate_ma20_slope(ma20_values, MA20_SLOPE_PERIOD)
    
    # 캔들 분석
    today_candle = prices[-1]
    today_ma20 = ma20_values[-1]
    candle_analysis = analyze_candle(today_candle, today_ma20)
    
    return IndicatorResult(
        cci=cci_values[-1],
        cci_slope=cci_slope,
        ma20=ma20_values[-1],
        ma20_slope=ma20_slope,
        candle=candle_analysis,
        cci_values=cci_values,
        ma20_values=ma20_values,
    )


if __name__ == "__main__":
    # 테스트용 더미 데이터
    from datetime import date, timedelta
    
    # 20일치 더미 데이터 생성
    base_date = date.today()
    dummy_prices = []
    
    base_price = 50000
    for i in range(25):
        d = base_date - timedelta(days=24 - i)
        # 상승 추세 시뮬레이션
        close = base_price + (i * 500) + (i % 3 - 1) * 200
        open_price = close - 300 + (i % 2) * 100
        high = max(close, open_price) + 200
        low = min(close, open_price) - 200
        
        dummy_prices.append(DailyPrice(
            date=d,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=1000000 + i * 10000,
        ))
    
    print("=== 지표 계산 테스트 ===")
    result = calculate_all_indicators(dummy_prices)
    
    if result:
        print(f"CCI: {result.cci:.2f}")
        print(f"CCI 기울기: {result.cci_slope:.2f}")
        print(f"MA20: {result.ma20:,.0f}")
        print(f"MA20 기울기: {result.ma20_slope:.2f}%")
        print(f"양봉 여부: {result.candle.is_bullish}")
        print(f"윗꼬리 비율: {result.candle.upper_wick_ratio:.2f}")
        print(f"MA20 위 안착: {result.candle.is_above_ma20}")
        print(f"MA20 대비 위치: {result.candle.ma20_position:.2f}%")
    else:
        print("데이터 부족으로 계산 불가")
