# -*- coding: utf-8 -*-
"""YouTube Shorts 업로드·연결 점검.

필수 환경변수:
  YOUTUBE_CLIENT_ID
  YOUTUBE_CLIENT_SECRET
  YOUTUBE_REFRESH_TOKEN

기본 업로드 공개범위는 private이다. 공개 전환은 명시적으로 --privacy public을
지정한 경우에만 가능하다.
"""
import argparse
import json
import os
import sys

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def youtube():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        raise RuntimeError(
            "google-api-python-client google-auth google-auth-oauthlib 설치 필요"
        )

    client_id = os.environ.get("YOUTUBE_CLIENT_ID", "")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")
    missing = [
        name for name, value in (
            ("YOUTUBE_CLIENT_ID", client_id),
            ("YOUTUBE_CLIENT_SECRET", client_secret),
            ("YOUTUBE_REFRESH_TOKEN", refresh_token),
        ) if not value
    ]
    if missing:
        raise RuntimeError("환경변수 미설정: " + ", ".join(missing))

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def check():
    yt = youtube()
    result = yt.channels().list(part="snippet,statistics", mine=True).execute()
    items = result.get("items", [])
    if not items:
        raise RuntimeError("연결된 YouTube 채널이 없습니다")
    ch = items[0]
    stats = ch.get("statistics", {})
    print(json.dumps({
        "channel_id": ch.get("id"),
        "title": ch.get("snippet", {}).get("title"),
        "subscribers": stats.get("subscriberCount"),
        "videos": stats.get("videoCount"),
        "views": stats.get("viewCount"),
    }, ensure_ascii=False, indent=2))
    return True


def upload(video, title, description="", privacy="private", category="22"):
    from googleapiclient.http import MediaFileUpload
    if not os.path.isfile(video):
        raise RuntimeError(f"영상 파일 없음: {video}")
    if privacy not in {"private", "unlisted", "public"}:
        raise RuntimeError("privacy는 private, unlisted, public 중 하나여야 합니다")
    yt = youtube()
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "categoryId": str(category),
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(video, mimetype="video/mp4", resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = req.next_chunk()
        if status:
            print(f"업로드 {int(status.progress() * 100)}%")
    print(json.dumps({
        "video_id": response.get("id"),
        "url": f"https://youtu.be/{response.get('id')}",
        "privacy": privacy,
    }, ensure_ascii=False, indent=2))
    return response


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true")
    p.add_argument("--video")
    p.add_argument("--title")
    p.add_argument("--description", default="")
    p.add_argument("--privacy", default="private",
                   choices=["private", "unlisted", "public"])
    args = p.parse_args()
    try:
        if args.check:
            check()
        else:
            if not args.video or not args.title:
                p.error("--video와 --title이 필요합니다")
            upload(args.video, args.title, args.description, args.privacy)
    except Exception as e:
        print(f"[오류] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
