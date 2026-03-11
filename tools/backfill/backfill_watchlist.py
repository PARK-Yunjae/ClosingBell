"""
기존 스크리닝 로그 → 워치리스트 백필
=====================================
data/logs/*.json에서 D+5 이내 로그를 워치리스트로 변환.
1회만 실행하면 됨.

사용법:
    python backfill_watchlist.py
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import LOG_DIR, WATCHLIST_DIR, WATCHLIST_MAX_DAYS

# 순위별 타이밍 (watchlist_monitor.py의 RANK_TIMING과 동일)
RANK_TIMING = {
    1: {"sweet_spot": 1, "window": (1, 2)},
    2: {"sweet_spot": 4, "window": (3, 5)},
    3: {"sweet_spot": 3, "window": (2, 4)},
}


def _trading_days_since(date_str: str) -> int:
    d = datetime.strptime(date_str, "%Y-%m-%d")
    today = datetime.now()
    count = 0
    cur = d + timedelta(days=1)
    while cur.date() <= today.date():
        if cur.weekday() < 5:
            count += 1
        cur += timedelta(days=1)
    return count


def _add_trading_days(date_str: str, n: int) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d")
    added = 0
    current = d
    while added < n:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current.strftime("%Y-%m-%d")


def backfill():
    today = datetime.now().strftime("%Y-%m-%d")
    created = 0
    skipped = 0

    for lf in sorted(LOG_DIR.glob("*.json")):
        rec_date = lf.stem
        days = _trading_days_since(rec_date)

        # D+0(오늘)과 만료(D+5 초과)는 스킵
        if days < 1 or days > WATCHLIST_MAX_DAYS:
            skipped += 1
            continue

        # 이미 워치리스트가 있으면 스킵
        wl_path = WATCHLIST_DIR / f"{rec_date}.json"
        if wl_path.exists():
            print(f"  ⏭️  {rec_date} D+{days} — 이미 존재")
            continue

        try:
            data = json.loads(lf.read_text(encoding="utf-8"))
            if data.get("skipped"):
                continue

            top = data.get("all_scored", data.get("top", []))[:5]
            if not top:
                continue

            expires = _add_trading_days(rec_date, WATCHLIST_MAX_DAYS)

            # 만료일이 이미 지났으면 스킵
            if expires < today:
                skipped += 1
                continue

            watchlist = {
                "created": rec_date,
                "expires": expires,
                "stocks": [],
            }

            for stock in top:
                rank = stock.get("rank", 99)
                timing = RANK_TIMING.get(rank, RANK_TIMING[3])

                watchlist["stocks"].append({
                    "code": stock["code"],
                    "name": stock.get("name", stock["code"]),
                    "rank": rank,
                    "score": stock.get("score", 0),
                    "entry_price": stock.get("price", 0),
                    "cci_at_screen": stock.get("cci", 0),
                    "rsi_at_screen": stock.get("rsi", 0),
                    "ma20_gap_at_screen": stock.get("ma20_gap", 0),
                    "overheat": stock.get("overheat", False),
                    "sweet_spot_day": timing["sweet_spot"],
                    "window_start": timing["window"][0],
                    "window_end": timing["window"][1],
                    "triggered": False,
                    "trigger_date": None,
                    "trigger_price": None,
                    "trigger_type": None,
                    "conviction": None,
                })

            wl_path.write_text(
                json.dumps(watchlist, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            names = [f"#{s['rank']}{s['name']}" for s in top[:3]]
            print(f"  ✅ {rec_date} D+{days} — {len(top)}종목 [{' '.join(names)}]")
            created += 1

        except Exception as e:
            print(f"  ❌ {rec_date} — {e}")

    print(f"\n완료: {created}개 생성, {skipped}개 스킵")
    print(f"워치리스트 경로: {WATCHLIST_DIR}")


if __name__ == "__main__":
    print("=" * 60)
    print("  기존 로그 → 워치리스트 백필")
    print("=" * 60)
    backfill()
