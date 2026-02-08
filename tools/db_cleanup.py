#!/usr/bin/env python3
"""ClosingBell DB 진단 + 정리 도구 v10.1

사용:
    python tools/db_cleanup.py              # 진단만
    python tools/db_cleanup.py --fix        # 진단 + 휴장일 데이터 삭제
    python tools/db_cleanup.py --repair-mcap  # 시가총액 누락 복구 (네이버 금융)
    python tools/db_cleanup.py --fix --repair-mcap  # 전부
"""

import sys
import os
from pathlib import Path
from datetime import date, timedelta

# 프로젝트 루트
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import settings
from src.infrastructure.database import get_database, init_database
from src.utils.market_calendar import is_market_open

DO_FIX = "--fix" in sys.argv
DO_REPAIR_MCAP = "--repair-mcap" in sys.argv


def main():
    print("=" * 60)
    print("🔧 ClosingBell DB 진단 도구")
    print(f"   DB: {settings.database.path}")
    print(f"   모드: {'수정' if DO_FIX else '진단만'}" + (" + 시총복구" if DO_REPAIR_MCAP else ""))
    print("=" * 60)

    init_database()
    db = get_database()

    issues = 0

    # ═════════════════════════════════════════
    # 1. 휴장일 데이터 탐지
    # ═════════════════════════════════════════
    print("\n📋 1. 휴장일에 수집된 데이터 탐지")
    print("-" * 50)

    tables_date_col = {
        "closing_top5_history": "screen_date",
        "nomad_candidates": "study_date",
        "pullback_signals": "signal_date",
    }

    for table, col in tables_date_col.items():
        rows = db.fetch_all(
            f"SELECT DISTINCT {col} as d FROM {table} ORDER BY {col} DESC LIMIT 30"
        )
        holiday_dates = []
        for r in rows:
            d = date.fromisoformat(r["d"])
            if not is_market_open(d):
                weekday_kr = ['월','화','수','목','금','토','일'][d.weekday()]
                count = db.fetch_one(
                    f"SELECT COUNT(*) as cnt FROM {table} WHERE {col} = ?", (r["d"],)
                )["cnt"]
                holiday_dates.append((r["d"], weekday_kr, count))

        if holiday_dates:
            for hd, wd, cnt in holiday_dates:
                issues += 1
                print(f"  ⚠️ {table}.{col} = {hd} ({wd}) — {cnt}건")
                if DO_FIX:
                    db.execute(f"DELETE FROM {table} WHERE {col} = ?", (hd,))
                    print(f"     ✅ 삭제 완료")
        else:
            print(f"  ✅ {table}: 휴장일 데이터 없음")

    # ═════════════════════════════════════════
    # 2. 최근 데이터 연속성 확인
    # ═════════════════════════════════════════
    print("\n📋 2. 최근 5 거래일 데이터 연속성")
    print("-" * 50)

    # 최근 5 거래일 구하기
    market_days = []
    d = date.today()
    for _ in range(20):
        if is_market_open(d):
            market_days.append(d)
            if len(market_days) >= 5:
                break
        d -= timedelta(days=1)

    for table, col in tables_date_col.items():
        missing = []
        for md in market_days:
            count = db.fetch_one(
                f"SELECT COUNT(*) as cnt FROM {table} WHERE {col} = ?",
                (md.isoformat(),)
            )["cnt"]
            if count == 0:
                weekday_kr = ['월','화','수','목','금','토','일'][md.weekday()]
                missing.append(f"{md}({weekday_kr})")

        if missing:
            issues += 1
            print(f"  ⚠️ {table}: 누락일 = {', '.join(missing)}")
        else:
            print(f"  ✅ {table}: 최근 5거래일 모두 있음")

    # ═════════════════════════════════════════
    # 3. TOP5 2/7 (토요일) 데이터 특별 확인
    # ═════════════════════════════════════════
    print("\n📋 3. 2026-02-07 (토요일) 데이터 확인")
    print("-" * 50)

    for table, col in tables_date_col.items():
        count = db.fetch_one(
            f"SELECT COUNT(*) as cnt FROM {table} WHERE {col} = '2026-02-07'"
        )["cnt"]
        if count > 0:
            issues += 1
            print(f"  ⚠️ {table}: {count}건 존재")
            if DO_FIX:
                db.execute(f"DELETE FROM {table} WHERE {col} = '2026-02-07'")
                print(f"     ✅ 삭제 완료")
        else:
            print(f"  ✅ {table}: 없음 (정상)")

    # top5_daily_prices도 확인
    count = db.fetch_one(
        "SELECT COUNT(*) as cnt FROM top5_daily_prices WHERE trade_date = '2026-02-07'"
    )["cnt"]
    if count > 0:
        issues += 1
        print(f"  ⚠️ top5_daily_prices: {count}건 존재")
        if DO_FIX:
            db.execute("DELETE FROM top5_daily_prices WHERE trade_date = '2026-02-07'")
            print(f"     ✅ 삭제 완료")
    else:
        print(f"  ✅ top5_daily_prices: 없음 (정상)")

    # ═════════════════════════════════════════
    # 4. 기업정보 + 시가총액 확인
    # ═════════════════════════════════════════
    print("\n📋 4. 유목민 종목 기업정보 누락 확인")
    print("-" * 50)

    try:
        recent_date = market_days[0].isoformat() if market_days else date.today().isoformat()
        nomad_stocks = db.fetch_all(
            "SELECT stock_code, stock_name, market_cap, company_info_collected "
            "FROM nomad_candidates WHERE study_date = ? LIMIT 10",
            (recent_date,)
        )

        if nomad_stocks:
            for s in nomad_stocks:
                code = s["stock_code"]
                name = s["stock_name"]
                cap = s["market_cap"]
                collected = s["company_info_collected"]
                
                if cap and cap > 0:
                    if cap >= 10000:
                        cap_str = f"{cap/10000:.1f}조"
                    else:
                        cap_str = f"{cap:,.0f}억"
                    print(f"  ✅ {name}({code}): 시총 {cap_str}")
                else:
                    issues += 1
                    info_status = "수집완료" if collected else "미수집"
                    print(f"  ⚠️ {name}({code}): 시총 누락 (기업정보: {info_status})")
        else:
            print(f"  ℹ️ {recent_date} 유목민 데이터 없음")
    except Exception as e:
        print(f"  ⚠️ 조회 실패: {e}")

    # ═════════════════════════════════════════
    # 5. 보유종목 + 심층분석 리포트 확인
    # ═════════════════════════════════════════
    print("\n📋 5. 보유종목 및 심층분석 리포트")
    print("-" * 50)

    try:
        holdings = db.fetch_all(
            "SELECT stock_code, stock_name, last_qty, status FROM holdings_watch ORDER BY last_seen DESC"
        )
        if holdings:
            report_dir = PROJECT_ROOT / "reports"
            
            for h in holdings:
                code = h["stock_code"]
                name = h["stock_name"]
                status = h["status"]
                qty = h["last_qty"]
                
                # reports/ 폴더에서 해당 종목 리포트 찾기
                report_files = sorted(
                    report_dir.glob(f"*_{code}.md"), 
                    key=lambda p: p.name, reverse=True
                ) if report_dir.exists() else []
                
                if report_files:
                    latest = report_files[0]
                    # 파일명에서 날짜 추출 (예: 20260206_090710.md)
                    rp_date = latest.stem.split("_")[0]
                    date_str = f"{rp_date[:4]}-{rp_date[4:6]}-{rp_date[6:]}" if len(rp_date) == 8 else rp_date
                    print(f"  ✅ {name}({code}) [{status}] {qty}주 → 리포트: {date_str}")
                else:
                    if status == 'holding':
                        issues += 1
                        print(f"  ⚠️ {name}({code}) [{status}] {qty}주 → 리포트 없음!")
                        print(f"     💡 수동 생성: python main.py --analysis {code}")
                    else:
                        print(f"  ℹ️ {name}({code}) [{status}] → 매도완료")
        else:
            print("  ℹ️ 보유종목 없음")
    except Exception as e:
        print(f"  ⚠️ 조회 실패: {e}")

    # ═════════════════════════════════════════
    # 6. 테이블 행 수 요약
    # ═════════════════════════════════════════
    print("\n📋 6. 테이블 행 수 요약")
    print("-" * 50)

    tables_to_check = [
        'closing_top5_history', 'top5_daily_prices',
        'nomad_candidates', 'nomad_news',
        'pullback_signals', 'holdings_watch', 'trade_journal',
    ]
    # 있으면 추가
    for extra in ['short_selling_daily', 'stock_lending_daily',
                   'support_resistance_cache', 'pullback_daily_prices',
                   'broker_signals']:
        try:
            db.fetch_one(f"SELECT COUNT(*) as cnt FROM {extra}")
            tables_to_check.append(extra)
        except Exception:
            pass

    for table in tables_to_check:
        try:
            count = db.fetch_one(f"SELECT COUNT(*) as cnt FROM {table}")["cnt"]
            print(f"  {table}: {count:,}건")
        except Exception:
            print(f"  {table}: (테이블 없음)")

    # ═════════════════════════════════════════
    # 7. 시총 복구 (--repair-mcap)
    # ═════════════════════════════════════════
    if DO_REPAIR_MCAP:
        print("\n📋 7. 시가총액 복구 (네이버 금융)")
        print("-" * 50)
        
        try:
            from src.services.company_service import fetch_naver_finance
            import time
            
            # market_cap이 NULL인 최근 종목 조회
            null_mcap = db.fetch_all(
                "SELECT id, stock_code, stock_name, study_date "
                "FROM nomad_candidates "
                "WHERE (market_cap IS NULL OR market_cap = 0) "
                "AND company_info_collected = 1 "
                "ORDER BY study_date DESC LIMIT 30"
            )
            
            if not null_mcap:
                print("  ✅ 시총 누락 종목 없음")
            else:
                # 중복 코드 제거 (같은 종목 여러 날짜)
                seen_codes = set()
                unique = []
                for r in null_mcap:
                    if r["stock_code"] not in seen_codes:
                        seen_codes.add(r["stock_code"])
                        unique.append(r)
                
                print(f"  📋 복구 대상: {len(unique)}개 종목 ({len(null_mcap)}건)")
                
                repaired = 0
                for i, r in enumerate(unique):
                    code = r["stock_code"]
                    name = r["stock_name"]
                    
                    print(f"  [{i+1}/{len(unique)}] {name}({code})...", end=" ")
                    
                    try:
                        info = fetch_naver_finance(code)
                        mcap = info.get('market_cap')
                        
                        if mcap and mcap > 0:
                            # 해당 종목의 모든 날짜 레코드 업데이트
                            db.execute(
                                "UPDATE nomad_candidates SET market_cap = ?, "
                                "market_cap_rank = ?, per = COALESCE(per, ?), "
                                "pbr = COALESCE(pbr, ?), roe = COALESCE(roe, ?), "
                                "foreign_rate = COALESCE(foreign_rate, ?) "
                                "WHERE stock_code = ? AND (market_cap IS NULL OR market_cap = 0)",
                                (mcap, info.get('market_cap_rank'),
                                 info.get('per'), info.get('pbr'), info.get('roe'),
                                 info.get('foreign_rate'), code)
                            )
                            
                            if mcap >= 10000:
                                mcap_str = f"{mcap/10000:.1f}조"
                            else:
                                mcap_str = f"{mcap:,.0f}억"
                            print(f"✅ 시총 {mcap_str}")
                            repaired += 1
                        else:
                            # 수집은 됐는데 시총이 없음 → 상장폐지/거래정지 가능성
                            has_any = any(v for v in info.values() if v is not None)
                            if has_any:
                                print(f"⚠️ 시총 없음 (거래정지/소형주?)")
                            else:
                                print(f"⚠️ 네이버 정보 없음 (상장폐지?)")
                        
                        time.sleep(0.5)
                    except Exception as e:
                        print(f"❌ {e}")
                
                print(f"\n  📊 복구: {repaired}/{len(unique)}개 종목")
        except ImportError as e:
            print(f"  ❌ 모듈 로드 실패: {e}")

    # 결과
    print(f"\n{'='*60}")
    if issues == 0:
        print("✅ 이슈 없음!")
    else:
        print(f"⚠️ {issues}개 이슈 발견" + (" → 수정 완료" if DO_FIX else " (--fix로 수정)"))
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
