@echo off
chcp 65001 >nul
cd /d "%~dp0.."

py -3 -m pip install -q requests 2>nul

echo Searching for price API parameters...
py -3 probe2.py

echo.
pause
