# -*- coding: utf-8 -*-
"""Facebook 페이지에 공개 URL의 MP4를 릴스로 발행한다."""
import argparse
import json
import os
import sys
import time

import requests

API_VERSION = os.environ.get("FB_API_VERSION", "v26.0")
BASE = f"https://graph.facebook.com/{API_VERSION}"
TOKEN = os.environ.get("FB_ACCESS_TOKEN") or os.environ.get("IG_ACCESS_TOKEN", "")
PAGE_ID = os.environ.get("FB_PAGE_ID", "1277209758815845")
MANIFEST = os.environ.get("UPLOAD_MANIFEST", "out/uploaded.json")


def fail(message):
    print(f"::error::{message}")
    raise SystemExit(1)


def graph(method, path, token=None, **params):
    headers = {"Authorization": f"Bearer {token or TOKEN}"}
    url = f"{BASE}/{path.lstrip('/')}"
    r = requests.request(method, url, headers=headers, data=params or None, timeout=60)
    try:
        body = r.json()
    except ValueError:
        fail(f"Graph API 응답 오류: HTTP {r.status_code} {r.text[:200]}")
    if r.status_code >= 400 or "error" in body:
        err = body.get("error", {})
        fail(f"Graph API 오류 [{err.get('code', r.status_code)}]: {err.get('message', body)}")
    return body


def page_token():
    """사용자 토큰과 페이지 토큰을 모두 지원한다."""
    accounts = graph(
        "GET",
        "me/accounts",
        fields="id,name,access_token,tasks",
        limit=100,
    )
    for page in accounts.get("data", []):
        if str(page.get("id")) == str(PAGE_ID):
            tasks = set(page.get("tasks") or [])
            if tasks and "CREATE_CONTENT" not in tasks:
                fail("쫌봐봐 페이지에 CREATE_CONTENT 권한이 없습니다.")
            return page.get("access_token") or TOKEN

    # 이미 페이지 토큰이면 /me/accounts가 비어 있을 수 있다.
    me = graph("GET", "me", fields="id,name")
    if str(me.get("id")) == str(PAGE_ID):
        return TOKEN
    fail("액세스 토큰에서 쫌봐봐 페이지를 찾지 못했습니다.")


def load_target():
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            items = json.load(f).get("items", [])
    except (OSError, ValueError) as e:
        fail(f"업로드 매니페스트를 읽지 못했습니다: {e}")
    if not items:
        fail("업로드된 영상이 없습니다.")
    item = items[0]
    if item.get("verify_failed") or not item.get("video_url"):
        fail("공개 접근이 확인된 video_url이 없습니다.")
    return item


def caption_from_script(path):
    if not path or not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        script = json.load(f)
    lines = [script.get("title", "").strip()]
    subtitles = [
        s.get("subtitle", "").strip()
        for s in script.get("scenes", [])
        if s.get("subtitle")
    ]
    lines.extend(s for s in subtitles[:4] if "프로필" not in s and "팔로우" not in s)
    attribution = (script.get("meta") or {}).get("attribution")
    if attribution:
        lines.append(f"출처: {attribution}")
    lines.extend(["", "유용했다면 저장하고 공유해 주세요.", "#쫌봐봐 #릴스"])
    return "\n".join(x for x in lines if x is not None).strip()


def publish(video_url, description, token):
    # 1) Facebook Reels 업로드 세션 생성
    start = graph(
        "POST",
        f"{PAGE_ID}/video_reels",
        token=token,
        upload_phase="start",
    )
    video_id = str(start.get("video_id") or "")
    upload_url = start.get("upload_url")
    if not video_id or not upload_url:
        fail(f"릴스 업로드 세션 생성 실패: {start}")

    # 2) Meta가 공개 URL에서 영상을 가져가도록 전달
    headers = {
        "Authorization": f"OAuth {token}",
        "file_url": video_url,
    }
    r = requests.post(upload_url, headers=headers, timeout=120)
    try:
        uploaded = r.json()
    except ValueError:
        fail(f"영상 전달 응답 오류: HTTP {r.status_code} {r.text[:200]}")
    if r.status_code >= 400 or not uploaded.get("success", False):
        fail(f"영상 전달 실패: {uploaded}")

    # 3) 실제 공개 발행
    finish = graph(
        "POST",
        f"{PAGE_ID}/video_reels",
        token=token,
        upload_phase="finish",
        video_id=video_id,
        video_state="PUBLISHED",
        description=description,
    )

    # 처리 결과가 바로 안 보일 수 있어 짧게 상태를 확인한다.
    for _ in range(12):
        status = graph(
            "GET",
            video_id,
            token=token,
            fields="status,permalink_url",
        )
        processing = (status.get("status") or {}).get("video_status")
        if processing in ("ready", "published", "complete"):
            break
        if processing in ("error", "expired"):
            fail(f"페이스북 릴스 처리 실패: {status}")
        time.sleep(5)

    print("페이스북 릴스 발행 완료")
    print("video_id:", video_id)
    if finish.get("post_id"):
        print("post_id:", finish["post_id"])
    return video_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", help="캡션을 만들 대본 JSON")
    args = ap.parse_args()

    if not TOKEN:
        fail("FB_ACCESS_TOKEN 또는 IG_ACCESS_TOKEN 시크릿이 없습니다.")
    print("::add-mask::" + TOKEN)
    token = page_token()
    print("::add-mask::" + token)

    item = load_target()
    description = caption_from_script(args.script)
    publish(item["video_url"], description, token)


if __name__ == "__main__":
    main()
