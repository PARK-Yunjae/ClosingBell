"""
ClosingBell v3 — FDR 데이터 갱신
=================================
FinanceDataReader로 OHLCV + 글로벌 지수를 최신 거래일까지 갱신.
키움 API 없이 동작 (주말/공휴일에도 실행 가능).

사용법:
    python fdr_update.py                    # 전체 갱신 (최근 30일분만 추가)
    python fdr_update.py --check            # 갱신 상태만 확인
    python fdr_update.py --code 005930      # 특정 종목만
    python fdr_update.py --global-only      # 글로벌 지수만
    python fdr_update.py --full             # 전체 종목 강제 갱신 (느림, 1~2시간)
"""
import argparse
import logging
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fdr_update")

# ── 설정 ──
DATA_DIR = Path("C:/Coding/data")
OHLCV_DIR = DATA_DIR / "ohlcv"
GLOBAL_DIR = DATA_DIR / "global"
MAPPING_CSV = DATA_DIR / "stock_mapping.csv"


def check_status():
    """현재 데이터 상태 확인"""
    print("=" * 60)
    print("📊 데이터 상태 확인")
    print("=" * 60)

    # OHLCV 샘플 확인 (삼성전자 + 랜덤 5개)
    sample_codes = ["005930"]
    csv_files = list(OHLCV_DIR.glob("*.csv"))
    print(f"\nOHLCV 파일 수: {len(csv_files)}개")

    import random
    if len(csv_files) > 5:
        extras = random.sample(csv_files, 5)
        sample_codes += [f.stem for f in extras]

    for code in sample_codes:
        path = OHLCV_DIR / f"{code}.csv"
        if not path.exists():
            print(f"  {code}: 파일 없음")
            continue
        df = pd.read_csv(path)
        df.columns = [c.lower() for c in df.columns]
        if "date" not in df.columns:
            print(f"  {code}: date 컬럼 없음 ({list(df.columns)})")
            continue
        df["date"] = pd.to_datetime(df["date"])
        last_date = df["date"].max().strftime("%Y-%m-%d")
        first_date = df["date"].min().strftime("%Y-%m-%d")
        print(f"  {code}: {first_date} ~ {last_date} ({len(df)}일)")

    # 글로벌 지수
    global_csv = GLOBAL_DIR / "global_merged.csv"
    if global_csv.exists():
        gdf = pd.read_csv(global_csv)
        gdf.columns = [c.strip().lower() for c in gdf.columns]
        date_col = "date"
        if date_col in gdf.columns:
            gdf[date_col] = pd.to_datetime(gdf[date_col])
            print(f"\n글로벌 지수: {gdf[date_col].min().strftime('%Y-%m-%d')} ~ "
                  f"{gdf[date_col].max().strftime('%Y-%m-%d')} ({len(gdf)}일)")
            # 각 지수별 마지막 유효 날짜
            for col in ["kospi_close", "nasdaq_close", "sp500_close", "usdkrw_close"]:
                if col in gdf.columns:
                    valid = gdf.dropna(subset=[col])
                    last = valid[date_col].max().strftime("%Y-%m-%d") if len(valid) > 0 else "없음"
                    empty_count = len(gdf) - len(valid)
                    status = f"⚠️ {empty_count}일 빈값" if empty_count > 0 else "✅"
                    print(f"  {col}: ~{last} {status}")
    else:
        print("\n글로벌 지수: 파일 없음")

    print(f"\n오늘: {datetime.now().strftime('%Y-%m-%d')} "
          f"({'주말' if datetime.now().weekday() >= 5 else '평일'})")
    print("=" * 60)


def update_global():
    """글로벌 지수 갱신 (코스피, 코스닥, 나스닥, S&P500, 다우, 환율)"""
    import FinanceDataReader as fdr

    logger.info("글로벌 지수 갱신 시작...")
    GLOBAL_DIR.mkdir(parents=True, exist_ok=True)
    global_csv = GLOBAL_DIR / "global_merged.csv"

    # 기존 데이터 로드
    if global_csv.exists():
        existing = pd.read_csv(global_csv)
        existing.columns = [c.strip().lower() for c in existing.columns]
        existing["date"] = pd.to_datetime(existing["date"])
        logger.info("기존 글로벌: %d일, 컬럼: %s", len(existing), list(existing.columns))

        # 나스닥이 비어있는 마지막 유효 날짜 확인
        nasdaq_valid = existing.dropna(subset=["nasdaq_close"])
        if len(nasdaq_valid) > 0:
            nasdaq_last = nasdaq_valid["date"].max()
            logger.info("나스닥 마지막 유효: %s", nasdaq_last.strftime("%Y-%m-%d"))
        else:
            nasdaq_last = existing["date"].min()

        kospi_last = existing["date"].max()
        logger.info("코스피 마지막: %s", kospi_last.strftime("%Y-%m-%d"))
    else:
        existing = None
        nasdaq_last = pd.Timestamp("2016-01-01")
        kospi_last = pd.Timestamp("2016-01-01")

    end = datetime.now().strftime("%Y-%m-%d")

    # 각 지수별로 빈 구간 채우기
    symbols = {
        "kospi": ("KS11", "kospi_close", "kospi_change_pct"),
        "kosdaq": ("KQ11", "kosdaq_close", "kosdaq_change_pct"),
        "nasdaq": ("IXIC", "nasdaq_close", "nasdaq_change_pct"),
        "sp500": ("US500", "sp500_close", "sp500_change_pct"),
        "dow": ("DJI", "dow_close", "dow_change_pct"),
        "usdkrw": ("USD/KRW", "usdkrw_close", "usdkrw_change_pct"),
    }

    updates = {}
    for name, (symbol, close_col, chg_col) in symbols.items():
        try:
            # 해당 지수의 빈 데이터 시작점 찾기
            if existing is not None and close_col in existing.columns:
                valid = existing.dropna(subset=[close_col])
                start_from = (valid["date"].max() + timedelta(days=1)).strftime("%Y-%m-%d") if len(valid) > 0 else "2016-01-01"
            else:
                start_from = "2016-01-01"

            data = None
            for retry in range(3):
                try:
                    data = fdr.DataReader(symbol, start_from, end)
                    if data is not None and len(data) > 0:
                        break
                except Exception as retry_err:
                    err_str = str(retry_err)
                    if "LOGOUT" in err_str or "session" in err_str.lower():
                        logger.debug("%s LOGOUT 재시도 %d/3", name, retry + 1)
                        time.sleep(2)
                        import importlib
                        importlib.reload(fdr)
                        continue
                    raise

            if data is not None and len(data) > 0:
                updates[name] = {
                    "dates": data.index,
                    "close": data["Close"].values,
                    "change": data["Close"].pct_change().values * 100,
                }
                logger.info("%s: %d일 신규 (%s~)", name, len(data), start_from)
            else:
                logger.info("%s: 새 데이터 없음", name)
        except Exception as e:
            logger.warning("%s 조회 실패: %s", name, e)

    if not updates:
        logger.info("갱신할 데이터 없음")
        return

    # 기존 데이터에 업데이트 머지
    if existing is not None:
        result = existing.copy()
    else:
        result = pd.DataFrame(columns=["date"])

    for name, (symbol, close_col, chg_col) in symbols.items():
        if name not in updates:
            continue
        upd = updates[name]
        for i, dt in enumerate(upd["dates"]):
            dt_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
            mask = result["date"] == pd.Timestamp(dt_str)

            if mask.any():
                # 기존 행 업데이트 (빈 값만)
                idx = result.index[mask][0]
                if pd.isna(result.at[idx, close_col]) if close_col in result.columns else True:
                    if close_col not in result.columns:
                        result[close_col] = np.nan
                    result.at[idx, close_col] = upd["close"][i]
                if pd.isna(result.at[idx, chg_col]) if chg_col in result.columns else True:
                    if chg_col not in result.columns:
                        result[chg_col] = np.nan
                    result.at[idx, chg_col] = round(upd["change"][i], 2) if not np.isnan(upd["change"][i]) else np.nan
            else:
                # 새 행 추가
                new_row = {"date": pd.Timestamp(dt_str)}
                new_row[close_col] = upd["close"][i]
                new_row[chg_col] = round(upd["change"][i], 2) if not np.isnan(upd["change"][i]) else np.nan
                result = pd.concat([result, pd.DataFrame([new_row])], ignore_index=True)

    result = result.sort_values("date").reset_index(drop=True)
    result["date"] = result["date"].dt.strftime("%Y-%m-%d") if hasattr(result["date"].iloc[0], "strftime") else result["date"]
    result.to_csv(global_csv, index=False)
    logger.info("글로벌 갱신 완료: %d일", len(result))


def update_ohlcv_single(code: str, force_days: int = 30):
    """
    개별 종목 OHLCV 갱신
    기존 CSV에 최근 데이터만 추가 (전체 다운 안 함)
    """
    import FinanceDataReader as fdr

    code = code.strip().zfill(6)
    path = OHLCV_DIR / f"{code}.csv"

    # 기존 데이터 로드
    if path.exists():
        df = pd.read_csv(path)
        # 컬럼 통일 (소문자)
        df.columns = [c.lower() for c in df.columns]
        df["date"] = pd.to_datetime(df["date"])
        last_date = df["date"].max()
        start = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        df = pd.DataFrame()
        start = (datetime.now() - timedelta(days=365 * 10)).strftime("%Y-%m-%d")

    end = datetime.now().strftime("%Y-%m-%d")

    try:
        new_data = fdr.DataReader(code, start, end)
        if new_data is None or len(new_data) == 0:
            return 0

        new_df = pd.DataFrame({
            "date": new_data.index,
            "open": new_data["Open"].values,
            "high": new_data["High"].values,
            "low": new_data["Low"].values,
            "close": new_data["Close"].values,
            "volume": new_data["Volume"].values,
        })

        if len(df) > 0:
            existing_dates = set(df["date"].dt.strftime("%Y-%m-%d"))
            new_rows = new_df[~new_df["date"].dt.strftime("%Y-%m-%d").isin(existing_dates)]
            if len(new_rows) > 0:
                combined = pd.concat([df, new_rows], ignore_index=True)
            else:
                return 0
        else:
            combined = new_df

        combined = combined.sort_values("date").reset_index(drop=True)
        # 소문자 컬럼으로 저장 (v3 호환)
        combined.to_csv(path, index=False)
        return len(new_rows) if len(df) > 0 else len(combined)

    except Exception:
        return -1


def update_ohlcv_all(full: bool = False):
    """
    전체 OHLCV 갱신 (스마트 스킵)
    1) 삼성전자로 최신 거래일 확인
    2) 각 종목 CSV의 마지막 날짜와 비교
    3) 이미 최신이면 FDR 호출 없이 스킵 → ~3분 소요
    """
    import FinanceDataReader as fdr

    # stock_mapping에서 종목 코드 로드
    if MAPPING_CSV.exists():
        mapping = pd.read_csv(MAPPING_CSV, dtype={"code": str})
        mapping["code"] = mapping["code"].str.zfill(6)
        codes = mapping["code"].tolist()
        logger.info("stock_mapping: %d종목", len(codes))
    else:
        codes = [f.stem for f in OHLCV_DIR.glob("*.csv") if not f.stem.startswith("INDEX")]
        logger.info("CSV 파일 기반: %d종목", len(codes))

    # 1) 삼성전자로 최신 거래일 확인
    latest_trading_day = None
    try:
        ref = update_ohlcv_single("005930")
        sample_path = OHLCV_DIR / "005930.csv"
        if sample_path.exists():
            sdf = pd.read_csv(sample_path)
            sdf.columns = [c.lower() for c in sdf.columns]
            sdf["date"] = pd.to_datetime(sdf["date"])
            latest_trading_day = sdf["date"].max().strftime("%Y-%m-%d")
            logger.info("최신 거래일: %s (삼성전자 기준)", latest_trading_day)
    except Exception:
        pass

    updated = 0
    failed = 0
    skipped = 0
    total = len(codes)

    for i, code in enumerate(codes):
        if code == "005930":
            skipped += 1
            continue

        # 스마트 스킵: CSV 마지막 날짜가 최신 거래일이면 FDR 호출 안 함
        if latest_trading_day and not full:
            csv_path = OHLCV_DIR / f"{code.strip().zfill(6)}.csv"
            if csv_path.exists():
                try:
                    peek = pd.read_csv(csv_path, usecols=[0], nrows=0)
                    date_col = peek.columns[0]
                    tail = pd.read_csv(csv_path, usecols=[date_col]).iloc[-1][date_col]
                    if str(tail)[:10] >= latest_trading_day:
                        skipped += 1
                        continue
                except Exception:
                    pass

        # FDR 갱신 필요
        result = update_ohlcv_single(code)
        if result > 0:
            updated += 1
        elif result == 0:
            skipped += 1
        else:
            failed += 1

        # 진행률 (200개마다)
        if (i + 1) % 200 == 0 or i == total - 1:
            logger.info("진행: %d/%d (갱신 %d, 스킵 %d, 실패 %d)",
                         i + 1, total, updated, skipped, failed)

        time.sleep(0.2)

    logger.info("=" * 50)
    logger.info("OHLCV 갱신 완료!")
    logger.info("  갱신: %d종목", updated)
    logger.info("  스킵(이미 최신): %d종목", skipped)
    logger.info("  실패: %d종목", failed)
    if latest_trading_day:
        logger.info("  최신 거래일: %s", latest_trading_day)


def main():
    parser = argparse.ArgumentParser(description="ClosingBell v3 — FDR 데이터 갱신")
    parser.add_argument("--check", action="store_true", help="갱신 상태만 확인")
    parser.add_argument("--global-only", action="store_true", help="글로벌 지수만 갱신")
    parser.add_argument("--code", type=str, default="", help="특정 종목만 갱신")
    parser.add_argument("--full", action="store_true", help="전체 종목 강제 갱신")
    args = parser.parse_args()

    if args.check:
        check_status()
        return

    if args.global_only:
        update_global()
        return

    if args.code:
        result = update_ohlcv_single(args.code)
        if result > 0:
            logger.info("%s: %d일 추가", args.code, result)
        elif result == 0:
            logger.info("%s: 이미 최신", args.code)
        else:
            logger.error("%s: 갱신 실패", args.code)
        return

    # 전체 갱신: 글로벌 먼저 → OHLCV
    update_global()
    update_ohlcv_all(full=args.full)


if __name__ == "__main__":
    main()