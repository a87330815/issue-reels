@echo off
chcp 65001 >nul
cd /d "%~dp0.."

if not exist ".env" (
  echo [오류] .env 파일이 없습니다. .env.example을 복사해 인증키를 넣으세요.
  pause
  exit /b 1
)

echo [1/3] 필요 패키지 확인 중...
pip install -q pyyaml requests 2>nul
if errorlevel 1 (
  py -m pip install -q pyyaml requests 2>nul
)

echo [2/3] 수집 시작...
python collect.py
if errorlevel 1 (
  py collect.py
)

echo [3/3] 수집 완료.
pause
