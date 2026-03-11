"""
ClosingBell — 데이터 무결성 검증기
===================================
OHLCV, 글로벌 지수, stock_mapping 데이터 품질 검사.
문제 발견 시 자동 수정 옵션 제공.

사용법:
    python data_validator.py                # 전체 검사 (요약)
    python data_validator.py --verbose      # 상세 출력
    python data_validator.py --fix          # 자동 수정 가능한 항목 수정
    python data_validator.py --ohlcv-only   # OHLCV만 검사
    python data_validator.py --global-only  # 글로벌 지수만 검사
"""
import argparse
import logging
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import DATA_DIR, GLOBAL_CSV, LOG_DIR, MAPPING_CSV, OHLCV_DIR, PERFORMANCE_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("validator")

# ── 설정 (config.py와 동일) ──
PERF_FILE = PERFORMANCE_DIR / "tracking.json"

# 한국 공휴일 (2024~2026 주요일만 — 완벽하지 않아도 됨, 경고 수준 조정용)
KR_HOLIDAYS = {
    "2024-01-01", "2024-02-09", "2024-02-10", "2024-02-11", "2024-02-12",
    "2024-03-01", "2024-04-10", "2024-05-01", "2024-05-05", "2024-05-06",
    "2024-05-15", "2024-06-06", "2024-08-15", "2024-09-16", "2024-09-17",
    "2024-09-18", "2024-10-03", "2024-10-09", "2024-12-25",
    "2025-01-01", "2025-01-28", "2025-01-29", "2025-01-30",
    "2025-03-01", "2025-03-03", "2025-05-01", "2025-05-05", "2025-05-06",
    "2025-06-06", "2025-08-15", "2025-10-03", "2025-10-05", "2025-10-06",
    "2025-10-07", "2025-10-09", "2025-12-25",
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18",
    "2026-03-01", "2026-03-02", "2026-05-01", "2026-05-05",
    "2026-05-24", "2026-06-06", "2026-08-15", "2026-08-17",
    "2026-09-24", "2026-09-25", "2026-09-26", "2026-10-03", "2026-10-09",
    "2026-12-25",
}


class ValidationResult:
    def __init__(self):
        self.errors = []     # 반드시 수정 필요
        self.warnings = []   # 확인 필요
        self.fixes = []      # 자동 수정된 항목
        self.stats = {}

    def error(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    def fix(self, msg):
        self.fixes.append(msg)

    def summary(self):
        return f"❌ {len(self.errors)}건 에러 | ⚠️ {len(self.warnings)}건 경고 | 🔧 {len(self.fixes)}건 수정"


# ══════════════════════════════════════════════
# 1. OHLCV 검증
# ══════════════════════════════════════════════
def validate_ohlcv(verbose=False, fix=False) -> ValidationResult:
    """OHLCV CSV 전체 검증"""
    result = ValidationResult()

    csv_files = sorted(OHLCV_DIR.glob("*.csv"))
    index_files = [f for f in csv_files if f.stem.startswith("INDEX_")]
    stock_files = [f for f in csv_files if not f.stem.startswith("INDEX_")]

    result.stats["total_files"] = len(csv_files)
    result.stats["stock_files"] = len(stock_files)
    result.stats["index_files"] = len(index_files)

    logger.info("OHLCV 검사 시작: %d파일 (%d종목 + %d인덱스)",
                len(csv_files), len(stock_files), len(index_files))

    # 기준: 삼성전자의 마지막 날짜
    ref_path = OHLCV_DIR / "005930.csv"
    ref_last_date = None
    if ref_path.exists():
        ref_df = pd.read_csv(ref_path)
        ref_df.columns = [c.lower() for c in ref_df.columns]
        ref_df["date"] = pd.to_datetime(ref_df["date"])
        ref_last_date = ref_df["date"].max()
        result.stats["ref_last_date"] = ref_last_date.strftime("%Y-%m-%d")
        logger.info("기준 날짜 (005930): %s", result.stats["ref_last_date"])

    # 통계 수집
    stale_count = 0
    short_count = 0
    price_issues = 0
    volume_issues = 0
    column_issues = 0
    gap_issues = 0
    extreme_changes = []
    required_cols = {"date", "open", "high", "low", "close", "volume"}

    for i, f in enumerate(stock_files):
        code = f.stem
        try:
            df = pd.read_csv(f)
            df.columns = [c.lower().strip() for c in df.columns]
        except Exception as e:
            result.error(f"{code}: CSV 읽기 실패 — {e}")
            continue

        # (1) 컬럼 확인
        actual_cols = set(df.columns)
        missing_cols = required_cols - actual_cols
        if missing_cols:
            result.error(f"{code}: 필수 컬럼 누락 — {missing_cols}")
            column_issues += 1
            continue

        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])

        if len(df) == 0:
            result.error(f"{code}: 유효한 행 없음")
            continue

        df = df.sort_values("date").reset_index(drop=True)

        # (2) 데이터 길이
        if len(df) < 20:
            result.warn(f"{code}: 데이터 부족 ({len(df)}일) — 지표 계산 불가")
            short_count += 1

        # (3) 최신 날짜 확인
        last_date = df["date"].max()
        if ref_last_date and (ref_last_date - last_date).days > 5:
            stale_days = (ref_last_date - last_date).days
            if stale_days > 30:
                result.warn(f"{code}: {stale_days}일 미갱신 (마지막: {last_date.strftime('%Y-%m-%d')})")
            stale_count += 1

        # (4) 가격 정합성: Low ≤ Open, Close ≤ High
        bad_hl = df[(df["low"] > df["high"])]
        if len(bad_hl) > 0:
            result.error(f"{code}: Low > High — {len(bad_hl)}건")
            price_issues += 1
            if fix:
                for idx in bad_hl.index:
                    lo, hi = df.at[idx, "low"], df.at[idx, "high"]
                    df.at[idx, "low"] = hi
                    df.at[idx, "high"] = lo
                result.fix(f"{code}: Low/High 스왑 {len(bad_hl)}건")

        bad_open_hi = df[(df["open"] > df["high"]) & (df["high"] > 0)]
        bad_open_lo = df[(df["open"] < df["low"]) & (df["low"] > 0)]
        if len(bad_open_hi) > 0:
            result.warn(f"{code}: Open > High — {len(bad_open_hi)}건")
            price_issues += 1
        if len(bad_open_lo) > 0:
            result.warn(f"{code}: Open < Low — {len(bad_open_lo)}건")
            price_issues += 1

        bad_close_hi = df[(df["close"] > df["high"]) & (df["high"] > 0)]
        bad_close_lo = df[(df["close"] < df["low"]) & (df["low"] > 0)]
        if len(bad_close_hi) > 0:
            result.warn(f"{code}: Close > High — {len(bad_close_hi)}건")
            price_issues += 1
        if len(bad_close_lo) > 0:
            result.warn(f"{code}: Close < Low — {len(bad_close_lo)}건")
            price_issues += 1

        # (5) 0원 종가 (거래정지 vs 에러)
        zero_close = df[df["close"] == 0]
        if len(zero_close) > 0:
            result.warn(f"{code}: 종가 0원 — {len(zero_close)}건 (거래정지?)")

        # (6) 음수 거래량
        neg_vol = df[df["volume"] < 0]
        if len(neg_vol) > 0:
            result.error(f"{code}: 음수 거래량 — {len(neg_vol)}건")
            volume_issues += 1
            if fix:
                df.loc[df["volume"] < 0, "volume"] = 0
                result.fix(f"{code}: 음수 거래량 → 0 수정")

        # (7) 급등락 이상치 (1일 ±30% 이상, 상한가 외)
        df["pct_change"] = df["close"].pct_change() * 100
        extreme = df[(df["pct_change"].abs() > 30) & (df["close"] > 0)]
        if len(extreme) > 0:
            for _, row in extreme.head(3).iterrows():
                extreme_changes.append({
                    "code": code,
                    "date": row["date"].strftime("%Y-%m-%d"),
                    "change": round(row["pct_change"], 1),
                    "close": row["close"],
                })

        # (8) 날짜 갭 (영업일 5일 이상 연속 누락 = 경고)
        dates = df["date"].tolist()
        for j in range(1, len(dates)):
            gap_days = (dates[j] - dates[j-1]).days
            if gap_days > 7:  # 주말+공휴일 감안해도 7일 이상이면 확인
                gap_str = f"{dates[j-1].strftime('%Y-%m-%d')} → {dates[j].strftime('%Y-%m-%d')}"
                # 공휴일 시즌(설/추석) 제외
                mid_date = dates[j-1] + timedelta(days=gap_days//2)
                mid_str = mid_date.strftime("%Y-%m-%d")
                if mid_str not in KR_HOLIDAYS and gap_days > 10:
                    result.warn(f"{code}: 날짜 갭 {gap_days}일 ({gap_str})")
                    gap_issues += 1

        # 수정 저장
        if fix and (len(bad_hl) > 0 or len(neg_vol) > 0):
            df.drop(columns=["pct_change"], inplace=True, errors="ignore")
            df.to_csv(f, index=False)

        # 진행률
        if (i + 1) % 500 == 0:
            logger.info("  진행: %d/%d...", i + 1, len(stock_files))

    result.stats.update({
        "stale": stale_count,
        "short": short_count,
        "price_issues": price_issues,
        "volume_issues": volume_issues,
        "column_issues": column_issues,
        "gap_issues": gap_issues,
        "extreme_changes": len(extreme_changes),
    })

    # 극단 변동 상위 10 출력
    if extreme_changes and verbose:
        extreme_changes.sort(key=lambda x: abs(x["change"]), reverse=True)
        logger.info("급등락 이상치 TOP10:")
        for ec in extreme_changes[:10]:
            logger.info("  %s %s: %+.1f%% (종가 %s)",
                        ec["code"], ec["date"], ec["change"], ec["close"])

    return result


# ══════════════════════════════════════════════
# 2. 글로벌 지수 검증
# ══════════════════════════════════════════════
def validate_global(verbose=False, fix=False) -> ValidationResult:
    """global_merged.csv 검증"""
    result = ValidationResult()

    if not GLOBAL_CSV.exists():
        result.error(f"글로벌 파일 없음: {GLOBAL_CSV}")
        return result

    df = pd.read_csv(GLOBAL_CSV)
    df.columns = [c.strip().lower() for c in df.columns]

    if "date" not in df.columns:
        result.error("date 컬럼 없음")
        return result

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    result.stats["rows"] = len(df)
    result.stats["date_range"] = f"{df['date'].min().strftime('%Y-%m-%d')} ~ {df['date'].max().strftime('%Y-%m-%d')}"
    result.stats["columns"] = list(df.columns)

    logger.info("글로벌 검사: %d행, %s", len(df), result.stats["date_range"])

    # 필수 컬럼 확인
    expected_close = ["kospi_close", "kosdaq_close", "nasdaq_close"]
    expected_change = ["kospi_change_pct", "kosdaq_change_pct", "nasdaq_change_pct"]

    for col in expected_close + expected_change:
        if col not in df.columns:
            result.error(f"컬럼 누락: {col}")
        else:
            null_count = df[col].isna().sum()
            null_pct = null_count / len(df) * 100
            if null_pct > 20:
                result.warn(f"{col}: 결측 {null_count}건 ({null_pct:.0f}%)")
            elif null_pct > 5:
                result.warn(f"{col}: 결측 {null_count}건 ({null_pct:.1f}%)")
            result.stats[f"{col}_null"] = null_count

    # 날짜 연속성
    dates = df["date"].tolist()
    for i in range(1, len(dates)):
        gap = (dates[i] - dates[i-1]).days
        if gap > 7:
            result.warn(f"날짜 갭: {dates[i-1].strftime('%Y-%m-%d')} → {dates[i].strftime('%Y-%m-%d')} ({gap}일)")

    # 지수 이상치 (일간 변동 ±10% 이상)
    for col in expected_close:
        if col not in df.columns:
            continue
        pct = df[col].pct_change() * 100
        extreme = pct[pct.abs() > 10].dropna()
        if len(extreme) > 0:
            for idx in extreme.index[:5]:
                result.warn(f"{col}: 급변 {pct.at[idx]:+.1f}% ({df.at[idx, 'date'].strftime('%Y-%m-%d')})")

    # change_pct와 실제 변동 일치 검증
    for close_col, change_col in zip(expected_close, expected_change):
        if close_col not in df.columns or change_col not in df.columns:
            continue
        calc_change = df[close_col].pct_change() * 100
        reported = df[change_col]
        # 둘 다 유효한 행에서 비교
        both_valid = df[[close_col, change_col]].dropna().index
        if len(both_valid) > 1:
            diff = (calc_change.loc[both_valid] - reported.loc[both_valid]).abs()
            big_diff = diff[diff > 1.0].dropna()
            if len(big_diff) > 0:
                result.warn(f"{change_col}: 계산값과 불일치 {len(big_diff)}건 (>1.0%p)")

    # 중복 날짜
    dup_dates = df[df.duplicated(subset=["date"], keep=False)]
    if len(dup_dates) > 0:
        result.error(f"중복 날짜: {len(dup_dates)//2}건")
        if fix:
            df = df.drop_duplicates(subset=["date"], keep="last")
            df.to_csv(GLOBAL_CSV, index=False)
            result.fix(f"중복 날짜 제거 ({len(dup_dates)//2}건)")

    return result


# ══════════════════════════════════════════════
# 3. stock_mapping 검증
# ══════════════════════════════════════════════
def validate_mapping(verbose=False) -> ValidationResult:
    """stock_mapping.csv ↔ OHLCV 파일 정합성"""
    result = ValidationResult()

    if not MAPPING_CSV.exists():
        result.error(f"매핑 파일 없음: {MAPPING_CSV}")
        return result

    df = pd.read_csv(MAPPING_CSV, dtype={"code": str}, encoding="utf-8-sig")
    df["code"] = df["code"].str.zfill(6)

    result.stats["mapping_count"] = len(df)
    result.stats["columns"] = list(df.columns)

    # OHLCV 파일 목록
    ohlcv_codes = {f.stem for f in OHLCV_DIR.glob("*.csv") if not f.stem.startswith("INDEX_")}

    # 매핑에 있는데 OHLCV 없는 종목
    mapping_codes = set(df["code"].tolist())
    missing_ohlcv = mapping_codes - ohlcv_codes
    if missing_ohlcv:
        result.warn(f"매핑에는 있지만 OHLCV 없음: {len(missing_ohlcv)}종목")
        if verbose:
            for code in sorted(missing_ohlcv)[:20]:
                name = df[df["code"] == code]["name"].values[0] if "name" in df.columns else code
                logger.info("  %s %s", code, name)

    # OHLCV 있는데 매핑 없는 종목
    extra_ohlcv = ohlcv_codes - mapping_codes
    if extra_ohlcv:
        result.warn(f"OHLCV는 있지만 매핑 없음: {len(extra_ohlcv)}종목")

    # 이름 누락
    if "name" in df.columns:
        empty_name = df[df["name"].isna() | (df["name"] == "")]
        if len(empty_name) > 0:
            result.warn(f"이름 빈값: {len(empty_name)}종목")

    # 섹터 빈값
    if "sector" in df.columns:
        empty_sector = df[df["sector"].isna() | (df["sector"] == "")]
        pct = len(empty_sector) / len(df) * 100
        result.stats["empty_sector_pct"] = round(pct, 1)
        if pct > 30:
            result.warn(f"섹터 빈값: {len(empty_sector)}종목 ({pct:.0f}%)")

    # 코드 중복
    dup = df[df.duplicated(subset=["code"], keep=False)]
    if len(dup) > 0:
        result.error(f"코드 중복: {len(dup)//2}건")

    # 코드 형식 (6자리 숫자)
    bad_format = df[~df["code"].str.match(r"^\d{6}$")]
    if len(bad_format) > 0:
        result.error(f"코드 형식 오류: {len(bad_format)}건")

    result.stats["ohlcv_files"] = len(ohlcv_codes)
    result.stats["match_rate"] = round(
        len(mapping_codes & ohlcv_codes) / max(len(mapping_codes), 1) * 100, 1)

    return result


# ══════════════════════════════════════════════
# 4. 로그 ↔ OHLCV 정합성
# ══════════════════════════════════════════════
def validate_logs(verbose=False) -> ValidationResult:
    """로그/트래킹 데이터 정합성"""
    import json
    result = ValidationResult()

    log_files = sorted(LOG_DIR.glob("*.json"))
    result.stats["log_count"] = len(log_files)

    missing_ohlcv_codes = set()
    for lf in log_files:
        try:
            data = json.loads(lf.read_text(encoding="utf-8"))
            if data.get("skipped"):
                continue
            for s in data.get("all_scored", data.get("top", [])):
                code = s.get("code", "").strip().zfill(6)
                csv_path = OHLCV_DIR / f"{code}.csv"
                if not csv_path.exists():
                    missing_ohlcv_codes.add(code)
        except Exception:
            result.warn(f"로그 파싱 실패: {lf.name}")

    if missing_ohlcv_codes:
        result.warn(f"로그 종목 중 OHLCV 없음: {len(missing_ohlcv_codes)}건")

    # 트래킹 수익률 재검증 (OHLCV 대비 샘플)
    if PERF_FILE.exists():
        try:
            tracking = json.loads(PERF_FILE.read_text(encoding="utf-8"))
            records = tracking.get("records", [])
            result.stats["tracking_records"] = len(records)

            mismatches = 0
            checked = 0
            for r in records[:50]:  # 상위 50건만 샘플
                code = r.get("code", "").strip().zfill(6)
                csv_path = OHLCV_DIR / f"{code}.csv"
                if not csv_path.exists():
                    continue

                df = pd.read_csv(csv_path)
                df.columns = [c.lower() for c in df.columns]
                df["date"] = pd.to_datetime(df["date"])

                track_date = r.get("track_date", "")
                track_price = r.get("track_price", 0)
                if not track_date or track_price <= 0:
                    continue

                match = df[df["date"] == pd.Timestamp(track_date)]
                if len(match) == 0:
                    continue

                actual_close = int(match.iloc[0]["close"])
                checked += 1
                if abs(actual_close - track_price) > 1:  # 1원 오차 허용
                    mismatches += 1
                    if verbose:
                        logger.info("  불일치: %s %s D+%d — 추적=%d, OHLCV=%d",
                                    r["name"], track_date, r["track_day"],
                                    track_price, actual_close)

            if mismatches > 0:
                result.warn(f"성과 추적 가격 불일치: {mismatches}/{checked}건")
            result.stats["tracking_checked"] = checked
            result.stats["tracking_mismatches"] = mismatches

        except Exception as e:
            result.warn(f"트래킹 검증 실패: {e}")

    return result


# ══════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="ClosingBell 데이터 검증")
    parser.add_argument("--verbose", "-v", action="store_true", help="상세 출력")
    parser.add_argument("--fix", action="store_true", help="자동 수정 적용")
    parser.add_argument("--ohlcv-only", action="store_true", help="OHLCV만 검사")
    parser.add_argument("--global-only", action="store_true", help="글로벌만 검사")
    args = parser.parse_args()

    print("=" * 70)
    print("📋 ClosingBell — 데이터 무결성 검증")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    all_results = {}

    if not args.global_only:
        print("\n[1/4] OHLCV 검사...")
        r = validate_ohlcv(args.verbose, args.fix)
        all_results["ohlcv"] = r
        print(f"  {r.summary()}")
        print(f"  파일: {r.stats.get('stock_files', 0)}종목 + {r.stats.get('index_files', 0)}인덱스")
        print(f"  미갱신: {r.stats.get('stale', 0)}건 | 데이터부족: {r.stats.get('short', 0)}건")
        print(f"  가격이상: {r.stats.get('price_issues', 0)}건 | 거래량이상: {r.stats.get('volume_issues', 0)}건")
        print(f"  급등락(±30%): {r.stats.get('extreme_changes', 0)}건")

    if not args.ohlcv_only:
        print("\n[2/4] 글로벌 지수 검사...")
        r = validate_global(args.verbose, args.fix)
        all_results["global"] = r
        print(f"  {r.summary()}")
        print(f"  범위: {r.stats.get('date_range', '?')} ({r.stats.get('rows', 0)}행)")
        for col in ["kospi_close_null", "nasdaq_close_null"]:
            if col in r.stats:
                print(f"  {col.replace('_null','')}: 결측 {r.stats[col]}건")

    if not args.ohlcv_only and not args.global_only:
        print("\n[3/4] stock_mapping 검사...")
        r = validate_mapping(args.verbose)
        all_results["mapping"] = r
        print(f"  {r.summary()}")
        print(f"  매핑: {r.stats.get('mapping_count', 0)}종목 | OHLCV: {r.stats.get('ohlcv_files', 0)}파일")
        print(f"  매칭률: {r.stats.get('match_rate', 0)}%")

        print("\n[4/4] 로그/트래킹 검사...")
        r = validate_logs(args.verbose)
        all_results["logs"] = r
        print(f"  {r.summary()}")
        print(f"  로그: {r.stats.get('log_count', 0)}파일 | 추적: {r.stats.get('tracking_records', 0)}건")
        if r.stats.get("tracking_mismatches", 0) > 0:
            print(f"  ⚠️ 가격 불일치: {r.stats['tracking_mismatches']}/{r.stats['tracking_checked']}건")

    # 총 요약
    total_errors = sum(len(r.errors) for r in all_results.values())
    total_warnings = sum(len(r.warnings) for r in all_results.values())
    total_fixes = sum(len(r.fixes) for r in all_results.values())

    print("\n" + "=" * 70)
    if total_errors == 0 and total_warnings < 10:
        print(f"🟢 검증 완료 — 에러 {total_errors}건, 경고 {total_warnings}건")
    elif total_errors == 0:
        print(f"🟡 검증 완료 — 에러 없음, 경고 {total_warnings}건 확인 필요")
    else:
        print(f"🔴 검증 완료 — 에러 {total_errors}건 수정 필요, 경고 {total_warnings}건")

    if total_fixes > 0:
        print(f"🔧 자동 수정: {total_fixes}건")
    print("=" * 70)

    # 상세 출력
    if args.verbose:
        for name, r in all_results.items():
            if r.errors:
                print(f"\n── {name} 에러 ──")
                for e in r.errors[:30]:
                    print(f"  ❌ {e}")
            if r.warnings:
                print(f"\n── {name} 경고 ──")
                for w in r.warnings[:30]:
                    print(f"  ⚠️ {w}")
            if r.fixes:
                print(f"\n── {name} 수정 ──")
                for f in r.fixes:
                    print(f"  🔧 {f}")


if __name__ == "__main__":
    main()
