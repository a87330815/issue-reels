@echo off
chcp 65001 >nul
cd /d "%~dp0.."

if not exist ".env" (
  echo [오류] .env 파일이 없습니다.
  echo .env.example 파일을 복사해서 .env로 이름을 바꾸고 인증키를 넣으세요.
  pause
  exit /b 1
)

echo [1/3] 필요 패키지 확인 중...
py -3 -m pip install -q pyyaml requests 2>nul

echo [2/3] 수집 시작...
py -3 collect.py
if errorlevel 1 (
  echo.
  echo [오류] 실행 실패. 위의 에러 메시지를 캡처해서 보내주세요.
)

echo.
echo [3/3] 완료.
pause
