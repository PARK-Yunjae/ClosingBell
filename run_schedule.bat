@echo off
chcp 65001 > nul
title ClosingBell
cd /d "C:\Coding\ClosingBell"
call venv\Scripts\activate.bat
python main.py
deactivate
