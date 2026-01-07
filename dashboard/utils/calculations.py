"""
통계 계산 모듈

책임:
- 성과 통계 계산
- 누적 수익률 계산
- MDD 계산
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import date


def calculate_cumulative_returns(daily_returns: List[float]) -> List[float]:
    """누적 수익률 계산"""
    if not daily_returns:
        return []
    
    cumulative = []
    total = 0
    for r in daily_returns:
        total += r
        cumulative.append(total)
    return cumulative


def calculate_mdd(cumulative_returns: List[float]) -> float:
    """최대 낙폭(MDD) 계산"""
    if not cumulative_returns:
        return 0.0
    
    peak = cumulative_returns[0]
    max_drawdown = 0
    
    for value in cumulative_returns:
        if value > peak:
            peak = value
        drawdown = peak - value
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    
    return max_drawdown


def calculate_streak(results: List[bool]) -> Tuple[int, int]:
    """연속 승리/패배 계산
    
    Returns:
        (최대 연속 승리, 최대 연속 패배)
    """
    if not results:
        return 0, 0
    
    max_win_streak = 0
    max_loss_streak = 0
    current_win = 0
    current_loss = 0
    
    for is_win in results:
        if is_win:
            current_win += 1
            current_loss = 0
            max_win_streak = max(max_win_streak, current_win)
        else:
            current_loss += 1
            current_win = 0
            max_loss_streak = max(max_loss_streak, current_loss)
    
    return max_win_streak, max_loss_streak


def calculate_sharpe_ratio(returns: List[float], risk_free_rate: float = 0.0) -> float:
    """샤프 비율 계산 (연환산)"""
    if not returns or len(returns) < 2:
        return 0.0
    
    returns_array = np.array(returns)
    mean_return = np.mean(returns_array) * 252  # 연환산 (거래일 기준)
    std_return = np.std(returns_array) * np.sqrt(252)
    
    if std_return == 0:
        return 0.0
    
    return (mean_return - risk_free_rate) / std_return


def calculate_win_loss_ratio(wins: int, losses: int) -> float:
    """승패 비율 계산"""
    if losses == 0:
        return float('inf') if wins > 0 else 0.0
    return wins / losses


def calculate_profit_factor(
    winning_returns: List[float],
    losing_returns: List[float],
) -> float:
    """수익 팩터 계산"""
    total_wins = sum(winning_returns) if winning_returns else 0
    total_losses = abs(sum(losing_returns)) if losing_returns else 0
    
    if total_losses == 0:
        return float('inf') if total_wins > 0 else 0.0
    
    return total_wins / total_losses


def analyze_performance_by_rank(df: pd.DataFrame) -> pd.DataFrame:
    """순위별 성과 분석"""
    if df.empty or 'rank' not in df.columns:
        return pd.DataFrame()
    
    grouped = df.groupby('rank').agg({
        'gap_rate': ['count', 'mean', 'std', 'min', 'max'],
        'is_open_up': 'sum',
    }).reset_index()
    
    grouped.columns = ['rank', 'count', 'avg_gap', 'std_gap', 'min_gap', 'max_gap', 'wins']
    grouped['win_rate'] = (grouped['wins'] / grouped['count'] * 100).round(2)
    
    return grouped


def analyze_performance_by_cci(df: pd.DataFrame, bins: int = 5) -> pd.DataFrame:
    """CCI 구간별 성과 분석"""
    if df.empty or 'raw_cci' not in df.columns:
        return pd.DataFrame()
    
    df_valid = df[df['raw_cci'].notna() & df['gap_rate'].notna()].copy()
    if df_valid.empty:
        return pd.DataFrame()
    
    df_valid['cci_bin'] = pd.cut(df_valid['raw_cci'], bins=bins)
    
    grouped = df_valid.groupby('cci_bin').agg({
        'gap_rate': ['count', 'mean'],
        'is_open_up': 'sum',
    }).reset_index()
    
    grouped.columns = ['cci_range', 'count', 'avg_gap', 'wins']
    grouped['win_rate'] = (grouped['wins'] / grouped['count'] * 100).round(2)
    
    return grouped


def calculate_correlation_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """지표별 상관관계 매트릭스"""
    score_cols = [
        'score_cci_value', 'score_cci_slope', 'score_ma20_slope',
        'score_candle', 'score_change'
    ]
    
    cols_present = [c for c in score_cols if c in df.columns]
    if 'gap_rate' not in df.columns or not cols_present:
        return pd.DataFrame()
    
    cols_to_correlate = cols_present + ['gap_rate']
    return df[cols_to_correlate].corr()


def format_currency(value: float) -> str:
    """원화 포맷"""
    if value >= 100000000:  # 1억 이상
        return f"{value / 100000000:.1f}억"
    elif value >= 10000:  # 1만 이상
        return f"{value / 10000:.0f}만"
    else:
        return f"{value:,.0f}"


def format_percent(value: float, decimal: int = 2) -> str:
    """퍼센트 포맷"""
    if value > 0:
        return f"+{value:.{decimal}f}%"
    return f"{value:.{decimal}f}%"


def get_result_emoji(is_win: bool) -> str:
    """결과 이모지"""
    return "✅" if is_win else "❌"


def get_trend_emoji(value: float, threshold: float = 0) -> str:
    """추세 이모지"""
    if value > threshold:
        return "📈"
    elif value < -threshold:
        return "📉"
    return "➡️"
