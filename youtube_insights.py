# -*- coding: utf-8 -*-
"""YouTube 채널·영상 성과를 수집해 회사 통합분석에 제공한다."""
import json
import os
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "data", "youtube_insights.json")
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

def credentials():
    required = ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"]
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise RuntimeError("미설정 보안키: " + ", ".join(missing))
    return Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=SCOPES,
    )

yt = build("youtube", "v3", credentials=credentials(), cache_discovery=False)
channel_response = yt.channels().list(
    part="snippet,statistics,contentDetails", mine=True
).execute()
items = channel_response.get("items", [])
if not items:
    raise RuntimeError("연결된 YouTube 채널을 찾지 못했습니다")

channel = items[0]
uploads_playlist = (
    channel.get("contentDetails", {})
    .get("relatedPlaylists", {})
    .get("uploads", "")
)

video_ids = []
if uploads_playlist:
    page_token = None
    while len(video_ids) < 50:
        response = yt.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_playlist,
            maxResults=min(50, 50 - len(video_ids)),
            pageToken=page_token,
        ).execute()
        video_ids.extend(
            item.get("contentDetails", {}).get("videoId", "")
            for item in response.get("items", [])
            if item.get("contentDetails", {}).get("videoId")
        )
        page_token = response.get("nextPageToken")
        if not page_token:
            break

videos = []
if video_ids:
    response = yt.videos().list(
        part="snippet,statistics,status",
        id=",".join(video_ids),
    ).execute()
    for item in response.get("items", []):
        stats = item.get("statistics", {})
        snippet = item.get("snippet", {})
        videos.append({
            "video_id": item.get("id", ""),
            "title": snippet.get("title", ""),
            "published_at": snippet.get("publishedAt", ""),
            "privacy": item.get("status", {}).get("privacyStatus", ""),
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
        })

stats = channel.get("statistics", {})
payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "channel": {
        "channel_id": channel.get("id", ""),
        "title": channel.get("snippet", {}).get("title", ""),
        "subscribers": int(stats.get("subscriberCount", 0)),
        "videos": int(stats.get("videoCount", 0)),
        "views": int(stats.get("viewCount", 0)),
    },
    "recent_videos": sorted(
        videos, key=lambda item: item.get("published_at", ""), reverse=True
    ),
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
print(json.dumps(payload["channel"], ensure_ascii=False, indent=2))
