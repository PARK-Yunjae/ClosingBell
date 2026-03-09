"""
ClosingBell v3.5 — 성과 추적기 (D+1 ~ D+5)
==========================================
매일 장마감 후 과거 추천 종목의 수익률을 추적.
순위별(TOP1/2/3), 기간별(D+1~D+5) 승률 집계.

사용법:
    python performance_tracker.py            # 오늘 추적 실행
    python performance_tracker.py --report   # 누적 성과 리포트
    python performance_tracker.py --rebuild  # 전체 재계산
"""
import json
import logging
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

from config import (
    LOG_DIR, PERFORMANCE_DIR, PERFORMANCE_TRACK_DAYS,
    KIWOOM_BASE_URL, KIWOOM_APPKEY, KIWOOM_SECRETKEY, API_DELAY,
    OHLCV_DIR,
)

logger = logging.getLogger("closingbell")

PERF_FILE = PERFORMANCE_DIR / "tracking.json"


def _load_tracking() -> dict:
    """추적 데이터 로드"""
    if PERF_FILE.exists():
        return json.loads(PERF_FILE.read_text(encoding="utf-8"))
    return {"records": [], "last_updated": None}


def _save_tracking(data: dict):
    """추적 데이터 저장"""
    data["last_updated"] = datetime.now().isoformat(timespec="seconds")
    PERF_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def track_today():
    """
    오늘까지의 수익률 추적
    과거 D일 ~ D-TRACK_DAYS 추천 종목의 현재가를 조회하여 수익률 기록
    """
    from kiwoom_api import KiwoomAPI

    today = datetime.now().strftime("%Y-%m-%d")
    tracking = _load_tracking()
    existing_keys = {
        f"{r['rec_date']}_{r['code']}_{r['track_day']}"
        for r in tracking["records"]
    }

    api = KiwoomAPI(KIWOOM_APPKEY, KIWOOM_SECRETKEY, KIWOOM_BASE_URL, API_DELAY)
    api.ensure_token()

    # 과거 로그에서 추천 종목 수집
    log_files = sorted(LOG_DIR.glob("*.json"))
    new_records = 0

    for lf in log_files:
        rec_date = lf.stem
        # 오늘 것은 아직 추적 불가 (D+1부터)
        if rec_date >= today:
            continue

        try:
            data = json.loads(lf.read_text(encoding="utf-8"))
            if data.get("skipped"):
                continue
        except Exception:
            continue

        top = data.get("top", [])
        if not top:
            continue

        # 추천일로부터 며칠 지났는지
        rec_dt = datetime.strptime(rec_date, "%Y-%m-%d")
        days_diff = _trading_days_between(rec_date, today)

        if days_diff < 1 or days_diff > PERFORMANCE_TRACK_DAYS:
            continue

        for stock in top:
            key = f"{rec_date}_{stock['code']}_{days_diff}"
            if key in existing_keys:
                continue

            try:
                # 현재가 조회 (장마감 후이므로 종가)
                cur = api.get_current_price(stock["code"])
                if cur["price"] <= 0:
                    continue

                buy_price = stock["price"]
                if buy_price <= 0:
                    continue

                ret = (cur["price"] / buy_price - 1) * 100

                record = {
                    "rec_date": rec_date,
                    "code": stock["code"],
                    "name": stock.get("name", ""),
                    "rank": stock.get("rank", 0),
                    "score": stock.get("score", 0),
                    "buy_price": buy_price,
                    "track_day": days_diff,  # D+1, D+2, ...
                    "track_date": today,
                    "track_price": cur["price"],
                    "return_pct": round(ret, 2),
                    "win": ret > 0,
                }
                tracking["records"].append(record)
                existing_keys.add(key)
                new_records += 1

            except Exception as e:
                logger.debug("성과 추적 실패 [%s %s]: %s", rec_date, stock["code"], e)

    _save_tracking(tracking)
    logger.info("성과 추적: %d건 신규 기록 (총 %d건)", new_records, len(tracking["records"]))
    return new_records


def track_from_ohlcv():
    """
    API 없이 OHLCV 파일에서 수익률 계산 (재계산/백필용)
    """
    today = datetime.now().strftime("%Y-%m-%d")
    tracking = {"records": [], "last_updated": None}

    log_files = sorted(LOG_DIR.glob("*.json"))

    for lf in log_files:
        rec_date = lf.stem
        try:
            data = json.loads(lf.read_text(encoding="utf-8"))
            if data.get("skipped"):
                continue
        except Exception:
            continue

        top = data.get("top", [])
        for stock in top:
            code = stock["code"].strip().zfill(6)
            csv_path = OHLCV_DIR / f"{code}.csv"
            if not csv_path.exists():
                continue

            try:
                df = pd.read_csv(csv_path)
                df.columns = [c.lower() for c in df.columns]
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date")

                # 추천일 이후 거래일 찾기
                mask = df["date"] > pd.Timestamp(rec_date)
                future_days = df[mask].head(PERFORMANCE_TRACK_DAYS)

                buy_price = stock["price"]
                if buy_price <= 0:
                    continue

                for i, (_, row) in enumerate(future_days.iterrows(), 1):
                    ret = (row["close"] / buy_price - 1) * 100
                    tracking["records"].append({
                        "rec_date": rec_date,
                        "code": code,
                        "name": stock.get("name", ""),
                        "rank": stock.get("rank", 0),
                        "score": stock.get("score", 0),
                        "buy_price": buy_price,
                        "track_day": i,
                        "track_date": row["date"].strftime("%Y-%m-%d"),
                        "track_price": int(row["close"]),
                        "return_pct": round(ret, 2),
                        "win": ret > 0,
                    })
            except Exception:
                continue

    _save_tracking(tracking)
    logger.info("OHLCV 기반 재계산 완료: %d건", len(tracking["records"]))


def generate_report() -> dict:
    """
    누적 성과 리포트 생성
    - 순위별 D+1~D+5 승률
    - 전체 평균 수익률
    - 최고/최저 수익 종목
    """
    tracking = _load_tracking()
    records = tracking.get("records", [])

    if not records:
        return {"error": "추적 데이터 없음"}

    df = pd.DataFrame(records)

    report = {
        "total_records": len(df),
        "unique_recommendations": df["rec_date"].nunique(),
        "period": f"{df['rec_date'].min()} ~ {df['rec_date'].max()}",
    }

    # 순위별 × 기간별 승률
    rank_day_stats = []
    for rank in sorted(df["rank"].unique()):
        for day in range(1, PERFORMANCE_TRACK_DAYS + 1):
            subset = df[(df["rank"] == rank) & (df["track_day"] == day)]
            if len(subset) == 0:
                continue
            wins = subset["win"].sum()
            total = len(subset)
            avg_ret = subset["return_pct"].mean()
            rank_day_stats.append({
                "rank": int(rank),
                "track_day": f"D+{day}",
                "trades": int(total),
                "wins": int(wins),
                "win_rate": round(wins / total * 100, 1),
                "avg_return": round(avg_ret, 2),
            })
    report["rank_day_matrix"] = rank_day_stats

    # 기간별 전체 승률
    day_stats = []
    for day in range(1, PERFORMANCE_TRACK_DAYS + 1):
        subset = df[df["track_day"] == day]
        if len(subset) == 0:
            continue
        wins = subset["win"].sum()
        total = len(subset)
        day_stats.append({
            "track_day": f"D+{day}",
            "trades": int(total),
            "win_rate": round(wins / total * 100, 1),
            "avg_return": round(subset["return_pct"].mean(), 2),
            "median_return": round(subset["return_pct"].median(), 2),
        })
    report["day_stats"] = day_stats

    # TOP/WORST
    if len(df) > 0:
        best = df.loc[df["return_pct"].idxmax()]
        worst = df.loc[df["return_pct"].idxmin()]
        report["best"] = {
            "name": best["name"], "rec_date": best["rec_date"],
            "track_day": f"D+{best['track_day']}",
            "return_pct": best["return_pct"],
        }
        report["worst"] = {
            "name": worst["name"], "rec_date": worst["rec_date"],
            "track_day": f"D+{worst['track_day']}",
            "return_pct": worst["return_pct"],
        }

    return report


def _trading_days_between(date1: str, date2: str) -> int:
    """두 날짜 사이의 거래일 수 (주말 제외, 공휴일 미반영)"""
    d1 = datetime.strptime(date1, "%Y-%m-%d")
    d2 = datetime.strptime(date2, "%Y-%m-%d")
    count = 0
    current = d1 + timedelta(days=1)
    while current <= d2:
        if current.weekday() < 5:  # 월~금
            count += 1
        current += timedelta(days=1)
    return count


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="ClosingBell — 성과 추적")
    parser.add_argument("--report", action="store_true", help="성과 리포트")
    parser.add_argument("--rebuild", action="store_true", help="OHLCV 기반 전체 재계산")
    args = parser.parse_args()

    if args.report:
        report = generate_report()
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.rebuild:
        track_from_ohlcv()
        report = generate_report()
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        track_today()