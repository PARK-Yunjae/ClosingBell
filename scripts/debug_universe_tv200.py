#!/usr/bin/env python
"""
TV200 조건검색 유니버스 디버그 스크립트

사용법:
    python scripts/debug_universe_tv200.py
    python scripts/debug_universe_tv200.py --condition "TV200"
    python scripts/debug_universe_tv200.py --user-id "YOUR_HTS_ID"

환경변수:
    KIS_HTS_ID 또는 hts_id: HTS 사용자 ID (필수)
    CONDITION_NAME: 조건검색식 이름 (기본: TV200)
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime
from collections import Counter

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.adapters.kis_client import get_kis_client
from src.utils.stock_filters import (
    filter_universe_stocks,
    is_eligible_universe_stock,
    get_exclusion_stats,
    EXCLUDE_KEYWORDS,
)
from src.domain.models import StockInfo

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)


def print_header(title: str):
    """섹션 헤더 출력"""
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)


def print_stock_list(stocks: list, title: str, limit: int = 30):
    """종목 리스트 출력"""
    print_header(title)
    if not stocks:
        print("  (없음)")
        return
    
    for i, stock in enumerate(stocks[:limit], 1):
        if isinstance(stock, StockInfo):
            print(f"  {i:3d}. {stock.name:20s} ({stock.code}) [{stock.market}]")
        elif isinstance(stock, tuple) and len(stock) >= 2:
            s, reason = stock[0], stock[1]
            print(f"  {i:3d}. {s.name:20s} ({s.code}) - {reason}")
        else:
            print(f"  {i:3d}. {stock}")
    
    if len(stocks) > limit:
        print(f"  ... 외 {len(stocks) - limit}개 더")


def main():
    parser = argparse.ArgumentParser(description="TV200 조건검색 유니버스 디버그")
    parser.add_argument(
        "--condition", "-c",
        default=os.getenv("CONDITION_NAME", "TV200"),
        help="조건검색식 이름 (기본: TV200)",
    )
    parser.add_argument(
        "--user-id", "-u",
        default=os.getenv("KIS_HTS_ID") or os.getenv("hts_id"),
        help="HTS 사용자 ID",
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=30,
        help="출력할 종목 수 (기본: 30)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="상세 출력",
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # 설정 확인
    print_header("설정 확인")
    print(f"  조건검색식: {args.condition}")
    print(f"  HTS User ID: {args.user_id or '(미설정)'}")
    print(f"  제외 키워드: {len(EXCLUDE_KEYWORDS)}개")
    print(f"  실행 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if not args.user_id:
        print("\n[에러] HTS 사용자 ID가 설정되지 않았습니다.")
        print("  환경변수 KIS_HTS_ID 또는 --user-id 옵션을 설정하세요.")
        return 1
    
    # KIS 클라이언트 초기화
    try:
        client = get_kis_client()
        print("\n  KIS 클라이언트 초기화 완료")
    except Exception as e:
        print(f"\n[에러] KIS 클라이언트 초기화 실패: {e}")
        return 1
    
    # ============================================================
    # 1. 조건검색식 목록 조회
    # ============================================================
    print_header("조건검색식 목록")
    conditions = client.get_condition_list(args.user_id)
    
    if not conditions:
        print("  조건검색식이 없거나 조회에 실패했습니다.")
        print("  HTS에서 조건검색식을 먼저 등록하세요.")
        return 1
    
    for cond in conditions:
        marker = " <--" if cond["name"] == args.condition else ""
        print(f"  seq={cond['seq']:3s}: {cond['name']}{marker}")
    
    # 타겟 조건검색식 확인
    target_cond = next((c for c in conditions if c["name"] == args.condition), None)
    if not target_cond:
        print(f"\n[에러] 조건검색식 '{args.condition}'을 찾을 수 없습니다.")
        return 1
    
    # ============================================================
    # 2. 조건검색 결과 조회 (Raw)
    # ============================================================
    print_header(f"조건검색 결과 (Raw): {args.condition}")
    
    stocks_raw = client.get_condition_universe(
        condition_name=args.condition,
        user_id=args.user_id,
        limit=500,
        fetch_names=True,
    )
    
    print(f"  총 {len(stocks_raw)}개 종목 조회됨")
    
    if stocks_raw:
        print(f"\n  상위 {min(args.limit, len(stocks_raw))}개:")
        for i, stock in enumerate(stocks_raw[:args.limit], 1):
            print(f"    {i:3d}. {stock.name:20s} ({stock.code}) [{stock.market}]")
        
        if len(stocks_raw) > args.limit:
            print(f"    ... 외 {len(stocks_raw) - args.limit}개 더")
    
    # ============================================================
    # 3. 2차 필터 적용
    # ============================================================
    print_header("2차 필터 적용 결과")
    
    eligible_stocks, filter_result = filter_universe_stocks(stocks_raw, log_details=False)
    
    print(f"  Raw 종목 수: {filter_result.raw_count}개")
    print(f"  적격 종목 수: {filter_result.eligible_count}개")
    print(f"  제외 종목 수: {filter_result.excluded_count}개")
    print(f"\n  제외 사유별 집계:")
    for reason, count in sorted(filter_result.reason_counts.items(), key=lambda x: -x[1]):
        print(f"    - {reason}: {count}개")
    
    # 적격 종목 출력
    print_stock_list(eligible_stocks, f"적격 종목 (상위 {args.limit}개)", args.limit)
    
    # ============================================================
    # 4. 제외된 종목 상세
    # ============================================================
    excluded_stocks = []
    for stock in stocks_raw:
        eligible, reason = is_eligible_universe_stock(stock.code, stock.name)
        if not eligible:
            excluded_stocks.append((stock, reason))
    
    print_stock_list(excluded_stocks, f"제외된 종목 (상위 {args.limit}개)", args.limit)
    
    # ============================================================
    # 5. 제외 사유별 분류
    # ============================================================
    stats = get_exclusion_stats(stocks_raw)
    
    print_header("제외 사유별 상세 분류")
    for category, items in stats.items():
        if category == "eligible":
            continue
        print(f"\n  [{category}] - {len(items)}개")
        for stock in items[:10]:
            print(f"    - {stock.name} ({stock.code})")
        if len(items) > 10:
            print(f"    ... 외 {len(items) - 10}개 더")
    
    # ============================================================
    # 6. 총계 요약
    # ============================================================
    print_header("총계 요약")
    print(f"  조건검색 결과 (raw):     {len(stocks_raw):4d}개")
    print(f"  2차 필터 후 (eligible):  {len(eligible_stocks):4d}개")
    print(f"  제외됨 (excluded):       {len(excluded_stocks):4d}개")
    
    if filter_result.reason_counts:
        print(f"\n  제외 사유: {dict(filter_result.reason_counts)}")
    
    # 인버스/레버리지 체크
    inverse_count = sum(
        1 for s in stocks_raw
        if any(kw in (s.name or "").upper() for kw in ["인버스", "레버", "2X", "3X"])
    )
    if inverse_count > 0:
        print(f"\n  ⚠️ 인버스/레버리지 종목 발견: {inverse_count}개")
        print("     -> 2차 필터로 제외됨 ✓")
    
    print("\n" + "=" * 60)
    print(" 완료")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
