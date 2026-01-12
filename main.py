"""
종가매매 스크리너 v5.1

📊 점수 체계 (100점 만점):
- 핵심 6개 지표: 각 15점 (총 90점)
- 보너스 3개: 총 10점

📈 등급별 매도전략:
- S등급 (85+): 시초 30% + 목표 +4%
- A등급 (75-84): 시초 40% + 목표 +3%
- B등급 (65-74): 시초 50% + 목표 +2.5%
- C등급 (55-64): 시초 70% + 목표 +2%
- D등급 (<55): 시초 전량매도

사용법:
    python main.py              # 스케줄러 모드
    python main.py --run        # 즉시 실행
    python main.py --run-test   # 테스트 (알림X)
    python main.py --validate   # 설정 검증
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

from src.services.screener_service import run_screening, ScreenerService
from src.domain.score_calculator import (
    StockScoreV5,
    StockGrade,
    SellStrategy,
    SELL_STRATEGIES,
)


def print_banner():
    """시작 배너"""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   🔔  종가매매 스크리너 v5.1                                   ║
║                                                              ║
║   📊 점수제 (100점 만점)                                       ║
║      핵심 6지표 × 15점 + 보너스 10점                           ║
║                                                              ║
║   🏆 등급별 매도전략                                           ║
║      S(85+) → 시초30% + 목표+4%                               ║
║      D(<55) → 시초 전량매도                                    ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """
    print(banner)


def print_score_detail(score: StockScoreV5, rank: int = None):
    """종목 점수 상세 출력"""
    d = score.score_detail
    s = score.sell_strategy
    
    grade_emoji = {"S": "🏆", "A": "🥇", "B": "🥈", "C": "🥉", "D": "⚠️"}
    rank_str = f"#{rank} " if rank else ""
    
    print(f"\n{'─'*60}")
    print(f"{rank_str}📌 {score.stock_name} ({score.stock_code})")
    print(f"{'─'*60}")
    print(f"   💰 현재가: {score.current_price:,}원 ({score.change_rate:+.2f}%)")
    print(f"   📊 총점: {score.score_total:.1f}점 {grade_emoji[score.grade.value]}{score.grade.value}등급")
    print(f"   💵 거래대금: {score.trading_value:,.0f}억원")
    print()
    
    # 핵심 지표
    print(f"   [핵심 지표] (90점 만점)")
    print(f"      CCI({d.raw_cci:.0f}):        {d.cci_score:>5.1f}/15")
    print(f"      등락률({d.raw_change_rate:.1f}%):   {d.change_score:>5.1f}/15")
    print(f"      이격도({d.raw_distance:.1f}%):   {d.distance_score:>5.1f}/15")
    print(f"      연속양봉({d.raw_consec_days}일):   {d.consec_score:>5.1f}/15")
    print(f"      거래량비({d.raw_volume_ratio:.1f}x): {d.volume_score:>5.1f}/15")
    print(f"      캔들품질:        {d.candle_score:>5.1f}/15")
    
    base_total = d.cci_score + d.change_score + d.distance_score + d.consec_score + d.volume_score + d.candle_score
    print(f"      {'─'*20}")
    print(f"      소계:            {base_total:>5.1f}/90")
    print()
    
    # 보너스
    cci_check = "✅" if d.is_cci_rising else "❌"
    ma20_check = "✅" if d.is_ma20_3day_up else "❌"
    candle_check = "❌" if d.is_high_eq_close else "✅"
    
    print(f"   [보너스] (10점 만점)")
    print(f"      CCI 상승중 {cci_check}:    {d.cci_rising_bonus:>5.1f}/4")
    print(f"      MA20 3일↑ {ma20_check}:   {d.ma20_3day_bonus:>5.1f}/3")
    print(f"      고가≠종가 {candle_check}:  {d.not_high_eq_close_bonus:>5.1f}/3")
    
    bonus_total = d.cci_rising_bonus + d.ma20_3day_bonus + d.not_high_eq_close_bonus
    print(f"      {'─'*20}")
    print(f"      소계:            {bonus_total:>5.1f}/10")
    print()
    
    # 매도 전략
    print(f"   [매도 전략] 신뢰도: {s.confidence}")
    print(f"      📈 시초가 {s.open_sell_ratio}% 매도")
    if s.target_sell_ratio > 0:
        print(f"      🎯 나머지 {s.target_sell_ratio}%: 목표가 +{s.target_profit}%")
    print(f"      🛡️ 손절가: {s.stop_loss}%")


def print_result(result: dict):
    """결과 출력"""
    print(f"\n{'='*60}")
    print(f"📊 스크리닝 결과")
    print(f"{'='*60}")
    print(f"📅 날짜: {result['screen_date']}")
    print(f"⏰ 시간: {result['screen_time']}")
    print(f"📈 상태: {result['status']}")
    print(f"📋 분석 종목: {result['total_count']}개")
    print(f"⏱️ 실행 시간: {result['execution_time_sec']:.1f}초")
    
    top_n = result.get('top_n', [])
    if top_n:
        print(f"\n🏆 TOP {len(top_n)}")
        for score in top_n:
            print_score_detail(score, score.rank)
    else:
        print("\n❌ 적합한 종목이 없습니다.")
    
    # 매도전략 안내
    print(f"\n{'='*60}")
    print("📋 등급별 매도전략")
    print(f"{'='*60}")
    print("🏆 S등급 (85점+): 시초 30% + 목표 +4% | 손절 -3%")
    print("🥇 A등급 (75-84): 시초 40% + 목표 +3% | 손절 -2.5%")
    print("🥈 B등급 (65-74): 시초 50% + 목표 +2.5% | 손절 -2%")
    print("🥉 C등급 (55-64): 시초 70% + 목표 +2% | 손절 -1.5%")
    print("⚠️ D등급 (<55):   시초 전량매도 | 손절 -1%")


def run_scheduler_mode():
    """스케줄러 모드"""
    logger = logging.getLogger(__name__)
    
    print_banner()
    logger.info("스케줄러 모드 시작")
    logger.info(f"프리뷰: {settings.screening.screening_time_preview}")
    logger.info(f"메인: {settings.screening.screening_time_main}")
    logger.info(f"오늘 장 운영: {'예' if is_market_open() else '아니오'}")
    
    scheduler = create_scheduler(blocking=True)
    scheduler.start()


def run_immediate(send_alert: bool = True, save_to_db: bool = True):
    """즉시 실행"""
    logger = logging.getLogger(__name__)
    
    print_banner()
    logger.info("즉시 실행 모드")
    
    now = datetime.now()
    is_preview = now.hour < 13
    screen_time = "12:30" if is_preview else "15:00"
    
    result = run_screening(
        screen_time=screen_time,
        save_to_db=save_to_db,
        send_alert=send_alert,
        is_preview=is_preview,
    )
    
    print_result(result)


def run_test_mode():
    """테스트 모드 (알림/저장 없음)"""
    logger = logging.getLogger(__name__)
    
    print_banner()
    logger.info("테스트 모드")
    
    result = run_screening(
        screen_time="15:00",
        save_to_db=False,
        send_alert=False,
        is_preview=False,
    )
    
    print_result(result)


def main():
    parser = argparse.ArgumentParser(description='종가매매 스크리너 v5.1')
    parser.add_argument('--run', action='store_true', help='즉시 실행')
    parser.add_argument('--run-test', action='store_true', help='테스트 모드')
    parser.add_argument('--no-alert', action='store_true', help='알림 없음')
    parser.add_argument('--validate', action='store_true', help='설정 검증')
    parser.add_argument('--init-db', action='store_true', help='DB 초기화')
    
    args = parser.parse_args()
    
    # 로깅 설정
    init_logging()
    logger = logging.getLogger(__name__)
    
    # 설정 검증
    try:
        if args.run_test or args.validate:
            result = validate_settings(raise_on_error=False)
            if args.validate:
                print_settings_summary()
                if result.valid:
                    print("\n✅ 설정 검증 완료")
                else:
                    print("\n❌ 설정 검증 실패")
                    sys.exit(1)
                return
        else:
            validate_settings(raise_on_error=True)
    except ConfigValidationError as e:
        print(str(e))
        sys.exit(1)
    
    # DB 초기화
    logger.info("DB 초기화...")
    init_database()
    
    if args.init_db:
        logger.info("DB 초기화 완료")
        return
    
    # 실행
    if args.run_test:
        run_test_mode()
    elif args.run:
        run_immediate(send_alert=not args.no_alert)
    else:
        run_scheduler_mode()


if __name__ == "__main__":
    main()
