"""
ClosingBell v3 — 자동 튜닝
============================
축적된 로그 + OHLCV 데이터로 각 지표의 최적 구간을 분석하고
.env 파라미터 변경을 제안.

사용법:
    python auto_tuner.py               # 분석 + 제안 출력
    python auto_tuner.py --apply       # 분석 + .env 자동 수정
    python auto_tuner.py --min-days 10 # 최소 10일 데이터 필요 (기본 5)

원리:
    1) 로그에서 추천 종목 + 지표값 수집
    2) OHLCV에서 익일 시가 수익률 계산
    3) 지표별 구간 × 승률 매트릭스 생성
    4) 승률이 가장 높은 구간 → 최적값 제안
    5) 현재 .env 값과 비교해서 변경분만 출력
"""
import argparse
import json
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tuner")

# 설정
PROJECT_DIR = Path(__file__).parent
LOG_DIR = PROJECT_DIR / "data" / "logs"
OHLCV_DIR = Path("C:/Coding/data/ohlcv")
ENV_FILE = PROJECT_DIR / ".env"

# 분석할 지표 정의
INDICATORS = {
    "cci": {
        "env_optimal_low": "CCI_OPTIMAL_LOW",
        "env_optimal_high": "CCI_OPTIMAL_HIGH",
        "bins": [0, 80, 120, 140, 160, 180, 200, 220, 250, 300, 500],
        "default_optimal": (160, 180),
    },
    "rsi": {
        "env_optimal_low": "RSI_OPTIMAL_LOW",
        "env_optimal_high": "RSI_OPTIMAL_HIGH",
        "bins": [0, 25, 35, 45, 50, 55, 60, 65, 70, 75, 85, 100],
        "default_optimal": (50, 70),
    },
    "ma20_gap": {
        "env_optimal_low": "MA20_GAP_OPTIMAL_LOW",
        "env_optimal_high": "MA20_GAP_OPTIMAL_HIGH",
        "bins": [-20, -5, 0, 2, 4, 6, 8, 10, 15, 20, 40],
        "default_optimal": (2, 8),
    },
    "change_rate": {
        "env_optimal_low": "CHANGE_OPTIMAL_LOW",
        "env_optimal_high": "CHANGE_OPTIMAL_HIGH",
        "bins": [0, 1, 2, 3, 4, 5, 6, 8, 10, 15, 20, 30],
        "default_optimal": (2, 8),
    },
}


def load_recommendations() -> list[dict]:
    """로그에서 추천 종목 + 지표값 수집"""
    records = []
    log_files = sorted(LOG_DIR.glob("*.json"))
    logger.info("로그 파일: %d개", len(log_files))

    for lf in log_files:
        try:
            data = json.loads(lf.read_text(encoding="utf-8"))
            if data.get("skipped"):
                continue
            rec_date = data["date"]

            for stock in data.get("all_scored", []):
                records.append({
                    "date": rec_date,
                    "code": stock.get("code", "").replace("_AL", "").replace("_NX", "").zfill(6),
                    "name": stock.get("name", ""),
                    "rank": stock.get("rank", 99),
                    "score": stock.get("score", 0),
                    "cci": stock.get("cci", 0),
                    "rsi": stock.get("rsi", 0),
                    "ma20_gap": stock.get("ma20_gap", 0),
                    "change_rate": stock.get("change_rate", 0),
                    "vp_above_pct": stock.get("vp_above_pct", 50),
                    "broker_score": stock.get("broker_score", 0),
                    "ai_action": stock.get("ai_action", ""),
                    "price": stock.get("price", 0),
                })
        except Exception:
            pass

    logger.info("추천 레코드: %d건 (%d거래일)", len(records),
                len(set(r["date"] for r in records)))
    return records


def calc_next_day_returns(records: list[dict]) -> pd.DataFrame:
    """각 추천 종목의 익일 시가 수익률 계산"""
    df = pd.DataFrame(records)
    df["return_d1"] = np.nan

    # 종목별로 OHLCV에서 익일 시가 조회
    ohlcv_cache = {}
    for _, row in df.iterrows():
        code = row["code"]
        rec_date = row["date"]

        if code not in ohlcv_cache:
            path = OHLCV_DIR / f"{code}.csv"
            if path.exists():
                try:
                    odf = pd.read_csv(path)
                    odf.columns = [c.lower() for c in odf.columns]
                    odf["date"] = pd.to_datetime(odf["date"]).dt.strftime("%Y-%m-%d")
                    ohlcv_cache[code] = odf.set_index("date")
                except Exception:
                    ohlcv_cache[code] = None
            else:
                ohlcv_cache[code] = None

        odf = ohlcv_cache.get(code)
        if odf is None:
            continue

        # 추천일 다음 거래일의 시가 찾기
        try:
            dates_after = [d for d in odf.index if d > rec_date]
            if dates_after:
                next_date = min(dates_after)
                next_open = odf.loc[next_date, "open"]
                buy_price = row["price"]
                if buy_price > 0 and next_open > 0:
                    ret = (next_open / buy_price - 1) * 100
                    df.at[_, "return_d1"] = ret
        except Exception:
            pass

    valid = df.dropna(subset=["return_d1"])
    logger.info("익일 수익률 매칭: %d/%d건 (%.0f%%)",
                len(valid), len(df), len(valid) / len(df) * 100 if len(df) > 0 else 0)
    return valid


def analyze_indicator(df: pd.DataFrame, indicator: str, config: dict) -> dict:
    """지표별 구간 승률 분석"""
    bins = config["bins"]
    labels = [f"{bins[i]}~{bins[i+1]}" for i in range(len(bins) - 1)]

    df["bin"] = pd.cut(df[indicator], bins=bins, labels=labels, include_lowest=True)
    grouped = df.groupby("bin", observed=True).agg(
        count=("return_d1", "count"),
        win_rate=("return_d1", lambda x: (x > 0).mean() * 100),
        avg_return=("return_d1", "mean"),
    ).reset_index()

    # 최소 5건 이상인 구간만
    significant = grouped[grouped["count"] >= 5]

    if len(significant) == 0:
        return {"best_range": config["default_optimal"], "data": grouped}

    # 승률 기준 최적 구간 찾기
    best = significant.loc[significant["win_rate"].idxmax()]
    best_label = best["bin"]

    # 라벨에서 숫자 추출
    parts = best_label.split("~")
    best_low = float(parts[0])
    best_high = float(parts[1])

    # 인접 구간도 승률 좋으면 확장
    best_idx = list(grouped["bin"]).index(best_label) if best_label in list(grouped["bin"]) else -1
    if best_idx > 0:
        prev = grouped.iloc[best_idx - 1]
        if prev["count"] >= 5 and prev["win_rate"] >= best["win_rate"] * 0.9:
            prev_parts = prev["bin"].split("~")
            best_low = float(prev_parts[0])
    if best_idx < len(grouped) - 1:
        nxt = grouped.iloc[best_idx + 1]
        if nxt["count"] >= 5 and nxt["win_rate"] >= best["win_rate"] * 0.9:
            nxt_parts = nxt["bin"].split("~")
            best_high = float(nxt_parts[1])

    return {
        "best_range": (best_low, best_high),
        "best_win_rate": round(best["win_rate"], 1),
        "best_avg_return": round(best["avg_return"], 2),
        "best_count": int(best["count"]),
        "data": grouped,
    }


def run_analysis(min_days: int = 5):
    """전체 분석 실행"""
    records = load_recommendations()
    if not records:
        logger.error("로그 데이터 없음")
        return {}

    trading_days = len(set(r["date"] for r in records))
    if trading_days < min_days:
        logger.warning("데이터 부족: %d일 (최소 %d일 필요)", trading_days, min_days)
        return {}

    df = calc_next_day_returns(records)
    if len(df) == 0:
        logger.error("익일 수익률 매칭 실패")
        return {}

    # 전체 승률
    total_win = (df["return_d1"] > 0).mean() * 100
    total_avg = df["return_d1"].mean()
    logger.info("전체 승률: %.1f%%, 평균 수익률: %+.2f%%", total_win, total_avg)

    # TOP3만 따로
    top3 = df[df["rank"] <= 3]
    if len(top3) > 0:
        top3_win = (top3["return_d1"] > 0).mean() * 100
        top3_avg = top3["return_d1"].mean()
        logger.info("TOP3 승률: %.1f%%, 평균 수익률: %+.2f%%", top3_win, top3_avg)

    # 지표별 분석
    results = {}
    for indicator, config in INDICATORS.items():
        logger.info("분석 중: %s", indicator)
        result = analyze_indicator(df.copy(), indicator, config)
        results[indicator] = result

    return results


def print_report(results: dict):
    """분석 결과 리포트 출력"""
    print("\n" + "=" * 70)
    print("📊 ClosingBell v3 — 자동 튜닝 리포트")
    print("=" * 70)

    suggestions = {}

    for indicator, result in results.items():
        config = INDICATORS[indicator]
        current = config["default_optimal"]
        suggested = result.get("best_range", current)

        print(f"\n── {indicator} ──")
        print(f"  현재 최적 구간: {current[0]} ~ {current[1]}")

        if "data" in result:
            print(f"  {'구간':>12s} {'건수':>6s} {'승률':>6s} {'평균수익':>8s}")
            for _, row in result["data"].iterrows():
                marker = " ◀" if row["bin"] == f"{suggested[0]}~{suggested[1]}" else ""
                print(f"  {row['bin']:>12s} {row['count']:>6.0f} {row['win_rate']:>5.1f}% {row['avg_return']:>+7.2f}%{marker}")

        if suggested != current:
            print(f"  ✨ 제안: {suggested[0]} ~ {suggested[1]} "
                  f"(승률 {result.get('best_win_rate', 0):.1f}%, "
                  f"평균 {result.get('best_avg_return', 0):+.2f}%)")
            suggestions[config["env_optimal_low"]] = suggested[0]
            suggestions[config["env_optimal_high"]] = suggested[1]
        else:
            print(f"  ✅ 현재 설정 유지")

    # .env 변경 제안
    if suggestions:
        print("\n" + "=" * 70)
        print("📝 .env 변경 제안:")
        print("=" * 70)
        for key, value in suggestions.items():
            print(f"  {key}={value}")
    else:
        print("\n✅ 현재 설정이 최적입니다. 변경 불필요.")

    return suggestions


def apply_to_env(suggestions: dict):
    """제안된 값을 .env에 적용"""
    if not suggestions:
        print("변경할 내용 없음")
        return

    if not ENV_FILE.exists():
        print(f".env 파일 없음: {ENV_FILE}")
        return

    content = ENV_FILE.read_text(encoding="utf-8")
    changes = 0

    for key, value in suggestions.items():
        # 기존 값 찾기
        import re
        pattern = rf"^{re.escape(key)}=.*$"
        if re.search(pattern, content, re.MULTILINE):
            content = re.sub(pattern, f"{key}={value}", content, flags=re.MULTILINE)
            changes += 1
        else:
            # 없으면 추가
            content += f"\n{key}={value}"
            changes += 1

    ENV_FILE.write_text(content, encoding="utf-8")
    print(f"\n✅ .env 수정 완료: {changes}개 항목")
    print("   다음 스크리닝부터 반영됩니다.")


def main():
    parser = argparse.ArgumentParser(description="ClosingBell v3 자동 튜닝")
    parser.add_argument("--apply", action="store_true", help=".env에 자동 적용")
    parser.add_argument("--min-days", type=int, default=5, help="최소 거래일 수")
    args = parser.parse_args()

    results = run_analysis(min_days=args.min_days)
    if not results:
        return

    suggestions = print_report(results)

    if args.apply and suggestions:
        confirm = input("\n위 변경사항을 .env에 적용할까요? (y/n): ")
        if confirm.lower() == "y":
            apply_to_env(suggestions)
        else:
            print("취소됨")


if __name__ == "__main__":
    main()
