"""수동 스크리닝 테스트 - ClosingBell 루트에서: python test_screening.py"""
import sys
sys.path.insert(0, '.')

from src.services.screener_service import ScreenerService

s = ScreenerService()
r = s.run_screening(screen_time='12:00', save_to_db=False, send_alert=False, is_preview=True)

print(f"\n{'='*60}")
print(f"종목수: {r['total_count']}, 필터후: {r.get('filtered_count',0)}")
print(f"{'='*60}")

for t in r['top_n']:
    mcap = getattr(t, '_market_cap', 0)
    broker = getattr(t, '_broker_adj', None)
    tag = f" {broker.tag}(+{broker.bonus})" if broker else ""
    print(f"  {t.stock_name:12s} {t.score_total:5.1f}점  시총={mcap:>10,}억{tag}")

ba = r.get('broker_adjustments', {})
print(f"\n거래원 이상감지: {len(ba)}개")
for code, adj in ba.items():
    print(f"  {code} → {adj.anomaly_score}점 {adj.tag}")

print("\n✅ 테스트 완료")
