"""
작업 스케줄러

책임:
- Cron 스케줄 관리
- 작업 등록/해제
- 장 운영일 체크

의존성:
- APScheduler
- services.*
"""

import logging
import time
import traceback
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_MISSED

from src.config.settings import settings
from src.services.data_updater import run_data_update
from src.services.learner_service import run_daily_learning
from src.services.nomad_study import run_nomad_study

logger = logging.getLogger(__name__)


# 한국 공휴일 (2025~2026년, 필요시 추가)
HOLIDAYS_2025_2026 = {
    # 2025년
    date(2025, 1, 1),    # 신정
    date(2025, 1, 28),   # 설날 연휴
    date(2025, 1, 29),   # 설날
    date(2025, 1, 30),   # 설날 연휴
    date(2025, 3, 1),    # 삼일절
    date(2025, 5, 5),    # 어린이날
    date(2025, 5, 6),    # 대체공휴일
    date(2025, 6, 6),    # 현충일
    date(2025, 8, 15),   # 광복절
    date(2025, 10, 3),   # 개천절
    date(2025, 10, 5),   # 추석 연휴
    date(2025, 10, 6),   # 추석
    date(2025, 10, 7),   # 추석 연휴
    date(2025, 10, 8),   # 대체공휴일
    date(2025, 10, 9),   # 한글날
    date(2025, 12, 25),  # 크리스마스
    # 2026년
    date(2026, 1, 1),    # 신정
    date(2026, 2, 16),   # 설날 연휴
    date(2026, 2, 17),   # 설날
    date(2026, 2, 18),   # 설날 연휴
    date(2026, 3, 1),    # 삼일절
    date(2026, 3, 2),    # 대체공휴일
    date(2026, 5, 5),    # 어린이날
    date(2026, 5, 25),   # 부처님오신날
    date(2026, 6, 6),    # 현충일
    date(2026, 8, 15),   # 광복절
    date(2026, 8, 17),   # 대체공휴일
    date(2026, 9, 24),   # 추석 연휴
    date(2026, 9, 25),   # 추석
    date(2026, 9, 26),   # 추석 연휴
    date(2026, 10, 3),   # 개천절
    date(2026, 10, 5),   # 대체공휴일
    date(2026, 10, 9),   # 한글날
    date(2026, 12, 25),  # 크리스마스
}


def is_market_open(check_date: Optional[date] = None) -> bool:
    """장 운영일 체크
    
    Args:
        check_date: 확인할 날짜 (기본: 오늘)
        
    Returns:
        장 운영 여부
    """
    if check_date is None:
        check_date = date.today()
    
    # 주말 체크
    if check_date.weekday() >= 5:  # 토(5), 일(6)
        return False
    
    # 공휴일 체크
    if check_date in HOLIDAYS_2025_2026:
        return False
    
    return True


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
        """기본 스케줄 설정 - v5.1"""
        from src.services.screener_service import (
            run_main_screening,
            run_preview_screening,
        )
        
        # 12:30 프리뷰 스크리닝
        preview_time = settings.screening.screening_time_preview
        preview_hour, preview_minute = map(int, preview_time.split(':'))
        self.add_job(
            job_id='preview_screening',
            func=run_preview_screening,
            hour=preview_hour,
            minute=preview_minute,
        )
        
        # 15:00 메인 스크리닝
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
        
        # 16:30 데이터 갱신 (OHLCV 자동 업데이트)
        self.add_job(
            job_id='daily_data_update',
            func=run_data_update,
            hour=16,
            minute=30,
        )
        
        # v5.2: 17:00 일일 학습 (익일 결과 수집 + 상관관계 분석)
        self.add_job(
            job_id='daily_learning',
            func=run_daily_learning,
            hour=17,
            minute=0,
        )
        
        # v5.2: 17:30 유목민 공부 (TOP5 기업 분석)
        self.add_job(
            job_id='nomad_study',
            func=run_nomad_study,
            hour=17,
            minute=30,
        )
        
        # v5.2: 17:35 Git 자동 커밋
        self.add_job(
            job_id='git_commit',
            func=run_git_commit,
            hour=17,
            minute=35,
        )
        
        logger.info("기본 스케줄 설정 완료 (v5.2: 스크리닝 + 학습 + 공부 + Git)")
    
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
    
    logger = logging.getLogger(__name__)
    
    # 프로젝트 루트 경로
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    try:
        os.chdir(project_root)
        
        # 변경사항 확인
        status = subprocess.run(
            ['git', 'status', '--porcelain'],
            capture_output=True, text=True, timeout=30
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
            capture_output=True, text=True, timeout=30
        )
        
        if result.returncode != 0:
            logger.warning(f"Git commit 실패: {result.stderr}")
            return False
        
        logger.info(f"Git: 커밋 완료 - {commit_msg}")
        
        # git push
        push_result = subprocess.run(
            ['git', 'push'],
            capture_output=True, text=True, timeout=60
        )
        
        if push_result.returncode == 0:
            logger.info("Git: 푸시 완료")
            return True
        else:
            logger.warning(f"Git push 실패: {push_result.stderr}")
            # 커밋은 됐으니 True 반환
            return True
            
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
