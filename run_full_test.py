#!/usr/bin/env python3
"""
ClosingBell v10.1.1 — 스크리닝 테스트 & 대시보드 데이터 투입
==============================================================

사용법:
    python run_full_test.py                   # 대화형 (단계별 선택)
    python run_full_test.py --step 1          # 특정 단계만 실행
    python run_full_test.py --step 1 2 3      # 여러 단계 실행
    python run_full_test.py --all             # 전체 순차 실행
    python run_full_test.py --status          # DB 현황만 확인

단계:
    0. DB 현황 확인
    1. 스크리닝 테스트 (--run-test, DB 저장 없음)
    2. 스크리닝 실행 (--run --no-alert, DB 저장 O)
    3. 백필 (TOP5 + 유목민 20일)
    4. TOP5 AI 분석 (전체 미분석)
    5. 유목민 AI 분석 (전체 미분석)
    6. 기업정보 수집
    7. 뉴스 수집
    8. 눌림목 스캔 + 추적
    9. 보유종목 동기화
    10. 대시보드 실행
"""

import sys
import os
import logging
import argparse
import sqlite3
import traceback
from pathlib import Path
from datetime import datetime

# 프로젝트 설정
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

DB_PATH = PROJECT_ROOT / "data" / "screener.db"


# ============================================================
# 유틸리티
# ============================================================

def print_header(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_db_status():
    """DB 현황 출력"""
    print_header("📊 DB 현황")
    
    if not DB_PATH.exists():
        print("  ❌ DB 파일 없음! --init-db 먼저 실행하세요.")
        return
    
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    
    # 대시보드 페이지별 데이터 현황
    checks = [
        ("1️⃣  TOP5 히스토리", "closing_top5_history", "screen_date"),
        ("1️⃣  TOP5 일별가격", "top5_daily_prices", "trade_date"),
        ("2️⃣  유목민 후보", "nomad_candidates", "screen_date"),
        ("2️⃣  유목민 뉴스", "nomad_news", None),
        ("3️⃣  기업정보", "company_profiles", None),
        ("4️⃣  거래원 시그널", "broker_signals", None),
        ("6️⃣  보유종목", "holdings_watch", None),
        ("7️⃣  거래량 폭발", "volume_spikes", "spike_date"),
        ("7️⃣  눌림목 시그널", "pullback_signals", "signal_date"),
        ("7️⃣  눌림목 추적", "pullback_daily_prices", "trade_date"),
        ("8️⃣  매매일지", "trade_journal", None),
        ("  ⚙️ 스크리닝 결과", "screenings", None),
        ("  ⚙️ 공매도 일별", "short_selling_daily", None),
        ("  ⚙️ 지지/저항 캐시", "support_resistance_cache", None),
    ]
    
    for label, table, date_col in checks:
        try:
            cnt = c.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
            latest = ""
            if date_col and cnt > 0:
                row = c.execute(f"SELECT MAX({date_col}) FROM [{table}]").fetchone()
                if row and row[0]:
                    latest = f" (최근: {row[0]})"
            
            status = "✅" if cnt > 0 else "⬜"
            print(f"  {status} {label}: {cnt}건{latest}")
        except Exception as e:
            print(f"  ❌ {label}: 오류 ({e})")
    
    # 공매도/SR 데이터 확인
    try:
        row = c.execute("""
            SELECT COUNT(*) FROM closing_top5_history 
            WHERE short_score > 0 OR sr_score > 0
        """).fetchone()
        sr_cnt = row[0]
        total = c.execute("SELECT COUNT(*) FROM closing_top5_history").fetchone()[0]
        print(f"\n  📉 공매도/SR 데이터 있는 TOP5: {sr_cnt}/{total}건")
    except:
        pass
    
    conn.close()


def confirm(msg: str) -> bool:
    """사용자 확인"""
    resp = input(f"\n{msg} (y/n): ").strip().lower()
    return resp in ('y', 'yes', '')


# ============================================================
# Step 함수들
# ============================================================

def step_0():
    """DB 현황 확인"""
    print_db_status()


def step_1():
    """스크리닝 테스트 (DB 저장 없음)"""
    print_header("🧪 Step 1: 스크리닝 테스트 (저장 없음)")
    print("  실행: python main.py --run-test")
    print("  → DB 저장 없음, 알림 없음, 결과만 콘솔 출력")
    print()
    
    from src.infrastructure.logging_config import init_logging
    from src.infrastructure.database import init_database
    init_logging()
    init_database()
    
    from src.services.screener_service import run_screening
    from src.config.settings import settings
    
    result = run_screening(
        screen_time=settings.screening.screening_time_main,
        save_to_db=False,
        send_alert=False,
        is_preview=False,
    )
    
    # 결과 요약
    print(f"\n{'─'*40}")
    print(f"  상태: {result.get('status')}")
    print(f"  분석 종목: {result.get('total_count')}개")
    print(f"  실행 시간: {result.get('execution_time_sec', 0):.1f}초")
    
    top_n = result.get('top_n', [])
    if top_n:
        print(f"\n  🏆 TOP {len(top_n)}:")
        for s in top_n:
            print(f"    #{s.rank} {s.stock_name} ({s.stock_code}) — {s.score_total:.1f}점 [{s.grade.value}]")
    else:
        print("  ❌ 적합한 종목 없음")
    
    return result


def step_2():
    """스크리닝 실행 (DB 저장 O, 알림 X)"""
    print_header("💾 Step 2: 스크리닝 실행 (DB 저장)")
    print("  실행: python main.py --run --no-alert")
    print("  → DB에 저장, Discord 알림 없음")
    print()
    
    from src.infrastructure.logging_config import init_logging
    from src.infrastructure.database import init_database
    init_logging()
    init_database()
    
    from src.services.screener_service import run_screening
    from src.config.settings import settings
    
    result = run_screening(
        screen_time=settings.screening.screening_time_main,
        save_to_db=True,
        send_alert=False,
        is_preview=False,
    )
    
    top_n = result.get('top_n', [])
    print(f"\n  ✅ 스크리닝 완료: {result.get('total_count')}개 분석, TOP {len(top_n)}개 DB 저장")
    
    if top_n:
        for s in top_n:
            print(f"    #{s.rank} {s.stock_name} — {s.score_total:.1f}점")
    
    return result


def step_3():
    """백필 (TOP5 + 유목민)"""
    print_header("🔄 Step 3: 백필 (20일)")
    print("  실행: python main.py --backfill 20")
    print("  → TOP5 히스토리 + 유목민 후보 과거 데이터 수집")
    print()
    
    from src.infrastructure.logging_config import init_logging
    from src.infrastructure.database import init_database
    init_logging()
    init_database()
    
    from src.cli.commands import run_backfill
    run_backfill(days=20, top5=True, nomad=True)


def step_4():
    """TOP5 AI 분석"""
    print_header("🤖 Step 4: TOP5 AI 분석 (전체 미분석)")
    print("  실행: python main.py --run-top5-ai-all")
    print("  → Gemini로 TOP5 종목 AI 분석")
    print()
    
    from src.infrastructure.logging_config import init_logging
    from src.infrastructure.database import init_database
    init_logging()
    init_database()
    
    from src.cli.commands import run_top5_ai_all_cli
    run_top5_ai_all_cli()


def step_5():
    """유목민 AI 분석"""
    print_header("🤖 Step 5: 유목민 AI 분석 (전체 미분석)")
    print("  실행: python main.py --run-ai-analysis-all")
    print("  → Gemini로 유목민 후보 AI 분석")
    print()
    
    from src.infrastructure.logging_config import init_logging
    from src.infrastructure.database import init_database
    init_logging()
    init_database()
    
    from src.cli.commands import run_ai_analysis_all_cli
    run_ai_analysis_all_cli()


def step_6():
    """기업정보 수집"""
    print_header("🏢 Step 6: 기업정보 수집")
    print("  실행: python main.py --run-company-info")
    print("  → 네이버금융에서 기업정보 수집")
    print()
    
    from src.infrastructure.logging_config import init_logging
    from src.infrastructure.database import init_database
    init_logging()
    init_database()
    
    from src.cli.commands import run_company_info_cli
    run_company_info_cli()


def step_7():
    """뉴스 수집"""
    print_header("📰 Step 7: 뉴스 수집")
    print("  실행: python main.py --run-news")
    print("  → 네이버+Gemini 뉴스 수집")
    print()
    
    from src.infrastructure.logging_config import init_logging
    from src.infrastructure.database import init_database
    init_logging()
    init_database()
    
    from src.cli.commands import run_news_collection_cli
    run_news_collection_cli()


def step_8():
    """눌림목 스캔 + 추적"""
    print_header("📉 Step 8: 눌림목 스캔 + 추적")
    print("  → 거래량 폭발 스캔 → 눌림목 시그널 감지 → D+1~D+5 추적")
    print()
    
    from src.infrastructure.logging_config import init_logging
    from src.infrastructure.database import init_database
    init_logging()
    init_database()
    
    # 8a: 거래량 폭발 스캔
    print("  [8a] 거래량 폭발 스캔...")
    try:
        from src.services.pullback_scanner import run_volume_spike_scan
        result = run_volume_spike_scan()
        print(f"    → {result}")
    except Exception as e:
        print(f"    ⚠️ 스킵: {e}")
    
    # 8b: 눌림목 시그널 스캔
    print("\n  [8b] 눌림목 시그널 스캔...")
    try:
        from src.services.pullback_scanner import run_pullback_scan
        result = run_pullback_scan()
        print(f"    → {result}")
    except Exception as e:
        print(f"    ⚠️ 스킵: {e}")
    
    # 8c: 눌림목 D+1~D+5 추적 (패치된 API 폴백 검증!)
    print("\n  [8c] 눌림목 D+1~D+5 추적 (API 폴백 테스트)...")
    try:
        from src.services.pullback_tracker import run_pullback_tracking
        result = run_pullback_tracking()
        print(f"    → {result}")
    except Exception as e:
        print(f"    ⚠️ 스킵: {e}")
    
    # 결과 확인
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    vs = c.execute("SELECT COUNT(*) FROM volume_spikes").fetchone()[0]
    ps = c.execute("SELECT COUNT(*) FROM pullback_signals").fetchone()[0]
    pd = c.execute("SELECT COUNT(*) FROM pullback_daily_prices").fetchone()[0]
    conn.close()
    print(f"\n  📊 결과: 거래량폭발={vs}건, 시그널={ps}건, 추적={pd}건")


def step_9():
    """보유종목 동기화"""
    print_header("💼 Step 9: 보유종목 동기화")
    print("  실행: python main.py --sync-holdings")
    print()
    
    from src.infrastructure.logging_config import init_logging
    from src.infrastructure.database import init_database
    init_logging()
    init_database()
    
    from src.cli.commands import run_holdings_sync_cli
    run_holdings_sync_cli()


def step_10():
    """대시보드 실행"""
    print_header("🖥️ Step 10: 대시보드 실행")
    print("  실행: streamlit run dashboard/app.py")
    print()
    
    import subprocess
    subprocess.run([
        sys.executable, "-m", "streamlit", "run",
        str(PROJECT_ROOT / "dashboard" / "app.py"),
        "--server.port", "8501",
    ])


# ============================================================
# 메인
# ============================================================

STEPS = {
    0: ("DB 현황 확인", step_0),
    1: ("스크리닝 테스트 (저장 없음)", step_1),
    2: ("스크리닝 실행 (DB 저장)", step_2),
    3: ("백필 20일 (TOP5 + 유목민)", step_3),
    4: ("TOP5 AI 분석", step_4),
    5: ("유목민 AI 분석", step_5),
    6: ("기업정보 수집", step_6),
    7: ("뉴스 수집", step_7),
    8: ("눌림목 스캔 + 추적", step_8),
    9: ("보유종목 동기화", step_9),
    10: ("대시보드 실행", step_10),
}


def run_interactive():
    """대화형 모드"""
    print_header("ClosingBell v10.1.1 — 테스트 & 데이터 투입")
    
    # 먼저 현황 보여주기
    step_0()
    
    print(f"\n{'─'*60}")
    print("📋 실행 단계:")
    for num, (name, _) in STEPS.items():
        if num == 0:
            continue
        print(f"  {num:2d}. {name}")
    
    print(f"\n💡 권장 순서:")
    print(f"   먼저:  1 (스크리닝 테스트) → 2 (DB 저장)")
    print(f"   그다음: 3 (백필) → 4,5 (AI) → 6,7 (기업/뉴스) → 8 (눌림목)")
    print(f"   마지막: 0 (현황 확인) → 10 (대시보드)")
    
    while True:
        print()
        choice = input("실행할 단계 번호 (q=종료, 0=현황): ").strip()
        
        if choice.lower() in ('q', 'quit', 'exit'):
            print("\n👋 종료합니다.")
            break
        
        try:
            num = int(choice)
            if num in STEPS:
                name, func = STEPS[num]
                try:
                    func()
                except KeyboardInterrupt:
                    print("\n  ⏹️ 중단됨")
                except Exception as e:
                    print(f"\n  ❌ 오류: {e}")
                    traceback.print_exc()
            else:
                print(f"  ⚠️ 유효한 번호: {list(STEPS.keys())}")
        except ValueError:
            print(f"  ⚠️ 숫자를 입력하세요")


def main():
    parser = argparse.ArgumentParser(description="ClosingBell 테스트 & 데이터 투입")
    parser.add_argument('--step', type=int, nargs='+', help='실행할 단계 번호')
    parser.add_argument('--all', action='store_true', help='전체 순차 실행 (1~9)')
    parser.add_argument('--status', action='store_true', help='DB 현황만 확인')
    parser.add_argument('--quick', action='store_true', help='빠른 테스트 (1→2→8→0)')
    args = parser.parse_args()
    
    if args.status:
        step_0()
        return
    
    if args.all:
        print_header("🚀 전체 순차 실행 (1~9)")
        for num in range(1, 10):
            name, func = STEPS[num]
            print(f"\n{'━'*60}")
            print(f"  [{num}/9] {name}")
            print(f"{'━'*60}")
            try:
                func()
            except KeyboardInterrupt:
                print(f"\n  ⏹️ 중단됨 (Step {num})")
                break
            except Exception as e:
                print(f"\n  ❌ 오류 (계속 진행): {e}")
        
        print(f"\n{'━'*60}")
        step_0()
        print("\n  🖥️ 대시보드: streamlit run dashboard/app.py")
        return
    
    if args.quick:
        print_header("⚡ 빠른 테스트 (스크리닝 → DB저장 → 눌림목 → 현황)")
        for num in [1, 2, 8, 0]:
            name, func = STEPS[num]
            try:
                func()
            except Exception as e:
                print(f"\n  ❌ Step {num} 오류: {e}")
        return
    
    if args.step:
        for num in args.step:
            if num in STEPS:
                name, func = STEPS[num]
                try:
                    func()
                except Exception as e:
                    print(f"\n  ❌ Step {num} 오류: {e}")
                    traceback.print_exc()
            else:
                print(f"  ⚠️ 유효하지 않은 단계: {num}")
        return
    
    # 기본: 대화형
    run_interactive()


if __name__ == "__main__":
    main()
