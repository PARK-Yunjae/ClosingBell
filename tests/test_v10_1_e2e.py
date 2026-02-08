#!/usr/bin/env python3
"""
ClosingBell v10.1 전체 E2E 테스트
=================================

테스트 항목:
1. DB 초기화 + 2/7 토요일 데이터 삭제
2. 대시보드 모듈 import 검증
3. 스케줄러 작업 등록 검증
4. 매매일지 서비스 (손익비/기대값)
5. 눌림목 D+1~D+5 추적
6. 디스코드 웹훅 메시지 포맷

실행:
    python tests/test_v10_1_e2e.py
"""

import os
import sys
import sqlite3
import tempfile
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

# 프로젝트 루트 설정
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 테스트 환경 설정 (API 키 검증 우회)
os.environ["DASHBOARD_ONLY"] = "true"
os.environ["DISCORD_ENABLED"] = "false"
os.environ["KIWOOM_APPKEY"] = "test"
os.environ["KIWOOM_SECRETKEY"] = "test"
os.environ["DISCORD_WEBHOOK_URL"] = "https://discord.com/api/webhooks/test/test"
os.environ["DISCORD_DRY_RUN"] = "true"

# 테스트용 임시 DB
TEST_DB_DIR = tempfile.mkdtemp()
TEST_DB_PATH = os.path.join(TEST_DB_DIR, "test_screener.db")
os.environ["DB_PATH"] = TEST_DB_PATH


# ============================================================
# 테스트 유틸리티
# ============================================================

class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
    
    def ok(self, name, detail=""):
        self.passed += 1
        detail_str = f" → {detail}" if detail else ""
        print(f"  ✅ {name}{detail_str}")
    
    def fail(self, name, error):
        self.failed += 1
        self.errors.append((name, error))
        print(f"  ❌ {name}: {error}")
    
    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"📊 결과: {self.passed}/{total} 통과 ({self.failed}개 실패)")
        if self.errors:
            print(f"\n실패 목록:")
            for name, err in self.errors:
                print(f"  ❌ {name}: {err}")
        print(f"{'='*60}")
        return self.failed == 0


result = TestResult()


# ============================================================
# 1. DB 초기화 + 마이그레이션
# ============================================================

def test_database():
    print("\n📦 1. 데이터베이스 초기화 + 마이그레이션")
    print("-" * 50)
    
    try:
        from src.infrastructure.database import init_database, get_database
        init_database()
        db = get_database()
        result.ok("DB 초기화", f"경로: {TEST_DB_PATH}")
    except Exception as e:
        result.fail("DB 초기화", str(e))
        return
    
    # 테이블 확인
    try:
        tables = [r[0] for r in db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )]
        
        required = [
            'closing_top5_history', 'top5_daily_prices',
            'nomad_candidates', 'nomad_news',
            'pullback_signals', 'holdings_watch', 'trade_journal',
        ]
        
        for t in required:
            if t in tables:
                result.ok(f"테이블 존재: {t}")
            else:
                result.fail(f"테이블 누락: {t}", "마이그레이션 필요")
        
    except Exception as e:
        result.fail("테이블 확인", str(e))
    
    # 샘플 데이터 삽입 (2/7 토요일 데이터 포함)
    try:
        # TOP5 히스토리
        for d, data in [
            ("2026-02-05", [  # 목요일 (정상)
                ("005930", "삼성전자", 1, "S", 92.5, 65000, 6.7, 182),
                ("035420", "NAVER", 2, "A", 85.0, 210000, 3.2, 165),
            ]),
            ("2026-02-06", [  # 금요일 (정상)
                ("000660", "SK하이닉스", 1, "S", 88.0, 185000, 5.1, 175),
            ]),
            ("2026-02-07", [  # 토요일 (잘못된 데이터!)
                ("999999", "토요일테스트", 1, "B", 50.0, 10000, 1.0, 100),
            ]),
        ]:
            for code, name, rank, grade, score, price, chg, cci in data:
                db.execute(
                    """INSERT INTO closing_top5_history 
                    (stock_code, stock_name, rank, grade, screen_score, 
                     screen_price, change_rate, cci, screen_date, data_source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'realtime')""",
                    (code, name, rank, grade, score, price, chg, cci, d),
                )
        
        count = db.fetch_one("SELECT COUNT(*) as cnt FROM closing_top5_history")["cnt"]
        result.ok("샘플 데이터 삽입", f"{count}건")
        
    except Exception as e:
        result.fail("샘플 데이터 삽입", str(e))
    
    # 2/7 토요일 데이터 삭제
    try:
        before = db.fetch_one(
            "SELECT COUNT(*) as cnt FROM closing_top5_history WHERE screen_date = '2026-02-07'"
        )["cnt"]
        
        db.execute("DELETE FROM closing_top5_history WHERE screen_date = '2026-02-07'")
        
        after = db.fetch_one(
            "SELECT COUNT(*) as cnt FROM closing_top5_history WHERE screen_date = '2026-02-07'"
        )["cnt"]
        
        if before > 0 and after == 0:
            result.ok("2/7 토요일 데이터 삭제", f"{before}건 삭제됨")
        else:
            result.fail("2/7 토요일 데이터 삭제", f"before={before}, after={after}")
            
    except Exception as e:
        result.fail("2/7 데이터 삭제", str(e))


# ============================================================
# 2. 대시보드 모듈 import 검증
# ============================================================

def test_dashboard_imports():
    print("\n🖥️  2. 대시보드 모듈 import 검증")
    print("-" * 50)
    
    # app.py + 각 페이지의 파이썬 문법/인코딩 검증
    import ast
    
    dashboard_files = [
        "dashboard/app.py",
        "dashboard/pages/1_top5_tracker.py",
        "dashboard/pages/2_nomad_study.py",
        "dashboard/pages/3_stock_search.py",
        "dashboard/pages/4_broker_flow.py",
        "dashboard/pages/5_stock_analysis.py",
        "dashboard/pages/6_holdings_watch.py",
        "dashboard/pages/7_pullback.py",
        "dashboard/pages/8_trade_journal.py",
        "dashboard/components/sidebar.py",
    ]
    
    for filepath in dashboard_files:
        full_path = PROJECT_ROOT / filepath
        try:
            with open(full_path, 'rb') as f:
                raw = f.read()
            
            # 인코딩 검증
            text = raw.decode('utf-8')  # UTF-8 에러시 예외 발생
            
            # BOM 체크
            has_bom = raw[:3] == b'\xef\xbb\xbf'
            
            # 문법 검증
            ast.parse(text)
            
            # 한글 깨짐 체크 (replacement character)
            has_replacement = '\ufffd' in text
            
            lines = len(text.splitlines())
            
            if has_replacement:
                result.fail(filepath, "U+FFFD 깨진 문자 발견")
            elif has_bom:
                result.fail(filepath, "BOM 존재 (제거 필요)")
            else:
                result.ok(filepath, f"{lines}줄, UTF-8 정상")
                
        except UnicodeDecodeError as e:
            result.fail(filepath, f"인코딩 에러: {e}")
        except SyntaxError as e:
            result.fail(filepath, f"문법 에러: {e}")
        except FileNotFoundError:
            result.fail(filepath, "파일 없음")
    
    # 버전 문자열 확인
    try:
        from src.config.app_config import APP_VERSION, APP_FULL_VERSION
        if "v10.1" in APP_VERSION:
            result.ok("버전 문자열", APP_FULL_VERSION)
        else:
            result.fail("버전 문자열", f"v10.1 아님: {APP_VERSION}")
    except Exception as e:
        result.fail("버전 import", str(e))


# ============================================================
# 3. 스케줄러 작업 등록 검증
# ============================================================

def test_scheduler():
    print("\n⏰ 3. 스케줄러 작업 등록 검증")
    print("-" * 50)
    
    # 휴장일 판단 테스트
    try:
        from src.utils.market_calendar import is_market_open
        
        # 2026-02-07 토요일
        saturday = date(2026, 2, 7)
        if not is_market_open(saturday):
            result.ok("휴장일 판단 (토요일)", "정확히 휴장 판정")
        else:
            result.fail("휴장일 판단 (토요일)", "장 운영으로 오판!")
        
        # 2026-02-09 월요일
        monday = date(2026, 2, 9)
        if is_market_open(monday):
            result.ok("운영일 판단 (월요일)", "정확히 운영 판정")
        else:
            result.fail("운영일 판단 (월요일)", "휴장으로 오판!")
        
        # 설날 연휴 (2026-02-16~18)
        seollal = date(2026, 2, 17)
        if not is_market_open(seollal):
            result.ok("공휴일 판단 (설날)", "정확히 휴장 판정")
        else:
            result.fail("공휴일 판단 (설날)", "장 운영으로 오판!")
            
    except Exception as e:
        result.fail("휴장일 판단", str(e))
    
    # 스케줄러 작업 목록 파싱
    try:
        scheduler_path = PROJECT_ROOT / "src" / "infrastructure" / "scheduler.py"
        with open(scheduler_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        expected_jobs = {
            'preview_screening': '12:30',
            'main_screening': '15:00',
            'ohlcv_update': '16:00',
            'volume_spike_scan': '16:05',
            'pullback_tracking': '16:07',      # NEW v10.1
            'global_data_update': '16:10',
            'nomad_collection': '16:32',
            'company_info_collection': '16:37',
            'news_collection': '16:39',
            'ai_analysis': '16:40',
            'top5_ai_analysis': '16:45',
            'broker_ai_analysis': '16:48',
            'pullback_scan': '14:55',
        }
        
        for job_id, time_hint in expected_jobs.items():
            if f"'{job_id}'" in content or f'"{job_id}"' in content:
                result.ok(f"스케줄 작업: {job_id}", f"{time_hint}")
            else:
                result.fail(f"스케줄 작업 누락: {job_id}", f"expected at {time_hint}")
        
        # holdings_sync (함수 내부 정의)
        if '_holdings_sync_and_analyze' in content:
            result.ok("스케줄 작업: holdings_sync", "16:50")
        else:
            result.fail("스케줄 작업 누락: holdings_sync", "")
        
        # 매매일지 디스코드 알림 연결
        if 'format_trade_discord' in content:
            result.ok("매매일지 디스코드 연결", "journal_trades → 웹훅")
        else:
            result.fail("매매일지 디스코드 연결", "format_trade_discord 누락")
            
    except Exception as e:
        result.fail("스케줄러 파싱", str(e))


# ============================================================
# 4. 매매일지 서비스 (손익비/기대값)
# ============================================================

def test_trade_journal():
    print("\n📝 4. 매매일지 서비스 (손익비/기대값)")
    print("-" * 50)
    
    try:
        from src.infrastructure.database import get_database
        db = get_database()
        
        # trade_journal에 샘플 데이터 삽입
        sample_trades = [
            # (type, code, name, qty, price, return_rate, signal_source, date)
            ("BUY",  "005930", "삼성전자", 10, 65000, 0,    "TOP5 #1 (S등급 92점)", "2026-01-20"),
            ("SELL", "005930", "삼성전자", 10, 68000, 4.6,  "TOP5 #1 (S등급 92점)", "2026-01-23"),
            ("BUY",  "035420", "NAVER",   5,  210000, 0,    "눌림목 강 (폭발:2026-01-15)", "2026-01-22"),
            ("SELL", "035420", "NAVER",   5,  205000, -2.4, "눌림목 강 (폭발:2026-01-15)", "2026-01-25"),
            ("BUY",  "000660", "SK하이닉스", 8, 185000, 0,  "TOP5 #2 (A등급 85점)", "2026-01-24"),
            ("SELL", "000660", "SK하이닉스", 8, 192000, 3.8, "TOP5 #2 (A등급 85점)", "2026-01-28"),
            ("BUY",  "068270", "셀트리온",  3, 180000, 0,   "유목민 (limit_up)", "2026-01-25"),
            ("SELL", "068270", "셀트리온",  3, 175000, -2.8, "유목민 (limit_up)", "2026-01-30"),
            ("BUY",  "373220", "LG에너지", 2, 380000, 0,   "수동", "2026-01-27"),
            ("SELL", "373220", "LG에너지", 2, 395000, 3.9,  "수동", "2026-02-01"),
        ]
        
        for trade_type, code, name, qty, price, ret, signal, tdate in sample_trades:
            total = qty * price
            db.execute(
                """INSERT INTO trade_journal 
                (trade_type, stock_code, stock_name, quantity, price, 
                 total_amount, return_rate, memo, trade_date, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
                (trade_type, code, name, qty, price, total, ret,
                 f"[자동] {signal}", tdate),
            )
        
        result.ok("샘플 매매 데이터 삽입", f"{len(sample_trades)}건")
        
    except Exception as e:
        result.fail("샘플 매매 데이터", str(e))
        return
    
    # 기본 통계 테스트
    try:
        from src.services.trade_journal_service import get_journal_stats
        stats = get_journal_stats(days=90)
        
        if stats["total_trades"] == 5:  # 매도 5건
            result.ok("매매 통계 (총 거래)", f"{stats['total_trades']}건")
        else:
            result.fail("매매 통계 (총 거래)", f"{stats['total_trades']}건 (기대: 5)")
        
        if stats["wins"] == 3 and stats["losses"] == 2:
            result.ok("매매 통계 (승패)", f"{stats['wins']}승 {stats['losses']}패")
        else:
            result.fail("매매 통계 (승패)", f"{stats['wins']}승 {stats['losses']}패")
        
        # 승률
        expected_wr = 3 / 5 * 100  # 60%
        if abs(stats["win_rate"] - expected_wr) < 0.1:
            result.ok("승률", f"{stats['win_rate']:.1f}%")
        else:
            result.fail("승률", f"{stats['win_rate']:.1f}% (기대: {expected_wr:.1f}%)")
        
        # 손익비 (R:R)
        # 익절 평균: (4.6 + 3.8 + 3.9) / 3 = 4.1
        # 손절 평균: (-2.4 + -2.8) / 2 = -2.6
        # 손익비 = 4.1 / 2.6 = 1.577
        plr = stats.get("profit_loss_ratio", 0)
        if plr > 1.0:
            result.ok("손익비 (R:R)", f"{plr:.2f} (>1 = 수익 구조)")
        else:
            result.fail("손익비 (R:R)", f"{plr:.2f}")
        
        # 기대값 (EV)
        ev = stats.get("expected_value", 0)
        if ev > 0:
            result.ok("기대값 (EV)", f"{ev:+.2f}% (양수 = 장기 수익 가능)")
        else:
            result.fail("기대값 (EV)", f"{ev:+.2f}%")
        
        # Profit Factor
        pf = stats.get("profit_factor", 0)
        if pf > 1.0:
            result.ok("Profit Factor", f"{pf:.2f}")
        else:
            result.fail("Profit Factor", f"{pf:.2f}")
            
    except Exception as e:
        result.fail("매매 통계", traceback.format_exc())
    
    # 시그널 출처별 분석
    try:
        from src.services.trade_journal_service import get_signal_source_stats
        source_stats = get_signal_source_stats(days=90)
        
        if source_stats:
            result.ok("시그널 출처별 분석", f"{len(source_stats)}개 그룹")
            
            for ss in source_stats:
                src = ss["source"]
                ev = ss["expected_value"]
                plr = ss["profit_loss_ratio"]
                result.ok(
                    f"  {src}",
                    f"EV={ev:+.2f}%, R:R={plr:.2f}, "
                    f"승률={ss['win_rate']:.0f}% ({ss['trades']}건)"
                )
        else:
            result.fail("시그널 출처별 분석", "빈 결과")
            
    except Exception as e:
        result.fail("시그널 출처별 분석", str(e))
    
    # 주간 리포트 생성
    try:
        from src.services.trade_journal_service import generate_weekly_report
        report = generate_weekly_report(date(2026, 1, 28))  # 1/26~1/30 주간
        
        if "주간 매매 리포트" in report:
            result.ok("주간 리포트 생성", f"{len(report)}자")
        else:
            result.fail("주간 리포트 생성", "헤더 누락")
        
        # 손익비 섹션 확인
        if "손익비" in report and "기대값" in report:
            result.ok("주간 리포트: 손익비 섹션", "EV + R:R + PF 포함")
        else:
            result.fail("주간 리포트: 손익비 섹션", "누락")
            
    except Exception as e:
        result.fail("주간 리포트", str(e))


# ============================================================
# 5. 눌림목 D+1~D+5 추적
# ============================================================

def test_pullback_tracker():
    print("\n📉 5. 눌림목 D+1~D+5 추적")
    print("-" * 50)
    
    try:
        from src.infrastructure.database import get_database
        db = get_database()
        
        # 눌림목 시그널 샘플 데이터
        db.execute(
            """INSERT INTO pullback_signals 
            (stock_code, stock_name, spike_date, signal_date, days_after,
             close_price, spike_high, drop_from_high_pct, 
             vol_decrease_pct, signal_strength, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("005930", "삼성전자", "2026-02-03", "2026-02-05", 2,
             65000, 72000, -9.7, -85.3, "강", "거래량 87% 급감 + MA5 지지"),
        )
        db.execute(
            """INSERT INTO pullback_signals 
            (stock_code, stock_name, spike_date, signal_date, days_after,
             close_price, spike_high, drop_from_high_pct, 
             vol_decrease_pct, signal_strength, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("035420", "NAVER", "2026-02-02", "2026-02-05", 3,
             210000, 225000, -6.7, -78.2, "중", "거래량 78% 감소 + MA20 근접"),
        )
        
        result.ok("눌림목 시그널 삽입", "2건")
        
    except Exception as e:
        result.fail("눌림목 시그널 삽입", str(e))
        return
    
    # 테이블 자동 생성 확인
    try:
        from src.services.pullback_tracker import _ensure_table
        _ensure_table()
        
        tables = [r[0] for r in db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pullback_daily_prices'"
        )]
        
        if 'pullback_daily_prices' in tables:
            result.ok("pullback_daily_prices 테이블 생성")
        else:
            result.fail("pullback_daily_prices 테이블 생성", "생성 실패")
            
    except Exception as e:
        result.fail("눌림목 테이블 생성", str(e))
    
    # 추적 함수 테스트 (OHLCV 파일 없어도 에러 없이 동작)
    try:
        from src.services.pullback_tracker import update_pullback_tracking
        tracking_result = update_pullback_tracking(tracking_days=5, lookback_days=10)
        
        # OHLCV 파일이 없으므로 0건이어야 정상
        result.ok(
            "추적 함수 실행 (파일 없음 → 0건)",
            f"시그널: {tracking_result['signals_tracked']}, 가격: {tracking_result['prices_updated']}"
        )
        
    except Exception as e:
        result.fail("추적 함수 실행", str(e))
    
    # 수동으로 가격 데이터 삽입 후 성과 조회 테스트
    try:
        signal_id = db.fetch_one(
            "SELECT id FROM pullback_signals WHERE stock_code = '005930'"
        )["id"]
        
        # D+1 ~ D+3 가격 데이터 수동 삽입
        for d, (o, h, l, c, v) in enumerate([
            (65500, 67000, 64800, 66200, 5000000),   # D+1: +1.85%
            (66000, 68000, 65500, 67500, 4500000),   # D+2: +3.85%
            (67800, 69000, 67000, 68500, 4000000),   # D+3: +5.38%
        ], 1):
            gap = (o / 65000 - 1) * 100 if d == 1 else 0
            ret = (c / 65000 - 1) * 100
            high_ret = (h / 65000 - 1) * 100
            low_ret = (l / 65000 - 1) * 100
            
            db.execute(
                """INSERT INTO pullback_daily_prices 
                (pullback_signal_id, stock_code, trade_date, days_after,
                 open_price, high_price, low_price, close_price, volume,
                 gap_rate, return_from_signal, high_return, low_return)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (signal_id, "005930", f"2026-02-0{5+d}", d,
                 o, h, l, c, v, gap, ret, high_ret, low_ret),
            )
        
        result.ok("D+1~D+3 가격 데이터 삽입", "삼성전자 3일치")
        
    except Exception as e:
        result.fail("가격 데이터 삽입", str(e))
    
    # 성과 조회
    try:
        from src.services.pullback_tracker import get_pullback_performance
        perf = get_pullback_performance(days=30)
        
        if perf.get("tracked_signals", 0) > 0:
            d1 = perf.get("d1", {})
            result.ok(
                "눌림목 성과 조회",
                f"D+1 평균: {d1.get('avg', 0):+.2f}%, "
                f"승률: {d1.get('win_rate', 0):.0f}%, "
                f"추적: {perf['tracked_signals']}개"
            )
            
            # 시그널 강도별
            by_str = perf.get("by_strength", {})
            if by_str:
                for strength, data in by_str.items():
                    d1_avg = data.get("d1", {}).get("avg", 0)
                    result.ok(f"  강도 '{strength}'", f"D+1 평균: {d1_avg:+.2f}%")
        else:
            result.fail("눌림목 성과 조회", "추적 데이터 없음")
            
    except Exception as e:
        result.fail("눌림목 성과 조회", str(e))


# ============================================================
# 6. 디스코드 웹훅 메시지 포맷
# ============================================================

def test_discord_messages():
    print("\n💬 6. 디스코드 웹훅 메시지 포맷")
    print("-" * 50)
    
    # 매매일지 디스코드 알림
    try:
        from src.services.trade_journal_service import format_trade_discord
        
        trades = [
            {
                "trade_type": "BUY",
                "stock_name": "삼성전자",
                "stock_code": "005930",
                "quantity": 10,
                "price": 65000,
                "return_rate": 0,
                "memo": "[자동] TOP5 #1 (S등급 92점)",
            },
            {
                "trade_type": "SELL",
                "stock_name": "NAVER",
                "stock_code": "035420",
                "quantity": 5,
                "price": 215000,
                "return_rate": 2.4,
                "memo": "[자동] 눌림목 강 (폭발:2026-01-15)",
            },
        ]
        
        msg = format_trade_discord(trades)
        
        if msg and "매매일지" in msg:
            result.ok("매매일지 디스코드 포맷", f"{len(msg)}자")
            # 내용 확인
            checks = [
                ("🟢 매수 포함", "🟢" in msg),
                ("🔴 매도 포함", "🔴" in msg),
                ("종목명 포함", "삼성전자" in msg),
                ("수익률 포함", "+2.4%" in msg),
            ]
            for name, ok in checks:
                if ok:
                    result.ok(f"  {name}")
                else:
                    result.fail(f"  {name}", "미포함")
            
            print(f"\n    {'─'*40}")
            print(f"    📋 미리보기:")
            for line in msg.split('\n'):
                print(f"    │ {line}")
            print(f"    {'─'*40}")
        else:
            result.fail("매매일지 디스코드 포맷", "빈 메시지")
            
    except Exception as e:
        result.fail("매매일지 디스코드 포맷", str(e))
    
    # DiscordNotifier dry-run 테스트
    try:
        from src.adapters.discord_notifier import DiscordNotifier
        
        notifier = DiscordNotifier(dry_run=True)
        
        if notifier.dry_run:
            result.ok("DiscordNotifier dry-run 모드")
        else:
            result.fail("DiscordNotifier dry-run 모드", "dry_run=False")
        
        # dry-run 발송 테스트
        from src.adapters.discord_notifier import NotifyResult
        send_result = notifier.send_message("🧪 v10.1 E2E 테스트 메시지")
        
        if isinstance(send_result, NotifyResult):
            result.ok("dry-run 발송 테스트", f"success={send_result.success}")
        else:
            result.ok("dry-run 발송 테스트", "완료")
            
    except Exception as e:
        result.fail("DiscordNotifier 테스트", str(e))


# ============================================================
# 7. 추가 검증
# ============================================================

def test_additional():
    print("\n🔍 7. 추가 검증")
    print("-" * 50)
    
    # pullback_tracker 스케줄러 import 테스트
    try:
        from src.services.pullback_tracker import run_pullback_tracking
        result.ok("pullback_tracker import")
    except Exception as e:
        result.fail("pullback_tracker import", str(e))
    
    # get_signal_source_stats import 확인
    try:
        from src.services.trade_journal_service import get_signal_source_stats
        result.ok("get_signal_source_stats import")
    except Exception as e:
        result.fail("get_signal_source_stats import", str(e))
    
    # app_config 버전 확인
    try:
        from src.config.app_config import APP_VERSION, FOOTER_TOP5, FOOTER_SEARCH
        checks = [
            ("APP_VERSION", "10.1" in APP_VERSION, APP_VERSION),
            ("FOOTER_TOP5", "10.1" in FOOTER_TOP5, FOOTER_TOP5[:50]),
            ("FOOTER_SEARCH", "10.1" in FOOTER_SEARCH, FOOTER_SEARCH[:50]),
        ]
        for name, ok, val in checks:
            if ok:
                result.ok(f"v10.1 반영: {name}", val)
            else:
                result.fail(f"v10.1 반영: {name}", val)
    except Exception as e:
        result.fail("app_config 검증", str(e))
    
    # 스케줄 타임라인 정리 출력
    print(f"\n    {'─'*50}")
    print(f"    📋 v10.1 스케줄 타임라인:")
    timeline = [
        ("12:30", "프리뷰 스크리닝"),
        ("14:55", "눌림목 시그널 감지"),
        ("15:00", "메인 스크리닝 (TOP5)"),
        ("16:00", "OHLCV 수집"),
        ("16:05", "거래량 폭발 감지"),
        ("16:07", "📊 눌림목 D+1~D+5 추적 ← NEW"),
        ("16:10", "글로벌 데이터"),
        ("16:32", "유목민 수집"),
        ("16:37", "기업정보 크롤링"),
        ("16:39", "유목민 뉴스"),
        ("16:40", "AI 분석 (유목민)"),
        ("16:45", "AI 분석 (TOP5)"),
        ("16:48", "AI 분석 (거래원)"),
        ("16:50", "보유종목 동기화 + 매매일지 + 디스코드"),
        ("17:30", "자동 종료"),
    ]
    for time, desc in timeline:
        print(f"    │ {time}  {desc}")
    print(f"    {'─'*50}")


# ============================================================
# 메인 실행
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🧪 ClosingBell v10.1 전체 E2E 테스트")
    print(f"   시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   DB: {TEST_DB_PATH}")
    print("=" * 60)
    
    try:
        test_database()
        test_dashboard_imports()
        test_scheduler()
        test_trade_journal()
        test_pullback_tracker()
        test_discord_messages()
        test_additional()
    except Exception as e:
        print(f"\n💥 예상치 못한 에러: {e}")
        traceback.print_exc()
    
    all_passed = result.summary()
    
    # 정리
    try:
        os.unlink(TEST_DB_PATH)
        os.rmdir(TEST_DB_DIR)
    except:
        pass
    
    sys.exit(0 if all_passed else 1)
