@echo off
chcp 65001 > nul

:: 로그 폴더 생성
if not exist "C:\Coding\ClosingBell\logs" mkdir "C:\Coding\ClosingBell\logs"

:: 로그 파일명 (날짜)
set LOGFILE=C:\Coding\ClosingBell\logs\screener_%date:~0,4%%date:~5,2%%date:~8,2%.log

cd /d "C:\Coding\ClosingBell"
call venv\Scripts\activate.bat

:: 콘솔 + 파일 동시 출력
python main.py 2>&1 | powershell -Command "$input | Tee-Object -FilePath '%LOGFILE%' -Append"

deactivate