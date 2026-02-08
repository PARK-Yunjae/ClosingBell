"""CLI command handlers for main.py."""
import logging


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
    print(f"   OHLCV: {config.get_active_ohlcv_dir()} (소스: {config.data_source})")
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


def run_nomad_study(force: bool = False):
    """유목민 공부 실행

    Args:
        force: True면 기존 데이터 삭제 후 재수집
    """
    logger = logging.getLogger(__name__)
    print("\n📚 유목민 공부 실행...")

    try:
        from src.services.nomad_collector import run_nomad_collection

        result = run_nomad_collection(force=force)

        if result.get('skipped'):
            print(f"\n⚠️ 이미 {result['total']}개 후보가 있어 스킵됨")
            print("   재수집하려면: python main.py --run-nomad --force")
        else:
            print(f"\n✅ 유목민 수집 완료!")
            print(f"   상한가: {result.get('limit_up', 0)}개")
            print(f"   거래량천만: {result.get('volume_explosion', 0)}개")
            print(f"   총: {result.get('total', 0)}개")

    except Exception as e:
        logger.error(f"유목민 공부 실패: {e}")
        print(f"\n❌ 오류: {e}")


def run_news_collection_cli():
    """유목민 뉴스 수집 CLI"""
    logger = logging.getLogger(__name__)
    print("\n📰 유목민 뉴스 수집 시작...")

    try:
        from src.services.news_service import collect_news_for_candidates

        result = collect_news_for_candidates(limit=1000)

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

        result = collect_company_info_for_candidates(limit=1000)

        print(f"\n✅ 기업정보 수집 완료!")
        print(f"   대상 종목: {result.get('total', 0)}개")
        print(f"   성공: {result.get('success', 0)}개")

    except Exception as e:
        logger.error(f"기업정보 수집 실패: {e}")
        import traceback
        traceback.print_exc()


def run_ai_analysis_cli():
    """AI 분석 CLI (오늘 날짜만)"""
    logger = logging.getLogger(__name__)
    print("\n🤖 AI 분석 시작 (Gemini 2.0 Flash)...")

    try:
        from src.services.ai_service import analyze_candidates_with_ai

        result = analyze_candidates_with_ai(limit=1000)

        print(f"\n✅ AI 분석 완료!")
        print(f"   대상 종목: {result.get('total', 0)}개")
        print(f"   분석 완료: {result.get('analyzed', 0)}개")
        if result.get('failed', 0) > 0:
            print(f"   실패: {result.get('failed', 0)}개")

    except Exception as e:
        logger.error(f"AI 분석 실패: {e}")
        import traceback
        traceback.print_exc()


def run_ai_analysis_all_cli():
    """AI 분석 CLI (전체 미분석 - 백필 포함)"""
    logger = logging.getLogger(__name__)
    print("\n🤖 전체 AI 분석 시작 (백필 데이터 포함)...")

    try:
        from src.services.ai_service import analyze_all_pending

        result = analyze_all_pending(limit=1000)

        print(f"\n✅ 전체 AI 분석 완료!")
        print(f"   대상 종목: {result.get('total', 0)}개")
        print(f"   분석 완료: {result.get('analyzed', 0)}개")
        if result.get('failed', 0) > 0:
            print(f"   실패: {result.get('failed', 0)}개")

    except Exception as e:
        logger.error(f"AI 분석 실패: {e}")
        import traceback
        traceback.print_exc()


def run_top5_ai_cli():
    """감시종목 TOP5 AI 분석 CLI (최신 1일)"""
    logger = logging.getLogger(__name__)

    print("🤖 감시종목 TOP5 AI 분석 시작 (Gemini 2.5 Flash)...")

    try:
        from src.services.top5_ai_service import run_top5_ai_analysis

        result = run_top5_ai_analysis()

        print(f"\n✅ TOP5 AI 분석 완료!")
        print(f"   분석 완료: {result.get('analyzed', 0)}개")
        print(f"   스킵: {result.get('skipped', 0)}개")
        if result.get('failed', 0) > 0:
            print(f"   실패: {result.get('failed', 0)}개")

    except Exception as e:
        logger.error(f"TOP5 AI 분석 실패: {e}")
        import traceback
        traceback.print_exc()


def run_top5_ai_all_cli():
    """감시종목 TOP5 AI 분석 CLI (전체 미분석 - 백필용)"""
    logger = logging.getLogger(__name__)

    print("🤖 감시종목 TOP5 AI 전체 분석 시작 (백필용)...")

    try:
        from src.services.top5_ai_service import run_top5_ai_analysis_all

        result = run_top5_ai_analysis_all()

        print(f"\n✅ TOP5 AI 전체 분석 완료!")
        print(f"   분석 완료: {result.get('analyzed', 0)}개")
        print(f"   스킵: {result.get('skipped', 0)}개")
        if result.get('failed', 0) > 0:
            print(f"   실패: {result.get('failed', 0)}개")

    except Exception as e:
        logger.error(f"TOP5 AI 전체 분석 실패: {e}")
        import traceback
        traceback.print_exc()


def run_holdings_sync_cli():
    """보유종목 동기화 CLI."""
    try:
        from src.services.account_service import sync_holdings_watchlist
        result = sync_holdings_watchlist()
        print("\n✅ 보유종목 동기화 완료")
        print(f"   보유: {result.get('holding_count', 0)}개")
        print(f"   매도 표기: {result.get('sold_marked', 0)}개")
    except Exception as e:
        print(f"\n❌ 보유종목 동기화 오류: {e}")


def run_holdings_analysis_cli(full: bool = True) -> None:
    """보유종목 심층 분석 리포트 생성."""
    try:
        from src.services.holdings_analysis_service import generate_holdings_reports
        result = generate_holdings_reports(full=full)
        print("\n✅ 보유종목 분석 완료")
        print(f"   분석: {result.analyzed}개")
        print(f"   실패: {result.failed}개")
    except Exception as e:
        print(f"\n❌ 보유종목 분석 오류: {e}")


def run_pipeline(days: int = 20) -> None:
    """백필→감시종목 AI→기업정보→뉴스→유목민 AI 순차 실행."""
    logger = logging.getLogger(__name__)
    if days <= 0:
        logger.warning("pipeline days must be positive")
        return

    print("\n🚦 파이프라인 시작")
    print("   1) 백필")
    print("   2) 감시종목 AI")
    print("   3) 기업정보")
    print("   4) 뉴스")
    print("   5) 유목민 AI")

    steps = []

    def _run_step(name, func):
        try:
            print(f"\n▶ {name} 시작...")
            func()
            steps.append((name, "성공"))
        except Exception as e:
            steps.append((name, f"실패: {e}"))
            logger.error(f"pipeline {name} 실패: {e}")

    _run_step(f"백필 {days}일", lambda: run_backfill(days, top5=True, nomad=True))
    _run_step("감시종목 AI (전체)", run_top5_ai_all_cli)
    _run_step("기업정보 수집", run_company_info_cli)
    _run_step("뉴스 수집", run_news_collection_cli)
    _run_step("유목민 AI (전체)", run_ai_analysis_all_cli)

    print("\n" + "=" * 60)
    print("파이프라인 요약")
    print("=" * 60)
    for name, status in steps:
        print(f"  - {name}: {status}")
