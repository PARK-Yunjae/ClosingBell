"""
ClosingBell v4.1 signal backtest
================================

Validate the new OHLCV-derived v4.1 signals on historical screen_runs:
  - OBV divergence
  - RSI dead zone

This tool intentionally avoids touching the existing simulator so we can
evaluate the new signals in isolation before deciding whether to reflect
them in the ranking score.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (
    APP_DB_PATH,
    OHLCV_DIR,
    OBV_DIVERGENCE_LOOKBACK,
    OBV_DIVERGENCE_PRICE_THRESH,
    RSI_DEAD_ZONE_HIGH,
    RSI_DEAD_ZONE_LOOKBACK,
    RSI_DEAD_ZONE_LOW,
    RSI_DEAD_ZONE_RATIO,
    RSI_PERIOD,
)


def load_screen_runs(limit: int = 0) -> list[dict]:
    db = sqlite3.connect(str(APP_DB_PATH))
    cur = db.cursor()
    query = "SELECT run_date, payload FROM screen_runs ORDER BY run_date"
    if limit:
        query += f" LIMIT {int(limit)}"
    cur.execute(query)

    runs = []
    for run_date, payload_blob in cur.fetchall():
        try:
            payload = json.loads(gzip.decompress(payload_blob).decode("utf-8"))
        except Exception:
            try:
                payload = json.loads(payload_blob)
            except Exception:
                continue
        stocks = payload.get("all_scored", [])
        if stocks:
            runs.append({"date": run_date, "stocks": stocks})

    db.close()
    return runs


def load_ohlcv_cache(codes: set[str]) -> dict[str, pd.DataFrame]:
    cache: dict[str, pd.DataFrame] = {}
    ohlcv_dir = Path(OHLCV_DIR)

    for code in sorted(codes):
        csv_path = ohlcv_dir / f"{code.zfill(6)}.csv"
        if not csv_path.exists():
            continue
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            continue
        df.columns = [c.lower().strip() for c in df.columns]
        required = {"date", "close", "volume"}
        if not required.issubset(df.columns):
            continue
        try:
            df["date"] = pd.to_datetime(df["date"])
        except Exception:
            continue
        df = df.sort_values("date").reset_index(drop=True)
        df = enrich_ohlcv(df)
        cache[code] = df

    return cache


def enrich_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    delta = out["close"].diff()
    gain = delta.clip(lower=0).rolling(RSI_PERIOD).mean()
    loss = (-delta.clip(upper=0)).rolling(RSI_PERIOD).mean()
    rs = gain / loss.replace(0, np.nan)
    out["rsi"] = 100 - (100 / (1 + rs))

    direction = np.sign(out["close"].diff().fillna(0))
    out["obv"] = (direction * out["volume"]).cumsum()
    out["obv_ma20"] = out["obv"].rolling(20).mean()
    return out


def compute_signals(df: pd.DataFrame, run_date: str) -> dict | None:
    hist = df[df["date"] <= pd.Timestamp(run_date)].tail(80).copy()
    if len(hist) < max(25, RSI_PERIOD + RSI_DEAD_ZONE_LOOKBACK):
        return None

    latest = hist.iloc[-1]
    result = {
        "obv_divergence": "none",
        "obv_above_ma": bool(
            pd.notna(latest.get("obv_ma20")) and latest.get("obv", 0) > latest.get("obv_ma20", 0)
        ),
        "rsi_dead_zone": False,
    }

    obv_lookback = max(1, int(OBV_DIVERGENCE_LOOKBACK))
    if len(hist) > obv_lookback:
        base_close = float(hist["close"].iloc[-(obv_lookback + 1)])
        if base_close > 0:
            price_move = (float(latest["close"]) / base_close - 1) * 100
            obv_move = float(latest["obv"]) - float(hist["obv"].iloc[-(obv_lookback + 1)])
            if price_move <= -float(OBV_DIVERGENCE_PRICE_THRESH) and obv_move > 0:
                result["obv_divergence"] = "bullish"
            elif price_move >= float(OBV_DIVERGENCE_PRICE_THRESH) and obv_move < 0:
                result["obv_divergence"] = "bearish"

    zone_lookback = max(1, int(RSI_DEAD_ZONE_LOOKBACK))
    required = max(1, int(np.ceil(zone_lookback * float(RSI_DEAD_ZONE_RATIO))))
    rsi_vals = hist["rsi"].dropna().tail(zone_lookback)
    if len(rsi_vals) >= required:
        in_zone = ((rsi_vals >= float(RSI_DEAD_ZONE_LOW)) & (rsi_vals <= float(RSI_DEAD_ZONE_HIGH))).sum()
        result["rsi_dead_zone"] = bool(in_zone >= required)

    return result


def get_return(df: pd.DataFrame, run_date: str, days: int) -> float | None:
    base_dt = pd.Timestamp(run_date)
    base_rows = df[df["date"] <= base_dt].tail(1)
    future_rows = df[df["date"] > base_dt].head(days)
    if base_rows.empty or future_rows.empty:
        return None

    buy_price = float(base_rows.iloc[-1]["close"])
    sell_price = float(future_rows.iloc[-1]["close"])
    if buy_price <= 0:
        return None
    return (sell_price / buy_price - 1) * 100


def build_candidate_frame(runs: list[dict], ohlcv_cache: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict] = []

    for run in runs:
        run_date = run["date"]
        for stock in run["stocks"]:
            code = str(stock.get("code", "")).strip().zfill(6)
            df = ohlcv_cache.get(code)
            if df is None or df.empty:
                continue

            signals = compute_signals(df, run_date)
            if not signals:
                continue

            rows.append(
                {
                    "date": run_date,
                    "code": code,
                    "name": stock.get("name", code),
                    "rank": int(stock.get("rank", 999) or 999),
                    "score": float(stock.get("score", 0) or 0),
                    "obv_divergence": signals["obv_divergence"],
                    "obv_above_ma": bool(signals["obv_above_ma"]),
                    "rsi_dead_zone": bool(signals["rsi_dead_zone"]),
                    "d1_return": get_return(df, run_date, 1),
                    "d3_return": get_return(df, run_date, 3),
                    "d5_return": get_return(df, run_date, 5),
                }
            )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.dropna(subset=["d3_return"]).reset_index(drop=True)


def signal_stats(df: pd.DataFrame, mask: pd.Series) -> dict:
    subset = df[mask].copy()
    if subset.empty:
        return {"count": 0}
    return {
        "count": int(len(subset)),
        "d1_avg": round(float(subset["d1_return"].dropna().mean()), 3),
        "d3_avg": round(float(subset["d3_return"].dropna().mean()), 3),
        "d5_avg": round(float(subset["d5_return"].dropna().mean()), 3),
        "d1_pos": round(float((subset["d1_return"] > 0).mean() * 100), 1),
        "d3_pos": round(float((subset["d3_return"] > 0).mean() * 100), 1),
        "d5_pos": round(float((subset["d5_return"] > 0).mean() * 100), 1),
    }


def print_signal_stats(df: pd.DataFrame) -> None:
    groups = [
        ("All", pd.Series(True, index=df.index)),
        ("OBV bullish", df["obv_divergence"] == "bullish"),
        ("OBV bearish", df["obv_divergence"] == "bearish"),
        ("OBV none", df["obv_divergence"] == "none"),
        ("Dead zone", df["rsi_dead_zone"]),
        ("Not dead zone", ~df["rsi_dead_zone"]),
        ("Bullish + no dead zone", (df["obv_divergence"] == "bullish") & (~df["rsi_dead_zone"])),
    ]

    print("\nSignal cohort stats")
    print("-" * 72)
    print("Group                     Count   D+1 avg   D+3 avg   D+5 avg   D+3 > 0")
    print("-" * 72)
    for label, mask in groups:
        stats = signal_stats(df, mask)
        if not stats.get("count"):
            print(f"{label:24} {0:>6}")
            continue
        print(
            f"{label:24} {stats['count']:>6} "
            f"{stats['d1_avg']:>9.3f}% {stats['d3_avg']:>9.3f}% {stats['d5_avg']:>9.3f}% "
            f"{stats['d3_pos']:>8.1f}%"
        )


def simulate_adjustment(
    df: pd.DataFrame,
    bullish_bonus: float,
    bearish_penalty: float,
    dead_zone_penalty: float,
    top_k: int,
) -> dict:
    work = df.copy()
    work["adj_score"] = work["score"]
    work.loc[work["obv_divergence"] == "bullish", "adj_score"] += bullish_bonus
    work.loc[work["obv_divergence"] == "bearish", "adj_score"] += bearish_penalty
    work.loc[work["rsi_dead_zone"], "adj_score"] += dead_zone_penalty

    picks = (
        work.sort_values(["date", "adj_score", "score"], ascending=[True, False, False])
        .groupby("date", group_keys=False)
        .head(top_k)
        .copy()
    )

    return {
        "bullish_bonus": bullish_bonus,
        "bearish_penalty": bearish_penalty,
        "dead_zone_penalty": dead_zone_penalty,
        "dates": int(picks["date"].nunique()),
        "picks": int(len(picks)),
        "d1_avg": round(float(picks["d1_return"].dropna().mean()), 3),
        "d3_avg": round(float(picks["d3_return"].dropna().mean()), 3),
        "d5_avg": round(float(picks["d5_return"].dropna().mean()), 3),
        "d3_pos": round(float((picks["d3_return"] > 0).mean() * 100), 1),
    }


def print_adjustment_sweep(df: pd.DataFrame, top_k: int) -> None:
    configs = []
    for bull in [0, 1, 2, 3]:
        for bear in [0, -1, -2, -3]:
            for dead in [0, -1, -2, -3]:
                configs.append(simulate_adjustment(df, bull, bear, dead, top_k))

    configs.sort(
        key=lambda row: (
            row["d3_avg"],
            row["d5_avg"],
            row["d3_pos"],
        ),
        reverse=True,
    )

    baseline = next(
        row for row in configs
        if row["bullish_bonus"] == 0 and row["bearish_penalty"] == 0 and row["dead_zone_penalty"] == 0
    )
    best = configs[0]

    print("\nAdjustment sweep")
    print("-" * 72)
    print(
        "Baseline: "
        f"D+3 {baseline['d3_avg']:+.3f}% | D+5 {baseline['d5_avg']:+.3f}% | "
        f"D+3>0 {baseline['d3_pos']:.1f}%"
    )
    print(
        "Best:     "
        f"bull {best['bullish_bonus']:+.0f}, bear {best['bearish_penalty']:+.0f}, "
        f"dead {best['dead_zone_penalty']:+.0f} | "
        f"D+3 {best['d3_avg']:+.3f}% | D+5 {best['d5_avg']:+.3f}% | "
        f"D+3>0 {best['d3_pos']:.1f}%"
    )
    print(
        "Delta:    "
        f"D+3 {best['d3_avg'] - baseline['d3_avg']:+.3f}%p | "
        f"D+5 {best['d5_avg'] - baseline['d5_avg']:+.3f}%p | "
        f"D+3>0 {best['d3_pos'] - baseline['d3_pos']:+.1f}%p"
    )

    print("\nTop 8 configs by D+3 avg")
    print("-" * 72)
    print("bull  bear  dead   D+3 avg   D+5 avg   D+3 > 0")
    print("-" * 72)
    for row in configs[:8]:
        print(
            f"{row['bullish_bonus']:>4.0f} "
            f"{row['bearish_penalty']:>5.0f} "
            f"{row['dead_zone_penalty']:>5.0f} "
            f"{row['d3_avg']:>9.3f}% {row['d5_avg']:>9.3f}% {row['d3_pos']:>8.1f}%"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest ClosingBell v4.1 OHLCV signals")
    parser.add_argument("--limit", type=int, default=0, help="Use only the first N screen_runs")
    parser.add_argument("--top-k", type=int, default=5, help="Top K picks per day for adjustment sweep")
    args = parser.parse_args()

    print("=" * 72)
    print("ClosingBell v4.1 signal backtest")
    print("=" * 72)

    runs = load_screen_runs(limit=args.limit)
    if not runs:
        print("No screen_runs data found.")
        return
    print(f"screen_runs: {len(runs)} days")

    codes = {
        str(stock.get("code", "")).strip().zfill(6)
        for run in runs
        for stock in run["stocks"]
        if stock.get("code")
    }
    ohlcv_cache = load_ohlcv_cache(codes)
    print(f"OHLCV loaded: {len(ohlcv_cache)}/{len(codes)} codes")
    if not ohlcv_cache:
        print("No OHLCV data available.")
        return

    candidates = build_candidate_frame(runs, ohlcv_cache)
    if candidates.empty:
        print("No backtest candidates could be built.")
        return

    print(
        f"Candidates: {len(candidates)} rows | "
        f"Dates: {candidates['date'].nunique()} | "
        f"Codes: {candidates['code'].nunique()}"
    )
    print_signal_stats(candidates)
    print_adjustment_sweep(candidates, top_k=args.top_k)

    print("\nNote")
    print("-" * 72)
    print("This validates only OHLCV-derived v4.1 signals.")
    print("Short-covering and foreign exhaust still need separately stored historical API data.")


if __name__ == "__main__":
    main()

