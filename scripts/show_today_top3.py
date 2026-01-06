#!/usr/bin/env python
"""오늘의 TOP 3 확인"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.basicConfig(level=logging.WARNING)

from src.services.screener_service import run_screening
from src.infrastructure.database import init_database

init_database()
result = run_screening(screen_time='15:00', save_to_db=False, send_alert=False, is_preview=False)

print()
print('='*60)
print('🎯 오늘의 종가매매 TOP 3')
print('='*60)
print(f'📅 {result.screen_date} {result.screen_time}')
print(f'📊 분석 종목: {result.total_count}개')
print(f'⏱️ 실행 시간: {result.execution_time_sec:.1f}초')
print()

if result.top3:
    for stock in result.top3:
        print(f'{stock.rank}위: {stock.stock_name} ({stock.stock_code})')
        print(f'   💰 현재가: {stock.current_price:,}원 ({stock.change_rate:+.2f}%)')
        print(f'   📊 총점: {stock.score_total:.1f}점 / 50점')
        print(f'   📈 CCI값: {stock.score_cci_value:.1f} | CCI기울기: {stock.score_cci_slope:.1f}')
        print(f'   📈 MA20기울기: {stock.score_ma20_slope:.1f} | 양봉품질: {stock.score_candle:.1f}')
        print(f'   📈 상승률: {stock.score_change:.1f}')
        print(f'   📉 Raw CCI: {stock.raw_cci:.1f}')
        print()
else:
    print('적합한 종목이 없습니다.')

print('='*60)
