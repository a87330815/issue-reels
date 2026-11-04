# -*- coding: utf-8 -*-
"""
refresh_token.py — Meta 액세스 토큰 자동 갱신

장기 토큰(60일)을 만료 전에 새 장기 토큰으로 교환한다.
교환된 토큰은 GitHub Secrets에 자동 업데이트된다.

사용:
  python refresh_token.py              # 토큰 상태 확인 + 필요 시 갱신
  python refresh_token.py --force      # 강제 갱신
  python refresh_token.py --check-only # 상태만 확인

환경변수:
  IG_ACCESS_TOKEN   현재 장기 액세스 토큰
  META_APP_ID       Meta 앱 ID
  META_APP_SECRET   Meta 앱 시크릿
  GH_TOKEN          GitHub 토큰 (secrets 업데이트용, optional)
"""
import os
import sys
import time
import json
import requests

TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
APP_ID = os.environ.get("META_APP_ID", "1143191174807326")
APP_SECRET = os.environ.get("META_APP_SECRET", "")
HOST = os.environ.get("IG_API_HOST", "graph.facebook.com")
VERSION = os.environ.get("IG_API_VERSION", "v21.0")

BASE = f"https://{HOST}/{VERSION}"

# 만료 7일 전부터 갱신 시도
RENEW_THRESHOLD_DAYS = 7


def debug_token(token):
    """토큰 정보를 조회한다."""
    r = requests.get(f"{BASE}/debug_token", params={
        "input_token": token,
        "access_token": token,
    })
    data = r.json()
    if "error" in data:
        return None
    return data.get("data", {})


def exchange_long_lived(short_token):
    """단기 토큰 → 장기 토큰(60일) 교환."""
    r = requests.get(f"https://{HOST}/oauth/access_token", params={
        "grant_type": "fb_exchange_token",
        "client_id": APP_ID,
        "client_secret": APP_SECRET,
        "fb_exchange_token": short_token,
    })
    data = r.json()
    if "access_token" in data:
        return data["access_token"], data.get("expires_in", 0)
    raise RuntimeError(f"장기 토큰 교환 실패: {data}")


def refresh_long_lived(current_token):
    """장기 토큰 갱신 (만료 전에만 가능)."""
    r = requests.get(f"https://{HOST}/oauth/access_token", params={
        "grant_type": "fb_exchange_token",
        "client_id": APP_ID,
        "client_secret": APP_SECRET,
        "fb_exchange_token": current_token,
    })
    data = r.json()
    if "access_token" in data:
        return data["access_token"], data.get("expires_in", 0)
    raise RuntimeError(f"토큰 갱신 실패: {data}")


def get_page_token(user_token):
    """유저 토큰으로 페이지 토큰(영구)을 가져온다."""
    r = requests.get(f"{BASE}/me/accounts", params={
        "access_token": user_token,
    })
    data = r.json()
    pages = data.get("data", [])
    if not pages:
        return None, None
    # 첫 번째 페이지의 토큰 (보통 Instagram과 연결된 페이지)
    page = pages[0]
    return page.get("access_token"), page.get("name")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="강제 갱신")
    parser.add_argument("--check-only", action="store_true", help="상태만 확인")
    args = parser.parse_args()

    if not TOKEN:
        print("❌ IG_ACCESS_TOKEN 미설정")
        sys.exit(1)

    if not APP_SECRET:
        print("❌ META_APP_SECRET 미설정 — 토큰 갱신 불가")
        print("  GitHub Secrets에 META_APP_SECRET을 추가해주세요")
        print("  (Meta 개발자 콘솔 → 앱 설정 → 기본 설정 → 앱 시크릿 코드)")
        sys.exit(1)

    # 현재 토큰 상태 확인
    info = debug_token(TOKEN)
    if info is None:
        print("❌ 토큰이 유효하지 않거나 만료됨")
        if args.check_only:
            sys.exit(1)
        print("  → 새 토큰을 Graph API Explorer에서 발급받아 IG_ACCESS_TOKEN에 설정해주세요")
        sys.exit(1)

    is_valid = info.get("is_valid", False)
    expires_at = info.get("expires_at", 0)
    now = int(time.time())

    if expires_at == 0:
        print("✅ 토큰 만료 없음 (영구 토큰)")
        remaining = "영구"
    else:
        remaining_sec = expires_at - now
        remaining_days = remaining_sec / 86400
        remaining = f"{remaining_days:.1f}일"
        print(f"{'✅' if is_valid else '❌'} 토큰 상태: valid={is_valid}, 남은 기간: {remaining}")

    if args.check_only:
        sys.exit(0 if is_valid else 1)

    # 갱신 필요 여부 판단
    need_refresh = args.force
    if not need_refresh and expires_at > 0:
        remaining_sec = expires_at - now
        remaining_days = remaining_sec / 86400
        if remaining_days < RENEW_THRESHOLD_DAYS:
            need_refresh = True
            print(f"⚠ 만료까지 {remaining_days:.1f}일 — 자동 갱신 시작")

    if not need_refresh:
        print(f"✅ 갱신 불필요 (남은 기간: {remaining})")
        return

    # 토큰 갱신
    print("\n🔄 토큰 갱신 중...")
    try:
        new_token, expires_in = refresh_long_lived(TOKEN)
        new_days = expires_in / 86400 if expires_in else "?"
        print(f"✅ 새 토큰 발급 완료 (유효기간: {new_days}일)")

        # 새 토큰으로 페이지 토큰 가져오기
        page_token, page_name = get_page_token(new_token)
        if page_token:
            print(f"✅ 페이지 토큰 확보: {page_name}")
            # 페이지 토큰이 영구인지 확인
            pt_info = debug_token(page_token)
            if pt_info and pt_info.get("expires_at", 1) == 0:
                print("✅ 영구 페이지 토큰 — 이 토큰을 IG_ACCESS_TOKEN에 사용")
                final_token = page_token
            else:
                final_token = new_token
        else:
            final_token = new_token

        # GitHub Actions 출력으로 새 토큰 전달
        gh_output = os.environ.get("GITHUB_OUTPUT", "")
        if gh_output:
            with open(gh_output, "a") as f:
                f.write(f"new_token={final_token}\n")
                f.write(f"token_refreshed=true\n")
            print("✅ GITHUB_OUTPUT에 새 토큰 기록됨")

        # 토큰을 파일로도 저장 (후속 단계에서 사용)
        with open("/tmp/new_ig_token.txt", "w") as f:
            f.write(final_token)

    except RuntimeError as e:
        print(f"❌ {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
