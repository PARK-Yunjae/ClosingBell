"""
ka10081 일봉 vs ka10001 현재가 비교 진단
ClosingBell 루트에서: python debug_price.py
"""
import sys
sys.path.insert(0, '.')

from src.adapters.kiwoom_rest_client import get_kiwoom_client
from datetime import datetime

client = get_kiwoom_client()

# 삼영 (003720) 테스트
code = "003720"
print(f"{'='*60}")
print(f"삼영 ({code}) 가격 진단 - {datetime.now().strftime('%H:%M:%S')}")
print(f"{'='*60}")

# 1. ka10081 일봉 데이터
print(f"\n[ka10081 일봉 데이터 - 최근 5일]")
prices = client.get_daily_prices(code, count=10)
for i, p in enumerate(prices[:5]):
    marker = " ← daily_prices[0]" if i == 0 else ""
    marker = " ← daily_prices[-1] (=today)" if i == len(prices[:5]) - 1 else marker
    print(f"  [{i}] {p.date} | 시:{p.open} 고:{p.high} 저:{p.low} 종:{p.close} | 거래량:{p.volume:,}{marker}")

print(f"\n  총 {len(prices)}개 봉")
print(f"  prices[0]  = {prices[0].date} 종가 {prices[0].close}")
print(f"  prices[-1] = {prices[-1].date} 종가 {prices[-1].close}")

# 2. ka10001 현재가
print(f"\n[ka10001 현재가]")
current = client.get_current_price(code)
print(f"  현재가: {current.price}원")
print(f"  등락률: {current.change_rate}%")
print(f"  거래량: {current.volume:,}")
print(f"  시총: {current.market_cap:,}억")

# 3. 스크리닝에서 쓰는 값 시뮬레이션
print(f"\n[스크리닝 시뮬레이션]")
today_candle = prices[-1]   # screener_service.py L547
yest_candle = prices[-2]    # screener_service.py L548
calc_change = ((today_candle.close - yest_candle.close) / yest_candle.close) * 100

print(f"  today  = prices[-1]: {today_candle.date} 종가={today_candle.close}")
print(f"  yester = prices[-2]: {yest_candle.date} 종가={yest_candle.close}")
print(f"  계산된 등락률: {calc_change:+.1f}%")
print(f"  실제 등락률(ka10001): {current.change_rate}%")

if abs(today_candle.close - current.price) > 50:
    print(f"\n  ⚠️ 가격 불일치! 일봉={today_candle.close} vs 현재가={current.price} (차이: {current.price - today_candle.close}원)")
    print(f"  원인 추정: ka10081이 오늘 봉을 {'포함' if today_candle.date == datetime.now().strftime('%Y%m%d') else '미포함'}하고 있음")
else:
    print(f"\n  ✅ 가격 일치")
