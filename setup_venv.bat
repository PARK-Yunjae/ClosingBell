@echo off
chcp 65001 > nul
echo ========================================
echo   ClosingBell venv setup
echo ========================================

echo [1/4] Creating venv...
python -m venv venv

echo [2/4] Activating venv...
call venv\Scripts\activate.bat

echo [3/4] Upgrading pip...
python -m pip install --upgrade pip

echo [4/4] Installing packages...
pip install -r requirements.txt

echo.
echo Done!
echo.
echo Usage:
echo   venv\Scripts\activate
echo   python main.py
echo.
pause