"""
종가매매 스크리너 v5.0 - 소프트 필터 방식 (점수제)

🎯 핵심 변경 (v4 → v5):
- 하드 필터 최소화 (TV200 + 하락종목만 제외)
- 모든 조건은 점수로 반영 (100점 만점)
- 등급(S/A/B/C/D) 및 매도전략 자동 추천

📊 점수 체계:
- 핵심 6개 지표: 각 15점 (총 90점)
- 보너스 3개: 총 10점

📈 등급별 매도전략:
- S등급 (85+): 시초 30% + 목표 +4% (확신 높음)
- A등급 (75-84): 시초 40% + 목표 +3%
- B등급 (65-74): 시초 50% + 목표 +2.5%
- C등급 (55-64): 시초 70% + 목표 +2%
- D등급 (<55): 시초 전량매도 (확신 낮음)

사용법:
    python main.py              # 스케줄러 모드
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

# v5 서비스 임포트
from src.services.screener_service_v5 import (
    run_screening_v5,
    run_main_screening_v5,
    run_preview_screening_v5,
    ScreenerServiceV5,
)
from src.domain.score_calculator_v5 import (
    StockScoreV5,
    StockGrade,
    SellStrategy,
    SELL_STRATEGIES,
    format_score_display,
    format_simple_display,
)


def print_banner():
    """시작 배너 출력"""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   🔔  종가매매 스크리너 v5.0 (소프트 필터 방식)                  ║
║                                                              ║
║   📊 점수 체계 (100점 만점)                                    ║
║      - 핵심 6개 지표: 각 15점 (CCI, 등락률, 이격도 등)          ║
║      - 보너스 3개: 총 10점 (CCI↑, MA20↑, 고가≠종가)            ║
║                                                              ║
║   🏆 등급별 매도전략                                           ║
║      - S(85+): 시초30% + 목표+4% | 확신 높음                   ║
║      - D(<55): 시초 전량매도     | 확신 낮음                   ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """
    print(banner)


def run_scheduler_mode():
    """스케줄러 모드 실행"""
    logger = logging.getLogger(__name__)
    
    print_banner()
    logger.info("스케줄러 모드 시작 (v5.0)")
    logger.info(f"프리뷰 시간: {settings.screening.screening_time_preview}")
    logger.info(f"메인 시간: {settings.screening.screening_time_main}")
    logger.info(f"오늘 장 운영: {'예' if is_market_open() else '아니오'}")
    
    scheduler = create_scheduler(blocking=True)
    scheduler.start()


def run_immediate(send_alert: bool = True, save_to_db: bool = True):
    """즉시 실행 모드"""
    logger = logging.getLogger(__name__)
    
    print_banner()
    logger.info("즉시 실행 모드 (v5.0)")
    
    now = datetime.now()
    if now.hour < 13:
        logger.info("12:30 이전 - 프리뷰 모드로 실행")
        result = run_screening_v5(
            screen_time="12:30",
            save_to_db=save_to_db,
            send_alert=send_alert,
            is_preview=True,
        )
    else:
        logger.info("13:00 이후 - 메인 모드로 실행")
        result = run_screening_v5(
            screen_time="15:00",
            save_to_db=save_to_db,
            send_alert=send_alert,
            is_preview=False,
        )
    
    print_result(result)


def run_test_mode():
    """테스트 모드 (알림 없음) - TOP5 + 등급/매도전략"""
    logger = logging.getLogger(__name__)
    
    print_banner()
    logger.info("테스트 모드 (알림/저장 없음) - v5.0")
    
    result = run_screening_v5(
        screen_time="15:00",
        save_to_db=False,
        send_alert=False,
        is_preview=False,
    )
    
    print_result_detailed(result)


def print_score_detail_v5(score: StockScoreV5, rank: int = None):
    """v5 종목 점수 상세 출력"""
    d = score.score_detail
    s = score.sell_strategy
    
    grade_emoji = {
        StockGrade.S: "🏆",
        StockGrade.A: "🥇",
        StockGrade.B: "🥈",
        StockGrade.C: "🥉",
        StockGrade.D: "⚠️",
    }
    
    rank_str = f"#{rank} " if rank else ""
    
    print(f"\n{'─'*60}")
    print(f"{rank_str}📌 {score.stock_name} ({score.stock_code})")
    print(f"{'─'*60}")
    print(f"   💰 현재가: {score.current_price:,}원 ({score.change_rate:+.2f}%)")
    print(f"   📊 총점: {score.score_total:.1f}점 {grade_emoji[score.grade]} {score.grade.value}등급")
    print(f"   💵 거래대금: {score.trading_value:,.0f}억원")
    print()
    
    # 핵심 점수 (90점)
    print(f"   [핵심 지표] (90점 만점)")
    print(f"      CCI({d.raw_cci:.0f}):        {d.cci_score:>5.1f}/15")
    print(f"      등락률({d.raw_change_rate:.1f}%):   {d.change_score:>5.1f}/15")
    print(f"      이격도({d.raw_distance:.1f}%):   {d.distance_score:>5.1f}/15")
    print(f"      연속양봉({d.raw_consec_days}일):   {d.consec_score:>5.1f}/15")
    print(f"      거래량비({d.raw_volume_ratio:.1f}x): {d.volume_score:>5.1f}/15")
    print(f"      캔들품질:        {d.candle_score:>5.1f}/15")
    
    base_total = d.cci_score + d.change_score + d.distance_score + d.consec_score + d.volume_score + d.candle_score
    print(f"      ────────────────────")
    print(f"      소계:            {base_total:>5.1f}/90")
    print()
    
    # 보너스 점수 (10점)
    cci_check = "✅" if d.is_cci_rising else "❌"
    ma20_check = "✅" if d.is_ma20_3day_up else "❌"
    candle_check = "❌" if d.is_high_eq_close else "✅"
    
    print(f"   [보너스] (10점 만점)")
    print(f"      CCI 상승중 {cci_check}:    {d.cci_rising_bonus:>5.1f}/4")
    print(f"      MA20 3일↑ {ma20_check}:   {d.ma20_3day_bonus:>5.1f}/3")
    print(f"      고가≠종가 {candle_check}:  {d.not_high_eq_close_bonus:>5.1f}/3")
    
    bonus_total = d.cci_rising_bonus + d.ma20_3day_bonus + d.not_high_eq_close_bonus
    print(f"      ────────────────────")
    print(f"      소계:            {bonus_total:>5.1f}/10")
    print()
    
    # 매도 전략
    print(f"   [매도 전략] 신뢰도: {s.confidence}")
    print(f"      📈 시초가 {s.open_sell_ratio}% 매도")
    if s.target_sell_ratio > 0:
        print(f"      🎯 나머지 {s.target_sell_ratio}%: 목표가 +{s.target_profit}%")
    print(f"      🛡️ 손절가: {s.stop_loss}%")


def print_result(result: dict):
    """기본 결과 출력"""
    print(f"\n{'='*60}")
    print(f"📊 스크리닝 결과 (v5.0)")
    print(f"{'='*60}")
    print(f"📅 날짜: {result['screen_date']}")
    print(f"⏰ 시간: {result['screen_time']}")
    print(f"📈 상태: {result['status']}")
    print(f"📋 분석 종목: {result['total_count']}개")
    print(f"⏱️ 실행 시간: {result['execution_time_sec']:.1f}초")
    
    top_n = result.get('top_n', [])
    if top_n:
        print(f"\n🏆 TOP {len(top_n)}")
        print("-" * 50)
        for score in top_n:
            print_score_detail_v5(score, score.rank)
    else:
        print("\n❌ 적합한 종목이 없습니다.")


def print_result_detailed(result: dict):
    """상세 결과 출력 (TOP5 + 등급/매도전략)"""
    print(f"\n{'='*60}")
    print(f"📊 스크리닝 결과 - v5.0 (소프트 필터)")
    print(f"{'='*60}")
    print(f"📅 날짜: {result['screen_date']}")
    print(f"⏰ 시간: {result['screen_time']}")
    print(f"📈 상태: {result['status']}")
    print(f"📋 분석 종목: {result['total_count']}개")
    print(f"⏱️ 실행 시간: {result['execution_time_sec']:.1f}초")
    
    all_scores = result.get('all_scores', [])
    top_n = result.get('top_n', [])
    
    if not top_n:
        print("\n❌ 분석된 종목이 없습니다.")
        return
    
    # TOP 5 출력
    print(f"\n{'='*60}")
    print(f"🏆 TOP 5 종목 (등급 + 매도전략)")
    print(f"{'='*60}")
    
    for score in top_n:
        print_score_detail_v5(score, score.rank)
    
    # TOP 5 요약 테이블
    print(f"\n{'='*60}")
    print(f"📋 TOP 5 요약")
    print(f"{'='*60}")
    
    grade_emoji = {"S": "🏆", "A": "🥇", "B": "🥈", "C": "🥉", "D": "⚠️"}
    
    print(f"{'순위':<4} {'종목명':<12} {'총점':>6} {'등급':>6} {'등락률':>8} {'시초매도':>8} {'목표':>8}")
    print(f"{'-'*60}")
    
    for score in top_n:
        s = score.sell_strategy
        g = score.grade.value
        emoji = grade_emoji[g]
        target_str = f"+{s.target_profit}%" if s.target_sell_ratio > 0 else "-"
        print(f"{score.rank:<4} {score.stock_name:<12} {score.score_total:>5.1f}점 {emoji}{g:>4} {score.change_rate:>+7.1f}% {s.open_sell_ratio:>6}% {target_str:>8}")
    
    # 분석 의견
    print(f"\n{'='*60}")
    print(f"💡 TOP 5 분석 의견")
    print(f"{'='*60}")
    
    avg_score = sum(s.score_total for s in top_n) / len(top_n)
    grade_counts = {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0}
    for s in top_n:
        grade_counts[s.grade.value] += 1
    
    print(f"\n   평균 점수: {avg_score:.1f}점")
    print(f"   등급 분포: S({grade_counts['S']}) A({grade_counts['A']}) B({grade_counts['B']}) C({grade_counts['C']}) D({grade_counts['D']})")
    
    if avg_score >= 85:
        print(f"\n   🏆 오늘 TOP5 품질: 매우 우수")
        print(f"   👉 대부분 시초 30%만 매도, 나머지 +4% 홀딩 추천")
    elif avg_score >= 75:
        print(f"\n   📈 오늘 TOP5 품질: 우수")
        print(f"   👉 시초 30~40% 익절, 나머지 목표가 홀딩")
    elif avg_score >= 65:
        print(f"\n   📊 오늘 TOP5 품질: 양호")
        print(f"   👉 시초 50% 익절, 나머지 목표가 홀딩")
    elif avg_score >= 55:
        print(f"\n   ⚠️ 오늘 TOP5 품질: 보통")
        print(f"   👉 보수적 접근, 시초 70% 익절 권장")
    else:
        print(f"\n   🚨 오늘 TOP5 품질: 미흡")
        print(f"   👉 매수 자제, 시초 전량 매도 권장")
    
    # 등급별 매도전략 안내
    print(f"\n{'='*60}")
    print(f"📋 등급별 매도전략")
    print(f"{'='*60}")
    print("""
   🏆 S등급 (85점+): 시초 30% + 목표 +4% | 손절 -3%
   🥇 A등급 (75-84): 시초 40% + 목표 +3% | 손절 -2.5%
   🥈 B등급 (65-74): 시초 50% + 목표 +2.5% | 손절 -2%
   🥉 C등급 (55-64): 시초 70% + 목표 +2% | 손절 -1.5%
   ⚠️ D등급 (<55):   시초 전량매도 | 손절 -1%
    """)
    print(f"{'='*60}")


def run_learning_mode():
    """학습 모드 실행"""
    from src.services.learner_service import get_learner_service
    from src.adapters.discord_notifier import get_discord_notifier
    
    logger = logging.getLogger(__name__)
    
    print_banner()
    print("\n📚 수동 학습 모드 실행")
    print("=" * 60)
    
    logger.info("수동 학습 실행")
    
    learner = get_learner_service()
    report = learner.run_daily_learning()
    
    print(f"\n{report.message}")
    print("=" * 60)
    
    if report.sample_count > 0:
        notifier = get_discord_notifier()
        notifier.send_learning_report(report)
        logger.info("학습 리포트 디스코드 발송 완료")
    
    return report


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description='종가매매 스크리너 v5.0 (소프트 필터)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
    python main.py              스케줄러 모드
    python main.py --run        즉시 스크리닝 실행
    python main.py --run-test   테스트 실행 (TOP5 + 등급/매도전략)
    python main.py --learn      수동 학습 실행
    python main.py --init-db    DB 초기화
        """,
    )
    
    parser.add_argument('--run', action='store_true', help='즉시 스크리닝 실행')
    parser.add_argument('--run-test', action='store_true', help='테스트 모드')
    parser.add_argument('--learn', action='store_true', help='수동 학습 실행')
    parser.add_argument('--init-db', action='store_true', help='DB 초기화만 실행')
    parser.add_argument('--no-alert', action='store_true', help='알림 발송 안함')
    parser.add_argument('--validate', action='store_true', help='설정 검증만 실행')
    parser.add_argument('--show-config', action='store_true', help='현재 설정 요약 출력')
    
    args = parser.parse_args()
    
    # 로깅 설정
    init_logging()
    logger = logging.getLogger(__name__)
    
    if args.show_config:
        print_settings_summary()
        return
    
    # 설정 검증
    try:
        if args.run_test or args.validate:
            result = validate_settings(raise_on_error=False)
            if args.validate:
                print_settings_summary()
                if result.valid:
                    print("\n✅ 모든 필수 설정이 올바르게 구성되었습니다.")
                else:
                    print("\n❌ 설정 검증 실패.")
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
        run_immediate(send_alert=not args.no_alert, save_to_db=True)
    elif args.learn:
        run_learning_mode()
    else:
        run_scheduler_mode()


if __name__ == "__main__":
    main()
