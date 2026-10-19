@echo off
chcp 65001 >nul
cd /d "%~dp0.."

if not exist ".env" (
  echo [ERROR] .env file not found.
  pause
  exit /b 1
)

echo [1/3] Installing packages...
py -3 -m pip install -q pyyaml requests 2>nul

echo [2/3] Collecting...
py -3 collect.py

echo [3/3] Done.
pause
