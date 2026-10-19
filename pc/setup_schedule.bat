@echo off
chcp 65001 >nul
cd /d "%~dp0"

set TASKNAME=IssueReels_DailyCollect
set BATPATH=%~dp0collect_silent.bat

echo Registering daily task: %TASKNAME%
echo Script: %BATPATH%
echo.

schtasks /create /tn "%TASKNAME%" /tr "\"%BATPATH%\"" /sc daily /st 08:00 /f

if errorlevel 1 (
  echo.
  echo [FAILED] Could not register. Try running as administrator.
) else (
  echo.
  echo [OK] Registered. Runs daily at 08:00.
  echo Log goes to: issue-reels\logs\
)

echo.
pause
