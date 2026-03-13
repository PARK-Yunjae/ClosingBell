"""
Analyze major holder ratio effects on stored buy-signal performance.

Default output is markdown + json under `data/analysis/<timestamp>_holder`.
Use `--save-csv` only when the matched row dataset itself is needed.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import ANALYSIS_DIR, DATA_DIR, create_analysis_run_dir
from storage import load_backtest_dataset

HOLDER_CSV = DATA_DIR / "meta" / "major_holder.csv"
BUCKET_BINS = [0, 10, 20, 30, 40, 50, 60, 70, 100]
BUCKET_LABELS = ["0-10%", "10-20%", "20-30%", "30-40%", "40-50%", "50-60%", "60-70%", "70%+"]
CONVICTION_BINS = [0, 20, 30, 50, 100]
CONVICTION_LABELS = ["<20%", "20-30%", "30-50%", "50%+"]
CUTOFF_SCAN_VALUES = [10, 15, 20, 25, 30, 35, 40, 50]


def _normalize_code(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.zfill(6)


def _load_holder_frame() -> pd.DataFrame:
    if not HOLDER_CSV.exists():
        raise SystemExit(f"Missing holder data: {HOLDER_CSV}")

    holder = pd.read_csv(HOLDER_CSV, dtype={"code": str})
    required = {"code", "total_pct"}
    missing = required - set(holder.columns)
    if missing:
        raise SystemExit(f"holder csv missing columns: {sorted(missing)}")

    holder["code"] = _normalize_code(holder["code"])
    holder["total_pct"] = pd.to_numeric(holder["total_pct"], errors="coerce")
    holder = holder.dropna(subset=["code", "total_pct"]).copy()

    if "year" in holder.columns:
        holder["year"] = pd.to_numeric(holder["year"], errors="coerce")
        holder = holder.sort_values(["code", "year"], ascending=[True, False])

    return holder.drop_duplicates("code", keep="first")


def _load_perf_frame() -> pd.DataFrame:
    perf = load_backtest_dataset("buy_performance_v2")
    if not perf:
        perf = load_backtest_dataset("buy_performance")
    frame = pd.DataFrame(perf or [])
    if frame.empty:
        raise SystemExit("No buy_performance dataset found")
    if "code" not in frame.columns:
        raise SystemExit("buy_performance dataset missing 'code'")

    frame["code"] = _normalize_code(frame["code"])
    frame["track_day"] = pd.to_numeric(frame.get("track_day"), errors="coerce")
    frame["return_pct"] = pd.to_numeric(frame.get("return_pct"), errors="coerce")
    if "high_ret" in frame.columns:
        frame["high_ret"] = pd.to_numeric(frame["high_ret"], errors="coerce")
    else:
        frame["high_ret"] = pd.NA
    if "win" in frame.columns:
        frame["win"] = frame["win"].fillna(False).astype(bool)
    else:
        frame["win"] = frame["return_pct"] > 0
    frame = frame.dropna(subset=["track_day", "return_pct"]).copy()
    frame["track_day"] = frame["track_day"].astype(int)
    return frame


def _load_signal_frame() -> pd.DataFrame:
    signals = pd.DataFrame(load_backtest_dataset("buy_signals") or [])
    if signals.empty:
        raise SystemExit("No buy_signals dataset found")
    if "code" not in signals.columns:
        raise SystemExit("buy_signals dataset missing 'code'")
    signals["code"] = _normalize_code(signals["code"])
    return signals


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    holder = _load_holder_frame()
    holder_map = holder.set_index("code")["total_pct"].to_dict()

    signals = _load_signal_frame()
    perf = _load_perf_frame()

    signals["holder_pct"] = signals["code"].map(holder_map)
    perf["holder_pct"] = perf["code"].map(holder_map)

    matched_perf = perf[perf["holder_pct"].notna()].copy()
    summary = {
        "holder_universe": int(len(holder)),
        "signals_rows": int(len(signals)),
        "signals_matched": int(signals["holder_pct"].notna().sum()),
        "performance_rows": int(len(perf)),
        "performance_matched": int(len(matched_perf)),
        "matched_codes": int(matched_perf["code"].nunique()),
    }
    return signals, matched_perf, summary


def _summarize_subset(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {
            "count": 0,
            "win_rate": None,
            "avg_return": None,
            "avg_high_ret": None,
            "profit_loss": None,
        }

    wins = frame[frame["return_pct"] > 0]["return_pct"]
    losses = frame[frame["return_pct"] <= 0]["return_pct"]
    profit_loss = None
    if not losses.empty and float(losses.mean()) != 0:
        profit_loss = abs(float(wins.mean()) / float(losses.mean())) if not wins.empty else 0.0
    elif not wins.empty:
        profit_loss = float("inf")

    avg_high = None
    if "high_ret" in frame.columns and frame["high_ret"].notna().any():
        avg_high = float(frame["high_ret"].dropna().mean())

    return {
        "count": int(len(frame)),
        "win_rate": float(frame["win"].mean() * 100),
        "avg_return": float(frame["return_pct"].mean()),
        "avg_high_ret": avg_high,
        "profit_loss": profit_loss,
    }


def _prepare_perf(perf: pd.DataFrame) -> pd.DataFrame:
    prepared = perf.copy()
    prepared["holder_pct"] = pd.to_numeric(prepared["holder_pct"], errors="coerce")
    prepared = prepared.dropna(subset=["holder_pct"]).copy()
    prepared["bucket"] = pd.cut(
        prepared["holder_pct"],
        bins=BUCKET_BINS,
        labels=BUCKET_LABELS,
        right=False,
    )
    prepared["holder_bucket"] = pd.cut(
        prepared["holder_pct"],
        bins=CONVICTION_BINS,
        labels=CONVICTION_LABELS,
        right=False,
    )
    return prepared


def build_bucket_summary(perf: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []
    for track_day in [1, 2, 3, 5]:
        day_perf = perf[perf["track_day"] == track_day].copy()
        if day_perf.empty:
            continue

        bucket_rows = []
        for bucket in BUCKET_LABELS:
            sub = day_perf[day_perf["bucket"] == bucket]
            if len(sub) < 5:
                continue
            stats = _summarize_subset(sub)
            stats["bucket"] = bucket
            bucket_rows.append(stats)

        rows.append(
            {
                "track_day": track_day,
                "total": int(len(day_perf)),
                "overall": _summarize_subset(day_perf),
                "buckets": bucket_rows,
            }
        )
    return rows


def build_cutoff_scan(perf: pd.DataFrame) -> list[dict]:
    day1 = perf[perf["track_day"] == 1].copy()
    rows: list[dict] = []
    for cutoff in CUTOFF_SCAN_VALUES:
        kept = day1[day1["holder_pct"] >= cutoff]
        removed = day1[day1["holder_pct"] < cutoff]
        if len(kept) < 10 or len(removed) < 10:
            continue
        kept_stats = _summarize_subset(kept)
        removed_stats = _summarize_subset(removed)
        rows.append(
            {
                "cutoff": float(cutoff),
                "kept_count": kept_stats["count"],
                "kept_win_rate": kept_stats["win_rate"],
                "kept_avg_return": kept_stats["avg_return"],
                "removed_count": removed_stats["count"],
                "removed_win_rate": removed_stats["win_rate"],
                "removed_avg_return": removed_stats["avg_return"],
                "return_gap": (
                    None
                    if kept_stats["avg_return"] is None or removed_stats["avg_return"] is None
                    else kept_stats["avg_return"] - removed_stats["avg_return"]
                ),
            }
        )
    return rows


def build_cutoff_summary(perf: pd.DataFrame, cutoff: float) -> dict:
    day1 = perf[perf["track_day"] == 1].copy()
    kept = day1[day1["holder_pct"] >= cutoff]
    removed = day1[day1["holder_pct"] < cutoff]
    total_codes = int(day1["code"].nunique()) if not day1.empty else 0
    removed_codes = int(removed["code"].nunique()) if not removed.empty else 0

    conviction_rows = []
    if "conviction" in day1.columns:
        for grade in ["A", "B", "C"]:
            total = int((day1["conviction"] == grade).sum())
            if total == 0:
                continue
            removed_count = int((removed["conviction"] == grade).sum())
            conviction_rows.append(
                {
                    "conviction": grade,
                    "total": total,
                    "removed": removed_count,
                    "removed_pct": float(removed_count / total * 100),
                }
            )

    return {
        "cutoff": float(cutoff),
        "all": _summarize_subset(day1),
        "kept": _summarize_subset(kept),
        "removed": _summarize_subset(removed),
        "total_codes": total_codes,
        "removed_codes": removed_codes,
        "removed_codes_pct": float(removed_codes / total_codes * 100) if total_codes else None,
        "removed_rows_pct": float(len(removed) / len(day1) * 100) if len(day1) else None,
        "conviction_removal": conviction_rows,
    }


def build_conviction_breakdown(perf: pd.DataFrame) -> list[dict]:
    if "conviction" not in perf.columns:
        return []

    day1 = perf[perf["track_day"] == 1].copy()
    if day1.empty:
        return []

    rows = []
    for grade in ["A", "B", "C"]:
        for bucket in CONVICTION_LABELS:
            sub = day1[(day1["conviction"] == grade) & (day1["holder_bucket"] == bucket)]
            if len(sub) < 3:
                continue
            stats = _summarize_subset(sub)
            rows.append(
                {
                    "conviction": grade,
                    "holder_bucket": bucket,
                    "count": stats["count"],
                    "win_rate": stats["win_rate"],
                    "avg_return": stats["avg_return"],
                }
            )
    return rows


def _find_best_bucket(bucket_summary: list[dict], track_day: int) -> dict | None:
    for row in bucket_summary:
        if row["track_day"] != track_day:
            continue
        if not row["buckets"]:
            return None
        return max(
            row["buckets"],
            key=lambda item: (item["avg_return"] is not None, item["avg_return"] or float("-inf")),
        )
    return None


def _format_percent(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "-"
    return f"{value:+.2f}%" if signed else f"{value:.2f}%"


def _format_number(value: float | int | None) -> str:
    if value is None:
        return "-"
    if value == float("inf"):
        return "inf"
    if isinstance(value, int):
        return str(value)
    return f"{value:.2f}"


def build_payload(perf: pd.DataFrame, dataset: dict, cutoff: float, include_detail: bool) -> dict:
    bucket_summary = build_bucket_summary(perf)
    cutoff_scan = build_cutoff_scan(perf)
    cutoff_summary = build_cutoff_summary(perf, cutoff)
    conviction_rows = build_conviction_breakdown(perf) if include_detail else []

    best_bucket_d1 = _find_best_bucket(bucket_summary, 1)
    best_bucket_d3 = _find_best_bucket(bucket_summary, 3)
    best_cutoff = None
    if cutoff_scan:
        best_cutoff = max(
            cutoff_scan,
            key=lambda item: (item["return_gap"] is not None, item["return_gap"] or float("-inf")),
        )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dataset": dataset,
        "cutoff": float(cutoff),
        "key_findings": {
            "best_bucket_d1": best_bucket_d1,
            "best_bucket_d3": best_bucket_d3,
            "best_cutoff_by_return_gap": best_cutoff,
        },
        "bucket_summary": bucket_summary,
        "cutoff_scan": cutoff_scan,
        "cutoff_summary": cutoff_summary,
        "conviction_breakdown": conviction_rows,
    }


def build_report(payload: dict) -> str:
    dataset = payload["dataset"]
    cutoff = payload["cutoff"]
    findings = payload["key_findings"]
    chosen = payload["cutoff_summary"]

    lines = [
        "# Holder Filter Analysis",
        "",
        f"- Generated: {payload['generated_at']}",
        f"- Cutoff evaluated: {cutoff:.0f}%",
        f"- Holder universe: {dataset['holder_universe']}",
        (
            f"- Signal coverage: {dataset['signals_matched']}/{dataset['signals_rows']} "
            f"({_format_percent(dataset['signals_matched'] / dataset['signals_rows'] * 100 if dataset['signals_rows'] else None)})"
        ),
        (
            f"- Performance coverage: {dataset['performance_matched']}/{dataset['performance_rows']} "
            f"({_format_percent(dataset['performance_matched'] / dataset['performance_rows'] * 100 if dataset['performance_rows'] else None)})"
        ),
        f"- Matched codes: {dataset['matched_codes']}",
        "",
        "## Key Findings",
    ]

    best_d1 = findings.get("best_bucket_d1")
    if best_d1:
        lines.append(
            f"- Best D+1 holder bucket: {best_d1['bucket']} | "
            f"win {_format_percent(best_d1['win_rate'])} | "
            f"avg {_format_percent(best_d1['avg_return'], signed=True)}"
        )

    best_d3 = findings.get("best_bucket_d3")
    if best_d3:
        lines.append(
            f"- Best D+3 holder bucket: {best_d3['bucket']} | "
            f"win {_format_percent(best_d3['win_rate'])} | "
            f"avg {_format_percent(best_d3['avg_return'], signed=True)}"
        )

    best_cutoff = findings.get("best_cutoff_by_return_gap")
    if best_cutoff:
        lines.append(
            f"- Best D+1 cutoff gap in scan: {best_cutoff['cutoff']:.0f}% | "
            f"kept {_format_percent(best_cutoff['kept_avg_return'], signed=True)} vs "
            f"removed {_format_percent(best_cutoff['removed_avg_return'], signed=True)} | "
            f"gap {_format_percent(best_cutoff['return_gap'], signed=True)}"
        )

    lines.extend(
        [
            (
                f"- Chosen cutoff {cutoff:.0f}% keeps {_format_number(chosen['kept']['count'])} rows "
                f"with avg {_format_percent(chosen['kept']['avg_return'], signed=True)}"
            ),
            (
                f"- Chosen cutoff {cutoff:.0f}% removes {_format_number(chosen['removed']['count'])} rows "
                f"({_format_percent(chosen['removed_rows_pct'])}) and {_format_number(chosen['removed_codes'])}/"
                f"{_format_number(chosen['total_codes'])} codes ({_format_percent(chosen['removed_codes_pct'])})"
            ),
            "",
            "## Track-Day Bucket Summary",
        ]
    )

    for track_row in payload["bucket_summary"]:
        lines.extend(
            [
                "",
                f"### D+{track_row['track_day']}",
                "",
                "| Bucket | Count | Win Rate | Avg Return | Avg High | Profit/Loss |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for bucket_row in track_row["buckets"]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        bucket_row["bucket"],
                        str(bucket_row["count"]),
                        _format_percent(bucket_row["win_rate"]),
                        _format_percent(bucket_row["avg_return"], signed=True),
                        _format_percent(bucket_row["avg_high_ret"], signed=True),
                        _format_number(bucket_row["profit_loss"]),
                    ]
                )
                + " |"
            )
        overall = track_row["overall"]
        lines.append(
            "| Overall | "
            + " | ".join(
                [
                    str(overall["count"]),
                    _format_percent(overall["win_rate"]),
                    _format_percent(overall["avg_return"], signed=True),
                    _format_percent(overall["avg_high_ret"], signed=True),
                    _format_number(overall["profit_loss"]),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Chosen Cutoff Summary (D+1)",
            "",
            "| Group | Count | Win Rate | Avg Return | Avg High | Profit/Loss |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for label, key in [("All", "all"), ("Kept", "kept"), ("Removed", "removed")]:
        row = chosen[key]
        lines.append(
            "| "
            + " | ".join(
                [
                    label,
                    str(row["count"]),
                    _format_percent(row["win_rate"]),
                    _format_percent(row["avg_return"], signed=True),
                    _format_percent(row["avg_high_ret"], signed=True),
                    _format_number(row["profit_loss"]),
                ]
            )
            + " |"
        )

    if payload["cutoff_scan"]:
        lines.extend(
            [
                "",
                "## Cutoff Scan (D+1)",
                "",
                "| Cutoff | Kept Rows | Kept Win | Kept Avg | Removed Rows | Removed Win | Removed Avg | Gap |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in payload["cutoff_scan"]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"{row['cutoff']:.0f}%",
                        str(row["kept_count"]),
                        _format_percent(row["kept_win_rate"]),
                        _format_percent(row["kept_avg_return"], signed=True),
                        str(row["removed_count"]),
                        _format_percent(row["removed_win_rate"]),
                        _format_percent(row["removed_avg_return"], signed=True),
                        _format_percent(row["return_gap"], signed=True),
                    ]
                )
                + " |"
            )

    if payload["conviction_breakdown"]:
        lines.extend(
            [
                "",
                "## Conviction Cross Check (D+1)",
                "",
                "| Conviction | Holder Bucket | Count | Win Rate | Avg Return |",
                "| --- | --- | ---: | ---: | ---: |",
            ]
        )
        for row in payload["conviction_breakdown"]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        row["conviction"],
                        row["holder_bucket"],
                        str(row["count"]),
                        _format_percent(row["win_rate"]),
                        _format_percent(row["avg_return"], signed=True),
                    ]
                )
                + " |"
            )

    if chosen["conviction_removal"]:
        lines.extend(["", "## Conviction Removal Share", ""])
        for row in chosen["conviction_removal"]:
            lines.append(
                f"- {row['conviction']}: {row['removed']}/{row['total']} removed "
                f"({_format_percent(row['removed_pct'])})"
            )

    lines.append("")
    return "\n".join(lines)


def save_outputs(output_dir: Path, payload: dict, perf: pd.DataFrame, save_csv: bool) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "holder_analysis.md"
    json_path = output_dir / "holder_analysis.json"

    report_path.write_text(build_report(payload), encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if save_csv:
        csv_path = output_dir / "holder_analysis.csv"
        cols = [
            column
            for column in [
                "code",
                "name",
                "signal_date",
                "rank",
                "conviction",
                "track_day",
                "return_pct",
                "high_ret",
                "win",
                "holder_pct",
                "bucket",
                "holder_bucket",
            ]
            if column in perf.columns
        ]
        perf[cols].to_csv(csv_path, index=False, encoding="utf-8-sig")

    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze holder-ratio effects on stored buy performance")
    parser.add_argument("--cutoff", type=float, default=30.0, help="Selected holder cutoff for D+1 summary")
    parser.add_argument("--detail", action="store_true", help="Include conviction cross-check section")
    parser.add_argument("--save-csv", action="store_true", help="Also save matched row csv")
    parser.add_argument("--output-root", default=str(ANALYSIS_DIR), help="Output directory root")
    args = parser.parse_args()

    output_root = Path(args.output_root)
    if output_root.resolve() == ANALYSIS_DIR.resolve():
        output_dir = create_analysis_run_dir("holder")
    else:
        output_dir = output_root
        output_dir.mkdir(parents=True, exist_ok=True)

    _, perf, dataset = load_data()
    prepared = _prepare_perf(perf)
    payload = build_payload(prepared, dataset, args.cutoff, args.detail)
    report_path = save_outputs(output_dir, payload, prepared, args.save_csv)

    print(report_path.read_text(encoding="utf-8"))
    print(f"Report saved: {report_path}")


if __name__ == "__main__":
    main()
