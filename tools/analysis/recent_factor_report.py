from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import ANALYSIS_DIR, DATA_DIR, GLOBAL_CSV, PROJECT_DIR, create_analysis_run_dir
from storage import load_backtest_dataset


def _load_signals(start_date: date) -> pd.DataFrame:
    rows = load_backtest_dataset("buy_signals") or []
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["check_date"] = pd.to_datetime(df["check_date"], errors="coerce")
    return df[df["check_date"] >= pd.Timestamp(start_date)].copy()


def _load_perf(signals: pd.DataFrame) -> pd.DataFrame:
    rows = (
        load_backtest_dataset("buy_performance_v2")
        or load_backtest_dataset("buy_performance")
        or []
    )
    df = pd.DataFrame(rows)
    if df.empty or signals.empty:
        return df
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["signal_date"] = pd.to_datetime(df["signal_date"], errors="coerce")
    signal_keys = set(
        signals["code"] + "_" + signals["check_date"].dt.strftime("%Y-%m-%d")
    )
    df["key"] = df["code"] + "_" + df["signal_date"].dt.strftime("%Y-%m-%d")
    return df[df["key"].isin(signal_keys)].copy()


def _load_holder_maps() -> tuple[dict[str, float], dict[str, float]]:
    path = DATA_DIR / "meta" / "major_holder.csv"
    if not path.exists():
        return {}, {}
    h = pd.read_csv(path, dtype={"code": str}, encoding="utf-8-sig")
    h["code"] = h["code"].str.zfill(6)
    h["total_pct"] = h["total_pct"].clip(upper=100)

    latest = h.sort_values("year", ascending=False).drop_duplicates("code", keep="first")
    level = latest.set_index("code")["total_pct"].to_dict()

    years = sorted(h["year"].dropna().unique())
    change: dict[str, float] = {}
    if len(years) >= 2:
        y0, y1 = years[-2], years[-1]
        h0 = h[h["year"] == y0].set_index("code")["total_pct"]
        h1 = h[h["year"] == y1].set_index("code")["total_pct"]
        both = pd.DataFrame({"old": h0, "new": h1}).dropna()
        both["chg"] = both["new"] - both["old"]
        change = both["chg"].to_dict()
    return level, change


def _load_events() -> dict[str, list[dict]]:
    path = PROJECT_DIR / "data" / "reference" / "market_calendar.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    event_map: dict[str, list[dict]] = {}
    for ev in raw:
        try:
            center = datetime.strptime(ev["date"], "%Y-%m-%d").date()
        except Exception:
            continue
        for delta in (-1, 0, 1):
            d = (center + timedelta(days=delta)).isoformat()
            event_map.setdefault(d, []).append({**ev, "distance": delta})
    return event_map


def _load_global() -> pd.DataFrame:
    df = pd.read_csv(GLOBAL_CSV)
    df.columns = [c.strip().lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def _holder_bucket(level: float | None) -> str:
    if level is None or pd.isna(level):
        return "unknown"
    if level < 20:
        return "<20%"
    if level < 30:
        return "20-30%"
    if level < 50:
        return "30-50%"
    return "50%+"


def _holder_change_bucket(change: float | None) -> str:
    if change is None or pd.isna(change):
        return "unknown"
    if change <= -10:
        return "<=-10%p"
    if change <= -5:
        return "-10~-5%p"
    if change < 0:
        return "-5~0%p"
    if change < 3:
        return "0~+3%p"
    return ">=+3%p"


def _event_label(events: list[dict]) -> str:
    if not events:
        return "none"
    types = sorted({e["type"] for e in events})
    return "+".join(types)


def _event_impact(events: list[dict]) -> int:
    score_map = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    return max((score_map.get(e.get("impact", ""), 0) for e in events), default=0)


def _build_signal_frame(signals: pd.DataFrame) -> pd.DataFrame:
    level_map, change_map = _load_holder_maps()
    event_map = _load_events()
    global_df = _load_global()

    signal_rows = []
    for _, row in signals.iterrows():
        ds = row["check_date"].strftime("%Y-%m-%d")
        code = row["code"]
        events = event_map.get(ds, [])

        prev_global = global_df[global_df["date"] < row["check_date"]]
        same_or_prev = global_df[global_df["date"] <= row["check_date"]]
        nasdaq_prev = None
        if not prev_global.empty and "nasdaq_change_pct" in prev_global.columns:
            valid = prev_global.dropna(subset=["nasdaq_change_pct"])
            if not valid.empty:
                nasdaq_prev = float(valid.iloc[-1]["nasdaq_change_pct"])

        kospi_gap = None
        if not same_or_prev.empty and "kospi_close" in same_or_prev.columns:
            valid = same_or_prev.dropna(subset=["kospi_close"]).tail(20)
            if len(valid) >= 20:
                current = float(valid.iloc[-1]["kospi_close"])
                ma20 = float(valid["kospi_close"].mean())
                if ma20:
                    kospi_gap = (current / ma20 - 1) * 100

        level = level_map.get(code)
        change = change_map.get(code)
        impact = _event_impact(events)

        if nasdaq_prev is not None and nasdaq_prev > 0 and kospi_gap is not None and kospi_gap > 0:
            regime = "rising"
        elif (nasdaq_prev is not None and abs(nasdaq_prev) >= 1.5) or impact >= 3:
            regime = "chaotic"
        elif nasdaq_prev is not None and nasdaq_prev < 0 and kospi_gap is not None and kospi_gap < 0:
            regime = "weak"
        else:
            regime = "mixed"

        signal_rows.append(
            {
                "key": f"{code}_{ds}",
                "code": code,
                "name": row["name"],
                "signal_date": ds,
                "rank": row.get("rank"),
                "conviction": row.get("conviction", ""),
                "conviction_score": row.get("conviction_score", 0),
                "signal_type": row.get("signal_type", ""),
                "conditions_met": row.get("conditions_met", 0),
                "in_window": bool(row.get("in_window", False)),
                "dart_risk": row.get("dart_risk", ""),
                "ai_action": row.get("ai_action", ""),
                "broker_signal": row.get("broker_signal", ""),
                "holder_pct": level,
                "holder_bucket": _holder_bucket(level),
                "holder_change": change,
                "holder_change_bucket": _holder_change_bucket(change),
                "event_type": _event_label(events),
                "event_impact": impact,
                "nasdaq_prev_change": nasdaq_prev,
                "kospi_ma20_gap": kospi_gap,
                "regime": regime,
            }
        )
    df = pd.DataFrame(signal_rows)
    if df.empty:
        return df
    df = df.sort_values(
        ["key", "conviction_score", "rank", "signal_date"],
        ascending=[True, False, True, False],
    )
    df["dup_count"] = df.groupby("key")["key"].transform("size")
    return df.drop_duplicates("key", keep="first").reset_index(drop=True)


def _bucket_nasdaq(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "unknown"
    if value <= -2:
        return "<=-2%"
    if value < 0:
        return "-2~0%"
    if value < 2:
        return "0~+2%"
    return ">=+2%"


def _bucket_kospi_gap(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "unknown"
    if value <= -3:
        return "<=-3%"
    if value < 0:
        return "-3~0%"
    if value < 3:
        return "0~+3%"
    return ">=+3%"


def _summarize_group(df: pd.DataFrame, column: str, track_day: int, min_n: int = 20) -> list[dict]:
    subset = df[df["track_day"] == track_day].copy()
    if subset.empty:
        return []
    rows = []
    for value, grp in subset.groupby(column):
        if len(grp) < min_n:
            continue
        rows.append(
            {
                "group": str(value),
                "count": int(len(grp)),
                "win_rate": round(float(grp["win"].astype(int).mean() * 100), 2),
                "avg_return": round(float(grp["return_pct"].mean()), 4),
                "median_return": round(float(grp["return_pct"].median()), 4),
            }
        )
    rows.sort(key=lambda x: (x["avg_return"], x["win_rate"]), reverse=True)
    return rows


def _render_section(title: str, rows: list[dict], top_n: int = 5) -> list[str]:
    lines = [f"## {title}"]
    if not rows:
        lines.append("- no data")
        lines.append("")
        return lines
    lines.append("- top")
    for row in rows[:top_n]:
        lines.append(
            f"  - {row['group']}: n={row['count']} | WR {row['win_rate']:.2f}% | Avg {row['avg_return']:+.4f}%"
        )
    lines.append("- bottom")
    for row in rows[-top_n:]:
        lines.append(
            f"  - {row['group']}: n={row['count']} | WR {row['win_rate']:.2f}% | Avg {row['avg_return']:+.4f}%"
        )
    lines.append("")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Recent factor report")
    parser.add_argument("--start-date", default="2025-09-07")
    parser.add_argument("--output-root", default=str(ANALYSIS_DIR))
    parser.add_argument(
        "--save-dataset",
        action="store_true",
        help="Keep merged factor dataset CSV alongside the report",
    )
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start_date)
    signals = _load_signals(start_date)
    perf = _load_perf(signals)
    signal_factors = _build_signal_frame(signals)
    if perf.empty or signal_factors.empty:
        raise SystemExit("recent signal/performance data not found")

    perf["key"] = perf["code"] + "_" + perf["signal_date"].dt.strftime("%Y-%m-%d")
    merged = perf.merge(signal_factors, on="key", how="left", suffixes=("", "_sig"))
    merged["nasdaq_bucket"] = merged["nasdaq_prev_change"].apply(_bucket_nasdaq)
    merged["kospi_gap_bucket"] = merged["kospi_ma20_gap"].apply(_bucket_kospi_gap)

    if Path(args.output_root).resolve() == ANALYSIS_DIR.resolve():
        out_dir = create_analysis_run_dir("recent")
    else:
        out_dir = Path(args.output_root) / datetime.now().strftime("%Y%m%d_%H%M%S_recent")
        out_dir.mkdir(parents=True, exist_ok=True)

    if args.save_dataset:
        merged.to_csv(out_dir / "recent_factor_dataset.csv", index=False, encoding="utf-8-sig")

    report_lines = [
        "# Recent Factor Report",
        "",
        f"- Window: {start_date.isoformat()} ~ {date.today().isoformat()}",
        f"- Signals: {len(signals)} | D+3 rows: {len(merged[merged['track_day']==3])}",
        "",
    ]

    base_d3 = merged[merged["track_day"] == 3]
    base_d5 = merged[merged["track_day"] == 5]
    report_lines.append(
        f"- Baseline D+3: WR {base_d3['win'].astype(int).mean()*100:.2f}% | Avg {base_d3['return_pct'].mean():+.4f}%"
    )
    report_lines.append(
        f"- Baseline D+5: WR {base_d5['win'].astype(int).mean()*100:.2f}% | Avg {base_d5['return_pct'].mean():+.4f}%"
    )
    report_lines.append("")

    report_lines.extend(_render_section("Regime D+3", _summarize_group(merged, "regime", 3, min_n=20), top_n=4))
    report_lines.extend(_render_section("Event Type D+3", _summarize_group(merged, "event_type", 3, min_n=15)))
    report_lines.extend(_render_section("Nasdaq Prev D+3", _summarize_group(merged, "nasdaq_bucket", 3, min_n=20), top_n=4))
    report_lines.extend(_render_section("Kospi Gap D+3", _summarize_group(merged, "kospi_gap_bucket", 3, min_n=20), top_n=4))
    report_lines.extend(_render_section("Rank D+3", _summarize_group(merged, "rank", 3, min_n=20), top_n=3))
    report_lines.extend(_render_section("Conviction D+3", _summarize_group(merged, "conviction", 3, min_n=20), top_n=3))
    report_lines.extend(_render_section("Signal Type D+3", _summarize_group(merged, "signal_type", 3, min_n=20)))
    report_lines.extend(_render_section("Holder Bucket D+3", _summarize_group(merged, "holder_bucket", 3, min_n=20), top_n=4))
    report_lines.extend(_render_section("Holder Change D+3", _summarize_group(merged, "holder_change_bucket", 3, min_n=20), top_n=5))
    report_lines.extend(_render_section("DART Risk D+3", _summarize_group(merged, "dart_risk", 3, min_n=20), top_n=3))

    report_path = out_dir / "recent_factor_report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    summary_payload = {
        "report_path": str(report_path),
        "baseline": {
            "d3_win_rate": round(float(base_d3["win"].astype(int).mean() * 100), 4),
            "d3_avg_return": round(float(base_d3["return_pct"].mean()), 6),
            "d5_win_rate": round(float(base_d5["win"].astype(int).mean() * 100), 4),
            "d5_avg_return": round(float(base_d5["return_pct"].mean()), 6),
        },
        "sections": {
            "regime_d3": _summarize_group(merged, "regime", 3, min_n=20),
            "event_type_d3": _summarize_group(merged, "event_type", 3, min_n=15),
            "nasdaq_d3": _summarize_group(merged, "nasdaq_bucket", 3, min_n=20),
            "kospi_gap_d3": _summarize_group(merged, "kospi_gap_bucket", 3, min_n=20),
            "rank_d3": _summarize_group(merged, "rank", 3, min_n=20),
            "conviction_d3": _summarize_group(merged, "conviction", 3, min_n=20),
            "signal_type_d3": _summarize_group(merged, "signal_type", 3, min_n=20),
            "holder_bucket_d3": _summarize_group(merged, "holder_bucket", 3, min_n=20),
            "holder_change_d3": _summarize_group(merged, "holder_change_bucket", 3, min_n=20),
            "dart_d3": _summarize_group(merged, "dart_risk", 3, min_n=20),
        },
    }
    (out_dir / "recent_factor_report.json").write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\n".join(report_lines))
    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
