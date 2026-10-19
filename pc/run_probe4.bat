@echo off
chcp 65001 >nul
cd /d "%~dp0.."

py -3 -m pip install -q requests 2>nul

echo Probing apartment trade API...
py -3 probe4.py

echo.
pause
