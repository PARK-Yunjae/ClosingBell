#!/usr/bin/env python
"""
실전 스모크 실행 스크립트 (15:00 기다리지 않고 즉시 1회 실행)

사용법:
    python scripts/run_now.py                   # 즉시 1회 실행 (Discord + DB)
    python scripts/run_now.py --no-db           # DB 저장 없이 실행
    python scripts/run_now.py --no-alert        # 알림 없이 실행 (테스트용)
    python scripts/run_now.py --test            # 완전 테스트 모드 (알림/DB 없음)
    python scripts/run_now.py --preview         # 프리뷰 모드 (12:30)

이 스크립트의 목적:
- 15:00을 기다리지 않고 지금 즉시 스크리닝 실행
- Discord 웹훅이 실제로 발송되는지 확인
- DB에 결과가 저장되는지 확인
- 조건검색 유니버스가 정상 작동하는지 확인
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime, date

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

# 로깅 먼저 설정
from src.infrastructure.logging_config import init_logging
init_logging()

logger = logging.getLogger(__name__)


def print_banner():
    """실행 배너 출력"""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║   🚀  즉시 실행 스크립트 (run_now.py)                       ║
║                                                              ║
║   15:00 메인 스크리닝과 동일한 로직을 즉시 실행합니다.      ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(banner)


def print_config():
    """현재 설정 출력"""
    print("\n📋 현재 설정:")
    print("-" * 50)
    
    universe_source = os.getenv("UNIVERSE_SOURCE", "condition_search")
    condition_name = os.getenv("CONDITION_NAME", "TV200")
    hts_id = os.getenv("KIS_HTS_ID") or os.getenv("hts_id", "(미설정)")
    min_trading = os.getenv("MIN_TRADING_VALUE", "300")
    fallback = os.getenv("FALLBACK_ENABLED", "true")
    discord_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    
    print(f"  • 유니버스 소스: {universe_source}")
    print(f"  • 조건검색식: {condition_name}")
    print(f"  • HTS ID: {hts_id}")
    print(f"  • 최소 거래대금: {min_trading}억")
    print(f"  • Fallback: {fallback}")
    print(f"  • Discord 웹훅: {'설정됨' if discord_url else '❌ 미설정'}")
    print(f"  • 실행 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 50)


def run_screening_now(
    send_alert: bool = True,
    save_to_db: bool = True,
    is_preview: bool = False,
) -> dict:
    """즉시 스크리닝 실행"""
    from src.infrastructure.database import init_database
    from src.services.screener_service import run_screening
    
    # DB 초기화
    init_database()
    
    screen_time = "12:30" if is_preview else "15:00"
    
    logger.info(f"스크리닝 시작: {screen_time} 모드")
    logger.info(f"  - Discord 알림: {'예' if send_alert else '아니오'}")
    logger.info(f"  - DB 저장: {'예' if save_to_db else '아니오'}")
    logger.info(f"  - 프리뷰: {'예' if is_preview else '아니오'}")
    
    # 스크리닝 실행
    result = run_screening(
        screen_time=screen_time,
        save_to_db=save_to_db,
        send_alert=send_alert,
        is_preview=is_preview,
    )
    
    return result


def print_result(result):
    """결과 출력"""
    print(f"\n{'='*60}")
    print(f"📊 스크리닝 결과")
    print(f"{'='*60}")
    print(f"📅 날짜: {result.screen_date}")
    print(f"⏰ 시간: {result.screen_time}")
    print(f"📈 상태: {result.status.value}")
    print(f"📋 분석 종목: {result.total_count}개")
    print(f"⏱️ 실행 시간: {result.execution_time_sec:.1f}초")
    
    if result.top3:
        print(f"\n🏆 TOP {len(result.top3)}")
        print("-" * 50)
        for stock in result.top3:
            print(f"\n{stock.rank}위: {stock.stock_name} ({stock.stock_code})")
            print(f"   💰 현재가: {stock.current_price:,}원 ({stock.change_rate:+.2f}%)")
            print(f"   📊 총점: {stock.score_total:.1f}점")
            print(f"      CCI값: {stock.score_cci_value:.1f} | CCI기울기: {stock.score_cci_slope:.1f}")
            print(f"      MA20기울기: {stock.score_ma20_slope:.1f} | 양봉품질: {stock.score_candle:.1f}")
            print(f"      상승률: {stock.score_change:.1f}")
            if hasattr(stock, 'raw_cci') and stock.raw_cci:
                print(f"   📈 원시값: CCI={stock.raw_cci:.1f}")
    else:
        print("\n❌ 적합한 종목이 없습니다.")
    
    if result.error_message:
        print(f"\n⚠️ 에러: {result.error_message}")
    
    print(f"\n{'='*60}")


def print_verification_checklist(result, send_alert: bool, save_to_db: bool):
    """검증 체크리스트 출력"""
    print("\n✅ 검증 체크리스트")
    print("-" * 50)
    
    # 1. 유니버스 조회
    universe_ok = result.total_count > 0
    print(f"  {'✅' if universe_ok else '❌'} 유니버스 조회: {result.total_count}개 종목")
    
    # 2. 점수 계산
    scoring_ok = result.total_count > 0 or result.status.value == "SUCCESS"
    print(f"  {'✅' if scoring_ok else '❌'} 점수 계산 완료")
    
    # 3. TOP3 선정
    top3_ok = len(result.top3) > 0
    print(f"  {'✅' if top3_ok else '⚠️'} TOP3 선정: {len(result.top3)}개")
    
    # 4. Discord 알림
    if send_alert:
        # 실제 발송 여부는 로그에서 확인 필요
        print(f"  ℹ️ Discord 알림 발송 시도됨 (로그 확인)")
    else:
        print(f"  ⏭️ Discord 알림 스킵됨 (--no-alert)")
    
    # 5. DB 저장
    if save_to_db:
        print(f"  ℹ️ DB 저장 시도됨 (로그 확인)")
    else:
        print(f"  ⏭️ DB 저장 스킵됨 (--no-db)")
    
    # 6. 에러 여부
    error_ok = result.error_message is None or result.error_message == ""
    if not error_ok:
        print(f"  ❌ 에러 발생: {result.error_message}")
    else:
        print(f"  ✅ 에러 없음")
    
    print("-" * 50)
    
    # 전체 결과
    all_ok = universe_ok and scoring_ok and error_ok
    if all_ok:
        print("\n🎉 스크리닝 성공! 15:00 실전 준비 완료.")
    else:
        print("\n⚠️ 일부 문제가 있습니다. 위 항목을 확인하세요.")


def main():
    parser = argparse.ArgumentParser(
        description="즉시 스크리닝 실행 (실전 스모크 테스트)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
    python scripts/run_now.py                   즉시 실행 (Discord + DB)
    python scripts/run_now.py --test            테스트 모드 (알림/DB 없음)
    python scripts/run_now.py --no-alert        알림 없이 실행
    python scripts/run_now.py --preview         프리뷰 모드 (12:30)
        """,
    )
    
    parser.add_argument(
        "--no-alert",
        action="store_true",
        help="Discord 알림 발송 안함",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="DB 저장 안함",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="완전 테스트 모드 (알림/DB 없음)",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="프리뷰 모드 (12:30)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="배너/설정 출력 생략",
    )
    
    args = parser.parse_args()
    
    # 테스트 모드
    if args.test:
        args.no_alert = True
        args.no_db = True
    
    send_alert = not args.no_alert
    save_to_db = not args.no_db
    
    # 배너 및 설정 출력
    if not args.quiet:
        print_banner()
        print_config()
    
    # 스크리닝 실행
    try:
        result = run_screening_now(
            send_alert=send_alert,
            save_to_db=save_to_db,
            is_preview=args.preview,
        )
        
        # 결과 출력
        print_result(result)
        
        # 검증 체크리스트
        if not args.quiet:
            print_verification_checklist(result, send_alert, save_to_db)
        
        # 종료 코드
        if result.status.value == "SUCCESS":
            return 0
        else:
            return 1
            
    except Exception as e:
        logger.error(f"실행 에러: {e}", exc_info=True)
        print(f"\n❌ 치명적 에러: {e}")
        print("\n🔍 트러블슈팅:")
        print("  1. .env 파일에 KIS_APP_KEY, KIS_APP_SECRET 설정 확인")
        print("  2. KIS_HTS_ID 설정 확인 (조건검색 사용 시)")
        print("  3. DISCORD_WEBHOOK_URL 설정 확인")
        print("  4. 인터넷 연결 확인")
        print("  5. logs/ 폴더의 로그 파일 확인")
        return 1


if __name__ == "__main__":
    sys.exit(main())
