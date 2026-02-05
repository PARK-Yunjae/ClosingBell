"""
Analysis report generator (v9.0 MVP)

Generates reports/YYYYMMDD_<code>.md with:
1) OHLCV summary
2) Volume Profile summary
3) Basic indicators (CCI/MA)
4) Broker summary (if available)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Optional, Tuple, Any, List

import pandas as pd

from src.config.app_config import OHLCV_FULL_DIR, OHLCV_DIR
from src.config.backfill_config import get_backfill_config
from src.domain.models import DailyPrice
from src.domain.indicators import calculate_cci, calculate_ma
from src.domain.volume_profile import calc_volume_profile, VP_SCORE_NEUTRAL
from src.infrastructure.repository import get_broker_signal_repository
from src.services.backfill.data_loader import load_single_ohlcv


@dataclass
class AnalysisResult:
    report_path: Path
    summary: str


def _resolve_ohlcv_path(code: str) -> Optional[Path]:
    candidates: List[Path] = []
    bases: List[Path] = []

    for base in [OHLCV_FULL_DIR, OHLCV_DIR]:
        if base and base not in bases:
            bases.append(base)

    try:
        cfg = get_backfill_config()
        base = cfg.get_active_ohlcv_dir()
        if base and base not in bases:
            bases.append(base)
    except Exception:
        pass

    for base in bases:
        candidates.append(base / f"{code}.csv")
        candidates.append(base / f"A{code}.csv")

    for path in candidates:
        if path.exists():
            return path
    return None


def _load_ohlcv_df(code: str) -> Tuple[Optional[pd.DataFrame], Optional[Path]]:
    path = _resolve_ohlcv_path(code)
    if not path:
        return None, None
    df = load_single_ohlcv(path)
    if df is None or df.empty:
        return None, path
    return df, path


def _to_daily_prices(df: pd.DataFrame) -> List[DailyPrice]:
    prices: List[DailyPrice] = []
    for _, row in df.iterrows():
        prices.append(
            DailyPrice(
                date=row["date"].date(),
                open=int(row["open"]),
                high=int(row["high"]),
                low=int(row["low"]),
                close=int(row["close"]),
                volume=int(row["volume"]),
                trading_value=float(row.get("trading_value", 0.0)),
            )
        )
    return prices


def generate_analysis_report(stock_code: str, full: bool = False) -> AnalysisResult:
    code = str(stock_code).zfill(6)
    today = date.today()
    now = datetime.now()

    report_dir = Path("reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{today.strftime('%Y%m%d')}_{code}.md"

    df, data_path = _load_ohlcv_df(code)

    lines: List[str] = []
    lines.append("# ClosingBell v9.0 Analysis Report")
    lines.append("")
    lines.append(f"- Code: {code}")
    lines.append(f"- Generated: {now.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"- OHLCV Source: {data_path if data_path else 'not found'}")
    lines.append("")

    # OHLCV summary
    lines.append("## OHLCV Summary")
    last_close = None
    if df is None:
        lines.append("- OHLCV data not found.")
    else:
        df = df.sort_values("date").reset_index(drop=True)
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else None
        last_close = float(last["close"])
        change_pct = 0.0
        if prev is not None and float(prev["close"]) > 0:
            change_pct = (float(last["close"]) - float(prev["close"])) / float(prev["close"]) * 100.0

        period_start = df["date"].iloc[0].date()
        period_end = last["date"].date()
        tv = float(last.get("trading_value", 0.0))
        lines.append(f"- Period: {period_start} to {period_end} ({len(df)} days)")
        lines.append(
            f"- Latest ({period_end}): "
            f"O {int(last['open']):,} / H {int(last['high']):,} / "
            f"L {int(last['low']):,} / C {int(last['close']):,}"
        )
        lines.append(f"- Change vs prev close: {change_pct:+.2f}%")
        lines.append(f"- Volume: {int(last['volume']):,} | Trading value (100M KRW): {tv:.2f}")

        tail = df.tail(20) if len(df) >= 20 else df
        high_20 = float(tail["high"].max())
        low_20 = float(tail["low"].min())
        lines.append(f"- 20d High/Low: {high_20:,.0f} / {low_20:,.0f}")

    # Volume Profile summary
    lines.append("")
    lines.append("## Volume Profile")
    vp_tag = "N/A"
    if df is None or last_close is None:
        lines.append("- VP: N/A (no OHLCV data).")
    else:
        try:
            vp_result = calc_volume_profile(df, current_price=last_close, n_days=100)
            vp_tag = vp_result.tag
            lines.append(f"- Score: {vp_result.score:.1f}/13 | Tag: {vp_result.tag}")
            lines.append(
                f"- Above/Below: {vp_result.above_pct:.1f}% / {vp_result.below_pct:.1f}% | "
                f"POC: {vp_result.poc_price:,.0f} ({vp_result.poc_pct:.1f}%)"
            )
        except Exception:
            lines.append(f"- VP: error (using neutral {VP_SCORE_NEUTRAL:.1f}).")
            vp_tag = "error"

    # Indicators
    lines.append("")
    lines.append("## Indicators")
    cci_value = None
    ma20_value = None
    ma20_dist = None
    if df is None:
        lines.append("- Indicators: N/A (no OHLCV data).")
    else:
        prices = _to_daily_prices(df)
        cci_values = calculate_cci(prices, period=14)
        ma20_values = calculate_ma(prices, period=20)
        cci_value = cci_values[-1] if cci_values else None
        ma20_value = ma20_values[-1] if ma20_values else None
        if ma20_value and last_close:
            ma20_dist = (last_close - ma20_value) / ma20_value * 100.0

        lines.append(f"- CCI(14): {cci_value:.1f}" if cci_value is not None else "- CCI(14): N/A")
        if ma20_value is not None:
            dist_str = f"{ma20_dist:+.2f}%" if ma20_dist is not None else "N/A"
            lines.append(f"- MA20: {ma20_value:.2f} | Distance: {dist_str}")
        else:
            lines.append("- MA20: N/A")

    # Broker summary
    lines.append("")
    lines.append("## Broker Summary")
    try:
        repo = get_broker_signal_repository()
        rows = repo.get_signals_by_code(code, limit=5 if full else 1)
        if not rows:
            lines.append("- No broker signals found.")
        else:
            lines.append("| Date | Anomaly | Score | Tag |")
            lines.append("| --- | --- | --- | --- |")
            for row in rows:
                lines.append(
                    f"| {row.get('screen_date', '')} | {row.get('anomaly_score', '')} | "
                    f"{float(row.get('broker_score', 0.0)):.1f} | {row.get('tag', '')} |"
                )
    except Exception:
        lines.append("- Broker signals unavailable.")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary_parts = []
    if cci_value is not None:
        summary_parts.append(f"CCI {cci_value:.1f}")
    if ma20_value is not None:
        summary_parts.append(f"MA20 {ma20_value:.0f}")
    if vp_tag:
        summary_parts.append(f"VP {vp_tag}")
    summary = f"{code} | " + ", ".join(summary_parts) if summary_parts else f"{code} | report generated"

    return AnalysisResult(report_path=report_path, summary=summary)

