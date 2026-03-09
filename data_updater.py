"""
ClosingBell v3.5 — OHLCV 데이터 갱신
====================================
장 마감 후 당일 데이터를 로컬 CSV에 추가.
기존 v2 로직 유지 + 키움 API 대응.
"""
import logging
import pandas as pd
from datetime import datetime
from pathlib import Path
from config import (
    OHLCV_DIR, GLOBAL_CSV, LOG_DIR,
    KIWOOM_BASE_URL, KIWOOM_APPKEY, KIWOOM_SECRETKEY, API_DELAY,
)

logger = logging.getLogger("closingbell")


def update_ohlcv():
    """오늘 추천된 종목 + 전일 추천 종목의 OHLCV 갱신"""
    import json

    today = datetime.now().strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"{today}.json"
    if not log_file.exists():
        logger.info("오늘 로그 없음 → 갱신 스킵")
        return

    data = json.loads(log_file.read_text(encoding="utf-8"))
    if data.get("skipped"):
        return

    from kiwoom_api import KiwoomAPI
    api = KiwoomAPI(KIWOOM_APPKEY, KIWOOM_SECRETKEY, KIWOOM_BASE_URL, API_DELAY)
    api.ensure_token()

    # 갱신 대상: 오늘 TOP + 전일 TOP
    codes = set()
    for stock in data.get("top", []):
        codes.add(stock["code"])
    for stock in data.get("all_scored", [])[:20]:  # 상위 20종목까지
        codes.add(stock["code"])

    # 전일 로그
    log_files = sorted(LOG_DIR.glob("*.json"))
    for lf in reversed(log_files):
        if lf.stem != today:
            try:
                prev = json.loads(lf.read_text(encoding="utf-8"))
                for stock in prev.get("top", []):
                    codes.add(stock["code"])
            except Exception:
                pass
            break

    updated = 0
    for code in codes:
        try:
            _update_single(code, api)
            updated += 1
        except Exception as e:
            logger.debug("OHLCV 갱신 실패 [%s]: %s", code, e)

    logger.info("OHLCV 갱신: %d/%d종목", updated, len(codes))


def _update_single(code: str, api):
    """개별 종목 CSV 갱신"""
    code = code.strip().zfill(6)
    path = OHLCV_DIR / f"{code}.csv"

    # 기존 CSV 로드
    if path.exists():
        df = pd.read_csv(path)
        df.columns = [c.lower() for c in df.columns]  # 대문자→소문자 통일
        df["date"] = pd.to_datetime(df["date"])
    else:
        df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    # API에서 최근 5일 가져오기
    rows = api.get_daily_ohlcv(code)
    if not rows:
        return

    new_df = pd.DataFrame(rows)
    new_df["date"] = pd.to_datetime(new_df["date"])

    # 기존에 없는 날짜만 추가
    if len(df) > 0:
        existing_dates = set(df["date"].dt.strftime("%Y-%m-%d"))
        new_rows = new_df[~new_df["date"].dt.strftime("%Y-%m-%d").isin(existing_dates)]
        if len(new_rows) > 0:
            df = pd.concat([df, new_rows[["date", "open", "high", "low", "close", "volume"]]],
                           ignore_index=True)
    else:
        df = new_df[["date", "open", "high", "low", "close", "volume"]].copy()

    df = df.sort_values("date").reset_index(drop=True)
    df.to_csv(path, index=False)


def update_global_data():
    """global_merged.csv 갱신 (FDR 사용)"""
    try:
        import FinanceDataReader as fdr

        today = datetime.now()
        start = (today - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")

        kospi = fdr.DataReader("KS11", start, end)
        nasdaq = fdr.DataReader("IXIC", start, end)

        merged = pd.DataFrame({
            "date": kospi.index.strftime("%Y-%m-%d"),
            "kospi_close": kospi["Close"].values,
            "kospi_change_pct": kospi["Change"].values * 100 if "Change" in kospi.columns else 0,
        })

        if len(nasdaq) > 0:
            nasdaq_aligned = nasdaq.reindex(kospi.index, method="ffill")
            merged["nasdaq_close"] = nasdaq_aligned["Close"].values
            merged["nasdaq_change_pct"] = nasdaq_aligned["Change"].values * 100 if "Change" in nasdaq_aligned.columns else 0

        GLOBAL_CSV.parent.mkdir(parents=True, exist_ok=True)
        merged.to_csv(GLOBAL_CSV, index=False)
        logger.info("global_merged.csv 갱신 완료 (%d일)", len(merged))

    except Exception as e:
        logger.warning("글로벌 데이터 갱신 실패: %s", e)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    update_ohlcv()
    update_global_data()
