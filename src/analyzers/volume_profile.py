"""
Volume Profile 분석기 (v9.0)

기존 domain.volume_profile 계산 결과를 요약해
지지/저항 핵심 레벨을 추정합니다.
"""

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from src.domain.volume_profile import calc_volume_profile, VP_SCORE_NEUTRAL


@dataclass
class VolumeProfileSummary:
    score: float
    tag: str
    above_pct: float
    below_pct: float
    poc_price: float
    poc_pct: float
    support: Optional[float]
    resistance: Optional[float]
    reason: str = ""


def _pick_support(res_bands, current_price: float) -> Optional[float]:
    below = [b for b in res_bands if b.price_high <= current_price]
    if not below:
        return None
    return max(below, key=lambda b: b.pct).price_high


def _pick_resistance(res_bands, current_price: float) -> Optional[float]:
    above = [b for b in res_bands if b.price_low >= current_price]
    if not above:
        return None
    return max(above, key=lambda b: b.pct).price_low


def analyze_volume_profile(
    df: pd.DataFrame,
    current_price: float,
    n_days: int = 60,
    n_bands: int = 10,
) -> VolumeProfileSummary:
    if df is None or df.empty or current_price is None:
        return VolumeProfileSummary(
            score=VP_SCORE_NEUTRAL,
            tag="데이터부족",
            above_pct=0.0,
            below_pct=0.0,
            poc_price=0.0,
            poc_pct=0.0,
            support=None,
            resistance=None,
            reason="OHLCV 데이터 없음",
        )

    try:
        result = calc_volume_profile(
            df=df,
            current_price=current_price,
            n_days=n_days,
            n_bands=n_bands,
        )
    except Exception:
        return VolumeProfileSummary(
            score=VP_SCORE_NEUTRAL,
            tag="오류",
            above_pct=0.0,
            below_pct=0.0,
            poc_price=0.0,
            poc_pct=0.0,
            support=None,
            resistance=None,
            reason="매물대 계산 오류",
        )

    support = _pick_support(result.bands, current_price)
    resistance = _pick_resistance(result.bands, current_price)

    reason = ""
    if result.tag == "데이터부족":
        reason = "데이터 부족"

    return VolumeProfileSummary(
        score=result.score,
        tag=result.tag,
        above_pct=result.above_pct,
        below_pct=result.below_pct,
        poc_price=result.poc_price,
        poc_pct=result.poc_pct,
        support=support,
        resistance=resistance,
        reason=reason,
    )

