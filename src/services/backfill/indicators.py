"""
ClosingBell v6.0 백필 - 기술적 지표 계산

⚠️ 중요: 이 코드는 백테스트 코드와 100% 동일해야 함!
   다른 로직 사용 시 백테스트 결과와 불일치 발생
"""

import numpy as np
import pandas as pd
from typing import Optional


def calculate_cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """CCI (Commodity Channel Index) 계산
    
    백테스트 코드와 동일한 로직
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


def calculate_consecutive_up(df: pd.DataFrame) -> pd.Series:
    """연속 양봉 일수"""
    is_up = df['close'] > df['open']
    
    # 그룹 번호 생성 (연속된 양봉 구간별)
    groups = (~is_up).cumsum()
    
    # 연속 양봉 카운트
    consec = is_up.groupby(groups).cumsum()
    
    return consec


def calculate_candle_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """캔들 지표 계산"""
    result = pd.DataFrame(index=df.index)
    
    # 캔들 몸통
    body = df['close'] - df['open']
    result['body_pct'] = body / df['open'] * 100
    
    # 양봉 여부
    result['is_bullish'] = (df['close'] > df['open']).astype(int)
    
    # 아랫꼬리 (양봉 기준)
    lower_shadow = df['open'].where(df['close'] > df['open'], df['close']) - df['low']
    result['lower_shadow_pct'] = lower_shadow / df['close'] * 100
    
    # 윗꼬리
    upper_shadow = df['high'] - df['close'].where(df['close'] > df['open'], df['open'])
    result['upper_shadow_pct'] = upper_shadow / df['close'] * 100
    
    # 20일 내 위치
    rolling_high = df['high'].rolling(window=20).max()
    rolling_low = df['low'].rolling(window=20).min()
    result['position_in_20d'] = (df['close'] - rolling_low) / (rolling_high - rolling_low)
    
    return result


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """모든 지표 계산
    
    Args:
        df: OHLCV 데이터프레임 (columns: date, open, high, low, close, volume)
        
    Returns:
        지표가 추가된 데이터프레임
    """
    result = df.copy()
    
    # 등락률
    result['change_rate'] = result['close'].pct_change() * 100
    
    # CCI
    result['cci'] = calculate_cci(result)
    
    # RSI
    result['rsi'] = calculate_rsi(result)
    
    # 이동평균
    result['ma5'] = calculate_ma(result, 5)
    result['ma20'] = calculate_ma(result, 20)
    result['ma60'] = calculate_ma(result, 60)
    
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
    
    # 연속 양봉
    result['consecutive_up'] = calculate_consecutive_up(result)
    
    # 캔들 지표
    candle_metrics = calculate_candle_metrics(result)
    for col in candle_metrics.columns:
        result[col] = candle_metrics[col]
    
    # 거래대금 (억원)
    result['trading_value'] = result['close'] * result['volume'] / 100_000_000
    
    return result


def calculate_score(row: pd.Series, weights: Optional[dict] = None) -> float:
    """종목 점수 계산 (백테스트와 동일한 로직)
    
    기존 ClosingBell 점수 계산과 동일해야 함
    """
    if weights is None:
        weights = {
            'cci_value': 15,
            'change_rate': 15,
            'disparity': 15,
            'consecutive': 15,
            'volume_ratio': 15,
            'candle': 15,
        }
    
    score = 0.0
    
    # CCI 점수 (0~100 기준, -200~200 범위)
    cci = row.get('cci', 0)
    if pd.notna(cci):
        cci_normalized = min(max((cci + 200) / 400, 0), 1)
        score += cci_normalized * weights['cci_value']
    
    # 등락률 점수 (0~10% 기준)
    change = row.get('change_rate', 0)
    if pd.notna(change):
        change_normalized = min(max(change / 10, 0), 1)
        score += change_normalized * weights['change_rate']
    
    # 이격도 점수 (0~10% 기준)
    disparity = row.get('disparity_20', 0)
    if pd.notna(disparity):
        disparity_normalized = min(max(disparity / 10, 0), 1)
        score += disparity_normalized * weights['disparity']
    
    # 연속 양봉 점수 (0~3일 기준, 4일+ 감점)
    consec = row.get('consecutive_up', 0)
    if pd.notna(consec):
        if consec <= 3:
            consec_normalized = consec / 3
        else:
            consec_normalized = max(1 - (consec - 3) * 0.2, 0)  # 4일부터 감점
        score += consec_normalized * weights['consecutive']
    
    # 거래량 비율 점수 (1~5x 기준)
    vol_ratio = row.get('volume_ratio_5', 1)
    if pd.notna(vol_ratio):
        vol_normalized = min(max((vol_ratio - 1) / 4, 0), 1)
        score += vol_normalized * weights['volume_ratio']
    
    # 캔들 점수 (양봉 + 아랫꼬리)
    is_bullish = row.get('is_bullish', 0)
    lower_shadow = row.get('lower_shadow_pct', 0)
    if pd.notna(is_bullish) and pd.notna(lower_shadow):
        candle_score = is_bullish * 0.5 + min(lower_shadow / 3, 1) * 0.5
        score += candle_score * weights['candle']
    
    return score


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
