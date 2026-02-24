@echo off
chcp 65001 > nul
title ClosingBell v2
cd /d "C:\Coding\ClosingBell"
call venv\Scripts\activate.bat
python main.py
deactivate
