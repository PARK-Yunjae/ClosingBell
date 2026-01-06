#!/usr/bin/env python
"""수동 스크리닝 실행

사용법:
    python scripts/manual_screening.py              # 기본 실행
    python scripts/manual_screening.py --all        # 전체 종목 리스트 출력
    python scripts/manual_screening.py --save       # DB에 저장
    python scripts/manual_screening.py --notify     # 디스코드 알림 발송
"""

import sys
import os
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

from src.services.screener_service import run_screening
from src.infrastructure.database import init_database


def main():
    parser = argparse.ArgumentParser(description='수동 스크리닝 실행')
    parser.add_argument('--all', action='store_true', help='전체 종목 리스트 출력')
    parser.add_argument('--save', action='store_true', help='결과를 DB에 저장')
    parser.add_argument('--notify', action='store_true', help='디스코드 알림 발송')
    parser.add_argument('--preview', action='store_true', help='프리뷰 모드 (12:30)')
    args = parser.parse_args()
    
    # DB 초기화
    init_database()
    
    print()
    print("=" * 70)
    print("🔔 종가매매 스크리너 - 수동 실행")
    print("=" * 70)
    print(f"📅 실행 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📊 옵션: {'전체출력 ' if args.all else ''}{'DB저장 ' if args.save else ''}{'알림발송 ' if args.notify else ''}{'프리뷰' if args.preview else '최종'}")
    print("=" * 70)
    print()
    
    # 스크리닝 실행
    screen_time = "12:30" if args.preview else "15:00"
    result = run_screening(
        screen_time=screen_time,
        save_to_db=args.save,
        send_alert=args.notify,
        is_preview=args.preview,
    )
    
    # 결과 출력
    print()
    print("=" * 70)
    print("🎯 스크리닝 결과")
    print("=" * 70)
    print(f"📅 {result.screen_date} {result.screen_time}")
    print(f"📊 분석 종목: {result.total_count}개")
    print(f"⏱️ 실행 시간: {result.execution_time_sec:.1f}초")
    print(f"📌 상태: {result.status.value}")
    print()
    
    # TOP 3 출력
    if result.top3:
        print("=" * 70)
        print("🏆 TOP 3")
        print("=" * 70)
        for stock in result.top3:
            print()
            print(f"  {stock.rank}위: {stock.stock_name} ({stock.stock_code})")
            print(f"  ────────────────────────────────────────")
            print(f"  💰 현재가: {stock.current_price:,}원 ({stock.change_rate:+.2f}%)")
            print(f"  💵 거래대금: {stock.trading_value:,.0f}억원")
            print(f"  📊 총점: {stock.score_total:.1f}점 / 50점")
            print(f"  ├─ CCI 값:      {stock.score_cci_value:5.1f}점 (CCI: {stock.raw_cci:+.1f})")
            print(f"  ├─ CCI 기울기:  {stock.score_cci_slope:5.1f}점")
            print(f"  ├─ MA20 기울기: {stock.score_ma20_slope:5.1f}점")
            print(f"  ├─ 양봉 품질:   {stock.score_candle:5.1f}점")
            print(f"  └─ 상승률:      {stock.score_change:5.1f}점")
    else:
        print("적합한 종목이 없습니다.")
    
    # 전체 종목 리스트 출력
    if args.all and result.all_items:
        print()
        print("=" * 70)
        print("📋 전체 종목 순위")
        print("=" * 70)
        print()
        print(f"{'순위':>4} {'종목명':<15} {'현재가':>10} {'등락률':>8} {'총점':>6} {'CCI값':>6} {'CCI기':>6} {'MA20':>6} {'양봉':>6} {'상승':>6}")
        print("-" * 100)
        
        for i, stock in enumerate(result.all_items, 1):
            print(f"{i:>4} {stock.stock_name:<15} {stock.current_price:>10,} {stock.change_rate:>+7.2f}% {stock.score_total:>6.1f} {stock.score_cci_value:>6.1f} {stock.score_cci_slope:>6.1f} {stock.score_ma20_slope:>6.1f} {stock.score_candle:>6.1f} {stock.score_change:>6.1f}")
            
            # 50개까지만 출력
            if i >= 50:
                remaining = len(result.all_items) - 50
                if remaining > 0:
                    print(f"  ... 외 {remaining}개 종목")
                break
    
    print()
    print("=" * 70)
    
    # 저장/알림 상태
    if args.save:
        print("✅ 결과가 DB에 저장되었습니다.")
    if args.notify:
        print("✅ 디스코드 알림이 발송되었습니다.")
    
    print()


if __name__ == "__main__":
    main()
