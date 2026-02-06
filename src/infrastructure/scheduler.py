"""
작업 스케줄러 v8.0

책임:
- Cron 스케줄 관리
- 작업 등록/해제
- 장 운영일 체크

v8.0 스케줄 (14→11개):
- 12:00 프리뷰 스크리닝 (감시종목 TOP5)
- 15:00 메인 스크리닝 (감시종목 TOP5)
- 16:00 OHLCV 수집 (키움 기반)
- 16:10 글로벌 데이터 갱신 (FDR)
- 16:32 유목민 종목 수집
- 16:37 기업정보 크롤링
- 16:39 뉴스 수집
- 16:40 AI 분석 (유목민)
- 16:45 감시종목 AI 분석
- 17:00 Git 커밋
- 17:30 자동 종료

삭제 (v7→v8):
- 15:02 눌림목 스캐너
- 15:05 Quiet Accumulation
- 16:15 결과 수집
- 16:20 일일 학습

의존성:
- APScheduler
- services.*
"""

import logging
import time
import traceback
import os
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_MISSED

from src.config.settings import settings
from src.services.data_updater import run_data_update, update_global_data
from src.utils.market_calendar import is_market_open, HOLIDAYS_KR

logger = logging.getLogger(__name__)


# is_market_open()과 HOLIDAYS_KR은 src.utils.market_calendar에서 import


def market_day_wrapper(func: Callable) -> Callable:
    """장 운영일에만 실행하는 래퍼"""
    def wrapper(*args, **kwargs):
        if is_market_open():
            logger.info(f"장 운영일 - {func.__name__} 실행")
            return func(*args, **kwargs)
        else:
            logger.info(f"휴장일 - {func.__name__} 건너뜀")
            return None
    return wrapper


def _job_listener(event):
    """APScheduler 작업 이벤트 리스너"""
    if hasattr(event, 'job_id'):
        job_id = event.job_id
    else:
        job_id = "unknown"
    
    if event.code == EVENT_JOB_EXECUTED:
        logger.info(f"✅ 작업 실행 완료: {job_id}")
    elif event.code == EVENT_JOB_ERROR:
        logger.error(f"❌ 작업 실행 오류: {job_id}")
        if hasattr(event, 'exception') and event.exception:
            logger.error(f"   예외: {event.exception}")
            logger.error(f"   트레이스백: {traceback.format_exc()}")
    elif event.code == EVENT_JOB_MISSED:
        logger.warning(f"⚠️ 작업 놓침 (missed): {job_id}")


class ScreenerScheduler:
    """스크리너 스케줄러"""
    
    # Heartbeat 간격 (분)
    HEARTBEAT_INTERVAL_MINUTES = 5
    
    def __init__(self, blocking: bool = True):
        """
        Args:
            blocking: True면 BlockingScheduler, False면 BackgroundScheduler
        """
        if blocking:
            self.scheduler = BlockingScheduler(timezone='Asia/Seoul')
        else:
            self.scheduler = BackgroundScheduler(timezone='Asia/Seoul')
        
        self._jobs = {}
        self._start_time = None
        
        # 이벤트 리스너 등록
        self.scheduler.add_listener(
            _job_listener,
            EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED
        )
    
    def add_job(
        self,
        job_id: str,
        func: Callable,
        hour: int,
        minute: int,
        check_market_day: bool = True,
    ):
        """작업 추가
        
        Args:
            job_id: 작업 ID
            func: 실행할 함수
            hour: 실행 시각 (시)
            minute: 실행 시각 (분)
            check_market_day: 장 운영일 체크 여부
        """
        # 장 운영일 체크 래퍼
        if check_market_day:
            wrapped_func = market_day_wrapper(func)
        else:
            wrapped_func = func
        
        # Cron 트리거 (평일만)
        trigger = CronTrigger(
            day_of_week='mon-fri',
            hour=hour,
            minute=minute,
            timezone='Asia/Seoul',
        )
        
        job = self.scheduler.add_job(
            wrapped_func,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            max_instances=1,           # 동시 실행 방지
            coalesce=True,             # 누적된 실행 병합
            misfire_grace_time=300,    # 5분 내 미스파이어 허용
        )
        
        self._jobs[job_id] = job
        logger.info(f"작업 등록: {job_id} ({hour:02d}:{minute:02d})")
    
    def remove_job(self, job_id: str):
        """작업 제거"""
        if job_id in self._jobs:
            self.scheduler.remove_job(job_id)
            del self._jobs[job_id]
            logger.info(f"작업 제거: {job_id}")
    
    def _heartbeat(self):
        """Heartbeat 로그 출력 - 스케줄러가 살아있는지 확인"""
        now = datetime.now()
        uptime = now - self._start_time if self._start_time else timedelta(0)
        uptime_str = str(uptime).split('.')[0]  # 마이크로초 제거
        
        # 다음 작업 시간 계산
        next_jobs = []
        for job in self.scheduler.get_jobs():
            if job.id == 'heartbeat':
                continue
            next_time = getattr(job, 'next_run_time', None)
            if next_time:
                next_jobs.append(f"{job.id}({next_time.strftime('%H:%M')})")
        
        next_jobs_str = ', '.join(next_jobs) if next_jobs else '없음'
        logger.info(f"💓 Heartbeat: 가동시간 {uptime_str}, 대기 작업: {next_jobs_str}")
    
    def _auto_shutdown(self):
        """자동 종료 - 모든 일일 작업 완료 후
        
        ★ 안전 종료: 실행 중인 작업이 있으면 대기
        """
        import threading
        
        now = datetime.now()
        uptime = now - self._start_time if self._start_time else timedelta(0)
        uptime_str = str(uptime).split('.')[0]
        
        logger.info("=" * 50)
        logger.info("🔴 자동 종료 요청")
        logger.info(f"   요청 시간: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"   총 가동시간: {uptime_str}")
        logger.info("=" * 50)
        
        # ★ 실행 중인 작업 체크 (최대 30분 대기)
        def safe_shutdown():
            import time
            import os
            
            max_wait_minutes = 30
            check_interval = 30  # 30초마다 체크
            waited = 0
            
            while waited < max_wait_minutes * 60:
                # 실행 중인 잡 확인
                running_jobs = []
                for job in self.scheduler.get_jobs():
                    # next_run_time이 None이면 현재 실행 중일 수 있음
                    if hasattr(job, 'next_run_time') and job.next_run_time is None:
                        running_jobs.append(job.id)
                
                if not running_jobs:
                    logger.info("✅ 실행 중인 작업 없음. 안전하게 종료합니다.")
                    break
                
                logger.info(f"⏳ 실행 중인 작업 대기: {running_jobs} ({waited//60}분 경과)")
                time.sleep(check_interval)
                waited += check_interval
            
            if waited >= max_wait_minutes * 60:
                logger.warning(f"⚠️ {max_wait_minutes}분 대기 후 강제 종료")
            
            logger.info("🔴 프로그램 종료")
            self.scheduler.shutdown(wait=True)  # wait=True로 변경
            os._exit(0)
        
        shutdown_thread = threading.Thread(target=safe_shutdown, daemon=True)
        shutdown_thread.start()
    
    def _add_heartbeat_job(self):
        """Heartbeat 작업 추가"""
        trigger = IntervalTrigger(
            minutes=self.HEARTBEAT_INTERVAL_MINUTES,
            timezone='Asia/Seoul',
        )
        
        self.scheduler.add_job(
            self._heartbeat,
            trigger=trigger,
            id='heartbeat',
            replace_existing=True,
        )
        logger.info(f"Heartbeat 등록: {self.HEARTBEAT_INTERVAL_MINUTES}분 간격")
    
    def setup_default_schedules(self):
        """기본 스케줄 설정 - v8.0 (감시종목 TOP5 + 유목민)"""
        from src.services.screener_service import (
            run_main_screening,
            run_preview_screening,
        )
        from src.services.nomad_collector import run_nomad_collection
        
        # 12:30 프리뷰 스크리닝
        preview_time = settings.screening.screening_time_preview
        preview_hour, preview_minute = map(int, preview_time.split(':'))
        self.add_job(
            job_id='preview_screening',
            func=run_preview_screening,
            hour=preview_hour,
            minute=preview_minute,
        )
        
        # 15:00 메인 스크리닝 (TOP5 → closing_top5_history 저장)
        main_time = settings.screening.screening_time_main
        main_hour, main_minute = map(int, main_time.split(':'))
        self.add_job(
            job_id='main_screening',
            func=run_main_screening,
            hour=main_hour,
            minute=main_minute,
        )
        
        # Heartbeat 작업 추가 (5분마다)
        self._add_heartbeat_job()
        
        # 16:00 OHLCV 데이터 수집 (키움 기반)
        self.add_job(
            job_id='ohlcv_update',
            func=run_data_update,
            hour=16,
            minute=0,
        )
        
        # 16:10 글로벌 데이터 갱신 (나스닥/다우/환율/코스피/코스닥)
        self.add_job(
            job_id='global_data_update',
            func=update_global_data,
            hour=16,
            minute=10,
        )
        
        # 16:32 유목민 공부법 (상한가/거래량천만 → nomad_candidates)
        # ※ daily_data_update(16:30) 이후 실행해야 CSV에 오늘 데이터 있음
        self.add_job(
            job_id='nomad_collection',
            func=run_nomad_collection,
            hour=16,
            minute=32,
        )
        
        # 16:39 유목민 뉴스 수집 (네이버 뉴스 + Gemini 요약)
        # ※ nomad_collection(16:32) 이후 실행해야 후보 종목이 있음
        try:
            from src.services.news_service import run_news_collection
            self.add_job(
                job_id='news_collection',
                func=run_news_collection,
                hour=16,
                minute=39,
            )
        except ImportError:
            logger.warning("news_service 모듈 없음 - 뉴스 수집 스킵")
        
        # 16:37 기업정보 수집 (네이버 금융 크롤링)
        try:
            from src.services.company_service import run_company_info_collection
            self.add_job(
                job_id='company_info_collection',
                func=run_company_info_collection,
                hour=16,
                minute=37,
            )
        except ImportError:
            logger.warning("company_service 모듈 없음 - 기업정보 수집 스킵")
        
        # 16:40 AI 분석 - 유목민 (Gemini 2.5 Flash)
        try:
            from src.services.ai_service import run_ai_analysis
            self.add_job(
                job_id='ai_analysis',
                func=run_ai_analysis,
                hour=16,
                minute=40,
            )
        except ImportError:
            logger.warning("ai_service 모듈 없음 - AI 분석 스킵")
        
        # 16:45 AI 분석 - 종가매매 TOP5 (Gemini 2.5 Flash)
        try:
            from src.services.top5_ai_service import run_top5_ai_analysis
            self.add_job(
                job_id='top5_ai_analysis',
                func=run_top5_ai_analysis,
                hour=16,
                minute=45,
            )
        except ImportError:
            logger.warning("top5_ai_service 모듈 없음 - TOP5 AI 분석 스킵")

        # 16:48 AI 분석 - 거래원 수급 (Gemini)
        try:
            from src.services.broker_ai_service import run_broker_ai_analysis
            self.add_job(
                job_id='broker_ai_analysis',
                func=run_broker_ai_analysis,
                hour=16,
                minute=48,
            )
        except ImportError:
            logger.warning("broker_ai_service 모듈 없음 - 거래원 AI 분석 스킵")

        # 16:50 보유종목 동기화 + 전체 보유종목 분석 리포트
        try:
            from src.services.account_service import sync_holdings_watchlist
            from src.services.holdings_analysis_service import generate_holdings_reports

            def _holdings_sync_and_analyze():
                # 1단계: 계좌 동기화
                result = sync_holdings_watchlist()
                logger.info(f"[holdings] 동기화 완료: {result}")

                # 2단계: 전체 보유종목 리포트 생성 (매일)
                report_result = generate_holdings_reports(
                    codes=None, full=True, include_sold=True,
                )
                logger.info(
                    f"[holdings] 리포트 생성: "
                    f"{report_result.analyzed}개 성공, "
                    f"{report_result.failed}개 실패"
                )

            self.add_job(
                job_id='holdings_sync',
                func=_holdings_sync_and_analyze,
                hour=16,
                minute=50,
            )
        except ImportError:
            logger.warning("account_service 모듈 없음 - 보유종목 동기화 스킵")

        # Optional: Healthcheck 스케줄 (환경변수 지정 시)
        health_time = os.getenv("SCHEDULE_HEALTHCHECK_TIME", "").strip()
        if health_time:
            try:
                hour, minute = map(int, health_time.split(":"))
                from src.services.healthcheck_service import run_healthcheck

                def _healthcheck_job():
                    results, ok = run_healthcheck()
                    status = "OK" if ok else "WARN/FAIL"
                    logger.info(f"[Healthcheck] {status} ({len(results)} items)")

                self.add_job(
                    job_id='healthcheck',
                    func=_healthcheck_job,
                    hour=hour,
                    minute=minute,
                    check_market_day=False,
                )
            except Exception as e:
                logger.warning(f"healthcheck 스케줄 설정 실패: {e}")

        # Optional: 파이프라인 스케줄 (환경변수 지정 시)
        pipeline_time = os.getenv("SCHEDULE_PIPELINE_TIME", "").strip()
        if pipeline_time:
            try:
                hour, minute = map(int, pipeline_time.split(":"))
                days = int(os.getenv("SCHEDULE_PIPELINE_DAYS", "20"))
                from src.cli.commands import run_pipeline

                self.add_job(
                    job_id='pipeline_run',
                    func=lambda: run_pipeline(days),
                    hour=hour,
                    minute=minute,
                    check_market_day=False,
                )
            except Exception as e:
                logger.warning(f"pipeline 스케줄 설정 실패: {e}")
        
        # 17:00 보유종목 최종 동기화 + Git 자동 커밋
        def _sync_then_commit():
            try:
                from src.services.account_service import sync_holdings_watchlist
                sync_holdings_watchlist()
                logger.info("[git] 커밋 전 보유종목 동기화 완료")
            except Exception as e:
                logger.warning(f"[git] 커밋 전 동기화 실패 (무시): {e}")
            run_git_commit()

        self.add_job(
            job_id='git_commit',
            func=_sync_then_commit,
            hour=17,
            minute=0,
        )
        
        # 17:30 자동 종료 (안전 종료) (모든 작업 완료 후 - 휴장일에도 실행)
        self.add_job(
            job_id='auto_shutdown',
            func=self._auto_shutdown,
            hour=17,
            minute=30,
            check_market_day=False,  # 휴장일에도 종료
        )
        
        logger.info("기본 스케줄 설정 완료 (v8.0: 감시종목 + OHLCV + 글로벌 + 유목민 + 뉴스 + 기업정보 + AI분석)")
    
    def start(self):
        """스케줄러 시작"""
        self._start_time = datetime.now()
        logger.info("=" * 50)
        logger.info("🚀 스케줄러 시작")
        logger.info(f"   시작 시간: {self._start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 50)
        
        # 등록된 작업 출력
        jobs = self.scheduler.get_jobs()
        for job in jobs:
            try:
                next_time = getattr(job, 'next_run_time', None)
                if next_time is None:
                    # trigger에서 다음 실행 시간 계산
                    next_time = job.trigger.get_next_fire_time(None, datetime.now())
                logger.info(f"  - {job.id}: 다음 실행 {next_time}")
            except Exception as e:
                logger.info(f"  - {job.id}: 등록됨 (다음 실행 시간 계산 불가)")
        
        try:
            self.scheduler.start()
        except KeyboardInterrupt:
            logger.info("스케줄러 중지 (Ctrl+C)")
            self.shutdown()
        except Exception as e:
            logger.error(f"❌ 스케줄러 비정상 종료: {e}")
            logger.error(traceback.format_exc())
            self.shutdown()
            raise
    
    def shutdown(self):
        """스케줄러 종료"""
        self.scheduler.shutdown()
        logger.info("스케줄러 종료")
    
    def get_next_run_times(self) -> dict:
        """다음 실행 시각 조회"""
        result = {}
        for job_id, job in self._jobs.items():
            try:
                next_time = getattr(job, 'next_run_time', None)
                if next_time is None:
                    next_time = job.trigger.get_next_fire_time(None, datetime.now())
                result[job_id] = next_time
            except Exception:
                result[job_id] = None
        return result
def create_scheduler(blocking: bool = True) -> ScreenerScheduler:
    """스케줄러 생성 및 기본 설정"""
    scheduler = ScreenerScheduler(blocking=blocking)
    scheduler.setup_default_schedules()
    return scheduler


if __name__ == "__main__":
    # 테스트
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )
    
    print("=== 장 운영일 테스트 ===")
    today = date.today()
    print(f"오늘 ({today}): {'운영' if is_market_open() else '휴장'}")
    
    # 다음 7일 체크
    for i in range(7):
        check_date = today + timedelta(days=i)
        status = '운영' if is_market_open(check_date) else '휴장'
        weekday = ['월', '화', '수', '목', '금', '토', '일'][check_date.weekday()]
        print(f"  {check_date} ({weekday}): {status}")
    
    print("\n=== 스케줄러 설정 테스트 ===")
    scheduler = create_scheduler(blocking=False)
    
    next_runs = scheduler.get_next_run_times()
    for job_id, next_time in next_runs.items():
        print(f"  {job_id}: {next_time}")
    
    # 실제 스케줄러 시작은 하지 않음
    print("\n스케줄러 테스트 완료 (실행하지 않음)")


# ============================================================
# Git 자동 커밋 기능
# ============================================================

def git_auto_commit() -> bool:
    """Git 자동 커밋 및 푸시
    
    Returns:
        성공 여부
    """
    import subprocess
    import os
    import sqlite3
    
    logger = logging.getLogger(__name__)
    
    # 프로젝트 루트 경로
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    try:
        os.chdir(project_root)
        
        # WAL 모드 데이터를 메인 DB로 병합 (Streamlit Cloud 호환)
        db_path = os.path.join(project_root, 'data', 'screener.db')
        if os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path)
                conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                conn.close()
                logger.info("Git: DB WAL 병합 완료")
            except Exception as e:
                logger.warning(f"Git: DB WAL 병합 실패 (무시): {e}")
        
        # 변경사항 확인
        status = subprocess.run(
            ['git', 'status', '--porcelain'],
            capture_output=True, text=True, encoding='utf-8', timeout=30 # 👈 수정
        )
        
        if not status.stdout.strip():
            logger.info("Git: 변경사항 없음")
            return False
        
        # 커밋 메시지 생성
        today = date.today().strftime('%Y-%m-%d')
        commit_msg = f"📊 Daily update {today}"
        
        # git add
        subprocess.run(['git', 'add', '.'], check=True, timeout=30)
        logger.info("Git: 스테이징 완료")
        
        # git commit
        result = subprocess.run(
            ['git', 'commit', '-m', commit_msg],
            capture_output=True, text=True, encoding='utf-8', timeout=30 # 👈 수정
        )
        
        if result.returncode != 0:
            logger.warning(f"Git commit 실패: {result.stderr}")
            return False
        
        logger.info(f"Git: 커밋 완료 - {commit_msg}")
        
        # git push
        push_result = subprocess.run(
            ['git', 'push'],
            capture_output=True, text=True, encoding='utf-8', timeout=60 # 👈 수정
        )
        
        if push_result.returncode == 0:
            logger.info("Git: 푸시 완료")
            return True
        else:
            logger.warning(f"Git push 실패: {push_result.stderr}")
            return False  # 실패 시 False 반환
            
    except subprocess.TimeoutExpired:
        logger.error("Git: 타임아웃")
        return False
    except Exception as e:
        logger.error(f"Git 자동 커밋 실패: {e}")
        return False


def run_git_commit():
    """스케줄러용 Git 커밋 래퍼"""
    logger = logging.getLogger(__name__)
    logger.info("=" * 40)
    logger.info("📤 Git 자동 커밋 시작")
    logger.info("=" * 40)
    
    result = git_auto_commit()
    
    if result:
        logger.info("✅ Git 커밋/푸시 완료")
    else:
        logger.info("ℹ️ Git 커밋 스킵 (변경사항 없음 또는 실패)")