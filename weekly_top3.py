# -*- coding: utf-8 -*-
"""
weekly_top3.py — 주간 TOP3 릴스 스크립트 자동 생성

insights.csv에서 최근 7일 조회수 TOP3를 추출,
"이번 주 쫌봐봐 TOP3" 릴스 스크립트(JSON)를 생성한다.
매주 일요일 cron으로 실행 → pipeline이 영상 제작.

출력: scripts/ 디렉토리에 weekly_top3_YYYYMMDD.json
"""
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(ROOT, "data", "insights.csv")
SCRIPTS_DIR = os.path.join(ROOT, "scripts")


def _int(v):
    try:
        return int(v)
    except (ValueError, TypeError):
        return 0


def load_top3(days=7):
    """최근 N일 조회수 TOP3 반환."""
    if not os.path.exists(CSV_PATH):
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows_by_id = {}

    with open(CSV_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("collected_at", "") < cutoff:
                continue
            mid = row.get("media_id", "")
            existing = rows_by_id.get(mid)
            if not existing or row["collected_at"] > existing["collected_at"]:
                rows_by_id[mid] = row

    ranked = sorted(
        rows_by_id.values(),
        key=lambda r: _int(r.get("views")),
        reverse=True,
    )
    return ranked[:3]


def build_script(top3):
    """TOP3 데이터를 릴스 스크립트 JSON으로 변환."""
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%m월 %d일")

    scenes = []

    # 인트로
    scenes.append({
        "image": None,
        "photo_query": "trending fire news",
        "narration": f"이번 주 가장 많이 본 영상 세 개 모아왔습니다.",
        "subtitle": "🔥 주간 TOP 3",
    })

    # TOP 1~3
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(top3):
        caption = (row.get("caption_preview") or "")[:50].strip()
        views = _int(row.get("views"))
        likes = _int(row.get("like_count"))
        saves = _int(row.get("saved"))

        # 조회수 포맷
        if views >= 10000:
            views_str = f"{views / 10000:.1f}만"
        elif views >= 1000:
            views_str = f"{views / 1000:.1f}천"
        else:
            views_str = str(views)

        narration = f"{i+1}위. {caption}. 조회수 {views_str}회를 기록했습니다."
        scenes.append({
            "image": None,
            "photo_query": caption[:20] if caption else "news trending",
            "narration": narration,
            "subtitle": f"{medals[i]} {i+1}위 — 조회 {views_str}",
        })

    # 아웃트로
    scenes.append({
        "image": None,
        "photo_query": "subscribe follow bell notification",
        "narration": "다음 주에는 어떤 이슈가 TOP에 오를지 궁금하면 팔로우 눌러주이소. 매일 올려드립니다.",
        "subtitle": "팔로우 · 알림 설정",
    })

    script = {
        "title": f"이번 주 쫌봐봐 TOP 3 ({today})",
        "category": "이슈",
        "cover": {
            "hook": "이번 주\n가장 많이 본\nTOP 3",
            "badge": "주간 TOP 3",
            "sub": f"{today} 기준",
        },
        "scenes": scenes,
        "source": "weekly_top3",
    }
    return script


def main():
    top3 = load_top3(days=7)
    if len(top3) < 3:
        print(f"[스킵] TOP3 생성 불가 — 최근 7일 데이터 {len(top3)}건")
        return

    script = build_script(top3)

    os.makedirs(SCRIPTS_DIR, exist_ok=True)
    today_str = datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d")
    out_path = os.path.join(SCRIPTS_DIR, f"weekly_top3_{today_str}.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    print(f"주간 TOP3 스크립트 생성 → {out_path}")
    print(json.dumps(script["cover"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
