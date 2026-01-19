"""
종가매매 스크리너 v6.0

📊 종가매매 점수제 (100점 만점):
   거래량비·등락률·연속양봉·CCI·이격도·캔들

📈 등급별 매도전략:
- S등급 (85+): 시초 30% + 목표 +4%
- A등급 (75-84): 시초 40% + 목표 +3%
- B등급 (65-74): 시초 50% + 목표 +2.5%
- C등급 (55-64): 시초 70% + 목표 +2%
- D등급 (<55): 시초 전량매도

⚡ v6.0 업데이트:
- TOP5 20일 추적 (D+1 ~ D+20)
- 유목민 공부법 (상한가/거래량천만)
- 과거 데이터 백필
- 멀티페이지 대시보드

사용법:
    python main.py              # 스케줄러 모드 (17:40 자동종료)
    python main.py --run        # 스크리닝 즉시 실행
    python main.py --backfill 20  # 과거 20일 데이터 백필
    python main.py --run-all    # 모든 서비스 순차 실행 (테스트용)
    python main.py --run-test   # 테스트 (알림X)
    python main.py --check 종목코드  # 특정 종목 점수 확인 (예: --check 005930)
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
║   🔔  종가매매 스크리너 v6.0                                   ║
║                                                              ║
║   📊 점수제 (100점 만점)                                       ║
║      거래량 25 / 등락률 20 / CCI·연속·이격 15 / 캔들 10        ║
║                                                              ║
║   🆕 v6.0 새 기능                                             ║
║      • TOP5 20일 추적 (D+1 ~ D+20)                            ║
║      • 유목민 공부법 (상한가/거래량천만)                         ║
║      • 과거 데이터 백필                                        ║
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


def run_all_services():
    """모든 서비스 순차 실행 (테스트용)
    
    실행 순서:
    1. 스크리닝 (15:00)
    2. 데이터 갱신
    3. 익일 결과 수집
    4. 학습 (가중치 최적화)
    5. Git 커밋
    """
    logger = logging.getLogger(__name__)
    
    print_banner()
    print("\n🔄 모든 서비스 순차 실행 시작...")
    print("=" * 60)
    
    results = {}
    
    # 1. 스크리닝
    print("\n[1/5] 📊 스크리닝 실행...")
    try:
        result = run_screening(
            screen_time="15:00",
            save_to_db=True,
            send_alert=False,
            is_preview=False,
        )
        results['screening'] = '✅ 성공'
        print(f"      → {result['status']}, {result['total_count']}개 종목 분석")
    except Exception as e:
        results['screening'] = f'❌ 실패: {e}'
        logger.error(f"스크리닝 실패: {e}")
    
    # 2. 데이터 갱신
    print("\n[2/5] 📈 데이터 갱신...")
    try:
        from src.services.data_updater import run_data_update
        run_data_update()
        results['data_update'] = '✅ 성공'
    except Exception as e:
        results['data_update'] = f'❌ 실패: {e}'
        logger.error(f"데이터 갱신 실패: {e}")
    
    # 3. 익일 결과 수집
    print("\n[3/5] 📊 익일 결과 수집...")
    try:
        from src.services.result_collector import run_result_collection
        collect_result = run_result_collection()
        results['result_collection'] = f"✅ 성공 ({collect_result.get('collected', 0)}건 수집)"
    except Exception as e:
        results['result_collection'] = f'❌ 실패: {e}'
        logger.error(f"결과 수집 실패: {e}")
    
    # 4. 학습 (가중치 최적화)
    print("\n[4/5] 🧠 학습 실행...")
    try:
        from src.services.learner_service import run_daily_learning
        learn_result = run_daily_learning()
        results['learning'] = '✅ 성공'
    except Exception as e:
        results['learning'] = f'❌ 실패: {e}'
        logger.error(f"학습 실패: {e}")
    
    # 5. Git 커밋
    print("\n[5/5] 📤 Git 커밋...")
    try:
        from src.infrastructure.scheduler import git_auto_commit
        git_result = git_auto_commit()
        results['git_commit'] = '✅ 성공' if git_result else '⚠️ 변경사항 없음'
    except Exception as e:
        results['git_commit'] = f'❌ 실패: {e}'
        logger.error(f"Git 커밋 실패: {e}")
    
    # 결과 요약
    print("\n" + "=" * 60)
    print("📋 실행 결과 요약")
    print("=" * 60)
    for service, status in results.items():
        print(f"   {service}: {status}")
    
    return results


def check_stock(stock_code: str):
    """특정 종목 점수 확인
    
    Args:
        stock_code: 종목코드 (6자리)
    """
    logger = logging.getLogger(__name__)
    
    print_banner()
    print(f"\n🔍 종목 점수 확인: {stock_code}")
    print("=" * 60)
    
    from src.adapters.kis_client import get_kis_client
    from src.domain.models import StockData
    from src.domain.score_calculator import ScoreCalculatorV5
    from src.config.constants import MIN_DAILY_DATA_COUNT
    
    kis_client = get_kis_client()
    calculator = ScoreCalculatorV5()
    
    try:
        # 1. 종목명 조회
        current_data = kis_client.get_current_price(stock_code)
        if not current_data:
            print(f"❌ 종목을 찾을 수 없습니다: {stock_code}")
            return
        
        stock_name = current_data.name if hasattr(current_data, 'name') else stock_code
        print(f"📌 {stock_name} ({stock_code})")
        
        # 2. 일봉 데이터 조회
        daily_prices = kis_client.get_daily_prices(stock_code, count=MIN_DAILY_DATA_COUNT + 10)
        
        if len(daily_prices) < MIN_DAILY_DATA_COUNT:
            print(f"❌ 데이터 부족: {len(daily_prices)}일치 (최소 {MIN_DAILY_DATA_COUNT}일 필요)")
            return
        
        today = daily_prices[-1]
        yesterday = daily_prices[-2]
        change_rate = ((today.close - yesterday.close) / yesterday.close) * 100
        
        # 3. 거래대금 계산
        trading_value = 0.0
        if today.trading_value > 0:
            trading_value = today.trading_value / 100_000_000
        elif current_data and hasattr(current_data, 'trading_value') and current_data.trading_value > 0:
            trading_value = current_data.trading_value / 100_000_000
        elif today.volume > 0:
            trading_value = (today.volume * today.close) / 100_000_000
        
        # 4. StockData 생성
        stock_data = StockData(
            code=stock_code,
            name=stock_name,
            daily_prices=daily_prices,
            current_price=today.close,
            trading_value=trading_value,
        )
        
        # 5. 점수 계산
        scores = calculator.calculate_scores([stock_data])
        
        if not scores:
            print(f"❌ 점수 계산 실패 (하락 종목이거나 조건 미달)")
            print(f"   현재가: {today.close:,}원 ({change_rate:+.2f}%)")
            return
        
        score = scores[0]
        score.rank = 1  # 단일 종목이므로 1등
        
        # 6. 상세 출력
        print_score_detail(score, rank=None)
        
        # 추가 정보
        print(f"\n{'─'*60}")
        print(f"ℹ️ 참고")
        print(f"   데이터 기간: {daily_prices[0].date} ~ {daily_prices[-1].date}")
        print(f"   거래대금: {trading_value:,.1f}억원")
        if change_rate < 0:
            print(f"   ⚠️ 하락 종목은 종가매매 대상이 아닙니다")
        
    except Exception as e:
        logger.error(f"점수 확인 실패: {e}")
        import traceback
        traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(description='종가매매 스크리너 v6.0')
    parser.add_argument('--run', action='store_true', help='스크리닝 즉시 실행')
    parser.add_argument('--run-all', action='store_true', help='모든 서비스 순차 실행')
    parser.add_argument('--run-test', action='store_true', help='테스트 모드')
    parser.add_argument('--no-alert', action='store_true', help='알림 없음')
    parser.add_argument('--validate', action='store_true', help='설정 검증')
    parser.add_argument('--init-db', action='store_true', help='DB 초기화')
    parser.add_argument('--check', type=str, metavar='CODE', help='특정 종목 점수 확인 (예: --check 074610)')
    
    # v6.0 옵션
    parser.add_argument('--backfill', type=int, metavar='DAYS', help='과거 N일 데이터 백필 (TOP5 + 유목민)')
    parser.add_argument('--backfill-top5', type=int, metavar='DAYS', help='TOP5만 백필')
    parser.add_argument('--backfill-nomad', type=int, metavar='DAYS', help='유목민만 백필')
    parser.add_argument('--auto-fill', action='store_true', help='누락 데이터 자동 수집')
    parser.add_argument('--run-top5-update', action='store_true', help='TOP5 일일 추적 업데이트')
    parser.add_argument('--run-nomad', action='store_true', help='유목민 공부 실행')
    parser.add_argument('--run-news', action='store_true', help='유목민 뉴스 수집 (네이버+Gemini)')
    parser.add_argument('--run-company-info', action='store_true', help='유목민 기업정보 수집 (네이버금융)')
    parser.add_argument('--version', action='version', version='ClosingBell v6.0')
    
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
    
    # v6.0 명령어 처리
    if args.backfill:
        run_backfill(args.backfill, top5=True, nomad=True)
        return
    
    if args.backfill_top5:
        run_backfill(args.backfill_top5, top5=True, nomad=False)
        return
    
    if args.backfill_nomad:
        run_backfill(args.backfill_nomad, top5=False, nomad=True)
        return
    
    if args.auto_fill:
        run_auto_fill()
        return
    
    if args.run_top5_update:
        run_top5_daily_update()
        return
    
    if args.run_nomad:
        run_nomad_study()
        return
    
    if args.run_news:
        run_news_collection_cli()
        return
    
    if args.run_company_info:
        run_company_info_cli()
        return
    
    # 실행
    if args.check:
        check_stock(args.check)
    elif args.run_test:
        run_test_mode()
    elif args.run_all:
        run_all_services()
    elif args.run:
        run_immediate(send_alert=not args.no_alert)
    else:
        run_scheduler_mode()


# ========================================================================
# v6.0 함수들
# ========================================================================

def run_backfill(days: int, top5: bool = True, nomad: bool = True):
    """과거 데이터 백필"""
    logger = logging.getLogger(__name__)
    
    print(f"\n🔄 과거 {days}일 데이터 백필 시작...")
    print(f"   TOP5: {'✅' if top5 else '❌'}")
    print(f"   유목민: {'✅' if nomad else '❌'}")
    
    # 설정 검증
    from src.config.backfill_config import get_backfill_config
    config = get_backfill_config()
    
    is_valid, errors = config.validate()
    if not is_valid:
        print(f"\n❌ 백필 설정 오류:")
        for err in errors:
            print(f"   - {err}")
        return
    
    print(f"\n📁 데이터 경로:")
    print(f"   OHLCV: {config.ohlcv_dir}")
    print(f"   매핑: {config.stock_mapping_path}")
    print(f"   글로벌: {config.global_data_dir}")
    
    # 백필 서비스 실행
    try:
        from src.services.backfill import HistoricalBackfillService
        
        service = HistoricalBackfillService(config)
        
        # 데이터 로드
        print(f"\n📥 데이터 로드 중...")
        if not service.load_data():
            print("❌ 데이터 로드 실패")
            return
        
        # TOP5 백필
        if top5:
            print(f"\n📊 TOP5 백필 중... (최근 {days}일)")
            top5_result = service.backfill_top5(days=days)
            print(f"   ✅ TOP5 저장: {top5_result.get('top5_saved', 0)}개")
            print(f"   ✅ 가격 저장: {top5_result.get('prices_saved', 0)}개")
        
        # 유목민 백필
        if nomad:
            print(f"\n📚 유목민 백필 중... (최근 {days}일)")
            nomad_result = service.backfill_nomad(days=days)
            print(f"   ✅ 상한가: {nomad_result.get('limit_up', 0)}개")
            print(f"   ✅ 거래량천만: {nomad_result.get('volume_explosion', 0)}개")
        
        print(f"\n✅ 백필 완료!")
        print(f"   대시보드에서 확인: streamlit run dashboard/app.py")
        
    except Exception as e:
        logger.error(f"백필 실패: {e}")
        import traceback
        traceback.print_exc()


def run_auto_fill():
    """누락 데이터 자동 수집"""
    logger = logging.getLogger(__name__)
    print("\n🔄 누락 데이터 자동 수집...")
    
    # TODO: 실제 자동 채우기 로직 구현
    print(f"\n⚠️ 자동 채우기 기능은 Windows 환경에서 실행해주세요.")


def run_top5_daily_update():
    """TOP5 일일 추적 업데이트"""
    logger = logging.getLogger(__name__)
    print("\n📈 TOP5 일일 추적 업데이트...")
    
    try:
        from src.infrastructure.repository import get_top5_history_repository, get_top5_prices_repository
        
        history_repo = get_top5_history_repository()
        prices_repo = get_top5_prices_repository()
        
        # 활성 항목 조회
        active_items = history_repo.get_active_items()
        print(f"활성 추적 항목: {len(active_items)}개")
        
        if not active_items:
            print("추적할 항목이 없습니다.")
            return
        
        # TODO: KIS API로 일별 가격 수집
        print(f"\n⚠️ KIS API 연동이 필요합니다.")
        print(f"   --run 명령으로 스크리닝 후 자동 수집됩니다.")
        
    except Exception as e:
        logger.error(f"TOP5 업데이트 실패: {e}")
        print(f"\n❌ 오류: {e}")


def run_nomad_study():
    """유목민 공부 실행"""
    logger = logging.getLogger(__name__)
    print("\n📚 유목민 공부 실행...")
    
    try:
        from datetime import date
        from src.infrastructure.repository import get_nomad_candidates_repository
        
        repo = get_nomad_candidates_repository()
        today = date.today().isoformat()
        
        # 오늘 데이터 확인
        existing = repo.get_by_date(today)
        if existing:
            print(f"오늘({today}) 이미 {len(existing)}개 후보가 있습니다.")
            return
        
        # TODO: 상한가/거래량천만 종목 수집
        print(f"\n⚠️ 종목 수집 기능은 KIS API 연동이 필요합니다.")
        print(f"   --run 명령으로 스크리닝 후 자동 수집됩니다.")
        
    except Exception as e:
        logger.error(f"유목민 공부 실패: {e}")
        print(f"\n❌ 오류: {e}")


def run_news_collection_cli():
    """유목민 뉴스 수집 CLI"""
    logger = logging.getLogger(__name__)
    print("\n📰 유목민 뉴스 수집 시작...")
    
    try:
        from src.services.news_service import collect_news_for_candidates
        
        result = collect_news_for_candidates(limit=600)
        
        if 'error' in result:
            print(f"\n❌ 오류: {result['error']}")
            if result['error'] == 'no_naver_api_key':
                print("   .env 파일에 NaverAPI_Client_ID, NaverAPI_Client_Secret 설정 필요")
            return
        
        print(f"\n✅ 뉴스 수집 완료!")
        print(f"   대상 종목: {result.get('total', 0)}개")
        print(f"   수집 뉴스: {result.get('collected', 0)}개")
        print(f"   저장 완료: {result.get('saved', 0)}개")
        
    except ImportError as e:
        logger.error(f"모듈 임포트 실패: {e}")
        print(f"\n❌ 필요한 패키지가 없습니다.")
        print(f"   pip install google-genai")
    except Exception as e:
        logger.error(f"뉴스 수집 실패: {e}")
        import traceback
        traceback.print_exc()


def run_company_info_cli():
    """기업정보 수집 CLI"""
    logger = logging.getLogger(__name__)
    print("\n🏢 기업정보 수집 시작...")
    
    try:
        from src.services.company_service import collect_company_info_for_candidates
        
        result = collect_company_info_for_candidates(limit=600)
        
        print(f"\n✅ 기업정보 수집 완료!")
        print(f"   대상 종목: {result.get('total', 0)}개")
        print(f"   성공: {result.get('success', 0)}개")
        
    except Exception as e:
        logger.error(f"기업정보 수집 실패: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
