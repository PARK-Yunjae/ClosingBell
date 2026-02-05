"""
매수/매도 타점 계산기 (v9.0)
"""

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from src.analyzers.volume_profile import VolumeProfileSummary
from src.analyzers.technical_analyzer import TechnicalSummary


@dataclass
class EntryExitPlan:
    entry: Optional[float]
    target1: Optional[float]
    target2: Optional[float]
    stop_loss: Optional[float]
    holding_days: str
    note: str = ""


def _estimate_holding_days(df: pd.DataFrame) -> str:
    if df is None or df.empty or len(df) < 20:
        return "5~10일"
    returns = df["close"].pct_change().dropna().tail(20)
    if returns.empty:
        return "5~10일"
    vol = returns.std()
    if vol >= 0.08:
        return "3~7일"
    if vol >= 0.04:
        return "5~12일"
    return "7~15일"


def calculate_entry_exit(
    df: pd.DataFrame,
    current_price: float,
    vp: VolumeProfileSummary,
    tech: TechnicalSummary,
) -> EntryExitPlan:
    if df is None or df.empty or current_price is None or current_price <= 0:
        return EntryExitPlan(
            entry=None,
            target1=None,
            target2=None,
            stop_loss=None,
            holding_days="N/A",
            note="데이터 부족",
        )

    tail = df.tail(20) if len(df) >= 20 else df
    low_20 = float(tail["low"].min())
    high_20 = float(tail["high"].max())

    support = vp.support if vp.support else low_20
    resistance = vp.resistance if vp.resistance else high_20

    entry = round(support * 1.01, 0) if support > 0 else None
    target1 = round(resistance, 0) if resistance > 0 else None
    target2 = round(resistance * 1.08, 0) if resistance > 0 else None
    stop_loss = round(support * 0.95, 0) if support > 0 else None

    holding_days = _estimate_holding_days(df)

    note = ""
    if tech.rsi is not None and tech.rsi >= 70:
        note = "RSI 과열 구간"
    elif tech.rsi is not None and tech.rsi <= 30:
        note = "RSI 과매도 구간"

    return EntryExitPlan(
        entry=entry,
        target1=target1,
        target2=target2,
        stop_loss=stop_loss,
        holding_days=holding_days,
        note=note,
    )

