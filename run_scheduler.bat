@echo off
REM ClosingBell 스케줄러 실행
REM 사용법: run_scheduler.bat

echo ============================================
echo ClosingBell v6.5 스케줄러 시작
echo ============================================

REM 가상환경 활성화
call venv\Scripts\activate

REM 스케줄러 실행
python main.py --run-scheduler

pause
