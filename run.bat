@echo off
REM Distributed Banking Management System - Windows Launcher
title Distributed Banking Management System (ADBMS)

cd /d "%~dp0"

if not exist "venv" (
    echo [*] Creating Python virtual environment...
    python -m venv venv
    venv\Scripts\pip install -r requirements.txt
)

echo [*] Activating virtual environment...
call venv\Scripts\activate.bat

echo [*] Starting Distributed Banking Server...
echo [*] Open your browser at: http://127.0.0.1:5050
python app.py
pause
