"""
종가매매 스크리너 - 메인 실행 파일

사용법:
    python main.py              # 스케줄러 모드 (12:30, 15:00, 16:30 자동 실행)
    python main.py --run        # 즉시 스크리닝 실행
    python main.py --run-test   # 테스트 실행 (알림 없음)
    python main.py --learn      # 수동 학습 실행
    python main.py --init-db    # DB 초기화만
    python main.py --validate   # 설정 검증만
"""

import sys
import argparse
import logging
from datetime import datetime

from src.config.settings import settings
from src.infrastructure.database import init_database
from src.infrastructure.scheduler import create_scheduler, is_market_open
from src.infrastructure.logging_config import init_logging
from src.config.validator import validate_settings, ConfigValidationError, print_settings_summary
from src.services.screener_service import (
    run_screening,
    run_main_screening,
    run_preview_screening,
)


def print_banner():
    """시작 배너 출력"""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   🔔  종가매매 스크리너 (Closing Trade Screener) v3.1          ║
║                                                              ║
║   - 거래대금 100억 이상 종목 필터링                              ║
║   - 거래량 100위 이상 종목 필터링                                ║
║   - 5가지 기술 지표 점수 산출                                    ║
║   - TOP 3 종목 선정 및 디스코드 알림                             ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """
    print(banner)


def run_scheduler_mode():
    """스케줄러 모드 실행"""
    logger = logging.getLogger(__name__)
    
    print_banner()
    logger.info("스케줄러 모드 시작")
    logger.info(f"프리뷰 시간: {settings.screening.screening_time_preview}")
    logger.info(f"메인 시간: {settings.screening.screening_time_main}")
    logger.info(f"오늘 장 운영: {'예' if is_market_open() else '아니오'}")
    
    # 스케줄러 생성 및 시작
    scheduler = create_scheduler(blocking=True)
    scheduler.start()


def run_immediate(send_alert: bool = True, save_to_db: bool = True):
    """즉시 실행 모드"""
    logger = logging.getLogger(__name__)
    
    print_banner()
    logger.info("즉시 실행 모드")
    
    # 현재 시간에 따라 프리뷰/메인 결정
    now = datetime.now()
    if now.hour < 13:
        logger.info("12:30 이전 - 프리뷰 모드로 실행")
        result = run_screening(
            screen_time="12:30",
            save_to_db=save_to_db,
            send_alert=send_alert,
            is_preview=True,
        )
    else:
        logger.info("13:00 이후 - 메인 모드로 실행")
        result = run_screening(
            screen_time="15:00",
            save_to_db=save_to_db,
            send_alert=send_alert,
            is_preview=False,
        )
    
    # 결과 출력
    print_result(result)


def run_test_mode():
    """테스트 모드 (알림 없음)"""
    logger = logging.getLogger(__name__)
    
    print_banner()
    logger.info("테스트 모드 (알림/저장 없음)")
    
    result = run_screening(
        screen_time="15:00",
        save_to_db=False,
        send_alert=False,
        is_preview=False,
    )
    
    print_result(result)


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
            print(f"   📈 원시값: CCI={stock.raw_cci:.1f}")
    else:
        print("\n❌ 적합한 종목이 없습니다.")
    
    # # ★ 사용자 요청: 한화오션, 루미르 점수 확인
    # target_stocks = [
    #     {"name": "루미르", "code": None}  # 코드를 모를 경우 이름으로 검색
    # ]
    
    # print("\n🔎 관심 종목 상세 결과")
    # print("-" * 50)
    
    # if result.all_items:
    #     for target in target_stocks:
    #         target_name = target["name"]
    #         target_code = target["code"]
    #         found = None
            
    #         for stock in result.all_items:
    #             # 코드가 있으면 코드로, 없으면 이름으로 매칭
    #             if target_code:
    #                 if stock.stock_code == target_code:
    #                     found = stock
    #                     break
    #             else:
    #                 if stock.stock_name == target_name:
    #                     found = stock
    #                     break
            
    #         if found:
    #             stock = found
    #             print(f"\n📌 {stock.stock_name} ({stock.stock_code})")
    #             print(f"   순위: {stock.rank}위 / {result.total_count}개")
    #             print(f"   💰 현재가: {stock.current_price:,}원 ({stock.change_rate:+.2f}%)")
    #             print(f"   📊 총점: {stock.score_total:.1f}점")
    #             print(f"      CCI값: {stock.score_cci_value:.1f} | CCI기울기: {stock.score_cci_slope:.1f}")
    #             print(f"      MA20기울기: {stock.score_ma20_slope:.1f} | 양봉품질: {stock.score_candle:.1f}")
    #             print(f"      상승률: {stock.score_change:.1f}")
    #             print(f"   📈 원시값: CCI={stock.raw_cci:.1f}")
    #         else:
    #             code_display = f"({target_code})" if target_code else ""
    #             print(f"\n❓ {target_name} {code_display}")
    #             print("   결과 없음 (거래대금 부족으로 필터링되었거나 유니버스 미포함)")
    # else:
    #     print("   분석된 종목이 없습니다.")
    
    # if result.error_message:
    #     print(f"\n⚠️ 에러: {result.error_message}")
    
    # print(f"\n{'='*60}")


def run_learning_mode():
    """학습 모드 실행 (Phase 2)"""
    from src.services.learner_service import get_learner_service
    from src.adapters.discord_notifier import get_discord_notifier
    
    logger = logging.getLogger(__name__)
    
    print_banner()
    print("\n📚 수동 학습 모드 실행")
    print("=" * 60)
    
    logger.info("수동 학습 실행")
    
    # 학습 서비스 실행
    learner = get_learner_service()
    report = learner.run_daily_learning()
    
    # 결과 출력
    print(f"\n{report.message}")
    print("=" * 60)
    
    # 디스코드 알림 (선택)
    if report.sample_count > 0:
        notifier = get_discord_notifier()
        notifier.send_learning_report(report)
        logger.info("학습 리포트 디스코드 발송 완료")
    
    return report


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description='종가매매 스크리너',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
    python main.py              스케줄러 모드 (12:30, 15:00, 16:30 자동 실행)
    python main.py --run        즉시 스크리닝 실행 (알림 발송)
    python main.py --run-test   테스트 실행 (알림/저장 없음)
    python main.py --learn      수동 학습 실행
    python main.py --init-db    DB 초기화
        """,
    )
    
    parser.add_argument(
        '--run',
        action='store_true',
        help='즉시 스크리닝 실행',
    )
    parser.add_argument(
        '--run-test',
        action='store_true',
        help='테스트 모드 (알림/저장 없음)',
    )
    parser.add_argument(
        '--learn',
        action='store_true',
        help='수동 학습 실행',
    )
    parser.add_argument(
        '--init-db',
        action='store_true',
        help='DB 초기화만 실행',
    )
    parser.add_argument(
        '--no-alert',
        action='store_true',
        help='알림 발송 안함',
    )
    parser.add_argument(
        '--validate',
        action='store_true',
        help='설정 검증만 실행',
    )
    parser.add_argument(
        '--show-config',
        action='store_true',
        help='현재 설정 요약 출력',
    )
    
    args = parser.parse_args()
    
    # 로깅 설정 (일별 로그 파일 자동 분리)
    init_logging()
    logger = logging.getLogger(__name__)
    
    # 설정 요약만 출력
    if args.show_config:
        print_settings_summary()
        return
    
    # 설정 검증
    try:
        # 테스트 모드가 아니면 필수 설정 검증
        if args.run_test or args.validate:
            result = validate_settings(raise_on_error=False)
            if args.validate:
                print_settings_summary()
                if result.valid:
                    print("\n✅ 모든 필수 설정이 올바르게 구성되었습니다.")
                else:
                    print("\n❌ 설정 검증 실패. 위 에러를 확인하세요.")
                    sys.exit(1)
                return
        else:
            validate_settings(raise_on_error=True)
    except ConfigValidationError as e:
        print(str(e))
        sys.exit(1)
    
    # DB 초기화
    logger.info("DB 초기화 확인...")
    init_database()
    
    if args.init_db:
        logger.info("DB 초기화 완료")
        return
    
    # 실행 모드 선택
    if args.run_test:
        run_test_mode()
    elif args.run:
        run_immediate(
            send_alert=not args.no_alert,
            save_to_db=True,
        )
    elif args.learn:
        run_learning_mode()
    else:
        run_scheduler_mode()


if __name__ == "__main__":
    main()
