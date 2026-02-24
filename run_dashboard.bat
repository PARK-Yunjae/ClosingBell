@echo off
chcp 65001 > nul
title ClosingBell Dashboard
cd /d "C:\Coding\ClosingBell"
call venv\Scripts\activate.bat
streamlit run dashboard/app.py
deactivate
