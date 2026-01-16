@echo off
chcp 65001 >nul 2>&1
title ClosingBell Debug

echo ========================================
echo  ClosingBell v5.3 - Debug Mode
echo ========================================
echo.

:: Check venv
if exist "venv\Scripts\activate.bat" (
    echo [OK] Virtual environment found
    call venv\Scripts\activate.bat
) else (
    echo [WARN] No venv found, using system Python
)

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    pause
    exit /b 1
)

echo.
echo Select mode:
echo   1. Run screening now (--run)
echo   2. Run K-breakout now (--run-k)
echo   3. Run all services (--run-all)
echo   4. Check status (--status)
echo   5. Scheduler mode (default)
echo.

set /p choice="Enter choice (1-5): "

if "%choice%"=="1" (
    echo.
    echo Running screening...
    python main.py --run
) else if "%choice%"=="2" (
    echo.
    echo Running K-breakout...
    python main.py --run-k
) else if "%choice%"=="3" (
    echo.
    echo Running all services...
    python main.py --run-all
) else if "%choice%"=="4" (
    echo.
    echo Checking status...
    python main.py --status
) else (
    echo.
    echo Starting scheduler...
    python main.py
)

echo.
echo ========================================
echo  Finished
echo ========================================
pause
