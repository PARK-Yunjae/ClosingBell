"""
Auto-tuning helpers for screening and buy-pick stages.

Usage:
    python auto_tuner.py
    python auto_tuner.py --mode buy
    python auto_tuner.py --apply
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

import pandas as pd

from config import (
    BUY_A_MIN_SCORE,
    BUY_B_MIN_SCORE,
    BUY_DART_CAUTION_PENALTY,
    BUY_DART_DANGER_PENALTY,
    BUY_NEWS_CAUTION_PENALTY,
    BUY_NEWS_DANGER_PENALTY,
    CCI_OPTIMAL,
    CHANGE_OPTIMAL,
    MA20_GAP_OPTIMAL,
    OHLCV_DIR,
    RSI_OPTIMAL,
)
from storage import (
    iter_buy_pick_outcomes,
    iter_screen_results,
    load_backtest_dataset,
    load_screen_results_from_fs,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("auto_tuner")

PROJECT_DIR = Path(__file__).parent
ENV_FILE = PROJECT_DIR / ".env"

SCREEN_INDICATORS = {
    "cci": {
        "env_low": "CCI_OPTIMAL_LOW",
        "env_high": "CCI_OPTIMAL_HIGH",
        "bins": [0, 80, 120, 140, 160, 180, 200, 220, 250, 300, 500],
        "current": CCI_OPTIMAL,
    },
    "rsi": {
        "env_low": "RSI_OPTIMAL_LOW",
        "env_high": "RSI_OPTIMAL_HIGH",
        "bins": [0, 25, 35, 45, 50, 55, 60, 65, 70, 75, 85, 100],
        "current": RSI_OPTIMAL,
    },
    "ma20_gap": {
        "env_low": "MA20_GAP_OPTIMAL_LOW",
        "env_high": "MA20_GAP_OPTIMAL_HIGH",
        "bins": [-20, -5, 0, 2, 4, 6, 8, 10, 15, 20, 40],
        "current": MA20_GAP_OPTIMAL,
    },
    "change_rate": {
        "env_low": "CHANGE_OPTIMAL_LOW",
        "env_high": "CHANGE_OPTIMAL_HIGH",
        "bins": [0, 1, 2, 3, 4, 5, 6, 8, 10, 15, 20, 30],
        "current": CHANGE_OPTIMAL,
    },
}

SCREEN_PRIOR_FRACTION = 0.08
SCREEN_MIN_COVERAGE = 0.06
SCREEN_MOVE_PENALTY = 0.8
SCREEN_SINGLE_BIN_PENALTY = 2.0
SCREEN_CHANGE_THRESHOLD = 0.75

BUY_THRESHOLD_GRID = [35, 40, 45, 50, 55, 60, 65, 70, 75]
BUY_ENV_DEFAULTS = {
    "BUY_A_MIN_SCORE": BUY_A_MIN_SCORE,
    "BUY_B_MIN_SCORE": BUY_B_MIN_SCORE,
    "BUY_DART_CAUTION_PENALTY": BUY_DART_CAUTION_PENALTY,
    "BUY_DART_DANGER_PENALTY": BUY_DART_DANGER_PENALTY,
    "BUY_NEWS_CAUTION_PENALTY": BUY_NEWS_CAUTION_PENALTY,
    "BUY_NEWS_DANGER_PENALTY": BUY_NEWS_DANGER_PENALTY,
}


def load_screen_records() -> list[dict]:
    rows = []
    logs = iter_screen_results() or load_screen_results_from_fs()
    for payload in logs:
        if payload.get("skipped"):
            continue
        rec_date = payload.get("date", "")
        for stock in payload.get("all_scored", []):
            rows.append(
                {
                    "date": rec_date,
                    "code": str(stock.get("code", "")).replace("_AL", "").replace("_NX", "").zfill(6),
                    "name": stock.get("name", ""),
                    "rank": stock.get("rank", 99),
                    "score": stock.get("score", 0),
                    "cci": stock.get("cci", 0),
                    "rsi": stock.get("rsi", 0),
                    "ma20_gap": stock.get("ma20_gap", 0),
                    "change_rate": stock.get("change_rate", 0),
                    "price": stock.get("price", 0),
                }
            )
    return rows


def calc_screen_next_open(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(records)
    if df.empty:
        return df

    df["return_d1"] = pd.NA
    ohlcv_cache: dict[str, pd.DataFrame | None] = {}

    for idx, row in df.iterrows():
        code = row["code"]
        if code not in ohlcv_cache:
            path = OHLCV_DIR / f"{code}.csv"
            if path.exists():
                try:
                    odf = pd.read_csv(path)
                    odf.columns = [c.lower() for c in odf.columns]
                    odf["date"] = pd.to_datetime(odf["date"], errors="coerce").dt.strftime("%Y-%m-%d")
                    ohlcv_cache[code] = odf.set_index("date")
                except Exception:
                    ohlcv_cache[code] = None
            else:
                ohlcv_cache[code] = None

        odf = ohlcv_cache.get(code)
        if odf is None:
            continue

        try:
            dates_after = [d for d in odf.index if d > row["date"]]
            if not dates_after:
                continue
            next_date = min(dates_after)
            next_open = odf.loc[next_date, "open"]
            buy_price = row["price"]
            if buy_price > 0 and next_open > 0:
                df.at[idx, "return_d1"] = (next_open / buy_price - 1) * 100
        except Exception:
            continue

    return df.dropna(subset=["return_d1"]).copy()


def _find_range_indices(bins: list[float], low: float, high: float) -> tuple[int, int]:
    low_idx = max(i for i in range(len(bins) - 1) if bins[i] <= low)
    high_idx = next(
        (i for i in range(len(bins) - 1) if bins[i + 1] >= high),
        len(bins) - 2,
    )
    return low_idx, max(low_idx, high_idx)


def _screen_range_stats(
    grouped: pd.DataFrame,
    bins: list[float],
    start_idx: int,
    end_idx: int,
    *,
    overall_win: float,
    overall_avg: float,
    prior_count: int,
    current_low_idx: int,
    current_high_idx: int,
) -> dict:
    count = int(grouped.loc[start_idx:end_idx, "count"].sum())
    wins = float(grouped.loc[start_idx:end_idx, "wins"].sum())
    ret_sum = float(grouped.loc[start_idx:end_idx, "ret_sum"].sum())

    win_rate = wins / count * 100 if count else 0.0
    avg_return = ret_sum / count if count else 0.0
    shrunk_win = (
        (wins + prior_count * (overall_win / 100)) / (count + prior_count) * 100
        if count
        else overall_win
    )
    shrunk_avg = (
        (ret_sum + prior_count * overall_avg) / (count + prior_count)
        if count
        else overall_avg
    )
    coverage = count / float(grouped["count"].sum()) if count else 0.0
    movement = abs(start_idx - current_low_idx) + abs(end_idx - current_high_idx)
    width_bins = end_idx - start_idx + 1
    objective = (
        (shrunk_win - overall_win) * 1.2
        + max(shrunk_avg - overall_avg, 0) * 10
        + min(coverage, 0.30) * 8
        - movement * SCREEN_MOVE_PENALTY
        - (SCREEN_SINGLE_BIN_PENALTY if width_bins == 1 else 0)
    )
    return {
        "range": (float(bins[start_idx]), float(bins[end_idx + 1])),
        "count": count,
        "coverage": round(coverage * 100, 1),
        "win_rate": round(float(win_rate), 1),
        "avg_return": round(float(avg_return), 2),
        "objective": float(objective),
        "movement": int(movement),
        "width_bins": int(width_bins),
    }


def analyze_screen_indicator(df: pd.DataFrame, indicator: str, min_count: int) -> dict:
    config = SCREEN_INDICATORS[indicator]
    bins = config["bins"]
    labels = [f"{bins[i]}~{bins[i + 1]}" for i in range(len(bins) - 1)]
    work = df.copy()
    work["bin"] = pd.cut(work[indicator], bins=bins, labels=labels, include_lowest=True)
    grouped = (
        work.groupby("bin", observed=True)
        .agg(
            count=("return_d1", "count"),
            wins=("return_d1", lambda s: (s > 0).sum()),
            ret_sum=("return_d1", "sum"),
        )
        .reset_index()
    )
    grouped["win_rate"] = grouped["wins"] / grouped["count"] * 100
    grouped["avg_return"] = grouped["ret_sum"] / grouped["count"]

    total_count = int(grouped["count"].sum())
    if total_count == 0:
        return {"current": config["current"], "suggested": config["current"], "table": grouped}

    overall_win = float((df["return_d1"] > 0).mean() * 100)
    overall_avg = float(df["return_d1"].mean())
    prior_count = max(min_count * 3, int(total_count * SCREEN_PRIOR_FRACTION))
    required_count = max(min_count, int(total_count * SCREEN_MIN_COVERAGE))
    current_low_idx, current_high_idx = _find_range_indices(bins, *config["current"])
    current_stats = _screen_range_stats(
        grouped,
        bins,
        current_low_idx,
        current_high_idx,
        overall_win=overall_win,
        overall_avg=overall_avg,
        prior_count=prior_count,
        current_low_idx=current_low_idx,
        current_high_idx=current_high_idx,
    )

    best_stats = current_stats
    for start_idx in range(len(grouped)):
        for end_idx in range(start_idx, len(grouped)):
            stats = _screen_range_stats(
                grouped,
                bins,
                start_idx,
                end_idx,
                overall_win=overall_win,
                overall_avg=overall_avg,
                prior_count=prior_count,
                current_low_idx=current_low_idx,
                current_high_idx=current_high_idx,
            )
            if stats["count"] < required_count:
                continue
            if stats["objective"] > best_stats["objective"]:
                best_stats = stats

    chosen_stats = best_stats
    if best_stats["objective"] < current_stats["objective"] + SCREEN_CHANGE_THRESHOLD:
        chosen_stats = current_stats
    low, high = chosen_stats["range"]
    return {
        "current": config["current"],
        "suggested": (low, high),
        "overall": {
            "count": total_count,
            "win_rate": round(overall_win, 1),
            "avg_return": round(overall_avg, 2),
        },
        "current_stats": current_stats,
        "best_candidate": best_stats,
        "change_applied": chosen_stats["range"] != tuple(map(float, config["current"])),
        "required_count": required_count,
        "table": grouped[["bin", "count", "win_rate", "avg_return"]],
    }


def run_screen_analysis(min_days: int, min_count: int) -> dict:
    records = load_screen_records()
    trading_days = len({row["date"] for row in records})
    if trading_days < min_days:
        logger.warning("Not enough screening days: %d < %d", trading_days, min_days)
        return {}

    df = calc_screen_next_open(records)
    if df.empty:
        logger.warning("No valid screening returns were computed")
        return {}

    return {
        indicator: analyze_screen_indicator(df, indicator, min_count)
        for indicator in SCREEN_INDICATORS
    }


def load_buy_dataset() -> tuple[pd.DataFrame, str]:
    live_rows = iter_buy_pick_outcomes(desc=False)
    if live_rows:
        df = pd.DataFrame(live_rows)
        source = "live"
    else:
        fallback = load_backtest_dataset("buy_performance_v2") or load_backtest_dataset("buy_performance") or []
        df = pd.DataFrame(fallback)
        source = "backtest"

    for col in ("pick_date", "signal_date", "track_date", "watchlist_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df, source


def _threshold_stats(df: pd.DataFrame, threshold: int) -> dict | None:
    subset = df[df["conviction_score"] >= threshold]
    if subset.empty:
        return None
    target_col = "return_pct"
    win_rate = (subset[target_col] > 0).mean() * 100
    avg_return = subset[target_col].mean()
    return {
        "threshold": threshold,
        "count": int(len(subset)),
        "win_rate": round(float(win_rate), 1),
        "avg_return": round(float(avg_return), 2),
        "objective": float(win_rate + max(avg_return, 0) * 5),
    }


def analyze_buy_thresholds(df: pd.DataFrame, min_trades: int) -> dict:
    day1 = df[df["track_day"] == 1].copy()
    if day1.empty or "conviction_score" not in day1.columns:
        return {}

    threshold_rows = []
    for threshold in BUY_THRESHOLD_GRID:
        stats = _threshold_stats(day1, threshold)
        if stats and stats["count"] >= min_trades:
            threshold_rows.append(stats)

    if not threshold_rows:
        return {}

    table = pd.DataFrame(threshold_rows)
    best_a = table.sort_values(["objective", "count"], ascending=[False, False]).iloc[0]

    b_candidates = table[table["threshold"] < best_a["threshold"]].copy()
    if not b_candidates.empty:
        b_candidates = b_candidates[
            (b_candidates["avg_return"] >= 0) & (b_candidates["win_rate"] >= table["win_rate"].median())
        ]
    if b_candidates.empty:
        b_suggested = BUY_B_MIN_SCORE
    else:
        b_suggested = int(b_candidates.sort_values(["threshold"], ascending=True).iloc[0]["threshold"])

    a_suggested = int(best_a["threshold"])
    if b_suggested >= a_suggested:
        lower = [v for v in BUY_THRESHOLD_GRID if v < a_suggested]
        b_suggested = lower[-1] if lower else BUY_B_MIN_SCORE

    return {
        "table": table,
        "suggestions": {
            "BUY_A_MIN_SCORE": a_suggested,
            "BUY_B_MIN_SCORE": int(b_suggested),
        },
    }


def analyze_penalty(df: pd.DataFrame, field: str, current_caution: float, current_danger: float, min_trades: int) -> dict:
    day1 = df[df["track_day"] == 1].copy()
    if day1.empty or field not in day1.columns:
        return {}

    overall_win = (day1["return_pct"] > 0).mean() * 100
    overall_avg = day1["return_pct"].mean()

    def suggest(current: float, subset: pd.DataFrame) -> int:
        if len(subset) < min_trades:
            return int(current)
        sub_win = (subset["return_pct"] > 0).mean() * 100
        sub_avg = subset["return_pct"].mean()
        penalty = current
        if sub_avg < overall_avg - 1.0 or sub_win < overall_win - 12:
            penalty += 2
        elif sub_avg < overall_avg - 0.3 or sub_win < overall_win - 5:
            penalty += 1
        elif sub_avg >= overall_avg and sub_win >= overall_win:
            penalty = max(0, current - 1)
        return int(round(penalty))

    caution_df = day1[day1[field] == "주의"]
    danger_df = day1[day1[field] == "위험"]
    stats = {
        "caution_count": int(len(caution_df)),
        "danger_count": int(len(danger_df)),
        "caution_win": round(float((caution_df["return_pct"] > 0).mean() * 100), 1) if len(caution_df) else None,
        "danger_win": round(float((danger_df["return_pct"] > 0).mean() * 100), 1) if len(danger_df) else None,
        "caution_avg": round(float(caution_df["return_pct"].mean()), 2) if len(caution_df) else None,
        "danger_avg": round(float(danger_df["return_pct"].mean()), 2) if len(danger_df) else None,
    }
    return {
        "stats": stats,
        "suggestions": {
            f"{field.upper()}_CAUTION": suggest(current_caution, caution_df),
            f"{field.upper()}_DANGER": suggest(current_danger, danger_df),
        },
    }


def run_buy_analysis(min_trades: int) -> dict:
    df, source = load_buy_dataset()
    if df.empty:
        logger.warning("No buy-pick dataset available")
        return {}

    if "track_day" not in df.columns:
        logger.warning("Buy-pick dataset does not contain track_day")
        return {}

    day1 = df[df["track_day"] == 1]
    if len(day1) < min_trades:
        logger.warning("Not enough buy-pick day1 rows: %d < %d", len(day1), min_trades)
        return {}

    threshold_result = analyze_buy_thresholds(df, min_trades)
    dart_result = analyze_penalty(
        df,
        "dart_risk",
        BUY_DART_CAUTION_PENALTY,
        BUY_DART_DANGER_PENALTY,
        min_trades,
    )
    news_result = analyze_penalty(
        df,
        "news_risk",
        BUY_NEWS_CAUTION_PENALTY,
        BUY_NEWS_DANGER_PENALTY,
        min_trades,
    )

    suggestions = {}
    if threshold_result:
        suggestions.update(threshold_result["suggestions"])
    if dart_result:
        suggestions["BUY_DART_CAUTION_PENALTY"] = dart_result["suggestions"]["DART_RISK_CAUTION"]
        suggestions["BUY_DART_DANGER_PENALTY"] = dart_result["suggestions"]["DART_RISK_DANGER"]
    if news_result:
        suggestions["BUY_NEWS_CAUTION_PENALTY"] = news_result["suggestions"]["NEWS_RISK_CAUTION"]
        suggestions["BUY_NEWS_DANGER_PENALTY"] = news_result["suggestions"]["NEWS_RISK_DANGER"]

    return {
        "source": source,
        "rows": int(len(df)),
        "day1_rows": int(len(day1)),
        "thresholds": threshold_result,
        "dart": dart_result,
        "news": news_result,
        "suggestions": suggestions,
    }


def print_screen_report(results: dict) -> dict:
    suggestions = {}
    if not results:
        print("\n[screen] no actionable data")
        return suggestions

    print("\n" + "=" * 72)
    print("SCREEN TUNER")
    print("=" * 72)
    for indicator, result in results.items():
        current = tuple(result["current"])
        suggested = tuple(result["suggested"])
        print(f"\n[{indicator}] current={current[0]}~{current[1]} suggested={suggested[0]}~{suggested[1]}")
        overall = result.get("overall", {})
        current_stats = result.get("current_stats", {})
        best_candidate = result.get("best_candidate", {})
        if overall:
            print(
                f"overall count={overall.get('count', 0):,} "
                f"win={overall.get('win_rate')}% avg={overall.get('avg_return')}%"
            )
        if current_stats:
            print(
                f"current range count={current_stats.get('count', 0):,} "
                f"coverage={current_stats.get('coverage', 0)}% "
                f"win={current_stats.get('win_rate')}% avg={current_stats.get('avg_return')}% "
                f"obj={current_stats.get('objective', 0):.2f}"
            )
        if best_candidate:
            best_range = best_candidate.get("range", suggested)
            print(
                f"best candidate={best_range[0]}~{best_range[1]} "
                f"count={best_candidate.get('count', 0):,} "
                f"coverage={best_candidate.get('coverage', 0)}% "
                f"win={best_candidate.get('win_rate')}% avg={best_candidate.get('avg_return')}% "
                f"obj={best_candidate.get('objective', 0):.2f} "
                f"move={best_candidate.get('movement', 0)}"
            )
        if not result.get("change_applied"):
            print(
                f"decision=hold current "
                f"(required improvement >= {SCREEN_CHANGE_THRESHOLD:.2f}, "
                f"min_count={result.get('required_count', 0)})"
            )
        else:
            print(f"decision=change (min_count={result.get('required_count', 0)})")
        table = result.get("table", pd.DataFrame())
        if not table.empty:
            print("range            count  win_rate  avg_return")
            for _, row in table.iterrows():
                print(
                    f"{str(row['bin']):<15} {int(row['count']):>5}  "
                    f"{float(row['win_rate']):>7.1f}%  {float(row['avg_return']):>+9.2f}%"
                )
        if suggested != current:
            suggestions[SCREEN_INDICATORS[indicator]["env_low"]] = suggested[0]
            suggestions[SCREEN_INDICATORS[indicator]["env_high"]] = suggested[1]
    return suggestions


def print_buy_report(result: dict) -> dict:
    if not result:
        print("\n[buy] no actionable data")
        return {}

    print("\n" + "=" * 72)
    print(f"BUY TUNER ({result['source']})")
    print("=" * 72)
    print(f"rows={result['rows']:,} day1_rows={result['day1_rows']:,}")

    threshold_block = result.get("thresholds", {})
    if threshold_block:
        table = threshold_block["table"]
        print("\n[thresholds]")
        print("min_score   count  win_rate  avg_return")
        for _, row in table.iterrows():
            print(
                f"{int(row['threshold']):>9} {int(row['count']):>7}  "
                f"{float(row['win_rate']):>7.1f}%  {float(row['avg_return']):>+9.2f}%"
            )

    for label, block in (("dart", result.get("dart", {})), ("news", result.get("news", {}))):
        stats = block.get("stats", {})
        if not stats:
            continue
        print(f"\n[{label}]")
        print(
            f"caution count={stats.get('caution_count', 0)} "
            f"win={stats.get('caution_win')} avg={stats.get('caution_avg')}"
        )
        print(
            f"danger  count={stats.get('danger_count', 0)} "
            f"win={stats.get('danger_win')} avg={stats.get('danger_avg')}"
        )

    print("\n[suggestions]")
    for key, value in result.get("suggestions", {}).items():
        current = BUY_ENV_DEFAULTS.get(key)
        marker = "*" if current != value else "-"
        print(f"{marker} {key}={value} (current={current})")
    return result.get("suggestions", {})


def apply_to_env(suggestions: dict) -> None:
    if not suggestions:
        print("No changes to apply.")
        return
    if not ENV_FILE.exists():
        print(f"Missing .env: {ENV_FILE}")
        return

    content = ENV_FILE.read_text(encoding="utf-8")
    changes = 0
    for key, value in suggestions.items():
        pattern = rf"^{re.escape(key)}=.*$"
        if re.search(pattern, content, re.MULTILINE):
            content = re.sub(pattern, f"{key}={value}", content, flags=re.MULTILINE)
        else:
            content += f"\n{key}={value}"
        changes += 1

    ENV_FILE.write_text(content, encoding="utf-8")
    print(f"\nApplied {changes} env change(s).")


def main() -> None:
    parser = argparse.ArgumentParser(description="ClosingBell auto tuner")
    parser.add_argument("--apply", action="store_true", help="Apply suggested values to .env")
    parser.add_argument("--mode", choices=["all", "screen", "buy"], default="all")
    parser.add_argument("--min-days", type=int, default=20, help="Minimum screening days")
    parser.add_argument("--min-count", type=int, default=30, help="Minimum sample count per screen bin")
    parser.add_argument("--min-trades", type=int, default=20, help="Minimum day1 trades for buy analysis")
    args = parser.parse_args()

    suggestions = {}
    if args.mode in ("all", "screen"):
        suggestions.update(print_screen_report(run_screen_analysis(args.min_days, args.min_count)))
    if args.mode in ("all", "buy"):
        suggestions.update(print_buy_report(run_buy_analysis(args.min_trades)))

    if args.apply and suggestions:
        apply_to_env(suggestions)


if __name__ == "__main__":
    main()
