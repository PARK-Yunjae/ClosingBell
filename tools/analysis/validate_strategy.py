from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import ANALYSIS_DIR, create_analysis_run_dir
from storage import load_backtest_dataset


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _perf_snapshot(perf_df: pd.DataFrame, days: list[int], group_label: str) -> list[dict]:
    rows = []
    for day in days:
        sub = perf_df[perf_df["track_day"] == day]
        if sub.empty:
            continue
        rows.append(
            {
                "group": group_label,
                "track_day": day,
                "count": int(len(sub)),
                "win_rate": round(float(sub["win"].astype(int).mean() * 100), 2),
                "avg_return": round(float(sub["return_pct"].mean()), 4),
                "median_return": round(float(sub["return_pct"].median()), 4),
            }
        )
    return rows


def _summarize_signal_dataset(signals: pd.DataFrame, perf: pd.DataFrame, date_col: str) -> dict:
    result: dict[str, object] = {
        "signals": int(len(signals)),
        "unique_codes": int(signals["code"].nunique()) if not signals.empty else 0,
        "date_range": None,
        "signal_grades": {},
        "performance": [],
    }
    if not signals.empty:
        result["date_range"] = [
            str(signals[date_col].min().date()),
            str(signals[date_col].max().date()),
        ]
        for grade in ["A", "B", "C"]:
            result["signal_grades"][grade] = int((signals["conviction"] == grade).sum())

    if perf.empty:
        return result

    result["performance"].extend(_perf_snapshot(perf, [1, 3, 5], "all"))
    for grade in ["A", "B", "C"]:
        grade_perf = perf[perf["conviction"] == grade]
        if grade_perf.empty:
            continue
        result["performance"].extend(_perf_snapshot(grade_perf, [1, 3, 5], grade))
    return result


def _load_recent_actual(recent_start: date) -> dict:
    raw_signals = load_backtest_dataset("buy_signals") or []
    raw_perf = (
        load_backtest_dataset("buy_performance_v2")
        or load_backtest_dataset("buy_performance")
        or []
    )

    signals = pd.DataFrame(raw_signals)
    perf = pd.DataFrame(raw_perf)
    if signals.empty or perf.empty:
        return {"signals": 0, "performance": []}

    signals["check_date"] = pd.to_datetime(signals["check_date"], errors="coerce")
    perf["signal_date"] = pd.to_datetime(perf["signal_date"], errors="coerce")
    signals["code"] = signals["code"].astype(str).str.zfill(6)
    perf["code"] = perf["code"].astype(str).str.zfill(6)

    signals = signals[signals["check_date"] >= pd.Timestamp(recent_start)].copy()
    keep_keys = set(
        signals["code"] + "_" + signals["check_date"].dt.strftime("%Y-%m-%d")
    )
    perf["key"] = perf["code"] + "_" + perf["signal_date"].dt.strftime("%Y-%m-%d")
    perf = perf[perf["key"].isin(keep_keys)].copy()

    summary = _summarize_signal_dataset(signals, perf, "check_date")
    if not perf.empty and "dart_risk" in perf.columns:
        dart_rows = []
        for risk in ["정상", "주의", "위험"]:
            sub = perf[perf["dart_risk"] == risk]
            if len(sub) < 5:
                continue
            dart_rows.append(
                {
                    "risk": risk,
                    "count": int(len(sub)),
                    "win_rate": round(float(sub["win"].astype(int).mean() * 100), 2),
                    "avg_return": round(float(sub["return_pct"].mean()), 4),
                }
            )
        summary["dart_breakdown"] = dart_rows
    return summary


def _run_isolated_long_core(
    start_date: str,
    end_date: str,
    output_root: Path,
    keep_raw: bool = False,
) -> dict:
    import tools.backfill.backfill_full as bf

    phase_root = output_root / "long_core"
    bf.LOG_DIR = phase_root / "logs"
    bf.WATCHLIST_DIR = phase_root / "watchlist"
    bf.PERFORMANCE_DIR = phase_root / "performance"
    bf.BACKTEST_DIR = phase_root / "backtest"

    for path in [bf.PERFORMANCE_DIR, bf.BACKTEST_DIR]:
        path.mkdir(parents=True, exist_ok=True)

    bf.save_screen_result = lambda payload: None
    bf.save_watchlist_payload = lambda payload: None
    bf.save_backtest_dataset = lambda dataset_name, data: None

    def _write_backtest_only(path: Path, data) -> None:
        if path.parent == bf.BACKTEST_DIR:
            _write_json(path, data)

    bf.save_legacy_json = _write_backtest_only
    bf.get_screen_result = lambda run_date: None
    bf.get_watchlist = lambda created: None

    bf.run(
        start_date,
        end_date,
        force=True,
        use_dart=False,
        use_enrich=False,
        dry_run=False,
    )

    summary = _load_json(bf.BACKTEST_DIR / "summary.json")
    signals = pd.DataFrame(_load_json(bf.BACKTEST_DIR / "buy_signals.json"))
    perf = pd.DataFrame(_load_json(bf.BACKTEST_DIR / "buy_performance.json"))
    if not signals.empty:
        signals["check_date"] = pd.to_datetime(signals["check_date"], errors="coerce")
        signals["code"] = signals["code"].astype(str).str.zfill(6)
    if not perf.empty:
        perf["signal_date"] = pd.to_datetime(perf["signal_date"], errors="coerce")
        perf["code"] = perf["code"].astype(str).str.zfill(6)

    result = {
        "output_root": str(phase_root),
        "summary": summary,
        "dataset": _summarize_signal_dataset(signals, perf, "check_date"),
    }
    _write_json(phase_root / "summary_snapshot.json", summary)
    _write_json(phase_root / "dataset_summary.json", result["dataset"])

    if not keep_raw:
        shutil.rmtree(bf.BACKTEST_DIR, ignore_errors=True)
        shutil.rmtree(bf.PERFORMANCE_DIR, ignore_errors=True)

    return result


def _find_perf_row(rows: list[dict], group: str, track_day: int) -> dict | None:
    for row in rows:
        if row["group"] == group and row["track_day"] == track_day:
            return row
    return None


def _build_report(
    long_start: str,
    long_end: str,
    long_result: dict,
    recent_start: date,
    recent_result: dict,
) -> str:
    lines: list[str] = []
    lines.append("# ClosingBell Strategy Validation")
    lines.append("")
    lines.append(f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- Long core window: {long_start} ~ {long_end}")
    lines.append(
        f"- Recent actual window: {recent_start.isoformat()} ~ {date.today().isoformat()}"
    )
    lines.append("- Long core uses OHLCV + global regime only, with no DART and no broker enrich.")
    lines.append("- Recent actual uses stored local `buy_signals` / `buy_performance_v2` outputs.")
    lines.append("")

    long_summary = long_result["summary"]
    long_dataset = long_result["dataset"]
    lines.append("## Long Core")
    lines.append(
        f"- Trading days: {long_summary.get('total_days', 0)} | Logs: {long_summary.get('total_logs', 0)}"
    )
    sig_stats = long_summary.get("sig_stats", {})
    lines.append(
        f"- Signals: total {sig_stats.get('total', 0)} | A {sig_stats.get('A', 0)} | B {sig_stats.get('B', 0)} | C {sig_stats.get('C', 0)}"
    )
    for group in ["all", "A", "B"]:
        row = _find_perf_row(long_dataset.get("performance", []), group, 3)
        if not row:
            continue
        lines.append(
            f"- {group} D+3: n={row['count']} | WR {row['win_rate']:.2f}% | Avg {row['avg_return']:+.4f}%"
        )
    lines.append("")

    screen_rows = long_summary.get("screen", [])
    lines.append("### Long Screen Rank Stats")
    for rank in [1, 2, 3]:
        subset = [row for row in screen_rows if row.get("rank") == rank and row.get("day") in {"D+1", "D+3", "D+5"}]
        if not subset:
            continue
        parts = [
            f"{row['day']} WR {row['wr']:.1f}% Avg {row['avg']:+.2f}%"
            for row in subset
        ]
        lines.append(f"- Rank {rank}: " + " | ".join(parts))
    lines.append("")

    lines.append("## Recent Actual")
    lines.append(
        f"- Signals: {recent_result.get('signals', 0)} | Unique codes: {recent_result.get('unique_codes', 0)}"
    )
    for group in ["all", "A", "B", "C"]:
        row = _find_perf_row(recent_result.get("performance", []), group, 3)
        if not row:
            continue
        lines.append(
            f"- {group} D+3: n={row['count']} | WR {row['win_rate']:.2f}% | Avg {row['avg_return']:+.4f}%"
        )
    dart_rows = recent_result.get("dart_breakdown", [])
    if dart_rows:
        lines.append("")
        lines.append("### Recent DART Breakdown")
        for row in dart_rows:
            lines.append(
                f"- {row['risk']}: n={row['count']} | WR {row['win_rate']:.2f}% | Avg {row['avg_return']:+.4f}%"
            )
    lines.append("")

    long_d3 = _find_perf_row(long_dataset.get("performance", []), "A", 3) or _find_perf_row(
        long_dataset.get("performance", []), "all", 3
    )
    recent_d3 = _find_perf_row(recent_result.get("performance", []), "A", 3) or _find_perf_row(
        recent_result.get("performance", []), "all", 3
    )
    lines.append("## Preliminary View")
    if long_d3 and recent_d3:
        if long_d3["avg_return"] > 0 and recent_d3["avg_return"] > 0:
            verdict = "장기 코어와 최근 실제 신호 모두 양(+) 기대수익 구간입니다."
        elif long_d3["avg_return"] > 0 and recent_d3["avg_return"] <= 0:
            verdict = "장기 코어는 유효하지만 최근 운영 결과는 둔화되어 최근 적응 문제를 의심해야 합니다."
        elif long_d3["avg_return"] <= 0 and recent_d3["avg_return"] > 0:
            verdict = "최근 성과는 있으나 장기 코어 우위가 약해 최근 과적합 가능성을 점검해야 합니다."
        else:
            verdict = "장기/최근 모두 뚜렷한 우위를 보여주지 못해 전략 재설계가 필요합니다."
        lines.append(f"- {verdict}")
    lines.append(
        f"- Long core outputs: `{long_result['output_root']}`"
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="ClosingBell strategy validation")
    parser.add_argument("--long-start", default="2016-08-01")
    parser.add_argument("--long-end", default=date.today().isoformat())
    parser.add_argument("--recent-months", type=int, default=6)
    parser.add_argument("--output-root", default=str(ANALYSIS_DIR))
    parser.add_argument(
        "--keep-raw",
        action="store_true",
        help="Keep raw backtest/performance artifacts under long_core",
    )
    args = parser.parse_args()

    if Path(args.output_root).resolve() == ANALYSIS_DIR.resolve():
        output_root = create_analysis_run_dir("validation")
    else:
        output_root = Path(args.output_root) / datetime.now().strftime("%Y%m%d_%H%M%S_validation")
        output_root.mkdir(parents=True, exist_ok=True)

    recent_start = date.today() - timedelta(days=args.recent_months * 31)

    long_result = _run_isolated_long_core(
        args.long_start,
        args.long_end,
        output_root,
        keep_raw=args.keep_raw,
    )
    recent_result = _load_recent_actual(recent_start)

    report = _build_report(
        args.long_start,
        args.long_end,
        long_result,
        recent_start,
        recent_result,
    )
    report_path = output_root / "validation_report.md"
    report_path.write_text(report, encoding="utf-8")

    payload = {
        "long_core": long_result,
        "recent_actual": recent_result,
        "report_path": str(report_path),
    }
    _write_json(output_root / "validation_report.json", payload)
    print(report)
    print(f"Report saved: {report_path}")


if __name__ == "__main__":
    main()
