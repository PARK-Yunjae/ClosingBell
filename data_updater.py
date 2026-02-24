"""
ClosingBell v2 — 데이터 갱신 (장 종료 후)
"""
import json
import logging
import pandas as pd
from datetime import datetime
from pathlib import Path
from config import OHLCV_DIR, GLOBAL_CSV, LOG_DIR, API_DELAY
from kis_api import KisAPI

logger = logging.getLogger("closingbell")


class DataUpdater:
    """장 종료 후 OHLCV + 글로벌 갱신"""

    def __init__(self, api: KisAPI):
        self.api = api

    def update_ohlcv(self, codes: list[str]):
        """유니버스 종목 당일 OHLCV → CSV append"""
        today = datetime.now().strftime("%Y%m%d")
        today_dash = datetime.now().strftime("%Y-%m-%d")
        updated = 0

        for code in codes:
            try:
                csv_path = OHLCV_DIR / f"{code}.csv"

                # 이미 오늘 데이터 있는지 확인
                if csv_path.exists():
                    existing = pd.read_csv(csv_path, dtype=str)
                    if today_dash in existing["date"].values:
                        continue

                # API에서 당일 데이터
                rows = self.api.get_daily_prices(code, today, today)
                if not rows:
                    continue

                row = rows[-1]  # 가장 최근 1건

                # CSV에 append
                if csv_path.exists():
                    with open(csv_path, "a", encoding="utf-8") as f:
                        f.write(
                            f"\n{row['date']},{row['open']},{row['high']},"
                            f"{row['low']},{row['close']},{row['volume']}"
                        )
                else:
                    # 새 파일
                    with open(csv_path, "w", encoding="utf-8") as f:
                        f.write("date,open,high,low,close,volume\n")
                        f.write(
                            f"{row['date']},{row['open']},{row['high']},"
                            f"{row['low']},{row['close']},{row['volume']}"
                        )

                updated += 1
            except Exception as e:
                logger.debug("OHLCV 갱신 실패 [%s]: %s", code, e)

        logger.info("OHLCV 갱신: %d/%d 종목", updated, len(codes))
        return updated

    def update_global(self):
        """코스피/코스닥 → global_merged.csv append"""
        today_dash = datetime.now().strftime("%Y-%m-%d")

        try:
            # 이미 오늘 데이터 있는지 확인
            if GLOBAL_CSV.exists():
                df = pd.read_csv(GLOBAL_CSV, dtype=str)
                if today_dash in df["date"].values:
                    logger.info("글로벌 데이터 이미 존재: %s", today_dash)
                    return

            # API에서 코스피/코스닥
            kospi = self.api.get_index_price("0001")
            kosdaq = self.api.get_index_price("1001")

            # global_merged.csv에 append (나스닥/SP500/다우/환율은 빈칸)
            row = (
                f"\n{today_dash},"
                f"{kospi['price']},{kospi['change_rate']},"
                f"{kosdaq['price']},{kosdaq['change_rate']},"
                f",,,,,,"  # nasdaq ~ usdkrw (미국장 마감 후 별도 갱신)
            )

            with open(GLOBAL_CSV, "a", encoding="utf-8") as f:
                f.write(row)

            logger.info(
                "글로벌 갱신: 코스피 %.0f (%+.2f%%) | 코스닥 %.0f (%+.2f%%)",
                kospi["price"], kospi["change_rate"],
                kosdaq["price"], kosdaq["change_rate"],
            )
        except Exception as e:
            logger.warning("글로벌 갱신 실패: %s", e)

    # ──────────────────────────────────────────────
    # 로그 저장
    # ──────────────────────────────────────────────
    @staticmethod
    def save_log(result: dict):
        """스크리닝 결과 → data/logs/{date}.json"""
        date_str = result.get("date", datetime.now().strftime("%Y-%m-%d"))
        path = LOG_DIR / f"{date_str}.json"
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info("로그 저장: %s", path.name)

    @staticmethod
    def load_log(date_str: str) -> dict | None:
        """특정 날짜 로그 로드"""
        path = LOG_DIR / f"{date_str}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def load_all_logs() -> dict:
        """전체 로그 로드 → {date: data}"""
        logs = {}
        for f in sorted(LOG_DIR.glob("*.json")):
            try:
                logs[f.stem] = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
        return logs
