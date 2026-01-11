"""
종가매매 스크리너 v4.0 - 그리드 서치 최적화

사용법:
    python main.py              # 스케줄러 모드 (12:30, 15:00, 16:30 자동 실행)
    python main.py --run        # 즉시 스크리닝 실행
    python main.py --run-test   # 테스트 실행 (알림 없음) ★ TOP5 + 매도추천
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
║   🔔  종가매매 스크리너 v4.0 (그리드 서치 최적화)               ║
║                                                              ║
║   📊 최적 조건 (60% 승률)                                      ║
║      - CCI: 160~180 | 이격도: 2~8%                            ║
║      - 등락률: 2~8% | 연속양봉: ≤4일                           ║
║      - 거래대금: ≥200억 | CCI↑ | MA20 3일↑                    ║
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
    
    scheduler = create_scheduler(blocking=True)
    scheduler.start()


def run_immediate(send_alert: bool = True, save_to_db: bool = True):
    """즉시 실행 모드"""
    logger = logging.getLogger(__name__)
    
    print_banner()
    logger.info("즉시 실행 모드")
    
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
    
    print_result(result)


def run_test_mode():
    """테스트 모드 (알림 없음) - TOP5 + 매도추천 + 관심종목"""
    logger = logging.getLogger(__name__)
    
    print_banner()
    logger.info("테스트 모드 (알림/저장 없음)")
    
    result = run_screening(
        screen_time="15:00",
        save_to_db=False,
        send_alert=False,
        is_preview=False,
    )
    
    print_result_detailed(result)


def get_sell_recommendation(score_total: float) -> dict:
    """매도 추천 방식
    
    점수 기반 매도 전략:
    - 80점+: 시초가 매도 (익절)
    - 70~80점: 2~3% 익절 또는 손절 -2%
    - 60~70점: 1~2% 익절 또는 손절 -1.5%
    - 60점 미만: 보수적 (손절 -1%)
    """
    if score_total >= 80:
        return {
            "strategy": "🚀 시초가 매도",
            "target": "+1%~+3%",
            "stop": "-2%",
            "confidence": "★★★",
        }
    elif score_total >= 70:
        return {
            "strategy": "📈 목표가 매도",
            "target": "+2%~+3%",
            "stop": "-2%",
            "confidence": "★★☆",
        }
    elif score_total >= 60:
        return {
            "strategy": "⚖️ 보수적 익절",
            "target": "+1%~+2%",
            "stop": "-1.5%",
            "confidence": "★☆☆",
        }
    else:
        return {
            "strategy": "🛡️ 조기 손절",
            "target": "+1%",
            "stop": "-1%",
            "confidence": "☆☆☆",
        }


def print_score_detail(stock, show_sell_recommendation: bool = True):
    """종목 점수 상세 출력"""
    print(f"\n{'─'*50}")
    print(f"📌 {stock.stock_name} ({stock.stock_code})")
    print(f"{'─'*50}")
    print(f"   💰 현재가: {stock.current_price:,}원 ({stock.change_rate:+.2f}%)")
    print(f"   📊 총점: {stock.score_total:.1f}점 (순위: {stock.rank}위)")
    print(f"   💵 거래대금: {stock.trading_value:,.0f}억원")
    print()
    print(f"   [점수 상세]")
    print(f"      CCI 점수:     {stock.score_cci_value:>5.1f}점  (CCI: {stock.raw_cci:.0f})")
    print(f"      이격도 점수:  {stock.score_cci_slope:>5.1f}점")  # v4: 이격도
    print(f"      MA20추세:     {stock.score_ma20_slope:>5.1f}점")
    print(f"      캔들품질:     {stock.score_candle:>5.1f}점")
    print(f"      등락률점수:   {stock.score_change:>5.1f}점")
    
    if show_sell_recommendation:
        rec = get_sell_recommendation(stock.score_total)
        print()
        print(f"   [매도 추천] {rec['confidence']}")
        print(f"      전략: {rec['strategy']}")
        print(f"      목표: {rec['target']} | 손절: {rec['stop']}")


def print_result(result):
    """기본 결과 출력"""
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
            print(f"   📈 원시값: CCI={stock.raw_cci:.1f}")
    else:
        print("\n❌ 적합한 종목이 없습니다.")


def print_result_detailed(result):
    """상세 결과 출력 (TOP5 + 매도추천 + 관심종목)"""
    print(f"\n{'='*60}")
    print(f"📊 스크리닝 결과 (상세)")
    print(f"{'='*60}")
    print(f"📅 날짜: {result.screen_date}")
    print(f"⏰ 시간: {result.screen_time}")
    print(f"📈 상태: {result.status.value}")
    print(f"📋 분석 종목: {result.total_count}개")
    print(f"⏱️ 실행 시간: {result.execution_time_sec:.1f}초")
    
    # ============================================================
    # TOP 5 출력
    # ============================================================
    if result.all_items:
        top5 = result.all_items[:5]
        
        print(f"\n{'='*60}")
        print(f"🏆 TOP 5 종목 (매도 추천 포함)")
        print(f"{'='*60}")
        
        for stock in top5:
            print_score_detail(stock, show_sell_recommendation=True)
        
        # ============================================================
        # TOP 5 요약 테이블
        # ============================================================
        print(f"\n{'='*60}")
        print(f"📋 TOP 5 요약")
        print(f"{'='*60}")
        print(f"{'순위':<4} {'종목명':<12} {'총점':>6} {'등락률':>8} {'CCI':>6} {'매도전략':<15}")
        print(f"{'-'*60}")
        
        for stock in top5:
            rec = get_sell_recommendation(stock.score_total)
            print(f"{stock.rank:<4} {stock.stock_name:<12} {stock.score_total:>5.1f}점 {stock.change_rate:>+7.2f}% {stock.raw_cci:>6.0f} {rec['strategy']}")
        
        # ============================================================
        # 관심 종목 검색 (한화오션 등)
        # ============================================================
        target_stocks = [
            {"name": "한화오션", "code": "042660"},
            {"name": "루미르", "code": None},
        ]
        
        print(f"\n{'='*60}")
        print(f"🔎 관심 종목 점수")
        print(f"{'='*60}")
        
        for target in target_stocks:
            target_name = target["name"]
            target_code = target["code"]
            found = None
            
            for stock in result.all_items:
                if target_code:
                    if stock.stock_code == target_code:
                        found = stock
                        break
                else:
                    if target_name in stock.stock_name:
                        found = stock
                        break
            
            if found:
                print_score_detail(found, show_sell_recommendation=True)
            else:
                code_display = f"({target_code})" if target_code else ""
                print(f"\n❓ {target_name} {code_display}")
                print(f"   결과 없음 (필터링됨 또는 유니버스 미포함)")
        
        # ============================================================
        # TOP 5 의견
        # ============================================================
        print(f"\n{'='*60}")
        print(f"💡 TOP 5 분석 의견")
        print(f"{'='*60}")
        
        avg_score = sum(s.score_total for s in top5) / len(top5)
        high_score_count = sum(1 for s in top5 if s.score_total >= 70)
        
        print(f"\n   평균 점수: {avg_score:.1f}점")
        print(f"   70점+ 종목: {high_score_count}개")
        
        if avg_score >= 75:
            print(f"\n   📈 오늘 TOP5 품질: 우수")
            print(f"   👉 적극 매수 고려, 시초가 매도 전략 유효")
        elif avg_score >= 65:
            print(f"\n   📊 오늘 TOP5 품질: 양호")
            print(f"   👉 선별 매수, 목표가 도달 시 익절")
        elif avg_score >= 55:
            print(f"\n   ⚠️ 오늘 TOP5 품질: 보통")
            print(f"   👉 신중한 접근, 보수적 익절 권장")
        else:
            print(f"\n   🚨 오늘 TOP5 품질: 미흡")
            print(f"   👉 매수 자제, 관망 권장")
        
        # 위험 신호 체크
        warnings = []
        for stock in top5:
            if stock.raw_cci > 180:
                warnings.append(f"   ⚠️ {stock.stock_name}: CCI {stock.raw_cci:.0f} (과열)")
            if stock.change_rate > 10:
                warnings.append(f"   ⚠️ {stock.stock_name}: 등락률 {stock.change_rate:.1f}% (추격 위험)")
        
        if warnings:
            print(f"\n   [위험 신호]")
            for w in warnings:
                print(w)
    
    else:
        print("\n❌ 분석된 종목이 없습니다.")
    
    print(f"\n{'='*60}")


def run_learning_mode():
    """학습 모드 실행 (Phase 2)"""
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
        description='종가매매 스크리너 v4.0',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
    python main.py              스케줄러 모드 (12:30, 15:00, 16:30 자동 실행)
    python main.py --run        즉시 스크리닝 실행 (알림 발송)
    python main.py --run-test   테스트 실행 (TOP5 + 매도추천 + 관심종목)
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
        help='테스트 모드 (TOP5 + 매도추천 + 관심종목)',
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
    
    # 로깅 설정
    init_logging()
    logger = logging.getLogger(__name__)
    
    # 설정 요약만 출력
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
