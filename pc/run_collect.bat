@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist ".env" (
  echo [오류] .env 파일이 없습니다. .env.example을 복사해 인증키를 넣으세요.
  pause
  exit /b 1
)
python collect.py
if errorlevel 1 (
  echo [오류] 수집 실패
  exit /b 1
)
echo [완료] out\collected.json 갱신됨
