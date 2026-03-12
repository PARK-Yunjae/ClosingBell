"""
대주주 지분율 수집 — DART API hyslr_sttus
==========================================
buy_signals에 나온 종목 + 전체 매핑 종목에 대해
최대주주+특수관계인 합산 지분율을 수집.

사용법:
    python tools/collect_major_holder.py                 # 기본 (2024+2023 사업보고서)
    python tools/collect_major_holder.py --year 2024     # 특정 연도만
    python tools/collect_major_holder.py --signals-only  # buy_signals 종목만 (빠름)
    python tools/collect_major_holder.py --check         # 수집 결과 확인

출력: data/meta/major_holder.csv
"""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

# 프로젝트 루트 추가
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import DART_API_KEY, DATA_DIR, MAPPING_CSV
from storage import load_backtest_dataset

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("holder")

DART_BASE = "https://opendart.fss.or.kr/api"
CORP_MAP_PATH = ROOT / "data" / "dart_corp_map.json"
OUTPUT_DIR = DATA_DIR / "meta"
OUTPUT_CSV = OUTPUT_DIR / "major_holder.csv"

# 보고서 코드
REPRT_ANNUAL = "11011"      # 사업보고서
REPRT_3Q = "11014"          # 3분기보고서
REPRT_SEMI = "11012"        # 반기보고서
REPRT_1Q = "11013"          # 1분기보고서


def load_corp_map() -> dict:
    """종목코드(6자리) → DART corp_code(8자리) 매핑"""
    if not CORP_MAP_PATH.exists():
        log.error("dart_corp_map.json 없음 — 먼저 dart_checker.py 실행 필요")
        return {}
    return json.loads(CORP_MAP_PATH.read_text(encoding="utf-8"))


def get_signal_codes() -> set:
    """buy_signals에 등장한 종목코드 집합"""
    signals = load_backtest_dataset("buy_signals") or []
    return {str(s["code"]).zfill(6) for s in signals}


def fetch_holder(corp_code: str, bsns_year: str,
                 reprt_code: str = REPRT_ANNUAL) -> dict | None:
    """
    DART hyslr_sttus API 호출 → 최대주주+특수관계인 합산 지분율 반환.
    반환: {"total_pct": float, "holder_name": str, "holder_count": int, "raw": list}
    """
    try:
        time.sleep(0.15)  # rate limit 대응
        resp = requests.get(f"{DART_BASE}/hyslrSttus.json", params={
            "crtfc_key": DART_API_KEY,
            "corp_code": corp_code,
            "bsns_year": bsns_year,
            "reprt_code": reprt_code,
        }, timeout=10)

        data = resp.json()
        status = data.get("status", "")

        if status == "013":  # 데이터 없음
            return None
        if status != "000":
            return None

        holders = data.get("list", [])
        if not holders:
            return None

        # 합산: trmend_posesn_stock_qota_rt (기말 지분율)
        total_pct = 0.0
        top_holder = ""
        for h in holders:
            pct_str = h.get("trmend_posesn_stock_qota_rt", "0")
            try:
                pct = float(pct_str.replace(",", "").replace("-", "0"))
                total_pct += pct
            except (ValueError, AttributeError):
                pass
            # 최대주주 이름 (첫 번째 = 본인)
            if not top_holder and h.get("relate") in ("본인", "최대주주 본인", ""):
                top_holder = h.get("nm", "")

        if not top_holder and holders:
            top_holder = holders[0].get("nm", "")

        return {
            "total_pct": round(total_pct, 2),
            "holder_name": top_holder,
            "holder_count": len(holders),
        }

    except requests.Timeout:
        return None
    except Exception as e:
        log.debug("API 에러 [%s]: %s", corp_code, e)
        return None


def collect(years: list[int], signals_only: bool = False,
            resume: bool = True) -> pd.DataFrame:
    """전종목 대주주 지분율 수집"""

    corp_map = load_corp_map()
    if not corp_map:
        return pd.DataFrame()

    # 대상 종목 결정
    if signals_only:
        target_codes = get_signal_codes()
        log.info("buy_signals 종목만: %d개", len(target_codes))
    else:
        # stock_mapping 기준 전종목
        try:
            mapping = pd.read_csv(MAPPING_CSV, dtype={"code": str})
            target_codes = set(mapping["code"].str.zfill(6))
            log.info("stock_mapping 전종목: %d개", len(target_codes))
        except Exception:
            target_codes = set(corp_map.keys())
            log.info("corp_map 전종목: %d개", len(target_codes))

    # 기존 결과 로드 (이어하기)
    existing = pd.DataFrame()
    if resume and OUTPUT_CSV.exists():
        existing = pd.read_csv(OUTPUT_CSV, dtype={"code": str})
        existing["code"] = existing["code"].str.zfill(6)
        log.info("기존 수집 결과: %d건 로드", len(existing))

    existing_keys = set()
    if not existing.empty:
        existing_keys = set(
            existing["code"] + "_" + existing["year"].astype(str)
        )

    results = list(existing.to_dict("records")) if not existing.empty else []
    api_calls = 0
    success = 0
    skip = 0
    fail = 0
    total = len(target_codes) * len(years)

    log.info("수집 시작: %d종목 × %d년 = 최대 %d건",
             len(target_codes), len(years), total)

    for yi, year in enumerate(years):
        for ci, code in enumerate(sorted(target_codes)):
            key = f"{code}_{year}"
            if key in existing_keys:
                skip += 1
                continue

            corp_code = corp_map.get(code)
            if not corp_code:
                fail += 1
                continue

            result = fetch_holder(corp_code, str(year), REPRT_ANNUAL)
            api_calls += 1

            # 사업보고서 없으면 3분기 시도
            if result is None:
                result = fetch_holder(corp_code, str(year), REPRT_3Q)
                api_calls += 1

            if result is not None:
                results.append({
                    "code": code,
                    "year": year,
                    "total_pct": result["total_pct"],
                    "holder_name": result["holder_name"],
                    "holder_count": result["holder_count"],
                    "source": "dart_hyslr",
                })
                success += 1
            else:
                fail += 1

            # 진행 로그 (200건마다)
            done = skip + success + fail
            if done % 200 == 0:
                log.info("  진행: %d/%d (성공 %d, 스킵 %d, 실패 %d, API호출 %d)",
                         done, total, success, skip, fail, api_calls)

            # 1000건마다 중간 저장
            if success > 0 and success % 1000 == 0:
                _save(results)
                log.info("  중간 저장: %d건", len(results))

    # 최종 저장
    _save(results)
    log.info("="*50)
    log.info("수집 완료!")
    log.info("  성공: %d, 스킵(기존): %d, 실패: %d", success, skip, fail)
    log.info("  API 호출: %d건", api_calls)
    log.info("  저장: %s (%d건)", OUTPUT_CSV, len(results))

    return pd.DataFrame(results)


def _save(results: list):
    """CSV 저장"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(results)
    if not df.empty:
        df["code"] = df["code"].astype(str).str.zfill(6)
        df = df.drop_duplicates(subset=["code", "year"], keep="last")
        df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")


def check_status():
    """수집 결과 요약"""
    if not OUTPUT_CSV.exists():
        print("수집 결과 없음 — 먼저 수집 실행 필요")
        return

    df = pd.read_csv(OUTPUT_CSV, dtype={"code": str})
    print(f"\n{'='*50}")
    print(f"대주주 지분율 수집 현황")
    print(f"{'='*50}")
    print(f"총 건수: {len(df)}")
    print(f"종목 수: {df['code'].nunique()}")
    print(f"연도: {sorted(df['year'].unique())}")

    print(f"\n지분율 분포:")
    bins = [0, 10, 20, 30, 40, 50, 60, 70, 80, 100]
    df["bucket"] = pd.cut(df["total_pct"], bins=bins, right=False)
    dist = df["bucket"].value_counts().sort_index()
    for bucket, count in dist.items():
        print(f"  {bucket}: {count}개 ({count/len(df)*100:.1f}%)")

    print(f"\n평균 지분율: {df['total_pct'].mean():.1f}%")
    print(f"중앙값: {df['total_pct'].median():.1f}%")

    # buy_signals 매칭률
    signal_codes = get_signal_codes()
    holder_codes = set(df["code"].str.zfill(6))
    matched = signal_codes & holder_codes
    print(f"\nbuy_signals 종목: {len(signal_codes)}개")
    print(f"지분 데이터 있는 종목: {len(matched)}개 ({len(matched)/len(signal_codes)*100:.1f}%)")
    print(f"지분 데이터 없는 종목: {len(signal_codes - holder_codes)}개")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DART 대주주 지분율 수집")
    parser.add_argument("--year", type=int, nargs="+",
                        default=[2024, 2023],
                        help="수집 연도 (기본: 2024 2023)")
    parser.add_argument("--signals-only", action="store_true",
                        help="buy_signals 종목만 수집 (빠름)")
    parser.add_argument("--no-resume", action="store_true",
                        help="기존 결과 무시하고 처음부터")
    parser.add_argument("--check", action="store_true",
                        help="수집 결과 확인만")
    args = parser.parse_args()

    if not DART_API_KEY:
        print("❌ .env에 DART_API_KEY가 없습니다")
        sys.exit(1)

    if args.check:
        check_status()
    else:
        collect(
            years=args.year,
            signals_only=args.signals_only,
            resume=not args.no_resume,
        )
        check_status()
