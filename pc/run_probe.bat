@echo off
chcp 65001 >nul
cd /d "%~dp0"

py -3 -m pip install -q requests python-dotenv 2>nul

echo Running API probe...
py -3 probe.py

echo.
echo Done. Check out/ folder for results.
pause
