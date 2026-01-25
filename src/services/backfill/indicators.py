"""
ClosingBell v6.3.2 백필 - 기술적 지표 계산

⚠️ 중요: 실시간(score_calculator.py)과 100% 동일한 로직!
   - 기본 점수 90점 (6개 지표 각 15점)
   - 보너스 10점 (CCI 상승 4점, MA20 3일상승 3점, 고가≠종가 3점)
   
v6.3.2 변경사항:
   - CCI 기본 period를 14로 변경 (실시간과 동일)
   - 이전: period=20 → 현재: period=14
"""

import numpy as np
import pandas as pd
from typing import Optional, Tuple


def calculate_cci(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """CCI (Commodity Channel Index) 계산
    
    v6.3.2: period 기본값을 14로 변경 (실시간 ScoreCalculatorV5와 동일)
    - 실시간: src/config/constants.py의 CCI_PERIOD = 14
    - 백필: 동일하게 14일 기준
    """
    tp = (df['high'] + df['low'] + df['close']) / 3
    sma = tp.rolling(window=period).mean()
    mad = tp.rolling(window=period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    cci = (tp - sma) / (0.015 * mad)
    return cci


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """RSI (Relative Strength Index) 계산"""
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_ma(df: pd.DataFrame, period: int) -> pd.Series:
    """이동평균 계산"""
    return df['close'].rolling(window=period).mean()


def calculate_disparity(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """이격도 계산 (현재가 / MA * 100 - 100)"""
    ma = calculate_ma(df, period)
    return (df['close'] / ma - 1) * 100


def calculate_volume_ratio(df: pd.DataFrame, period: int = 5) -> pd.Series:
    """거래량 비율 (현재 / 평균)"""
    avg_vol = df['volume'].rolling(window=period).mean()
    return df['volume'] / avg_vol


def calculate_volume_ratio_exclude_today(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """거래량 비율 (당일 제외 평균) - 실시간과 동일
    
    실시간 score_calculator.py와 동일한 방식:
    - 20일 거래량 중 당일 제외한 19일 평균 대비 비율
    """
    # 당일 제외 평균: shift(1)로 하루 밀어서 계산
    avg_vol_excl_today = df['volume'].shift(1).rolling(window=period-1).mean()
    return df['volume'] / avg_vol_excl_today


def calculate_consecutive_up(df: pd.DataFrame) -> pd.Series:
    """연속 양봉 일수"""
    is_up = df['close'] > df['open']
    groups = (~is_up).cumsum()
    consec = is_up.groupby(groups).cumsum()
    return consec


def calculate_candle_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """캔들 지표 계산"""
    result = pd.DataFrame(index=df.index)
    
    body = df['close'] - df['open']
    result['body_pct'] = body / df['open'] * 100
    result['is_bullish'] = (df['close'] > df['open']).astype(int)
    
    lower_shadow = df['open'].where(df['close'] > df['open'], df['close']) - df['low']
    result['lower_shadow_pct'] = lower_shadow / df['close'] * 100
    
    upper_shadow = df['high'] - df['close'].where(df['close'] > df['open'], df['open'])
    result['upper_shadow_pct'] = upper_shadow / df['close'] * 100
    
    rolling_high = df['high'].rolling(window=20).max()
    rolling_low = df['low'].rolling(window=20).min()
    result['position_in_20d'] = (df['close'] - rolling_low) / (rolling_high - rolling_low)
    
    return result


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """모든 지표 계산
    
    v6.3.1: 보너스 계산용 지표 추가
    - prev_cci: 전일 CCI (CCI 상승 보너스용)
    - ma20_3day_up: MA20 3일 연속 상승 여부
    - high_eq_close: 고가=종가 여부
    """
    result = df.copy()
    
    # 등락률
    result['change_rate'] = result['close'].pct_change() * 100
    
    # CCI
    result['cci'] = calculate_cci(result)
    result['prev_cci'] = result['cci'].shift(1)  # v6.3.1: 전일 CCI
    
    # RSI
    result['rsi'] = calculate_rsi(result)
    
    # 이동평균
    result['ma5'] = calculate_ma(result, 5)
    result['ma20'] = calculate_ma(result, 20)
    result['ma60'] = calculate_ma(result, 60)
    
    # MA20 3일 상승 여부 (v6.3.1)
    ma20_diff = result['ma20'].diff()
    result['ma20_3day_up'] = (
        (ma20_diff > 0) & 
        (ma20_diff.shift(1) > 0) & 
        (ma20_diff.shift(2) > 0)
    ).astype(int)
    
    # MA20 2일 상승 여부 (부분 보너스용)
    result['ma20_2day_up'] = (
        (ma20_diff > 0) & 
        (ma20_diff.shift(1) > 0)
    ).astype(int)
    
    # MA 대비 위치
    result['above_ma5'] = (result['close'] > result['ma5']).astype(int)
    result['above_ma20'] = (result['close'] > result['ma20']).astype(int)
    result['above_ma60'] = (result['close'] > result['ma60']).astype(int)
    
    # 이격도
    result['disparity_5'] = calculate_disparity(result, 5)
    result['disparity_20'] = calculate_disparity(result, 20)
    
    # 거래량 비율
    result['volume_ratio_5'] = calculate_volume_ratio(result, 5)
    result['volume_ratio_20'] = calculate_volume_ratio(result, 20)
    result['volume_ratio_19'] = calculate_volume_ratio_exclude_today(result, 20)  # 실시간과 동일
    
    # 연속 양봉
    result['consecutive_up'] = calculate_consecutive_up(result)
    
    # 캔들 지표
    candle_metrics = calculate_candle_metrics(result)
    for col in candle_metrics.columns:
        result[col] = candle_metrics[col]
    
    # 고가=종가 여부 (v6.3.1)
    result['high_eq_close'] = (
        (result['high'] == result['close']) & 
        (result['is_bullish'] == 1)
    ).astype(int)
    
    # 거래대금 (억원)
    result['trading_value'] = result['close'] * result['volume'] / 100_000_000
    
    return result


# ============================================================
# v6.3.1 점수 계산 함수들 (실시간 score_calculator.py와 동일)
# ============================================================

def calc_cci_score(cci: float) -> float:
    """CCI 점수 (15점 만점) - v6.5 단순화"""
    if pd.isna(cci):
        return 7.5
    if cci < 0:
        return max(0, 5 + cci * 0.05)
    if 160 <= cci <= 180:
        return 15.0
    if cci < 160:
        return max(5, 15 - (160 - cci) * 0.0625)
    return max(3, 15 - (cci - 180) * 0.1)


def calc_change_score(change_rate: float) -> float:
    """등락률 점수 (15점 만점) - v6.5 단순화"""
    if pd.isna(change_rate):
        return 7.5
    if change_rate < 0:
        return max(0, 5 + change_rate * 0.5)
    if change_rate >= 25:
        return 2.0
    if 4 <= change_rate <= 6:
        return 15.0
    if change_rate < 4:
        return max(7, 15 - (4 - change_rate) * 2)
    return max(3, 15 - (change_rate - 6) * 0.63)


def calc_distance_score(distance: float) -> float:
    """이격도 점수 (15점 만점) - v6.5 단순화"""
    if pd.isna(distance):
        return 7.5
    if distance < 0:
        return max(0, 5 + distance * 0.5)
    if 2 <= distance <= 8:
        return 15.0
    if distance < 2:
        return max(10, 15 - (2 - distance) * 2.5)
    return max(3, 15 - (distance - 8) * 0.6)


def calc_consec_score(consec_days: int) -> float:
    """연속양봉 점수 (15점 만점) - v6.5 단순화"""
    if pd.isna(consec_days):
        consec_days = 0
    consec_days = int(consec_days)
    
    if 2 <= consec_days <= 3:
        return 15.0
    if consec_days < 2:
        return 7 + consec_days * 4
    return max(2, 15 - (consec_days - 3) * 3)


def calc_volume_score(volume_ratio: float) -> float:
    """거래량비율 점수 (15점 만점) - 단순 선형"""
    if pd.isna(volume_ratio) or volume_ratio < 1:
        return 0.0
    normalized = (volume_ratio - 1) / 4
    normalized = max(0, min(1, normalized))
    return normalized * 15


def calc_candle_score(is_bullish: int, lower_shadow_pct: float) -> float:
    """캔들품질 점수 (15점 만점)"""
    if pd.isna(is_bullish):
        is_bullish = 0
    if pd.isna(lower_shadow_pct):
        lower_shadow_pct = 0.0
    
    bullish_score = 1.0 if is_bullish else 0.0
    lower_score = min(lower_shadow_pct / 3, 1.0)
    total = bullish_score * 0.5 + lower_score * 0.5
    return total * 15


# ============================================================
# v6.3.1 보너스 점수 계산 함수들
# ============================================================

def calc_cci_rising_bonus(cci: float, prev_cci: float) -> Tuple[float, bool]:
    """CCI 상승 보너스 (4점)"""
    if pd.isna(cci) or pd.isna(prev_cci):
        return 0.0, False
    
    is_rising = cci > prev_cci
    
    if is_rising:
        rise_amount = cci - prev_cci
        if rise_amount > 20:
            return 4.0, True
        elif rise_amount > 10:
            return 3.5, True
        elif rise_amount > 5:
            return 3.0, True
        else:
            return 2.5, True
    
    return 0.0, False


def calc_ma20_3day_bonus(ma20_3day_up: int, ma20_2day_up: int) -> Tuple[float, bool]:
    """MA20 3일 연속 상승 보너스 (3점)"""
    if ma20_3day_up == 1:
        return 3.0, True
    elif ma20_2day_up == 1:
        return 1.5, False
    return 0.0, False


def calc_high_eq_close_bonus(high_eq_close: int) -> Tuple[float, bool]:
    """고가≠종가 보너스 (3점)"""
    if high_eq_close == 1:
        return 0.0, True  # 고가=종가면 보너스 없음
    return 3.0, False


# ============================================================
# v6.3.1 통합 점수 계산
# ============================================================

def calculate_score(row: pd.Series) -> float:
    """종목 점수 계산 (v6.3.1 - 실시간과 동일)
    
    기본 점수 (90점):
    - CCI: 15점
    - 등락률: 15점
    - 이격도: 15점
    - 연속양봉: 15점
    - 거래량비: 15점
    - 캔들품질: 15점
    
    보너스 (10점):
    - CCI 상승: 4점
    - MA20 3일상승: 3점
    - 고가≠종가: 3점
    """
    # 기본 점수 (90점)
    cci_score = calc_cci_score(row.get('cci'))
    change_score = calc_change_score(row.get('change_rate'))
    distance_score = calc_distance_score(row.get('disparity_20'))
    consec_score = calc_consec_score(row.get('consecutive_up'))
    volume_score = calc_volume_score(row.get('volume_ratio_19'))  # v6.3.2: 실시간과 동일하게 19일 평균
    candle_score = calc_candle_score(
        row.get('is_bullish', 0), 
        row.get('lower_shadow_pct', 0)
    )
    
    base_score = (
        cci_score + 
        change_score + 
        distance_score + 
        consec_score + 
        volume_score + 
        candle_score
    )
    
    # 보너스 (10점)
    cci_bonus, _ = calc_cci_rising_bonus(
        row.get('cci'), 
        row.get('prev_cci')
    )
    ma20_bonus, _ = calc_ma20_3day_bonus(
        row.get('ma20_3day_up', 0),
        row.get('ma20_2day_up', 0)
    )
    high_bonus, _ = calc_high_eq_close_bonus(
        row.get('high_eq_close', 0)
    )
    
    bonus_score = cci_bonus + ma20_bonus + high_bonus
    
    # 합계 (최대 100점)
    total = base_score + bonus_score
    return min(100.0, total)


def score_to_grade(score: float) -> str:
    """점수를 등급으로 변환"""
    if score >= 85:
        return 'S'
    elif score >= 75:
        return 'A'
    elif score >= 65:
        return 'B'
    elif score >= 55:
        return 'C'
    else:
        return 'D'


# ============================================================
# v6.3.3 글로벌 조정 (실시간과 동일)
# ============================================================

def calculate_global_adjustment(
    nasdaq_change: float,
    usdkrw_change: float,
) -> int:
    """글로벌 지표 기반 점수 조정값
    
    실시간 index_monitor.py와 동일한 로직:
    - 나스닥 폭락(-2%↓): +5점 (역발상, 백테스트 57.2%)
    - 나스닥↑ & 환율↓: +3점 (최적 조건, 백테스트 55.2%)
    
    Args:
        nasdaq_change: 나스닥 전일 대비 등락률 (%)
        usdkrw_change: 환율 전일 대비 등락률 (%)
        
    Returns:
        점수 조정값 (0, 3, 5)
    """
    if pd.isna(nasdaq_change):
        return 0
    
    # 나스닥 폭락 시 역발상 보너스 (백테스트 57.2%)
    if nasdaq_change <= -2.0:
        return 5
    
    # 나스닥↑ & 환율↓ 최적 조건 보너스
    if not pd.isna(usdkrw_change):
        if nasdaq_change > 0 and usdkrw_change < 0:
            return 3
    
    return 0