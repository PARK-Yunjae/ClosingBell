"""
ClosingBell v3.5 — 주간/분기 데이터 갱신
==========================================
주 1회 실행: stock_mapping, meta (관리종목, 상폐, 시총)
분기 1회: finstate (재무제표)

사용법:
    python weekly_update.py              # 주간 갱신 (매핑 + 메타)
    python weekly_update.py --finstate   # 분기 갱신 (재무제표 포함)
    python weekly_update.py --check      # 상태만 확인
"""
import argparse
import logging
import time
import pandas as pd
from datetime import datetime
from pathlib import Path

from config import DATA_DIR, MAPPING_CSV

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("weekly")

META_DIR = DATA_DIR / "meta"
FINSTATE_DIR = DATA_DIR / "finstate"


def update_stock_mapping():
    """KRX 상장 종목 매핑 갱신 (stock_mapping.csv)"""
    try:
        import FinanceDataReader as fdr

        logger.info("stock_mapping 갱신 시작...")

        # 코스피 + 코스닥 종목 리스트
        kospi = fdr.StockListing("KOSPI")
        kosdaq = fdr.StockListing("KOSDAQ")

        combined = pd.concat([kospi, kosdaq], ignore_index=True)

        # 컬럼 정리
        col_map = {
            "Code": "code", "Name": "name", "Market": "market",
            "Sector": "sector", "Industry": "industry",
        }
        # FDR 버전에 따라 컬럼명이 다를 수 있음
        for old, new in col_map.items():
            if old in combined.columns:
                combined = combined.rename(columns={old: new})

        if "code" not in combined.columns:
            # 소문자 버전 체크
            if "code" in [c.lower() for c in combined.columns]:
                combined.columns = [c.lower() for c in combined.columns]
            else:
                logger.warning("stock_mapping: 'code' 컬럼 없음 (%s)", list(combined.columns))
                return False

        combined["code"] = combined["code"].astype(str).str.zfill(6)

        # 기존 파일 백업
        if MAPPING_CSV.exists():
            backup = MAPPING_CSV.with_suffix(".csv.bak")
            MAPPING_CSV.rename(backup)
            logger.info("기존 매핑 백업: %s", backup.name)

        # 필요한 컬럼만 저장
        keep_cols = [c for c in ["code", "name", "market", "sector", "industry"]
                     if c in combined.columns]
        combined[keep_cols].to_csv(MAPPING_CSV, index=False, encoding="utf-8-sig")
        logger.info("stock_mapping 갱신 완료: %d종목", len(combined))
        return True

    except Exception as e:
        logger.error("stock_mapping 갱신 실패: %s", e)
        return False


def update_meta():
    """메타 데이터 갱신 (관리종목, 시총 등)"""
    try:
        import FinanceDataReader as fdr

        META_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("메타 데이터 갱신 시작...")

        # 시가총액 스냅샷
        try:
            kospi_cap = fdr.StockListing("KOSPI")
            kosdaq_cap = fdr.StockListing("KOSDAQ")
            marcap = pd.concat([kospi_cap, kosdaq_cap], ignore_index=True)
            marcap_path = META_DIR / "marcap_snapshot.csv"
            marcap.to_csv(marcap_path, index=False, encoding="utf-8-sig")
            logger.info("시총 스냅샷: %d종목", len(marcap))
        except Exception as e:
            logger.warning("시총 스냅샷 실패: %s", e)

        # KRX 기본 정보
        try:
            krx_desc = fdr.StockListing("KRX-DESC")
            krx_path = META_DIR / "krx_desc.csv"
            krx_desc.to_csv(krx_path, index=False, encoding="utf-8-sig")
            logger.info("KRX 기본정보: %d종목", len(krx_desc))
        except Exception as e:
            logger.warning("KRX 기본정보 실패: %s", e)

        # 관리종목
        try:
            admin = fdr.StockListing("KRX-ADMIN")
            admin_path = META_DIR / "admin_list.csv"
            admin.to_csv(admin_path, index=False, encoding="utf-8-sig")
            logger.info("관리종목: %d종목", len(admin))
        except Exception as e:
            logger.warning("관리종목 실패: %s", e)

        logger.info("메타 갱신 완료")
        return True

    except Exception as e:
        logger.error("메타 갱신 실패: %s", e)
        return False


def update_finstate():
    """재무제표 갱신 (DART, 분기별 실행 권장)"""
    try:
        from dart_checker import DartChecker

        FINSTATE_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("재무제표 갱신 시작... (시간 소요)")

        # stock_mapping에서 종목 코드
        if not MAPPING_CSV.exists():
            logger.error("stock_mapping.csv 없음")
            return False

        mapping = pd.read_csv(MAPPING_CSV, dtype={"code": str})
        codes = mapping["code"].str.zfill(6).tolist()

        dc = DartChecker()
        success = 0
        failed = 0

        for i, code in enumerate(codes):
            try:
                result = dc.check(code)
                if result:
                    # 개별 종목 재무 데이터 저장
                    fin_path = FINSTATE_DIR / f"{code}.json"
                    import json
                    fin_path.write_text(
                        json.dumps(result, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    success += 1
            except Exception:
                failed += 1

            if (i + 1) % 100 == 0:
                logger.info("재무 진행: %d/%d (성공 %d, 실패 %d)",
                            i + 1, len(codes), success, failed)
            time.sleep(0.5)  # DART API 속도 제한

        logger.info("재무제표 갱신 완료: %d성공, %d실패", success, failed)
        return True

    except Exception as e:
        logger.error("재무제표 갱신 실패: %s", e)
        return False


def check_status():
    """데이터 상태 확인"""
    print("=" * 60)
    print("  주간 데이터 상태")
    print("=" * 60)

    # stock_mapping
    if MAPPING_CSV.exists():
        df = pd.read_csv(MAPPING_CSV, dtype={"code": str})
        mod_time = datetime.fromtimestamp(MAPPING_CSV.stat().st_mtime)
        days_old = (datetime.now() - mod_time).days
        status = "✅" if days_old <= 7 else ("⚠️" if days_old <= 30 else "❌")
        print(f"  {status} stock_mapping: {len(df)}종목, {days_old}일 전 갱신")
    else:
        print(f"  ❌ stock_mapping: 없음")

    # meta
    if META_DIR.exists():
        meta_files = list(META_DIR.glob("*.csv"))
        if meta_files:
            latest = max(f.stat().st_mtime for f in meta_files)
            days_old = (datetime.now() - datetime.fromtimestamp(latest)).days
            status = "✅" if days_old <= 7 else ("⚠️" if days_old <= 30 else "❌")
            print(f"  {status} meta/: {len(meta_files)}파일, {days_old}일 전 갱신")
        else:
            print(f"  ❌ meta/: 파일 없음")
    else:
        print(f"  ❌ meta/: 폴더 없음")

    # finstate
    if FINSTATE_DIR.exists():
        fin_files = list(FINSTATE_DIR.glob("*"))
        if fin_files:
            latest = max(f.stat().st_mtime for f in fin_files)
            days_old = (datetime.now() - datetime.fromtimestamp(latest)).days
            status = "✅" if days_old <= 90 else ("⚠️" if days_old <= 180 else "❌")
            print(f"  {status} finstate/: {len(fin_files)}파일, {days_old}일 전 갱신")
        else:
            print(f"  ⚠️ finstate/: 파일 없음")
    else:
        print(f"  ⚠️ finstate/: 폴더 없음")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ClosingBell — 주간 데이터 갱신")
    parser.add_argument("--finstate", action="store_true", help="재무제표도 갱신 (분기)")
    parser.add_argument("--check", action="store_true", help="상태만 확인")
    args = parser.parse_args()

    if args.check:
        check_status()
    else:
        print("=" * 60)
        print("  주간 데이터 갱신")
        print("=" * 60)
        update_stock_mapping()
        update_meta()
        if args.finstate:
            update_finstate()
        check_status()
