# -*- coding: utf-8 -*-
"""
refresh_tiktok_token.py — TikTok 액세스 토큰 갱신

TikTok OAuth 토큰은 24시간 만료. refresh_token으로 갱신한다.
GitHub Actions에서 주기적으로 실행하여 토큰을 유지.

환경변수:
  TIKTOK_CLIENT_KEY       앱 Client Key
  TIKTOK_CLIENT_SECRET    앱 Client Secret
  TIKTOK_REFRESH_TOKEN    리프레시 토큰

사용:
  python refresh_tiktok_token.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_env():
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


load_env()


def refresh():
    import requests

    client_key = os.environ.get("TIKTOK_CLIENT_KEY", "")
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET", "")
    refresh_token = os.environ.get("TIKTOK_REFRESH_TOKEN", "")

    if not all([client_key, client_secret, refresh_token]):
        print("[중단] TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET / "
              "TIKTOK_REFRESH_TOKEN 미설정")
        return 1

    r = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )

    body = r.json()
    if r.status_code != 200 or body.get("error"):
        print(f"[실패] {body}")
        return 1

    new_access = body.get("access_token", "")
    new_refresh = body.get("refresh_token", "")
    open_id = body.get("open_id", "")
    expires_in = body.get("expires_in", 0)

    print(f"토큰 갱신 완료")
    print(f"  open_id:      {open_id[:8]}...")
    print(f"  expires_in:   {expires_in}초 ({expires_in // 3600}시간)")

    # GitHub Actions에서 사용할 수 있도록 출력
    # workflow에서 gh secret set으로 업데이트
    print(f"\n::set-output name=access_token::{new_access}")
    print(f"::set-output name=refresh_token::{new_refresh}")
    print(f"::set-output name=open_id::{open_id}")

    # 로컬 개발용 — .env.tiktok에도 저장
    env_path = os.path.join(ROOT, ".env.tiktok")
    with open(env_path, "w") as f:
        f.write(f"TIKTOK_ACCESS_TOKEN={new_access}\n")
        f.write(f"TIKTOK_OPEN_ID={open_id}\n")
        f.write(f"TIKTOK_REFRESH_TOKEN={new_refresh}\n")
    print(f"\n로컬 저장: {env_path}")

    return 0


if __name__ == "__main__":
    sys.exit(refresh())
