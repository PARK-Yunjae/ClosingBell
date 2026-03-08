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
        # 컬럼명 확인 (대문자/소문자)
        date_col = "Date" if "Date" in df.columns else "date"
        if date_col not in df.columns:
            print(f"  {code}: date 컬럼 없음 ({list(df.columns)})")
            continue
        df[date_col] = pd.to_datetime(df[date_col])
        last_date = df[date_col].max().strftime("%Y-%m-%d")
        first_date = df[date_col].min().strftime("%Y-%m-%d")
        cols = "대문자" if "Date" in df.columns else "소문자"
        print(f"  {code}: {first_date} ~ {last_date} ({len(df)}일, {cols} 컬럼)")

    # 글로벌 지수
    global_csv = GLOBAL_DIR / "global_merged.csv"
    if global_csv.exists():
        gdf = pd.read_csv(global_csv)
        date_col = "Date" if "Date" in gdf.columns else "date"
        if date_col in gdf.columns:
            gdf[date_col] = pd.to_datetime(gdf[date_col])
            print(f"\n글로벌 지수: {gdf[date_col].min().strftime('%Y-%m-%d')} ~ "
                  f"{gdf[date_col].max().strftime('%Y-%m-%d')} ({len(gdf)}일)")
    else:
        print("\n글로벌 지수: 파일 없음")

    print(f"\n오늘: {datetime.now().strftime('%Y-%m-%d')} "
          f"({'주말' if datetime.now().weekday() >= 5 else '평일'})")
    print("=" * 60)


def update_global():
    """글로벌 지수 갱신 (코스피, 코스닥, 나스닥)"""
    import FinanceDataReader as fdr

    logger.info("글로벌 지수 갱신 시작...")
    GLOBAL_DIR.mkdir(parents=True, exist_ok=True)
    global_csv = GLOBAL_DIR / "global_merged.csv"

    # 기존 데이터 로드
    if global_csv.exists():
        existing = pd.read_csv(global_csv)
        # 컬럼명 통일 (소문자)
        existing.columns = [c.lower() for c in existing.columns]
        existing["date"] = pd.to_datetime(existing["date"])
        last_date = existing["date"].max()
        start = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
        logger.info("기존 글로벌: ~%s (%d일)", last_date.strftime("%Y-%m-%d"), len(existing))
    else:
        existing = None
        start = "2016-01-01"

    end = datetime.now().strftime("%Y-%m-%d")

    try:
        # 코스피
        kospi = fdr.DataReader("KS11", start, end)
        # 코스닥
        kosdaq = fdr.DataReader("KQ11", start, end)
        # 나스닥
        nasdaq = fdr.DataReader("IXIC", start, end)

        if len(kospi) == 0:
            logger.info("글로벌: 새 데이터 없음 (이미 최신)")
            return

        # 병합
        merged = pd.DataFrame({"date": kospi.index})
        merged["kospi_close"] = kospi["Close"].values
        merged["kospi_change_pct"] = kospi["Close"].pct_change().values * 100
        merged["kosdaq_close"] = kosdaq.reindex(kospi.index, method="ffill")["Close"].values
        merged["nasdaq_close"] = nasdaq.reindex(kospi.index, method="ffill")["Close"].values
        merged["nasdaq_change_pct"] = nasdaq.reindex(kospi.index, method="ffill")["Close"].pct_change().values * 100

        merged["date"] = merged["date"].dt.strftime("%Y-%m-%d")

        if existing is not None:
            existing["date"] = existing["date"].dt.strftime("%Y-%m-%d")
            existing_dates = set(existing["date"])
            new_rows = merged[~merged["date"].isin(existing_dates)]
            if len(new_rows) > 0:
                combined = pd.concat([existing, new_rows], ignore_index=True)
            else:
                combined = existing
                logger.info("글로벌: 새 데이터 없음")
                return
        else:
            combined = merged

        combined.to_csv(global_csv, index=False)
        logger.info("글로벌 갱신 완료: %d일 (신규 %d일)",
                     len(combined), len(new_rows) if existing is not None else len(combined))

    except Exception as e:
        logger.error("글로벌 갱신 실패: %s", e)


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
    전체 OHLCV 갱신
    full=False: stock_mapping에 있는 종목만, 최근 데이터 추가
    full=True: 전체 종목 강제 갱신 (느림)
    """
    import FinanceDataReader as fdr

    # stock_mapping에서 종목 코드 로드
    if MAPPING_CSV.exists():
        mapping = pd.read_csv(MAPPING_CSV, dtype={"code": str})
        mapping["code"] = mapping["code"].str.zfill(6)
        codes = mapping["code"].tolist()
        logger.info("stock_mapping: %d종목", len(codes))
    else:
        # 파일 목록에서
        codes = [f.stem for f in OHLCV_DIR.glob("*.csv") if not f.stem.startswith("INDEX")]
        logger.info("CSV 파일 기반: %d종목", len(codes))

    # 먼저 샘플로 마지막 거래일 확인
    sample_path = OHLCV_DIR / "005930.csv"
    if sample_path.exists():
        sample = pd.read_csv(sample_path)
        date_col = "Date" if "Date" in sample.columns else "date"
        sample[date_col] = pd.to_datetime(sample[date_col])
        last_date = sample[date_col].max().strftime("%Y-%m-%d")
        logger.info("현재 마지막 거래일(삼성전자 기준): %s", last_date)
    else:
        last_date = "unknown"

    updated = 0
    failed = 0
    skipped = 0
    total = len(codes)

    for i, code in enumerate(codes):
        result = update_ohlcv_single(code)
        if result > 0:
            updated += 1
        elif result == 0:
            skipped += 1
        else:
            failed += 1

        # 진행률 (100개마다)
        if (i + 1) % 100 == 0 or i == total - 1:
            logger.info("진행: %d/%d (갱신 %d, 스킵 %d, 실패 %d)",
                         i + 1, total, updated, skipped, failed)

        # FDR 속도 제한 (너무 빠르면 차단)
        time.sleep(0.3)

    logger.info("=" * 50)
    logger.info("OHLCV 갱신 완료!")
    logger.info("  갱신: %d종목", updated)
    logger.info("  스킵(이미 최신): %d종목", skipped)
    logger.info("  실패: %d종목", failed)

    # 갱신 후 마지막 거래일 재확인
    if sample_path.exists():
        sample = pd.read_csv(sample_path)
        date_col = "Date" if "Date" in sample.columns else "date"
        sample[date_col] = pd.to_datetime(sample[date_col])
        new_last = sample[date_col].max().strftime("%Y-%m-%d")
        logger.info("  갱신 후 마지막 거래일: %s → %s", last_date, new_last)


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
