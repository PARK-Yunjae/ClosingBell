"""
전체 스케줄 dry-run 테스트
ClosingBell 루트에서: python test_full_schedule.py

각 스케줄 작업을 Discord 알림 없이 테스트합니다.
"""
import sys, time, traceback
sys.path.insert(0, '.')

from datetime import datetime

def test_step(name, func):
    """각 작업을 테스트하고 결과 출력"""
    print(f"\n{'='*60}")
    print(f"🧪 [{name}] 테스트 시작...")
    print(f"{'='*60}")
    t0 = time.time()
    try:
        result = func()
        elapsed = time.time() - t0
        print(f"✅ [{name}] 성공 ({elapsed:.1f}초)")
        return True, result
    except Exception as e:
        elapsed = time.time() - t0
        print(f"❌ [{name}] 실패 ({elapsed:.1f}초): {e}")
        traceback.print_exc()
        return False, None


results = {}

# ── 1. 프리뷰 스크리닝 (12:00) ──
def test_preview():
    from src.services.screener_service import ScreenerService
    s = ScreenerService()
    r = s.run_screening(
        screen_time='12:00', 
        save_to_db=False, 
        send_alert=False,  # 디스코드 안 보냄
        is_preview=True
    )
    top_n = r.get('top_n', [])
    ba = r.get('broker_adjustments', {})
    print(f"  종목수: {r['total_count']}, Top5: {len(top_n)}개, 거래원이상: {len(ba)}개")
    for t in top_n[:3]:
        mcap = getattr(t, '_market_cap', 0)
        print(f"    {t.stock_name} {t.score_total:.1f}점 시총={mcap:,}억")
    return r

ok, _ = test_step("12:00 프리뷰 스크리닝", test_preview)
results['preview'] = ok


# ── 2. 메인 스크리닝 (15:00) ──
def test_main():
    from src.services.screener_service import ScreenerService
    s = ScreenerService()
    r = s.run_screening(
        screen_time='15:00',
        save_to_db=False,
        send_alert=False,
        is_preview=False
    )
    top_n = r.get('top_n', [])
    ba = r.get('broker_adjustments', {})
    print(f"  종목수: {r['total_count']}, Top5: {len(top_n)}개, 거래원이상: {len(ba)}개")
    for t in top_n[:3]:
        mcap = getattr(t, '_market_cap', 0)
        broker = getattr(t, '_broker_adj', None)
        tag = f" {broker.tag}" if broker else ""
        print(f"    {t.stock_name} {t.score_total:.1f}점 시총={mcap:,}억{tag}")
    return r

ok, _ = test_step("15:00 메인 스크리닝", test_main)
results['main'] = ok


# ── 3. 눌림목 스캔 (15:02) ──
def test_dip():
    from src.services.dip_scanner import DipScanner
    scanner = DipScanner()
    signals = scanner.run(send_discord=False)  # 디스코드 안 보냄
    print(f"  신호: {len(signals)}개")
    for s in signals[:3]:
        print(f"    {s.stock_name} 점수={s.total_score:.0f}")
    return signals

ok, _ = test_step("15:02 눌림목 스캔", test_dip)
results['dip'] = ok


# ── 4. Quiet Accumulation (15:05) ──
def test_quiet():
    from src.services.quiet_accumulation import QuietAccumulationScanner
    scanner = QuietAccumulationScanner(use_market_filter=False)  # 장중이라 필터 끔
    stocks = scanner.scan()
    print(f"  감지: {len(stocks)}개")
    for s in stocks[:3]:
        print(f"    {s.name} ({s.code}) {s.grade}")
    return stocks

ok, _ = test_step("15:05 Quiet Accumulation", test_quiet)
results['quiet'] = ok


# ── 5. import 테스트 (나머지 모듈) ──
def test_imports():
    imports_ok = []
    imports_fail = []
    
    modules = [
        ("learner_service", "from src.services.learner_service import LearnerService"),
        ("result_collector", "from src.services.result_collector import ResultCollector"),
        ("data_updater", "from src.services.data_updater import DataUpdater"),
        ("nomad_collector", "from src.services.nomad_collector import NomadCollector"),
        ("news_service", "from src.services.news_service import NewsService"),
        ("company_service", "from src.services.company_service import collect_company_info"),
        ("ai_pipeline", "from src.services.ai_pipeline import AIPipeline"),
        ("top5_pipeline", "from src.services.top5_pipeline import Top5Pipeline"),
        ("broker_signal", "from src.services.broker_signal import get_broker_adjustments"),
    ]
    
    for name, imp in modules:
        try:
            exec(imp)
            imports_ok.append(name)
        except Exception as e:
            imports_fail.append(f"{name}: {e}")
    
    print(f"  성공: {len(imports_ok)}개 - {', '.join(imports_ok)}")
    if imports_fail:
        print(f"  실패: {len(imports_fail)}개")
        for f in imports_fail:
            print(f"    ❌ {f}")
    return len(imports_fail) == 0

ok, _ = test_step("16:00~17:00 모듈 import", test_imports)
results['imports'] = ok


# ── 최종 결과 ──
print(f"\n{'='*60}")
print(f"📋 전체 테스트 결과")
print(f"{'='*60}")

all_ok = True
for name, ok in results.items():
    icon = "✅" if ok else "❌"
    print(f"  {icon} {name}")
    if not ok:
        all_ok = False

if all_ok:
    print(f"\n🎉 전체 통과! 3시 스케줄러 안심하고 돌리세요.")
else:
    print(f"\n⚠️ 실패 항목이 있습니다. 결과를 클로드에 보내주세요.")
