@echo off
chcp 65001 > nul
echo ========================================
echo   ClosingBell v2 - venv setup
echo ========================================
echo.

echo [1/4] Creating virtual environment...
python -m venv venv
if errorlevel 1 (
    echo ERROR: Python not found. Install Python first.
    pause
    exit /b 1
)

echo [2/4] Activating venv...
call venv\Scripts\activate.bat

echo [3/4] Upgrading pip...
python -m pip install --upgrade pip

echo [4/4] Installing packages...
pip install -r requirements.txt

echo.
echo ========================================
echo   Setup complete!
echo ========================================
echo.
echo Next steps:
echo   1. copy .env.example .env
echo   2. notepad .env  (fill in API keys)
echo   3. python main.py --screen  (test)
echo.
pause
