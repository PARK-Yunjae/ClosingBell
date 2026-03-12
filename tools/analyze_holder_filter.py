"""
대주주 지분율 필터 효과 분석
============================
수집된 major_holder.csv + buy_signals + buy_performance_v2를
매칭해서 지분율 구간별 승률/수익률을 비교.

사용법:
    python tools/analyze_holder_filter.py              # 전체 분석
    python tools/analyze_holder_filter.py --cutoff 30  # 30% 컷오프 시뮬레이션
    python tools/analyze_holder_filter.py --detail      # 종목별 상세

출력: 콘솔 + data/meta/holder_analysis.csv
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import ANALYSIS_DIR, DATA_DIR, create_analysis_run_dir
from storage import load_backtest_dataset

HOLDER_CSV = DATA_DIR / "meta" / "major_holder.csv"
OUTPUT_CSV = ANALYSIS_DIR / "holder_analysis.csv"


def load_data():
    """3개 데이터셋 로드 + 매칭"""

    # 1. 대주주 지분율
    if not HOLDER_CSV.exists():
        print("❌ major_holder.csv 없음 — 먼저 collect_major_holder.py 실행")
        sys.exit(1)

    holder = pd.read_csv(HOLDER_CSV, dtype={"code": str})
    holder["code"] = holder["code"].str.zfill(6)

    # 종목당 가장 최근 연도 기준
    holder = holder.sort_values("year", ascending=False).drop_duplicates("code", keep="first")
    holder_map = holder.set_index("code")["total_pct"].to_dict()
    print(f"지분율 데이터: {len(holder_map)}종목")

    # 2. buy_signals
    signals = load_backtest_dataset("buy_signals") or []
    sig_df = pd.DataFrame(signals)
    sig_df["code"] = sig_df["code"].astype(str).str.zfill(6)
    print(f"buy_signals: {len(sig_df)}건")

    # 3. buy_performance_v2
    perf = load_backtest_dataset("buy_performance_v2")
    if not perf:
        perf = load_backtest_dataset("buy_performance")
    perf_df = pd.DataFrame(perf or [])
    if not perf_df.empty:
        perf_df["code"] = perf_df["code"].astype(str).str.zfill(6)
    print(f"performance: {len(perf_df)}건")

    # 4. 지분율 매칭
    sig_df["holder_pct"] = sig_df["code"].map(holder_map)
    perf_df["holder_pct"] = perf_df["code"].map(holder_map) if not perf_df.empty else None

    matched = sig_df["holder_pct"].notna().sum()
    print(f"매칭 성공: {matched}/{len(sig_df)} ({matched/len(sig_df)*100:.1f}%)")

    return sig_df, perf_df, holder_map


def bucket_analysis(sig_df: pd.DataFrame, perf_df: pd.DataFrame):
    """지분율 구간별 승률/수익률 분석"""

    # 매칭된 것만
    sig = sig_df[sig_df["holder_pct"].notna()].copy()
    perf = perf_df[perf_df["holder_pct"].notna()].copy() if not perf_df.empty else pd.DataFrame()

    if perf.empty:
        print("❌ 매칭된 performance 데이터 없음")
        return pd.DataFrame()

    # 구간 정의
    bins = [0, 10, 20, 30, 40, 50, 60, 70, 100]
    labels = ["0-10%", "10-20%", "20-30%", "30-40%", "40-50%", "50-60%", "60-70%", "70%+"]

    perf["bucket"] = pd.cut(perf["holder_pct"], bins=bins, labels=labels, right=False)

    print(f"\n{'='*80}")
    print(f"  구간별 D+1~D+5 성과 분석 (총 {len(perf)}건)")
    print(f"{'='*80}")

    for track_day in [1, 2, 3, 5]:
        day_perf = perf[perf["track_day"] == track_day]
        if day_perf.empty:
            continue

        print(f"\n── D+{track_day} ──")
        print(f"{'구간':<10} {'종목수':>6} {'승률':>8} {'평균수익':>10} {'고가평균':>10} {'손익비':>8}")
        print(f"{'-'*60}")

        for bucket in labels:
            sub = day_perf[day_perf["bucket"] == bucket]
            if len(sub) < 5:
                continue

            n = len(sub)
            wr = sub["win"].mean() * 100
            avg_ret = sub["return_pct"].mean()
            avg_high = sub["high_ret"].mean() if "high_ret" in sub.columns else 0

            # 손익비: 평균 이익 / 평균 손실
            wins = sub[sub["return_pct"] > 0]["return_pct"]
            losses = sub[sub["return_pct"] <= 0]["return_pct"]
            if len(losses) > 0 and losses.mean() != 0:
                profit_loss = abs(wins.mean() / losses.mean()) if len(wins) > 0 else 0
            else:
                profit_loss = float('inf') if len(wins) > 0 else 0

            pl_str = f"{profit_loss:.2f}" if profit_loss != float('inf') else "∞"
            print(f"{bucket:<10} {n:>6} {wr:>7.1f}% {avg_ret:>+9.2f}% {avg_high:>+9.2f}% {pl_str:>8}")

        # 전체 평균
        n = len(day_perf)
        wr = day_perf["win"].mean() * 100
        avg_ret = day_perf["return_pct"].mean()
        print(f"{'전체':<10} {n:>6} {wr:>7.1f}% {avg_ret:>+9.2f}%")

    return perf


def conviction_breakdown(sig_df: pd.DataFrame, perf_df: pd.DataFrame):
    """등급(A/B/C) × 지분율 구간 교차 분석"""

    perf = perf_df[perf_df["holder_pct"].notna()].copy() if not perf_df.empty else pd.DataFrame()
    if perf.empty:
        return

    bins = [0, 20, 30, 50, 100]
    labels = ["<20%", "20-30%", "30-50%", "50%+"]
    perf["holder_bucket"] = pd.cut(perf["holder_pct"], bins=bins, labels=labels, right=False)

    day1 = perf[perf["track_day"] == 1]
    if day1.empty:
        return

    print(f"\n{'='*80}")
    print(f"  등급 × 지분율 교차 분석 (D+1, {len(day1)}건)")
    print(f"{'='*80}")
    print(f"{'등급':<6} {'지분구간':<10} {'건수':>6} {'승률':>8} {'평균수익':>10}")
    print(f"{'-'*50}")

    for grade in ["A", "B", "C"]:
        for bucket in labels:
            sub = day1[(day1["conviction"] == grade) & (day1["holder_bucket"] == bucket)]
            if len(sub) < 3:
                continue
            wr = sub["win"].mean() * 100
            avg = sub["return_pct"].mean()
            print(f"{grade:<6} {bucket:<10} {len(sub):>6} {wr:>7.1f}% {avg:>+9.2f}%")
        print()


def cutoff_simulation(sig_df: pd.DataFrame, perf_df: pd.DataFrame, cutoff: float):
    """특정 컷오프로 제외했을 때 before/after 비교"""

    perf = perf_df[perf_df["holder_pct"].notna()].copy() if not perf_df.empty else pd.DataFrame()
    if perf.empty:
        return

    day1 = perf[perf["track_day"] == 1]
    above = day1[day1["holder_pct"] >= cutoff]
    below = day1[day1["holder_pct"] < cutoff]

    print(f"\n{'='*80}")
    print(f"  컷오프 시뮬레이션: 대주주 지분 {cutoff:.0f}% 미만 제외")
    print(f"{'='*80}")

    print(f"\n  {'':12} {'건수':>8} {'승률':>8} {'평균수익':>10} {'고가평균':>10}")
    print(f"  {'-'*52}")

    for label, df in [("현재 전체", day1), (f"≥{cutoff:.0f}% (유지)", above), (f"<{cutoff:.0f}% (제외)", below)]:
        if df.empty:
            continue
        wr = df["win"].mean() * 100
        avg = df["return_pct"].mean()
        hi = df["high_ret"].mean() if "high_ret" in df.columns else 0
        print(f"  {label:<12} {len(df):>8} {wr:>7.1f}% {avg:>+9.2f}% {hi:>+9.2f}%")

    # 제거되는 종목 비율
    removed_stocks = below["code"].nunique() if not below.empty else 0
    total_stocks = day1["code"].nunique()
    print(f"\n  제거 종목: {removed_stocks}/{total_stocks} ({removed_stocks/total_stocks*100:.1f}%)")
    print(f"  제거 신호: {len(below)}/{len(day1)} ({len(below)/len(day1)*100:.1f}%)")

    # 등급별 영향
    print(f"\n  등급별 제거 비율:")
    for grade in ["A", "B", "C"]:
        grade_total = len(day1[day1["conviction"] == grade])
        grade_removed = len(below[below["conviction"] == grade]) if not below.empty else 0
        if grade_total > 0:
            print(f"    {grade}등급: {grade_removed}/{grade_total} ({grade_removed/grade_total*100:.1f}%) 제거")


def multi_cutoff_scan(sig_df: pd.DataFrame, perf_df: pd.DataFrame):
    """여러 컷오프로 스캔해서 최적점 찾기"""

    perf = perf_df[perf_df["holder_pct"].notna()].copy() if not perf_df.empty else pd.DataFrame()
    if perf.empty:
        return

    day1 = perf[perf["track_day"] == 1]

    print(f"\n{'='*80}")
    print(f"  컷오프 스캔 (D+1 기준)")
    print(f"{'='*80}")
    print(f"  {'컷오프':>8} {'유지건수':>8} {'유지승률':>8} {'유지수익':>10} {'제거승률':>8} {'제거수익':>10} {'차이':>8}")
    print(f"  {'-'*70}")

    for cutoff in [10, 15, 20, 25, 30, 35, 40, 50]:
        above = day1[day1["holder_pct"] >= cutoff]
        below = day1[day1["holder_pct"] < cutoff]

        if len(above) < 10 or len(below) < 10:
            continue

        wr_above = above["win"].mean() * 100
        wr_below = below["win"].mean() * 100
        ret_above = above["return_pct"].mean()
        ret_below = below["return_pct"].mean()
        diff = ret_above - ret_below

        print(f"  {cutoff:>7.0f}% {len(above):>8} {wr_above:>7.1f}% {ret_above:>+9.2f}% "
              f"{wr_below:>7.1f}% {ret_below:>+9.2f}% {diff:>+7.2f}%")

    print(f"\n  ※ '차이'가 양수이면 해당 컷오프 이상을 유지하는 게 유리")
    print(f"  ※ '차이'가 0 부근이면 필터 효과 없음")


def save_analysis(perf_df: pd.DataFrame, output_csv: Path):
    """분석용 매칭 데이터 저장"""
    if perf_df.empty:
        return
    matched = perf_df[perf_df["holder_pct"].notna()].copy()
    if not matched.empty:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        cols = [c for c in ["code", "name", "signal_date", "rank", "conviction",
                            "track_day", "return_pct", "high_ret", "win",
                            "holder_pct", "bucket"] if c in matched.columns]
        matched[cols].to_csv(output_csv, index=False, encoding="utf-8-sig")
        print(f"\n분석 데이터 저장: {output_csv} ({len(matched)}건)")


def main():
    parser = argparse.ArgumentParser(description="대주주 지분율 필터 분석")
    parser.add_argument("--cutoff", type=float, default=30,
                        help="시뮬레이션 컷오프 (기본: 30)")
    parser.add_argument("--detail", action="store_true",
                        help="등급×지분율 교차 분석 포함")
    parser.add_argument("--output-root", default=str(ANALYSIS_DIR))
    args = parser.parse_args()

    if Path(args.output_root).resolve() == ANALYSIS_DIR.resolve():
        output_root = create_analysis_run_dir("holder")
    else:
        output_root = Path(args.output_root)
        output_root.mkdir(parents=True, exist_ok=True)
    output_csv = output_root / "holder_analysis.csv"

    sig_df, perf_df, holder_map = load_data()

    # 1. 구간별 분석
    perf_df = bucket_analysis(sig_df, perf_df)

    # 2. 컷오프 스캔
    multi_cutoff_scan(sig_df, perf_df)

    # 3. 특정 컷오프 시뮬
    cutoff_simulation(sig_df, perf_df, args.cutoff)

    # 4. 등급 교차 (--detail)
    if args.detail:
        conviction_breakdown(sig_df, perf_df)

    # 5. 저장
    save_analysis(perf_df, output_csv)


if __name__ == "__main__":
    main()
