"""
ClosingBell v3.5 → v3.6 업그레이드 시뮬레이션
==============================================
기존 buy_signals + buy_performance 데이터에 새 필터를 적용해서
"이 필터가 처음부터 있었다면 성과가 어떻게 달라졌을까"를 검증.

적용 필터:
  1. 대주주 지분 -10%p↓ 투매 종목 제외
  2. FOMC ±1일 감점 -3점
  3. 정치위기(계엄/탄핵) 보수모드 (TOP1만)
  4. 잡주(≤1만) + 지분<30% 감점 -2점
  5. 거래량감소 단독 신호 제외 (C등급 + 거래량감소만)
  6. 실적시즌마감 감점 -3점

사용법:
    python tools/simulate_v36.py
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from storage import load_backtest_dataset
from config import ANALYSIS_DIR, MAJOR_HOLDER_CSV, create_analysis_run_dir

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ══════════════════════════════════════════════════════════════
# 1. 데이터 로드
# ══════════════════════════════════════════════════════════════
def load_all():
    signals = pd.DataFrame(load_backtest_dataset("buy_signals") or [])
    signals["code"] = signals["code"].astype(str).str.zfill(6)

    perf = pd.DataFrame(load_backtest_dataset("buy_performance_v2") or [])
    if perf.empty:
        perf = pd.DataFrame(load_backtest_dataset("buy_performance") or [])
    perf["code"] = perf["code"].astype(str).str.zfill(6)
    perf["signal_date"] = pd.to_datetime(perf["signal_date"], errors="coerce")

    # 대주주 지분
    holder_path = MAJOR_HOLDER_CSV
    holder = pd.DataFrame()
    holder_change = {}
    holder_level = {}
    if holder_path.exists():
        h = pd.read_csv(holder_path, dtype={"code": str}, encoding="utf-8-sig")
        h["code"] = h["code"].str.zfill(6)
        h["total_pct"] = h["total_pct"].clip(upper=100)

        # 최신 지분율
        latest = h.sort_values("year", ascending=False).drop_duplicates("code", keep="first")
        holder_level = latest.set_index("code")["total_pct"].to_dict()

        # 변동율
        h23 = h[h["year"] == 2023].set_index("code")["total_pct"]
        h24 = h[h["year"] == 2024].set_index("code")["total_pct"]
        both = pd.DataFrame({"y23": h23, "y24": h24}).dropna()
        both["chg"] = both["y24"] - both["y23"]
        holder_change = both["chg"].to_dict()

    return signals, perf, holder_level, holder_change


# ══════════════════════════════════════════════════════════════
# 2. 캘린더 이벤트 맵
# ══════════════════════════════════════════════════════════════
EVENTS = [
    # FOMC
    *[{"date": d, "type": "fomc"} for d in [
        "2024-11-07","2024-12-18","2025-01-29","2025-03-19","2025-05-07",
        "2025-06-18","2025-07-30","2025-09-17","2025-10-29","2025-12-10",
        "2026-01-28","2026-03-18"]],
    # 정치위기
    *[{"date": d, "type": "political_critical"} for d in [
        "2024-12-03","2024-12-04","2024-12-14","2025-01-15","2025-04-04"]],
    # 실적시즌마감
    *[{"date": d, "type": "earnings_deadline"} for d in [
        "2025-05-15"]],
    # 옵션만기일 (가산점은 안 주고, 참고용)
    *[{"date": d, "type": "options_expiry"} for d in [
        "2024-11-14","2025-01-09","2025-02-13","2025-04-10","2025-05-08",
        "2025-07-10","2025-08-14","2025-10-02","2025-11-13",
        "2026-01-08","2026-02-12"]],
]

def build_event_tags():
    """날짜 → set of event types (±1일)"""
    m = {}
    for ev in EVENTS:
        center = datetime.strptime(ev["date"], "%Y-%m-%d").date()
        for delta in range(-1, 2):
            d = (center + timedelta(days=delta)).strftime("%Y-%m-%d")
            if d not in m:
                m[d] = set()
            m[d].add(ev["type"])
    return m


# ══════════════════════════════════════════════════════════════
# 3. v3.6 필터 적용
# ══════════════════════════════════════════════════════════════
def apply_v36_filters(signals, holder_level, holder_change, event_map):
    """
    signals DataFrame에 v3.6 필터를 적용.
    반환: (kept_signals, removed_signals, adjustments_log)
    """
    df = signals.copy()
    df["v36_action"] = "keep"
    df["v36_score_adj"] = 0.0
    df["v36_reason"] = ""

    reasons = []

    for idx, row in df.iterrows():
        code = row["code"]
        check_date = str(row.get("check_date", ""))[:10]
        price = row.get("current_price", row.get("entry_price", 0)) or 0
        conviction = row.get("conviction", "C")
        signal_type = str(row.get("signal_type", ""))
        score = row.get("conviction_score", 0) or 0
        adj = 0.0
        reason_parts = []

        # ── 필터 1: 투매 종목 제외 (-10%p↓) ──
        chg = holder_change.get(code)
        if chg is not None and chg <= -10:
            df.at[idx, "v36_action"] = "exclude"
            df.at[idx, "v36_reason"] = f"투매제외(지분변동{chg:+.1f}%p)"
            continue

        # ── 필터 2: 정치위기 → TOP1만 (rank>1 제외) ──
        events = event_map.get(check_date, set())
        if "political_critical" in events:
            if row.get("rank", 99) > 1:
                df.at[idx, "v36_action"] = "exclude"
                df.at[idx, "v36_reason"] = "정치위기_보수모드(TOP1만)"
                continue
            else:
                reason_parts.append("정치위기(TOP1유지)")

        # ── 필터 3: FOMC ±1일 감점 ──
        if "fomc" in events:
            adj -= 3.0
            reason_parts.append("FOMC감점-3")

        # ── 필터 4: 실적시즌마감 감점 ──
        if "earnings_deadline" in events:
            adj -= 3.0
            reason_parts.append("실적시즌감점-3")

        # ── 필터 5: 잡주(≤1만) + 지분<30% 감점 ──
        hlevel = holder_level.get(code)
        if hlevel is not None and hlevel < 30 and price <= 10000:
            adj -= 2.0
            reason_parts.append(f"잡주저지분감점-2(지분{hlevel:.0f}%)")

        # ── 필터 6: 거래량감소 단독 → C등급이면 제외 ──
        if signal_type == "거래량감소" and conviction == "C":
            df.at[idx, "v36_action"] = "exclude"
            df.at[idx, "v36_reason"] = "거래량감소단독_C등급"
            continue

        # 감점 반영 → 등급 재판정
        new_score = max(0, score + adj)
        df.at[idx, "v36_score_adj"] = adj
        if adj != 0:
            # 등급 재판정
            if new_score >= 60:
                new_conv = "A"
            elif new_score >= 40:
                new_conv = "B"
            else:
                new_conv = "C"
            df.at[idx, "v36_new_conviction"] = new_conv
        else:
            df.at[idx, "v36_new_conviction"] = conviction

        df.at[idx, "v36_reason"] = ", ".join(reason_parts) if reason_parts else "변경없음"

    kept = df[df["v36_action"] == "keep"]
    removed = df[df["v36_action"] == "exclude"]

    return kept, removed, df


# ══════════════════════════════════════════════════════════════
# 4. 성과 비교
# ══════════════════════════════════════════════════════════════
def compare_performance(perf, kept_signals, removed_signals, all_signals):
    """v3.5(전체) vs v3.6(필터 후) 성과 비교"""

    # 기존 전체
    old_codes_dates = set(
        all_signals["code"] + "_" + all_signals["check_date"].astype(str)
    )
    # 새 필터 후
    new_codes_dates = set(
        kept_signals["code"] + "_" + kept_signals["check_date"].astype(str)
    )
    # 제거된 것
    removed_codes_dates = set(
        removed_signals["code"] + "_" + removed_signals["check_date"].astype(str)
    )

    perf["key"] = perf["code"] + "_" + perf["signal_date"].dt.strftime("%Y-%m-%d")

    old_perf = perf[perf["key"].isin(old_codes_dates)]
    new_perf = perf[perf["key"].isin(new_codes_dates)]
    removed_perf = perf[perf["key"].isin(removed_codes_dates)]

    print(f"\n{'▓'*80}")
    print(f"  ClosingBell v3.5 → v3.6 시뮬레이션 결과")
    print(f"{'▓'*80}")

    # 필터 요약
    print(f"\n  신호 변화:")
    print(f"    v3.5 (기존): {len(all_signals)}건")
    print(f"    v3.6 (신규): {len(kept_signals)}건 ({len(removed_signals)}건 제거, "
          f"{len(removed_signals)/len(all_signals)*100:.1f}% 감소)")

    # 제거 사유 분포
    reasons = removed_signals["v36_reason"].value_counts()
    print(f"\n  제거 사유:")
    for reason, count in reasons.items():
        print(f"    {reason}: {count}건")

    # 등급별 영향
    print(f"\n  등급별 제거:")
    for grade in ["A", "B", "C"]:
        total = len(all_signals[all_signals["conviction"] == grade])
        removed = len(removed_signals[removed_signals["conviction"] == grade])
        if total > 0:
            print(f"    {grade}: {removed}/{total} ({removed/total*100:.1f}%) 제거")

    # D+1~D+5 성과 비교
    print(f"\n{'━'*80}")
    print(f"  D+1~D+5 성과 비교")
    print(f"{'━'*80}")

    header = f"  {'':>6}"
    for label in ["v3.5(기존)", "v3.6(신규)", "제거된것", "개선폭"]:
        header += f" │ {label:>14}"
    print(header)
    print(f"  {'─'*72}")

    improvements = {}

    for td in [1, 2, 3, 4, 5]:
        old_d = old_perf[old_perf["track_day"] == td]
        new_d = new_perf[new_perf["track_day"] == td]
        rem_d = removed_perf[removed_perf["track_day"] == td]

        if old_d.empty or new_d.empty:
            continue

        o_wr = old_d["win"].astype(int).mean() * 100
        n_wr = new_d["win"].astype(int).mean() * 100
        r_wr = rem_d["win"].astype(int).mean() * 100 if not rem_d.empty else 0

        o_avg = old_d["return_pct"].mean()
        n_avg = new_d["return_pct"].mean()
        r_avg = rem_d["return_pct"].mean() if not rem_d.empty else 0

        wr_diff = n_wr - o_wr
        avg_diff = n_avg - o_avg

        improvements[td] = {"wr_diff": wr_diff, "avg_diff": avg_diff}

        print(f"  D+{td} 승률 │ {o_wr:>13.1f}% │ {n_wr:>13.1f}% │ {r_wr:>13.1f}% │ {wr_diff:>+13.1f}%p")
        print(f"  D+{td} 수익 │ {o_avg:>+13.2f}% │ {n_avg:>+13.2f}% │ {r_avg:>+13.2f}% │ {avg_diff:>+13.2f}%p")

    # A등급만 비교
    print(f"\n{'━'*80}")
    print(f"  A등급만 비교")
    print(f"{'━'*80}")

    old_a = all_signals[all_signals["conviction"] == "A"]
    new_a = kept_signals[kept_signals["conviction"] == "A"]

    old_a_keys = set(old_a["code"] + "_" + old_a["check_date"].astype(str))
    new_a_keys = set(new_a["code"] + "_" + new_a["check_date"].astype(str))

    for td in [1, 3, 5]:
        old_ap = perf[(perf["key"].isin(old_a_keys)) & (perf["track_day"] == td)]
        new_ap = perf[(perf["key"].isin(new_a_keys)) & (perf["track_day"] == td)]

        if old_ap.empty or new_ap.empty:
            continue

        o_wr = old_ap["win"].astype(int).mean() * 100
        n_wr = new_ap["win"].astype(int).mean() * 100
        o_avg = old_ap["return_pct"].mean()
        n_avg = new_ap["return_pct"].mean()

        print(f"  A D+{td}: v3.5 {o_wr:.1f}% {o_avg:+.2f}% → v3.6 {n_wr:.1f}% {n_avg:+.2f}% "
              f"(승률 {n_wr-o_wr:+.1f}%p, 수익 {n_avg-o_avg:+.2f}%p)")

    # 고가 기준 비교
    print(f"\n{'━'*80}")
    print(f"  고가(장중최고) 기준 비교")
    print(f"{'━'*80}")

    for td in [1, 3, 5]:
        old_d = old_perf[old_perf["track_day"] == td]
        new_d = new_perf[new_perf["track_day"] == td]

        if "high_ret" not in old_d.columns:
            continue

        o_hit2 = (old_d["high_ret"] >= 2.0).mean() * 100
        n_hit2 = (new_d["high_ret"] >= 2.0).mean() * 100
        o_hit3 = (old_d["high_ret"] >= 3.0).mean() * 100
        n_hit3 = (new_d["high_ret"] >= 3.0).mean() * 100

        print(f"  D+{td} +2%도달: v3.5 {o_hit2:.1f}% → v3.6 {n_hit2:.1f}% ({n_hit2-o_hit2:+.1f}%p)")
        print(f"  D+{td} +3%도달: v3.5 {o_hit3:.1f}% → v3.6 {n_hit3:.1f}% ({n_hit3-o_hit3:+.1f}%p)")

    # 요약
    print(f"\n{'▓'*80}")
    print(f"  종합 평가")
    print(f"{'▓'*80}")

    d3_imp = improvements.get(3, {})
    d5_imp = improvements.get(5, {})

    print(f"\n  D+3 승률 개선: {d3_imp.get('wr_diff', 0):+.1f}%p")
    print(f"  D+3 수익 개선: {d3_imp.get('avg_diff', 0):+.2f}%p")
    print(f"  D+5 승률 개선: {d5_imp.get('wr_diff', 0):+.1f}%p")
    print(f"  D+5 수익 개선: {d5_imp.get('avg_diff', 0):+.2f}%p")
    print(f"  신호 감소: {len(removed_signals)}/{len(all_signals)} ({len(removed_signals)/len(all_signals)*100:.1f}%)")

    verdict = "✅ 업그레이드 추천" if d3_imp.get("avg_diff", 0) > 0 else "⚠️ 추가 검토 필요"
    print(f"\n  판정: {verdict}")

    return improvements


def write_summary_report(
    output_dir: Path,
    all_tagged: pd.DataFrame,
    kept: pd.DataFrame,
    removed: pd.DataFrame,
    improvements: dict,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    reason_counts = Counter()
    if not removed.empty and "v36_reason" in removed.columns:
        reason_counts.update(
            reason.strip()
            for reason in removed["v36_reason"].astype(str)
            if reason and reason.strip()
        )

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "signals": {
            "total": int(len(all_tagged)),
            "kept": int(len(kept)),
            "removed": int(len(removed)),
            "removed_ratio": round(float(len(removed) / len(all_tagged) * 100), 2) if len(all_tagged) else 0.0,
        },
        "improvements": {
            f"d{day}": {
                "win_rate_diff": round(float(values.get("wr_diff", 0.0)), 4),
                "avg_return_diff": round(float(values.get("avg_diff", 0.0)), 4),
            }
            for day, values in improvements.items()
        },
        "top_removed_reasons": reason_counts.most_common(10),
    }
    (output_dir / "v36_simulation_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# v3.6 Simulation Summary",
        "",
        f"- Generated: {payload['generated_at']}",
        f"- Signals: total {payload['signals']['total']} | kept {payload['signals']['kept']} | removed {payload['signals']['removed']} ({payload['signals']['removed_ratio']:.2f}%)",
    ]
    for day in (1, 3, 5):
        diff = payload["improvements"].get(f"d{day}")
        if not diff:
            continue
        lines.append(
            f"- D+{day}: win-rate {diff['win_rate_diff']:+.2f}%p | avg-return {diff['avg_return_diff']:+.4f}%p"
        )
    if payload["top_removed_reasons"]:
        lines.append("")
        lines.append("## Top Removed Reasons")
        for reason, count in payload["top_removed_reasons"]:
            lines.append(f"- {reason}: {count}")

    (output_dir / "v36_simulation_report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description="Run v3.6 filter simulation")
    parser.add_argument("--output-root", default=str(ANALYSIS_DIR))
    parser.add_argument(
        "--save-dataset",
        action="store_true",
        help="Keep the tagged simulation CSV alongside the summary report",
    )
    args = parser.parse_args()
    print("데이터 로드 중...")
    signals, perf, holder_level, holder_change = load_all()
    event_map = build_event_tags()

    print(f"  signals: {len(signals)}건")
    print(f"  performance: {len(perf)}건")
    print(f"  holder_level: {len(holder_level)}종목")
    print(f"  holder_change: {len(holder_change)}종목")
    print(f"  events: {len(EVENTS)}개")

    print("\nv3.6 필터 적용 중...")
    kept, removed, all_tagged = apply_v36_filters(
        signals, holder_level, holder_change, event_map
    )

    improvements = compare_performance(perf, kept, removed, signals)

    if Path(args.output_root).resolve() == ANALYSIS_DIR.resolve():
        output_dir = create_analysis_run_dir("v36")
    else:
        output_dir = Path(args.output_root) / datetime.now().strftime("%Y%m%d_%H%M%S_v36")
        output_dir.mkdir(parents=True, exist_ok=True)

    write_summary_report(output_dir, all_tagged, kept, removed, improvements)
    if not args.save_dataset:
        print(f"\n?붿빟 ??? {output_dir}")
        return

    # 태그된 전체 저장 (검증용)
    if args.save_dataset:
        out_path = output_dir / "v36_simulation.csv"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cols = ["code", "name", "check_date", "rank", "conviction", "conviction_score",
            "signal_type", "v36_action", "v36_score_adj", "v36_new_conviction", "v36_reason"]
        existing_cols = [c for c in cols if c in all_tagged.columns]
        all_tagged[existing_cols].to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n시뮬 결과 저장: {out_path}")
    print(f"\n?붿빟 ??? {output_dir}")


if __name__ == "__main__":
    main()
