@echo off
chcp 65001 >nul 2>&1
title ClosingBell Dashboard

echo ========================================
echo  ClosingBell v6.2 - Dashboard
echo ========================================
echo.

:: Check venv
if exist "venv\Scripts\activate.bat" (
    echo [OK] Virtual environment found
    call venv\Scripts\activate.bat
) else (
    echo [WARN] No venv found, using system Python
)

:: Check streamlit
streamlit --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Streamlit not found!
    echo Run: pip install streamlit
    pause
    exit /b 1
)

echo.
echo Starting dashboard...
echo Browser will open automatically
echo Press Ctrl+C to stop
echo.

:: dashboard 폴더로 이동 후 실행 (pages 폴더 인식 위해)
cd dashboard
streamlit run app.py
cd ..

pause
