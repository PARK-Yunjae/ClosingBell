@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo  ClosingBell v5.4 - Scheduler Mode
echo ========================================

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo [OK] Virtual environment activated
) else (
    echo [WARN] No venv found, using system Python
)

echo Starting scheduler mode...
python main.py

echo ========================================
echo  Finished
echo ========================================
pause