"""
ClosingBell v4.0 시뮬레이터
============================
100점 4계층 점수 체계 기반, 5순위 지원.
330일 실전 데이터 기반 가중치 최적화.

사용법:
    python tools/simulator.py                    # 기본 시뮬
    python tools/simulator.py --rank-sweep       # rank 보너스 조합 탐색
    python tools/simulator.py --full             # 전체 파라미터 스윕

데이터 소스:
    - screen_runs (SQLite) → 330일 × ~34종목 전체 스코어링
    - OHLCV CSVs → 종목별 실제 수익률 계산
    - tracking.json → 기존 실전 성적 비교 기준

출력:
    각 가중치 조합별 TOP3 승률, 평균수익, 최대손실
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import json
import gzip
import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from itertools import product as iter_product

from config import (
    APP_DB_PATH, OHLCV_DIR,
    RANK1_PULLBACK_BONUS, RANK2_PULLBACK_BONUS, RANK3_PULLBACK_BONUS,
    RANK4_PULLBACK_BONUS, RANK5_PULLBACK_BONUS,
    BUY_A_MIN_SCORE, BUY_B_MIN_SCORE,
)


def load_screen_runs(limit: int = 0) -> list[dict]:
    """SQLite에서 screen_runs 로드"""
    db = sqlite3.connect(str(APP_DB_PATH))
    cur = db.cursor()
    query = "SELECT run_date, payload FROM screen_runs ORDER BY run_date"
    if limit:
        query += f" LIMIT {limit}"
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
        all_scored = payload.get("all_scored", [])
        if not all_scored:
            continue
        runs.append({"date": run_date, "stocks": all_scored})

    db.close()
    print(f"screen_runs 로드: {len(runs)}일")
    return runs


def load_ohlcv_cache(codes: set[str]) -> dict[str, pd.DataFrame]:
    """필요한 종목만 OHLCV 로드"""
    cache = {}
    ohlcv_dir = Path(OHLCV_DIR)
    if not ohlcv_dir.exists():
        print(f"❌ OHLCV 경로 없음: {ohlcv_dir}")
        return cache

    loaded = 0
    for code in codes:
        csv_path = ohlcv_dir / f"{code.zfill(6)}.csv"
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path)
                df.columns = [c.lower().strip() for c in df.columns]
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").reset_index(drop=True)
                cache[code] = df
                loaded += 1
            except Exception:
                pass

    print(f"OHLCV 로드: {loaded}/{len(codes)}종목")
    return cache


def get_return(ohlcv_cache: dict, code: str, base_date: str, days: int) -> float | None:
    """base_date로부터 D+days 수익률 계산"""
    df = ohlcv_cache.get(code)
    if df is None or df.empty:
        return None

    base_dt = pd.Timestamp(base_date)
    future = df[df["date"] > base_dt].head(days)

    if future.empty:
        return None

    # base_date의 종가
    base_rows = df[df["date"] <= base_dt].tail(1)
    if base_rows.empty:
        return None

    buy_price = float(base_rows.iloc[-1]["close"])
    sell_price = float(future.iloc[-1]["close"])

    if buy_price <= 0:
        return None
    return (sell_price / buy_price - 1) * 100


def rescore_stocks(stocks: list[dict], rank_bonus: dict,
                   a_min: float = 68, b_min: float = 45) -> list[dict]:
    """
    기존 bell_score를 유지하면서, rank 보너스만 재적용.
    실제 _score_stock 전체를 재현하기엔 정보가 부족하므로,
    스크리닝 점수(bell_score) 기반으로 순위 보너스만 재조정.
    """
    rescored = []
    for s in stocks:
        new_score = float(s.get("score", 0))
        rank = s.get("rank", 99)

        # 기존 rank 보너스 제거 (원본 score에 포함되어 있지 않음 — bell_score는 순수 기술점수)
        # → screen_runs의 score는 bell_score (rank 보너스 미포함)
        # → 여기서 rank 보너스를 더해서 새 점수 생성
        bonus = rank_bonus.get(rank, 0)
        final_score = new_score + bonus

        grade = "A" if final_score >= a_min else ("B" if final_score >= b_min else "C")

        rescored.append({
            **s,
            "sim_score": final_score,
            "sim_grade": grade,
        })

    rescored.sort(key=lambda x: x["sim_score"], reverse=True)
    return rescored


def simulate_config(
    runs: list[dict],
    ohlcv_cache: dict,
    rank_bonus: dict,
    a_min: float = 68,
    b_min: float = 45,
    top_k: int = 5,
    track_days: list[int] | None = None,
    min_score: float = 0,       # 이 점수 이하면 관망 (0=필터 없음)
    exclude_c: bool = False,     # C등급 제외
    win_threshold: float = 2.0,  # 승리 기준 (%)
) -> dict:
    """하나의 가중치 설정으로 전체 기간 시뮬"""
    if track_days is None:
        track_days = [1, 2, 3, 5]

    results = {d: [] for d in track_days}
    skip_days = 0

    for run in runs:
        date = run["date"]
        stocks = run["stocks"]

        rescored = rescore_stocks(stocks, rank_bonus, a_min, b_min)

        # 등급 필터
        if exclude_c:
            rescored = [s for s in rescored if s["sim_grade"] != "C"]

        # 최소 점수 필터
        if min_score > 0:
            rescored = [s for s in rescored if s["sim_score"] >= min_score]

        top = rescored[:top_k]

        if not top:
            skip_days += 1
            continue

        for pick in top:
            code = pick.get("code", "")
            rank = pick.get("rank", 99)

            for td in track_days:
                ret = get_return(ohlcv_cache, code, date, td)
                if ret is not None:
                    results[td].append({
                        "date": date,
                        "code": code,
                        "rank": rank,
                        "score": pick["sim_score"],
                        "grade": pick["sim_grade"],
                        "return_pct": ret,
                        "win": ret >= win_threshold,
                    })

    # 집계
    summary = {"skip_days": skip_days, "total_days": len(runs)}
    for td in track_days:
        rows = results[td]
        if not rows:
            summary[f"D+{td}"] = {"count": 0}
            continue
        wins = sum(1 for r in rows if r["win"])
        avg_ret = sum(r["return_pct"] for r in rows) / len(rows)
        max_loss = min(r["return_pct"] for r in rows)
        max_gain = max(r["return_pct"] for r in rows)

        # 양수 비율 (0% 이상)
        positive = sum(1 for r in rows if r["return_pct"] > 0)

        # rank별
        rank_stats = {}
        for rk in [1, 2, 3]:
            rk_rows = [r for r in rows if r["rank"] == rk]
            if rk_rows:
                rk_wins = sum(1 for r in rk_rows if r["win"])
                rk_avg = sum(r["return_pct"] for r in rk_rows) / len(rk_rows)
                rank_stats[rk] = {
                    "count": len(rk_rows),
                    "win_rate": rk_wins / len(rk_rows) * 100,
                    "avg_return": rk_avg,
                }

        summary[f"D+{td}"] = {
            "count": len(rows),
            "win_rate": wins / len(rows) * 100,
            "positive_rate": positive / len(rows) * 100,
            "avg_return": avg_ret,
            "max_loss": max_loss,
            "max_gain": max_gain,
            "by_rank": rank_stats,
        }

    return summary


def print_summary(name: str, summary: dict, show_positive: bool = False):
    """결과 출력"""
    skip = summary.get("skip_days", 0)
    total = summary.get("total_days", 0)
    print(f"\n{'─'*60}")
    print(f"  {name}")
    if skip > 0:
        print(f"  (관망일: {skip}/{total}일)")
    print(f"{'─'*60}")
    for key in sorted(k for k in summary.keys() if k.startswith("D+")):
        s = summary[key]
        if s.get("count", 0) == 0:
            print(f"  {key}: 데이터 없음")
            continue
        line = (f"  {key}: {s['win_rate']:.1f}% 승률"
                f" | 평균 {s['avg_return']:+.2f}%"
                f" | 최대손실 {s['max_loss']:+.1f}% | {s['count']}건")
        if show_positive:
            line += f" | 양수 {s.get('positive_rate', 0):.1f}%"
        print(line)

        by_rank = s.get("by_rank", {})
        for rk in sorted(by_rank.keys()):
            rs = by_rank[rk]
            print(f"    #{rk}: {rs['win_rate']:.1f}% ({rs['count']}건) 평균 {rs['avg_return']:+.2f}%")


def rank_sweep(runs, ohlcv_cache):
    """rank 보너스 조합 탐색 (v4: 5순위)"""
    print("\n" + "=" * 60)
    print("  Rank 보너스 스윕 (v4: 5순위)")
    print("=" * 60)

    # 현재 설정
    current = {
        1: RANK1_PULLBACK_BONUS, 2: RANK2_PULLBACK_BONUS, 3: RANK3_PULLBACK_BONUS,
        4: RANK4_PULLBACK_BONUS, 5: RANK5_PULLBACK_BONUS,
    }
    print(f"\n현재 설정: #1={current[1]:+.0f}, #2={current[2]:+.0f}, #3={current[3]:+.0f}, "
          f"#4={current[4]:+.0f}, #5={current[5]:+.0f}")
    result = simulate_config(runs, ohlcv_cache, current)
    print_summary("현재 설정", result)

    # 탐색 범위 (rank 1~3만 스윕, 4/5는 고정 -5)
    r1_range = [5, 10, 15]
    r2_range = [-5, 0, 5, 10]
    r3_range = [-5, 0, 5, 10]

    best_config = None
    best_avg_d3 = -999

    configs_tested = 0
    total = len(r1_range) * len(r2_range) * len(r3_range)

    for r1, r2, r3 in iter_product(r1_range, r2_range, r3_range):
        bonus = {1: r1, 2: r2, 3: r3, 4: -5, 5: -5}
        result = simulate_config(runs, ohlcv_cache, bonus, track_days=[3])
        configs_tested += 1

        d3 = result.get("D+3", {})
        avg = d3.get("avg_return", -999)

        if avg > best_avg_d3:
            best_avg_d3 = avg
            best_config = (r1, r2, r3, result)

        if configs_tested % 12 == 0:
            print(f"  진행: {configs_tested}/{total}...", end="\r")

    print(f"  완료: {configs_tested}개 조합 테스트")

    if best_config:
        r1, r2, r3, result = best_config
        print(f"\n{'='*60}")
        print(f"  🏆 최적 rank 보너스: #1={r1:+.0f}, #2={r2:+.0f}, #3={r3:+.0f}, #4=-5, #5=-5")
        print(f"{'='*60}")
        best_result = simulate_config(runs, ohlcv_cache, {1: r1, 2: r2, 3: r3, 4: -5, 5: -5})
        print_summary("최적 설정", best_result)

    # 현재 vs 최적 비교
    print(f"\n{'='*60}")
    print(f"  현재 vs 최적 비교 (D+3 평균수익)")
    print(f"{'='*60}")
    current_d3 = simulate_config(runs, ohlcv_cache, current, track_days=[3]).get("D+3", {})
    print(f"  현재: {current_d3.get('avg_return', 0):+.2f}%")
    print(f"  최적: {best_avg_d3:+.2f}%")
    if best_config:
        print(f"  개선: {best_avg_d3 - current_d3.get('avg_return', 0):+.2f}%p")


def grade_sweep(runs, ohlcv_cache):
    """등급 기준값 + 필터링 전략 탐색"""
    print("\n" + "=" * 60)
    print("  등급 기준값 + 필터링 전략 스윕")
    print("=" * 60)

    rank_bonus = {
        1: RANK1_PULLBACK_BONUS, 2: RANK2_PULLBACK_BONUS, 3: RANK3_PULLBACK_BONUS,
        4: RANK4_PULLBACK_BONUS, 5: RANK5_PULLBACK_BONUS,
    }

    # 1) C등급 제외 효과
    print("\n  --- C등급 제외 효과 ---")
    for excl in [False, True]:
        label = "C등급 포함" if not excl else "C등급 제외"
        result = simulate_config(runs, ohlcv_cache, rank_bonus,
                                 exclude_c=excl, track_days=[3])
        d3 = result.get("D+3", {})
        skip = result.get("skip_days", 0)
        print(f"  {label}: D+3 승률 {d3.get('win_rate',0):.1f}% 평균 {d3.get('avg_return',0):+.2f}% "
              f"({d3.get('count',0)}건, 관망 {skip}일)")

    # 2) 최소 점수 필터 (몇 점 이하면 추천 안 하는 게 나은지)
    print("\n  --- 최소 점수 필터 (관망 임계값) ---")
    for min_s in [0, 50, 60, 70, 75, 80]:
        label = f"최소 {min_s}점" if min_s else "필터 없음"
        result = simulate_config(runs, ohlcv_cache, rank_bonus,
                                 min_score=min_s, track_days=[3])
        d3 = result.get("D+3", {})
        skip = result.get("skip_days", 0)
        print(f"  {label}: D+3 승률 {d3.get('win_rate',0):.1f}% 평균 {d3.get('avg_return',0):+.2f}% "
              f"({d3.get('count',0)}건, 관망 {skip}/{result.get('total_days',0)}일)")

    # 3) 승리 기준별 승률 비교
    print("\n  --- 승리 기준별 승률 ---")
    for thresh in [0.0, 1.0, 2.0, 3.0, 5.0]:
        label = f"≥{thresh}%"
        result = simulate_config(runs, ohlcv_cache, rank_bonus,
                                 win_threshold=thresh, track_days=[1, 3, 5])
        for td_key in ["D+1", "D+3", "D+5"]:
            d = result.get(td_key, {})
            if d.get("count", 0):
                print(f"  {label} {td_key}: {d['win_rate']:.1f}% ({d['count']}건)")


def main():
    parser = argparse.ArgumentParser(description="ClosingBell 시뮬레이터")
    parser.add_argument("--rank-sweep", action="store_true", help="rank 보너스 조합 탐색")
    parser.add_argument("--grade-sweep", action="store_true", help="등급 기준값 탐색")
    parser.add_argument("--full", action="store_true", help="전체 스윕 (rank + grade)")
    parser.add_argument("--limit", type=int, default=0, help="최근 N일만 (0=전체)")
    args = parser.parse_args()

    print("=" * 60)
    print("  ClosingBell v4.0 시뮬레이터")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # 데이터 로드
    runs = load_screen_runs(limit=args.limit)
    if not runs:
        print("❌ screen_runs 데이터 없음")
        return

    # 필요한 종목 코드 수집
    all_codes = set()
    for run in runs:
        for s in run["stocks"]:
            all_codes.add(s.get("code", "").zfill(6))

    ohlcv_cache = load_ohlcv_cache(all_codes)
    if not ohlcv_cache:
        print("❌ OHLCV 데이터 없음 — C:/Coding/data/ohlcv 확인")
        return

    # 현재 설정 기준 시뮬
    current_bonus = {
        1: RANK1_PULLBACK_BONUS, 2: RANK2_PULLBACK_BONUS, 3: RANK3_PULLBACK_BONUS,
        4: RANK4_PULLBACK_BONUS, 5: RANK5_PULLBACK_BONUS,
    }
    print(f"\n현재 rank 보너스: #1={current_bonus[1]:+.0f}, #2={current_bonus[2]:+.0f}, "
          f"#3={current_bonus[3]:+.0f}, #4={current_bonus[4]:+.0f}, #5={current_bonus[5]:+.0f}")
    print(f"등급 기준: A≥{BUY_A_MIN_SCORE}, B≥{BUY_B_MIN_SCORE} (100점 만점)")

    current_result = simulate_config(runs, ohlcv_cache, current_bonus)
    print_summary("현재 설정 시뮬레이션", current_result, show_positive=True)

    if args.rank_sweep or args.full:
        rank_sweep(runs, ohlcv_cache)

    if args.grade_sweep or args.full:
        grade_sweep(runs, ohlcv_cache)

    if not (args.rank_sweep or args.grade_sweep or args.full):
        print("\n💡 가중치 탐색을 하려면:")
        print("   python tools/simulator.py --rank-sweep")
        print("   python tools/simulator.py --grade-sweep")
        print("   python tools/simulator.py --full")


if __name__ == "__main__":
    main()
