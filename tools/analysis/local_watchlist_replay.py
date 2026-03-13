from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import ANALYSIS_DIR, OHLCV_DIR, create_analysis_run_dir
from trading_calendar import trading_days_since
from watchlist_monitor import (
    DAILY_PICK_TOP_K,
    _apply_market_context_adjustment,
    _score_stock,
    get_market_context,
    load_active_watchlists,
)


def _latest_local_quote(code: str, as_of: str) -> tuple[dict | None, str | None]:
    path = OHLCV_DIR / f"{code}.csv"
    if not path.exists():
        return None, None
    df = pd.read_csv(path)
    if "date" not in df.columns:
        return None, None
    df.columns = [c.lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    cutoff = pd.Timestamp(as_of)
    df = df[df["date"] <= cutoff]
    if df.empty:
        return None, None
    row = df.iloc[-1]
    return {
        "price": int(row.get("close", 0) or 0),
        "volume": int(row.get("volume", 0) or 0),
    }, row["date"].strftime("%Y-%m-%d")


def _blocked_reason(stock: dict, as_of: str, days_elapsed: int) -> str:
    quote, _ = _latest_local_quote(stock["code"], as_of)
    if not quote:
        return "missing_ohlcv"
    path = OHLCV_DIR / f"{stock['code']}.csv"
    df = pd.read_csv(path)
    if "date" not in df.columns:
        return "missing_date_column"
    if len(df) < 20:
        return "short_ohlcv"
    flags: list[str] = []
    _, info = _apply_market_context_adjustment(
        stock["code"],
        int(stock.get("rank", 99) or 99),
        quote["price"],
        0.0,
        flags,
        as_of,
    )
    if info["blocked"]:
        return ",".join(flags) if flags else "market_context_blocked"
    if days_elapsed < int(stock.get("window_start", 1) or 1):
        return "pre_window"
    if days_elapsed > int(stock.get("window_end", 5) or 5):
        return "post_window"
    return "score_none"


def _summarize_pick(row: dict) -> dict:
    return {
        "rank": row.get("rank"),
        "code": row.get("code"),
        "name": row.get("name"),
        "watchlist_date": row.get("watchlist_date"),
        "conviction": row.get("conviction"),
        "conviction_score": round(float(row.get("conviction_score", 0.0)), 2),
        "signal_type": row.get("signal_type", ""),
        "market_regime": row.get("market_regime", ""),
        "event_warning": row.get("event_warning", ""),
        "risk_flags": row.get("risk_flags", []),
        "price_source_date": row.get("price_source_date", ""),
        "current_price": row.get("current_price", 0),
    }


def _build_report(
    as_of: str,
    summary: dict,
    picks: list[dict],
    blocked_counts: Counter,
    top_risks: Counter,
) -> str:
    lines = [
        "# Local Watchlist Replay",
        "",
        f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- As of: {as_of}",
        "- Source: active watchlists + local OHLCV close/volume only",
        "- DART/news/webhook/API calls are excluded in this replay",
        "",
        "## Summary",
        f"- Active watchlists: {summary['watchlists']}",
        f"- Watched stocks: {summary['watched_stocks']}",
        f"- Replayed candidates: {summary['replayed']}",
        f"- Blocked/skipped: {summary['blocked']}",
        f"- Local top picks kept: {summary['picked']}",
        f"- Conservative mode: {summary['conservative']}",
        "",
    ]

    if blocked_counts:
        lines.append("## Blocked Reasons")
        for reason, count in blocked_counts.most_common(10):
            lines.append(f"- {reason}: {count}")
        lines.append("")

    if top_risks:
        lines.append("## Top Risk Flags")
        for flag, count in top_risks.most_common(10):
            lines.append(f"- {flag}: {count}")
        lines.append("")

    lines.append("## Top Picks")
    if not picks:
        lines.append("- no picks")
    else:
        for pick in picks:
            flags = ", ".join(pick.get("risk_flags", [])) or "없음"
            lines.append(
                f"- #{pick.get('rank', '-')} {pick.get('name', '-')} ({pick.get('code', '-')}) | "
                f"{pick.get('conviction', '-')} {pick.get('conviction_score', 0):.1f} | "
                f"{pick.get('signal_type', '-') or '-'} | "
                f"레짐 {pick.get('market_regime', '-') or '-'} | "
                f"이벤트 {pick.get('event_warning', '-') or '-'} | "
                f"리스크 {flags}"
            )
    lines.append("")
    return "\n".join(lines)


def run_local_watchlist_replay(
    as_of: str,
    created: str = "",
    output_root: str | Path = ANALYSIS_DIR,
) -> tuple[Path, dict]:
    output_root = Path(output_root)
    if output_root.resolve() == ANALYSIS_DIR.resolve():
        output_dir = create_analysis_run_dir("local_replay")
    else:
        output_dir = output_root
        output_dir.mkdir(parents=True, exist_ok=True)

    watchlists = load_active_watchlists()
    if created:
        watchlists = [wl for wl in watchlists if str(wl.get("created")) == created]

    blocked_counts: Counter[str] = Counter()
    risk_counts: Counter[str] = Counter()
    replayed: list[dict] = []
    watched_stocks = 0

    for wl in watchlists:
        created = wl.get("created")
        days_elapsed = trading_days_since(created, asof=as_of)
        for stock in wl.get("stocks", []):
            watched_stocks += 1
            code = str(stock.get("code", "")).strip().zfill(6)
            sweet_spot = int(stock.get("sweet_spot_day", 2) or 2)
            quote, price_source_date = _latest_local_quote(code, as_of)
            if not quote:
                blocked_counts["missing_ohlcv"] += 1
                continue

            result = _score_stock(code, stock, quote, days_elapsed, sweet_spot, as_of)
            if not result:
                blocked_counts[_blocked_reason(stock, as_of, days_elapsed)] += 1
                continue

            result["watchlist_date"] = created
            result["rank"] = stock.get("rank")
            result["days_elapsed"] = days_elapsed
            result["original_score"] = stock.get("score")
            result["price_source_date"] = price_source_date
            replayed.append(result)
            for flag in result.get("risk_flags", []):
                if str(flag).strip():
                    risk_counts[str(flag).strip()] += 1

    replayed.sort(key=lambda row: row.get("conviction_score", 0), reverse=True)

    market_ctx = get_market_context()
    pick_limit = DAILY_PICK_TOP_K
    conservative = False
    if market_ctx and market_ctx.should_conservative(as_of):
        pick_limit = 1
        conservative = True
    picks = replayed[:pick_limit]

    summary = {
        "as_of": as_of,
        "watchlists": len(watchlists),
        "watched_stocks": watched_stocks,
        "replayed": len(replayed),
        "blocked": sum(blocked_counts.values()),
        "picked": len(picks),
        "conservative": conservative,
        "pick_limit": pick_limit,
    }
    payload = {
        "summary": summary,
        "blocked_counts": dict(blocked_counts),
        "risk_counts": dict(risk_counts),
        "top_picks": [_summarize_pick(row) for row in picks],
        "replayed_rows": [_summarize_pick(row) for row in replayed[:50]],
    }

    report = _build_report(as_of, summary, payload["top_picks"], blocked_counts, risk_counts)
    report_path = output_dir / "local_watchlist_replay.md"
    report_path.write_text(report, encoding="utf-8")
    (output_dir / "local_watchlist_replay.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report_path, payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay daily watchlist scoring with local OHLCV only")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="Replay date in YYYY-MM-DD")
    parser.add_argument("--created", default="", help="Optional watchlist created date filter")
    parser.add_argument("--output-root", default=str(ANALYSIS_DIR))
    args = parser.parse_args()

    report_path, _ = run_local_watchlist_replay(
        as_of=args.as_of,
        created=args.created,
        output_root=args.output_root,
    )
    report = report_path.read_text(encoding="utf-8")
    print(report)
    print(f"Report saved: {report_path}")


if __name__ == "__main__":
    main()
