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
    """사용자 토큰과 페이지 토큰을 모두 지원한다.

    페이지 토큰으로 /me/accounts를 호출하면 Graph API가 accounts 필드를
    지원하지 않아 오류 100을 반환한다. 먼저 /me로 토큰 주체를 확인하고,
    사용자 토큰일 때만 /me/accounts에서 대상 페이지 토큰을 찾는다.
    """
    me = graph("GET", "me", fields="id,name")
    if str(me.get("id")) == str(PAGE_ID):
        print(f"페이지 토큰 확인: {me.get('name', PAGE_ID)}")
        return TOKEN

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
            print(f"사용자 토큰에서 페이지 토큰 선택: {page.get('name', PAGE_ID)}")
            return page.get("access_token") or TOKEN

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

    # finish 성공이 공식 발행 접수 결과다. 일부 페이지 토큰은 발행 후
    # video_id 단건 조회 권한이 없어 GET 시 오류 100을 반환하므로, 그 조회를
    # 발행 실패로 오판하지 않는다.
    if not finish.get("success", False):
        fail(f"페이스북 릴스 발행 접수 실패: {finish}")

    result = {
        "success": True,
        "video_id": video_id,
        "post_id": finish.get("post_id"),
        "page_id": PAGE_ID,
    }
    os.makedirs("out", exist_ok=True)
    with open("out/published_facebook.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("페이스북 릴스 발행 접수 완료")
    print(json.dumps(result, ensure_ascii=False, indent=2))
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
