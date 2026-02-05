@echo off
chcp 65001 >nul
cd /d C:\Coding\ClosingBell

echo ============================================
echo ClosingBell v6.5 Scheduler Start
echo ============================================

call venv\Scripts\activate

python main.py

pause