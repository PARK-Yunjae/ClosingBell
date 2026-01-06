#!/usr/bin/env python
"""디스코드 웹훅 테스트"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from src.adapters.discord_notifier import get_discord_notifier
from src.domain.models import (
    StockScore, ScoreDetail, ScreeningResult, ScreeningStatus
)

# 테스트용 더미 데이터 (이전 테스트 결과 기반)
test_stocks = [
    StockScore(
        stock_code="006800",
        stock_name="미래에셋증권",
        current_price=28700,
        change_rate=12.55,
        trading_value=4879.0,
        score_detail=ScoreDetail(
            cci_value=4.0,
            cci_slope=10.0,
            ma20_slope=5.0,
            candle=9.0,
            change=10.0,
            raw_cci=245.5,
            raw_ma20=22868,
        ),
        score_total=38.0,
        rank=1,
    ),
    StockScore(
        stock_code="000660",
        stock_name="SK하이닉스",
        current_price=185000,
        change_rate=5.12,
        trading_value=620.3,
        score_detail=ScoreDetail(
            cci_value=7.5,
            cci_slope=8.0,
            ma20_slope=7.5,
            candle=8.0,
            change=6.0,
            raw_cci=172.1,
            raw_ma20=175000,
        ),
        score_total=37.0,
        rank=2,
    ),
    StockScore(
        stock_code="005930",
        stock_name="삼성전자",
        current_price=71500,
        change_rate=3.25,
        trading_value=850.5,
        score_detail=ScoreDetail(
            cci_value=5.0,
            cci_slope=7.0,
            ma20_slope=8.0,
            candle=9.0,
            change=5.5,
            raw_cci=165.3,
            raw_ma20=70000,
        ),
        score_total=34.5,
        rank=3,
    ),
]

test_result = ScreeningResult(
    screen_date=date.today(),
    screen_time="15:00",
    total_count=15,
    top3=test_stocks,
    all_items=test_stocks,
    execution_time_sec=11.3,
    status=ScreeningStatus.SUCCESS,
)

print("=" * 60)
print("🔔 디스코드 웹훅 테스트")
print("=" * 60)
print()

notifier = get_discord_notifier()
print(f"웹훅 URL: {notifier.webhook_url[:50]}...")
print()

print("📤 알림 발송 중...")
result = notifier.send_screening_result(test_result, is_preview=False)

print()
print(f"✅ 발송 결과:")
print(f"   성공 여부: {result.success}")
print(f"   응답 코드: {result.response_code}")
if result.error_message:
    print(f"   에러: {result.error_message}")
print()
print("=" * 60)
