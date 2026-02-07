"""ClosingBell v9.1 눌림목 스캐너 테스트

사용법:
    python test_pullback.py           # 전체 테스트
    python test_pullback.py --db      # DB 마이그레이션만
    python test_pullback.py --spike   # 거래량 폭발 스캔
    python test_pullback.py --pull    # 눌림목 시그널 스캔
    python test_pullback.py --dash    # 대시보드 import 검증
    python test_pullback.py --enrich  # 섹터/뉴스/기업 enrichment
"""

import sys
import os

# 프로젝트 루트 경로
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"
results = []


def log(status, msg):
    results.append((status, msg))
    print(f"  {status} {msg}")


# ============================================================
# 테스트 함수들
# ============================================================

def test_db_migration():
    """1. DB 마이그레이션 테스트"""
    print("\n═══ 1. DB 마이그레이션 ═══")
    try:
        from src.infrastructure.database import get_database
        db = get_database()

        # 테이블 없으면 자동 생성
        db.run_migration_v91_pullback()

        tables = db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('volume_spikes', 'pullback_signals')"
        )
        table_names = [t['name'] for t in tables]

        if 'volume_spikes' in table_names:
            log(PASS, "volume_spikes 테이블 존재")
        else:
            log(FAIL, "volume_spikes 테이블 없음")

        if 'pullback_signals' in table_names:
            log(PASS, "pullback_signals 테이블 존재")
        else:
            log(FAIL, "pullback_signals 테이블 없음")

        # 컬럼 확인
        if 'volume_spikes' in table_names:
            cols = db.fetch_all("PRAGMA table_info(volume_spikes)")
            col_names = [c['name'] for c in cols]
            for required in ['stock_code', 'spike_date', 'spike_volume', 'high_price', 'status', 'sector']:
                if required in col_names:
                    log(PASS, f"  volume_spikes.{required} OK")
                else:
                    log(FAIL, f"  volume_spikes.{required} 없음")

        if 'pullback_signals' in table_names:
            cols = db.fetch_all("PRAGMA table_info(pullback_signals)")
            col_names = [c['name'] for c in cols]
            for required in ['stock_code', 'signal_date', 'vol_decrease_pct', 'ma_support', 'signal_strength', 'sector', 'has_recent_news']:
                if required in col_names:
                    log(PASS, f"  pullback_signals.{required} OK")
                else:
                    log(FAIL, f"  pullback_signals.{required} 없음")

    except Exception as e:
        log(FAIL, f"DB 연결 실패: {e}")
        import traceback
        traceback.print_exc()


def test_repository():
    """2. Repository 테스트"""
    print("\n═══ 2. Repository ═══")
    try:
        from src.infrastructure.repository import get_pullback_repository
        repo = get_pullback_repository()
        log(PASS, "PullbackRepository 생성 OK")

        spikes = repo.get_recent_spikes(days=7)
        log(PASS, f"get_recent_spikes: {len(spikes)}개")

        signals = repo.get_recent_signals(days=7)
        log(PASS, f"get_recent_signals: {len(signals)}개")

    except Exception as e:
        log(FAIL, f"Repository 실패: {e}")
        import traceback
        traceback.print_exc()


def test_volume_spike_scan():
    """3. 거래량 폭발 스캔 테스트"""
    print("\n═══ 3. 거래량 폭발 스캔 ═══")
    try:
        from src.services.pullback_scanner import scan_volume_spikes, _get_all_codes, _load_ohlcv

        codes = _get_all_codes()
        log(PASS if codes else WARN, f"OHLCV 파일: {len(codes)}개 종목")

        if not codes:
            log(WARN, "OHLCV 파일 없음 → 스킵")
            return

        sample = codes[0]
        df = _load_ohlcv(sample)
        if df is not None:
            log(PASS, f"샘플 로드 ({sample}): {len(df)}일")
        else:
            log(WARN, f"샘플 로드 ({sample}) 실패")

        from datetime import date
        spikes = scan_volume_spikes(target_date=date.today())
        log(PASS, f"오늘 거래량 폭발: {len(spikes)}개")
        for s in spikes[:3]:
            sector_tag = f" [{s.sector}]" if s.sector else ""
            print(f"    📊 {s.stock_name}({s.stock_code}){sector_tag} | {s.spike_volume:,}주 | {s.spike_ratio:.1f}배 | {s.change_pct:+.1f}%")

    except Exception as e:
        log(FAIL, f"폭발 스캔 실패: {e}")
        import traceback
        traceback.print_exc()


def test_pullback_scan():
    """4. 눌림목 시그널 스캔 테스트"""
    print("\n═══ 4. 눌림목 시그널 스캔 ═══")
    try:
        from src.services.pullback_scanner import scan_pullback_signals
        from src.infrastructure.repository import get_pullback_repository
        from datetime import date

        repo = get_pullback_repository()
        active = repo.get_active_spikes(date.today(), watch_days=3)
        log(PASS, f"감시풀: {len(active)}개 종목")

        if not active:
            log(WARN, "감시풀 비어있음 → --spike 먼저 실행")
            return

        for a in active:
            r = dict(a) if not isinstance(a, dict) else a
            print(f"    🔥 {r.get('stock_name')}({r.get('stock_code')}) | {r.get('spike_date')} | {int(r.get('spike_volume', 0)):,}주")

        signals = scan_pullback_signals(target_date=date.today())
        log(PASS, f"오늘 눌림목 시그널: {len(signals)}개")
        for s in signals[:3]:
            print(f"    📉 {s.stock_name}({s.stock_code}) | D+{s.days_after} | 거감{s.vol_decrease_pct*100:.0f}% | {s.ma_support} | {s.signal_strength}")
            if s.sector:
                print(f"       섹터: {s.sector} | 뉴스: {s.has_recent_news}")

    except Exception as e:
        log(FAIL, f"눌림목 스캔 실패: {e}")
        import traceback
        traceback.print_exc()


def test_live_ohlcv():
    """5. 실시간 OHLCV 로딩 테스트"""
    print("\n═══ 5. 실시간 OHLCV (키움 API) ═══")
    try:
        from src.services.pullback_scanner import _load_ohlcv_live

        df = _load_ohlcv_live("005930", days=30)
        if df is not None and len(df) > 0:
            last = df.iloc[-1]
            log(PASS, f"삼성전자: {len(df)}일 | 최신={last['date']} | 종가={last['close']:,.0f}")
        else:
            log(WARN, "삼성전자 로드 실패 (키움 미연결?)")

    except Exception as e:
        log(WARN, f"실시간 OHLCV 실패 (키움 미연결 시 정상): {e}")


def test_dashboard_imports():
    """6. 대시보드 import 검증"""
    print("\n═══ 6. 대시보드 Import ═══")

    files = [
        "dashboard/pages/7_pullback.py",
        "dashboard/pages/5_stock_analysis.py",
        "dashboard/pages/4_broker_flow.py",
        "dashboard/pages/6_holdings_watch.py",
        "dashboard/components/sidebar.py",
    ]

    for f in files:
        path = os.path.join(ROOT, f)
        if os.path.exists(path):
            try:
                import py_compile
                py_compile.compile(path, doraise=True)
                log(PASS, f"{f} 컴파일 OK")
            except py_compile.PyCompileError as e:
                log(FAIL, f"{f} 컴파일 실패: {e}")
        else:
            log(FAIL, f"{f} 파일 없음")

    try:
        sys.path.insert(0, os.path.join(ROOT, "dashboard"))
        from components.sidebar import NAV_ITEMS
        has_pullback = any("pullback" in item[0] for item in NAV_ITEMS)
        log(PASS if has_pullback else FAIL, f"사이드바 눌림목: {'있음' if has_pullback else '없음'}")
    except Exception as e:
        log(FAIL, f"사이드바 확인 실패: {e}")


def test_discord_format():
    """7. 디스코드 Embed 포맷 테스트"""
    print("\n═══ 7. 디스코드 Embed 포맷 ═══")
    try:
        from src.services.pullback_scanner import PullbackSignal

        sig = PullbackSignal(
            stock_code="011930", stock_name="신성이엔지",
            spike_date="2026-02-05", signal_date="2026-02-07",
            days_after=2, close_price=2205, open_price=2300,
            spike_high=2245, drop_from_high_pct=1.8,
            today_volume=500000, spike_volume=34653386,
            vol_decrease_pct=0.014, ma5=2180, ma20=1950,
            ma_support="5일선", ma_distance_pct=1.1,
            is_negative_candle=True, signal_strength="강",
            sector="반도체장비", is_leading_sector=True,
            has_recent_news=True,
            reason="거래량 99% 급감 | 5일선 지지 | 🔥반도체장비 | 📰재료살아있음",
        )

        strength_emoji = {"강": "🔴"}.get(sig.signal_strength, "⚪")
        field_value = (
            f"종가 {sig.close_price:,.0f}원 | 고점대비 -{sig.drop_from_high_pct:.1f}%\n"
            f"거래량 폭발일의 {sig.vol_decrease_pct*100:.0f}% | {sig.ma_support} 지지\n"
            f"D+{sig.days_after} | 폭발일: {sig.spike_date}\n"
            f"{'🔥' if sig.is_leading_sector else '📂'}{sig.sector} | 📰재료살아있음"
        )

        log(PASS, "Embed 생성 OK")
        print(f"    {strength_emoji} {sig.stock_name} ({sig.stock_code})")
        for line in field_value.split('\n'):
            print(f"    > {line}")

    except Exception as e:
        log(FAIL, f"Embed 포맷 실패: {e}")


def test_enrichment():
    """8. 재료/섹터/뉴스 Enrichment 테스트"""
    print("\n═══ 8. Enrichment (섹터/뉴스/기업) ═══")

    # 섹터 조회
    try:
        from src.services.pullback_scanner import _enrich_sector
        sector, is_leading = _enrich_sector("011930")
        log(PASS if sector else WARN, f"신성이엔지 섹터: '{sector}' | 주도: {is_leading}")

        sector2, _ = _enrich_sector("264850")
        log(PASS if sector2 else WARN, f"이랜시스 섹터: '{sector2}'")
    except Exception as e:
        log(FAIL, f"섹터 조회 실패: {e}")
        import traceback
        traceback.print_exc()

    # 뉴스 조회
    try:
        from src.services.pullback_scanner import _check_recent_news
        has_news, headline = _check_recent_news("신성이엔지", days=7)
        log(PASS if has_news else WARN, f"신성이엔지 뉴스: {has_news} | {headline[:40] if headline else '-'}")

        has_news2, headline2 = _check_recent_news("이랜시스", days=7)
        log(PASS if has_news2 else WARN, f"이랜시스 뉴스: {has_news2} | {headline2[:40] if headline2 else '-'}")
    except Exception as e:
        log(WARN, f"뉴스 조회 실패 (네이버 API키 미설정 시 정상): {e}")

    # 기업 프로필
    try:
        from src.services.pullback_scanner import _get_company_summary
        info = _get_company_summary("011930")
        log(PASS if info else WARN, f"신성이엔지 프로필: {info or '(DART 캐시 없음)'}")

        info2 = _get_company_summary("264850")
        log(PASS if info2 else WARN, f"이랜시스 프로필: {info2 or '(DART 캐시 없음)'}")
    except Exception as e:
        log(WARN, f"기업 프로필 실패: {e}")


# ============================================================
# 결과 요약
# ============================================================

def print_summary():
    print("\n" + "═" * 50)
    total = len(results)
    passed = sum(1 for s, _ in results if s == PASS)
    failed = sum(1 for s, _ in results if s == FAIL)
    warned = sum(1 for s, _ in results if s == WARN)

    print(f"총 {total}개 | {PASS} {passed} 통과 | {FAIL} {failed} 실패 | {WARN} {warned} 경고")

    if failed:
        print(f"\n실패 항목:")
        for s, m in results:
            if s == FAIL:
                print(f"  {FAIL} {m}")
    print()


# ============================================================
# 메인
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("ClosingBell v9.1 눌림목 스캐너 테스트")
    print("=" * 50)

    arg = sys.argv[1] if len(sys.argv) > 1 else "--all"

    if arg in ("--all", "--db"):
        test_db_migration()
    if arg in ("--all", "--db"):
        test_repository()
    if arg in ("--all", "--spike"):
        test_volume_spike_scan()
    if arg in ("--all", "--pull"):
        test_pullback_scan()
    if arg in ("--all", "--live"):
        test_live_ohlcv()
    if arg in ("--all", "--dash"):
        test_dashboard_imports()
    if arg in ("--all", "--enrich"):
        test_enrichment()
    if arg in ("--all",):
        test_discord_format()

    print_summary()