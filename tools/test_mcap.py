"""시총 수집 테스트 (Step 3)
사용: python tools/test_mcap.py
"""
import sys, os
sys.path.insert(0, os.getcwd())

from src.services.company_service import fetch_naver_finance

test_codes = [
    ("005930", "삼성전자"),    # 대형주
    ("150840", "인트로메딕"),  # 소형주
    ("263050", "유틸렉스"),    # 최근 유목민
]

passed = 0
for code, name in test_codes:
    print(f"\n{'='*40}")
    print(f"테스트: {name} ({code})")
    
    info = fetch_naver_finance(code)
    
    mcap = info.get("market_cap")
    per = info.get("per")
    pbr = info.get("pbr")
    
    if mcap and mcap > 0:
        if mcap >= 10000:
            mcap_str = f"{mcap/10000:.1f}조"
        else:
            mcap_str = f"{mcap:,.0f}억"
        print(f"  시총: {mcap_str}")
        print(f"  PER: {per}, PBR: {pbr}")
        print(f"  수집 항목: {len([v for v in info.values() if v is not None])}개")
        print(f"  ✅ 정상")
        passed += 1
    else:
        print(f"  ⚠️ 시총 없음")
        print(f"  수집된 키: {list(info.keys())}")
        # 원본 HTML 디버깅
        try:
            import re
            from src.services.company_service import fetch_html, BASE_URL
            url = f"{BASE_URL}/item/coinfo.naver?code={code}"
            html = fetch_html(url)
            if html:
                m = re.search(r'_market_sum.{0,150}', html, re.DOTALL)
                if m:
                    print(f"  HTML: {repr(m.group()[:100])}")
                else:
                    print(f"  _market_sum ID 없음")
                    # 시가총액 텍스트 검색
                    m2 = re.search(r'시가총액.{0,100}', html)
                    if m2:
                        print(f"  시가총액 근처: {repr(m2.group()[:80])}")
            else:
                print(f"  HTML 가져오기 실패")
        except Exception as e:
            print(f"  디버깅 실패: {e}")

print(f"\n{'='*40}")
print(f"결과: {passed}/{len(test_codes)} 통과")
if passed == len(test_codes):
    print("✅ 시총 수집 정상 → Step 4(백필)로 진행")
elif passed > 0:
    print("🟡 일부 통과 → 실패 종목 HTML 디버깅 결과 확인 후 진행")
else:
    print("❌ 전부 실패 → 네이버 크롤링 패턴 변경 가능성")
