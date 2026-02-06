"""
ClosingBell v9.0 (키움 REST API)

📊 감시종목 7핵심 지표 점수제 (100점 만점):
   CCI·등락률·이격도·연속양봉·거래량비·캔들·거래원 각 13점
   + 보너스 9점 (CCI상승3 + MA20↑3 + 고가≠종가3)

📈 등급: S(85+) / A(75-84) / B(65-74) / C(55-64) / D(<55)

🆕 v9.0 변경사항:
- 매물대(Volume Profile) 표시 추가
- 종목 심층 분석 리포트 (--analyze)
- 분석 대시보드 페이지 추가

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

# 콘솔 인코딩 이슈 방지 (Windows cp949 등)
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

from src.config.settings import settings
from src.config.app_config import APP_FULL_VERSION
from src.infrastructure.database import init_database
from src.infrastructure.scheduler import create_scheduler, is_market_open
from src.infrastructure.logging_config import init_logging
from src.config.validator import validate_settings, ConfigValidationError, print_settings_summary, run_cli_validation

from src.cli.commands import (
    run_backfill,
    run_top5_daily_update,
    run_nomad_study,
    run_news_collection_cli,
    run_company_info_cli,
    run_ai_analysis_cli,
    run_ai_analysis_all_cli,
    run_top5_ai_cli,
    run_top5_ai_all_cli,
    run_holdings_sync_cli,
    run_auto_fill,
    run_pipeline,
    run_holdings_analysis_cli,
)

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
║   🔔  ClosingBell v9.0                                       ║
║                                                              ║
║   📊 7핵심 지표 점수제 (100점 만점)                            ║
║      CCI·등락률·이격도·연속·거래량·캔들·거래원 각 13점          ║
║      + 보너스 9점 (CCI상승3 + MA20↑3 + 고가≠종가3)           ║
║                                                              ║
║   🆕 v9.0 변경사항                                            ║
║      • 매물대(Volume Profile) 표시                            ║
║      • --analyze 종목 심층 리포트                              ║
║      • 분석 대시보드 페이지 추가                              ║
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
    print(f"   [핵심 지표] (91점 만점)")
    print(f"      CCI({d.raw_cci:.0f}):        {d.cci_score:>5.1f}/13")
    print(f"      등락률({d.raw_change_rate:.1f}%):   {d.change_score:>5.1f}/13")
    print(f"      이격도({d.raw_distance:.1f}%):   {d.distance_score:>5.1f}/13")
    print(f"      연속양봉({d.raw_consec_days}일):   {d.consec_score:>5.1f}/13")
    print(f"      거래량비({d.raw_volume_ratio:.1f}x): {d.volume_score:>5.1f}/13")
    print(f"      캔들품질:        {d.candle_score:>5.1f}/13")
    print(f"      거래원:          {d.broker_score:>5.1f}/13")
    
    base_total = (
        d.cci_score + d.change_score + d.distance_score +
        d.consec_score + d.volume_score + d.candle_score +
        d.broker_score
    )
    print(f"      {'─'*20}")
    print(f"      소계:            {base_total:>5.1f}/91")
    print()
    
    # 보너스
    cci_check = "✅" if d.is_cci_rising else "❌"
    ma20_check = "✅" if d.is_ma20_3day_up else "❌"
    candle_check = "❌" if d.is_high_eq_close else "✅"
    
    print(f"   [보너스] (9점 만점)")
    print(f"      CCI 상승중 {cci_check}:    {d.cci_rising_bonus:>5.1f}/3")
    print(f"      MA20 3일↑ {ma20_check}:   {d.ma20_3day_bonus:>5.1f}/3")
    print(f"      고가≠종가 {candle_check}:  {d.not_high_eq_close_bonus:>5.1f}/3")
    
    bonus_total = d.cci_rising_bonus + d.ma20_3day_bonus + d.not_high_eq_close_bonus
    print(f"      {'─'*20}")
    print(f"      소계:            {bonus_total:>5.1f}/9")
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
    screen_time = (settings.screening.screening_time_preview if is_preview 
                   else settings.screening.screening_time_main)
    
    result = run_screening(
        screen_time=screen_time,
        save_to_db=save_to_db,
        send_alert=send_alert,
        is_preview=is_preview,
    )
    
    print_result(result)


def debug_universe(date_str: str):
    """유니버스 비교 디버그 (v6.4 거래량 TOP 방식)
    
    실시간과 백필 유니버스를 비교합니다.
    v6.4: 거래대금 150억+ / 거래량 TOP 150 / 등락률 1~29%
    
    Args:
        date_str: 날짜 문자열 (YYYY-MM-DD)
    """
    from datetime import datetime
    from pathlib import Path
    import json
    import pandas as pd
    
    logger = logging.getLogger(__name__)
    
    print(f"\n{'='*60}")
    print(f"📊 유니버스 비교: {date_str} (v6.4 거래량 TOP)")
    print(f"{'='*60}")
    
    # 필터 조건 출력
    from src.config.backfill_config import get_backfill_config
    config = get_backfill_config()
    
    print(f"\n📋 v6.4 필터 조건:")
    print(f"   - 거래대금: {config.min_trading_value}억원 이상")
    print(f"   - 거래량: 상위 {config.volume_top_n}위")
    print(f"   - 등락률: {config.min_change_rate}% ~ {config.max_change_rate}%")
    print(f"   - CCI 필터: {'사용' if config.use_cci_filter else '미사용'}")
    print(f"   - ETF/스팩 제외: {'있음' if config.exclude_patterns else '없음'}")
    
    # 1. 기존 스냅샷 조회 (있으면 참고용)
    snapshot_codes = []
    snapshot_names = {}
    
    # JSON 파일 확인
    json_path = Path(f"logs/tv200_{date_str}_after_filter.json")
    if json_path.exists():
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            snapshot_codes = [s['code'] for s in data.get('stocks', [])]
            snapshot_names = {s['code']: s['name'] for s in data.get('stocks', [])}
            print(f"\n✅ 기존 스냅샷 (JSON): {len(snapshot_codes)}개 (참고용)")
    
    # 2. 백필 유니버스 계산 (v6.4 방식)
    print(f"\n📊 백필 유니버스 계산 중...")
    
    backfill_service = None
    df_all = None
    df_filtered = None
    
    try:
        from src.services.backfill.backfill_service import HistoricalBackfillService
        from src.services.backfill.data_loader import filter_stocks
        
        backfill_service = HistoricalBackfillService()
        trade_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        
        # 데이터 로드
        backfill_service.load_data(
            start_date=trade_date,
            end_date=trade_date,
        )
        
        # 모든 종목의 당일 데이터 추출
        all_codes = list(backfill_service.ohlcv_data.keys())
        print(f"   OHLCV 종목 수: {len(all_codes)}개")
        
        stock_data_list = []
        for code in all_codes:
            df = backfill_service.ohlcv_data.get(code)
            if df is None or df.empty:
                continue
            
            mask = df['date'].dt.date <= trade_date
            df_until = df[mask]
            
            if len(df_until) < 2:
                continue
            
            last_row = df_until.iloc[-1]
            if last_row['date'].date() != trade_date:
                continue
            
            # 종목명 조회
            name_row = backfill_service.stock_mapping[backfill_service.stock_mapping['code'] == code]
            name = name_row['name'].iloc[0] if len(name_row) > 0 else code
            
            # 등락률 계산
            prev_close = df_until.iloc[-2]['close']
            change_rate = ((last_row['close'] - prev_close) / prev_close * 100) if prev_close > 0 else 0
            
            stock_data_list.append({
                'code': code,
                'name': name,
                'close': int(last_row['close']),
                'change_rate': change_rate,
                'volume': int(last_row['volume']),
                'trading_value': last_row.get('trading_value', last_row['close'] * last_row['volume'] / 100_000_000),
            })
        
        df_all = pd.DataFrame(stock_data_list)
        print(f"   당일 데이터 있는 종목: {len(df_all)}개")
        
        # v6.4 필터 적용
        df_filtered = filter_stocks(df_all, config, backfill_service.stock_mapping)
        backfill_codes = df_filtered['code'].tolist() if len(df_filtered) > 0 else []
        print(f"   필터 후: {len(backfill_codes)}개")
        
    except Exception as e:
        print(f"❌ 백필 유니버스 계산 실패: {e}")
        import traceback
        traceback.print_exc()
        backfill_codes = []
        df_all = pd.DataFrame()
    
    # 3. 필터링 단계별 분석
    if df_all is not None and len(df_all) > 0:
        print(f"\n{'='*60}")
        print("📊 필터링 단계별 분석")
        print(f"{'='*60}")
        
        # 1단계: 거래대금 필터
        df_step1 = df_all[df_all['trading_value'] >= config.min_trading_value]
        print(f"\n1️⃣ 거래대금 {config.min_trading_value}억+ 필터")
        print(f"   {len(df_all)} → {len(df_step1)}개 (제외: {len(df_all) - len(df_step1)}개)")
        
        # 2단계: 등락률 필터
        df_step2 = df_step1[
            (df_step1['change_rate'] >= config.min_change_rate) &
            (df_step1['change_rate'] < config.max_change_rate)
        ]
        print(f"\n2️⃣ 등락률 {config.min_change_rate}~{config.max_change_rate}% 필터")
        print(f"   {len(df_step1)} → {len(df_step2)}개 (제외: {len(df_step1) - len(df_step2)}개)")
        
        # 3단계: 거래량 TOP N
        df_step3 = df_step2.nlargest(config.volume_top_n, 'volume')
        print(f"\n3️⃣ 거래량 TOP {config.volume_top_n}")
        print(f"   {len(df_step2)} → {len(df_step3)}개 (컷: {len(df_step2) - len(df_step3)}개)")
        
        # 최종 결과
        print(f"\n{'─'*60}")
        print(f"✅ 최종 유니버스: {len(df_step3)}개")
        print(f"{'─'*60}")
        
        # 상위 20개 출력
        print(f"\n📋 거래량 TOP 20:")
        print(f"{'순위':<4} {'코드':<8} {'종목명':<14} {'거래량':>12} {'거래대금':>8} {'등락률':>7}")
        print(f"{'─'*60}")
        
        for i, (_, row) in enumerate(df_step3.head(20).iterrows(), 1):
            vol_str = f"{row['volume']:,}"
            print(f"{i:<4} {row['code']:<8} {row['name']:<14} {vol_str:>12} {row['trading_value']:>7.1f}억 {row['change_rate']:>6.2f}%")
    
    # 4. 기존 스냅샷과 비교 (있으면)
    if snapshot_codes and backfill_codes:
        print(f"\n{'='*60}")
        print("📊 기존 스냅샷 vs 백필 비교 (참고)")
        print(f"{'='*60}")
        
        snapshot_set = set(snapshot_codes)
        backfill_set = set(backfill_codes)
        
        common = snapshot_set & backfill_set
        only_snapshot = snapshot_set - backfill_set
        only_backfill = backfill_set - snapshot_set
        
        match_rate = len(common) / len(snapshot_set) * 100 if snapshot_set else 0
        
        print(f"\n📈 기존 스냅샷: {len(snapshot_codes)}개")
        print(f"📉 백필 (v6.4): {len(backfill_codes)}개")
        print(f"✅ 공통: {len(common)}개 ({match_rate:.1f}%)")
        print(f"🔵 스냅샷에만: {len(only_snapshot)}개")
        print(f"🟠 백필에만: {len(only_backfill)}개")
        
        if only_snapshot and len(only_snapshot) <= 10:
            print(f"\n🔵 스냅샷에만 있는 종목:")
            for code in sorted(only_snapshot):
                name = snapshot_names.get(code, code)
                print(f"   {code} {name}")
    
    print(f"\n{'='*60}")
    print("💡 v6.4 거래량 TOP 방식:")
    print("   - 실시간과 백필이 100% 동일한 조건 사용")
    print("   - HTS에서도 동일한 조건으로 검증 가능")
    print("   - CCI/ETF/스팩 제외 없음 (점수제에서 반영)")
    print(f"{'='*60}")


def run_test_mode():
    """테스트 모드 (알림/저장 없음)"""
    logger = logging.getLogger(__name__)
    
    print_banner()
    logger.info("테스트 모드")
    
    result = run_screening(
        screen_time=settings.screening.screening_time_main,
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
    3. Git 커밋
    """
    logger = logging.getLogger(__name__)
    
    print_banner()
    print("\n🔄 모든 서비스 순차 실행 시작...")
    print("=" * 60)
    
    results = {}
    
    # 1. 스크리닝
    print("\n[1/3] 📊 스크리닝 실행...")
    try:
        result = run_screening(
            screen_time=settings.screening.screening_time_main,
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
    print("\n[2/3] 📈 데이터 갱신...")
    try:
        from src.services.data_updater import run_data_update
        run_data_update()
        results['data_update'] = '✅ 성공'
    except Exception as e:
        results['data_update'] = f'❌ 실패: {e}'
        logger.error(f"데이터 갱신 실패: {e}")
    
    # 3. Git 커밋
    print("\n[3/3] 📤 Git 커밋...")
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
    
    from src.adapters.kiwoom_rest_client import get_kiwoom_client
    from src.domain.models import StockData
    from src.domain.score_calculator import ScoreCalculatorV5
    from src.config.constants import MIN_DAILY_DATA_COUNT
    
    client = get_kiwoom_client()
    calculator = ScoreCalculatorV5()
    
    try:
        # 1. 종목명 조회
        current_data = client.get_current_price(stock_code)
        if not current_data:
            print(f"❌ 종목을 찾을 수 없습니다: {stock_code}")
            return
        
        stock_name = current_data.name if hasattr(current_data, 'name') else stock_code
        print(f"📌 {stock_name} ({stock_code})")
        
        # 2. 일봉 데이터 조회
        daily_prices = client.get_daily_prices(stock_code, count=MIN_DAILY_DATA_COUNT + 10)
        
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
            print(f"   ⚠️ 하락 종목은 감시종목 대상이 아닙니다")
        
    except Exception as e:
        logger.error(f"점수 확인 실패: {e}")
        import traceback
        traceback.print_exc()



def run_analyze(stock_code: str, full: bool = False):
    """Generate a short analysis report for a single code."""
    from src.services.analysis_report import generate_analysis_report

    result = generate_analysis_report(stock_code, full=full)
    summary = getattr(result, 'summary', '')
    report_path = getattr(result, 'report_path', '')
    if summary:
        print(f"Analysis: {summary}")
    print(f"Report: {report_path}")

def main():
    parser = argparse.ArgumentParser(description=APP_FULL_VERSION)
    parser.add_argument('--run', action='store_true', help='스크리닝 즉시 실행')
    parser.add_argument('--run-all', action='store_true', help='모든 서비스 순차 실행')
    parser.add_argument('--run-test', action='store_true', help='테스트 모드')
    parser.add_argument('--no-alert', action='store_true', help='알림 없음')
    parser.add_argument('--validate', action='store_true', help='설정 검증')
    parser.add_argument('--healthcheck', action='store_true', help='외부 서비스 연결 점검')
    parser.add_argument('--init-db', action='store_true', help='DB 초기화')
    parser.add_argument('--check', type=str, metavar='CODE', help='특정 종목 점수 확인 (예: --check 074610)')
    parser.add_argument('--analyze', type=str, metavar='CODE', help='Generate analysis report (e.g. --analyze 005930)')
    parser.add_argument('--full', action='store_true', help='Include full broker history in analysis report')
    
    # v6.0 옵션
    parser.add_argument('--backfill', type=int, metavar='DAYS', help='과거 N일 데이터 백필 (TOP5 + 유목민)')
    parser.add_argument('--backfill-top5', type=int, metavar='DAYS', help='TOP5만 백필')
    parser.add_argument('--backfill-nomad', type=int, metavar='DAYS', help='유목민만 백필')
    parser.add_argument('--auto-fill', action='store_true', help='누락 데이터 자동 수집')
    parser.add_argument('--run-pipeline', type=int, metavar='DAYS', help='백필→감시종목 AI→기업정보→뉴스→유목민 AI 순차 실행')
    parser.add_argument('--run-top5-update', action='store_true', help='TOP5 일일 추적 업데이트')
    parser.add_argument('--run-nomad', action='store_true', help='유목민 공부 실행')
    parser.add_argument('--force', action='store_true', help='기존 데이터 삭제 후 재수집 (--run-nomad와 함께 사용)')
    parser.add_argument('--run-news', action='store_true', help='유목민 뉴스 수집 (네이버+Gemini)')
    parser.add_argument('--run-company-info', action='store_true', help='유목민 기업정보 수집 (네이버금융)')
    parser.add_argument('--run-ai-analysis', action='store_true', help='유목민 AI 분석 - 오늘만 (Gemini)')
    parser.add_argument('--run-ai-analysis-all', action='store_true', help='유목민 AI 분석 - 전체 미분석 (백필 포함)')
    parser.add_argument('--run-top5-ai', action='store_true', help='감시종목 TOP5 AI 분석 (Gemini) - 오늘만')
    parser.add_argument('--run-top5-ai-all', action='store_true', help='감시종목 TOP5 AI 분석 - 전체 미분석 (백필용)')
    parser.add_argument('--sync-holdings', action='store_true', help='보유종목 동기화')
    parser.add_argument('--analyze-holdings', action='store_true', help='보유종목 심층 분석 리포트 생성')
    parser.add_argument('--debug-universe', type=str, metavar='DATE', help='유니버스 비교 (TV200 vs 백필) - 예: --debug-universe 2026-01-23')
    parser.add_argument('--version', action='version', version=APP_FULL_VERSION)
    
    args = parser.parse_args()
    
    # --analyze 는 조용히 실행 (요약 + 보고서 경로만 출력)
    if args.analyze:
        logging.basicConfig(level=logging.ERROR)
        run_analyze(args.analyze, full=args.full)
        return

    if args.healthcheck:
        init_logging()
        from src.services.healthcheck_service import run_healthcheck
        results, ok = run_healthcheck()
        print("\n" + "=" * 60)
        print("Healthcheck")
        print("=" * 60)
        for item in results:
            print(f"  {item.name}: {item.status} - {item.message}")
        sys.exit(0 if ok else 1)
    
    # 로깅 설정
    init_logging()
    logger = logging.getLogger(__name__)
    # ??? ????
    try:
        should_continue = run_cli_validation(args.validate, args.run_test)
        if not should_continue:
            return
    except ConfigValidationError as e:
        print(str(e))
        sys.exit(1)

    # DB ?????
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

    if args.run_pipeline:
        run_pipeline(args.run_pipeline)
        return
    
    if args.run_top5_update:
        run_top5_daily_update()
        return
    
    if args.run_nomad:
        run_nomad_study(force=args.force)
        return
    
    if args.run_news:
        run_news_collection_cli()
        return
    
    if args.run_company_info:
        run_company_info_cli()
        return
    
    if args.run_ai_analysis:
        run_ai_analysis_cli()
        return
    
    if args.run_ai_analysis_all:
        run_ai_analysis_all_cli()
        return
    
    if args.run_top5_ai:
        run_top5_ai_cli()
        return
    
    if args.run_top5_ai_all:
        run_top5_ai_all_cli()
        return
    if args.sync_holdings:
        run_holdings_sync_cli()
        return
    if args.analyze_holdings:
        run_holdings_analysis_cli(full=True)
        return
    
    # v6.3.3: 유니버스 비교 디버그
    if args.debug_universe:
        debug_universe(args.debug_universe)
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


if __name__ == "__main__":
    main()
