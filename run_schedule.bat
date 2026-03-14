@echo off
chcp 65001 >nul

echo ============================================
echo ClosingBell v3.7 Scheduler
echo ============================================

cd /d %~dp0
call venv\Scripts\activate

python main.py

echo ============================================
echo Done
echo ============================================
pause
