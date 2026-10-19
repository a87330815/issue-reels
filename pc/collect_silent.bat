@echo off
chcp 65001 >nul
cd /d "%~dp0.."

if not exist "logs" mkdir logs

for /f "tokens=1-3 delims=/- " %%a in ("%date%") do set TODAY=%%a%%b%%c
set LOG=logs\collect_%TODAY%.log

echo ===== %date% %time% ===== >> "%LOG%"
py -3 collect.py >> "%LOG%" 2>&1
echo. >> "%LOG%"
