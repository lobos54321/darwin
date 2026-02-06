@echo off
title Project Darwin Agent Launcher
cd /d "%~dp0"

echo ------------------------------------------------
echo 🧬 Initializing Project Darwin Agent...
echo ------------------------------------------------

:: 1. Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python not found! Please install Python 3.9+ from python.org
    pause
    exit /b
)

:: 2. Install Dependencies
echo 📦 Installing dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ❌ Failed to install dependencies.
    pause
    exit /b
)

:: 3. Ask for ID
echo.
echo 🤖 Enter your Agent ID (e.g. MyBot_001):
set /p AGENT_ID="> "

if "%AGENT_ID%"=="" (
    set AGENT_ID=Anonymous_%RANDOM%
)

:: 4. Run Agent
echo.
echo 🚀 Launching Agent: %AGENT_ID%
python agent_template/agent.py --id "%AGENT_ID%"

pause
