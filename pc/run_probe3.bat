@echo off
chcp 65001 >nul
cd /d "%~dp0.."

py -3 -m pip install -q requests 2>nul

echo Searching for price data...
py -3 probe3.py

echo.
pause
