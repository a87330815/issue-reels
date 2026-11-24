# -*- coding: utf-8 -*-
"""매일 게시물 성과를 읽고 다음 편성 개선안을 생성하는 최적화 엔진."""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "company" / "optimization_report.json"

def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def main():
    ig = load(DATA / "instagram_insights.json")
    yt = load(DATA / "youtube_insights.json")
    rows = []
    for source, payload in [("instagram", ig), ("youtube", yt)]:
        items = payload.get("posts") or payload.get("videos") or []
        for item in items:
            rows.append({
                "source": source,
                "title": item.get("title") or item.get("caption") or item.get("name", ""),
                "views": item.get("views", item.get("reach", 0)),
                "saves": item.get("saves", 0),
                "shares": item.get("shares", 0),
                "followers": item.get("followers_gained", 0),
            })
    rows.sort(key=lambda x: (x["shares"], x["saves"], x["views"]), reverse=True)
    top = rows[:5]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_sources": ["instagram_insights.json", "youtube_insights.json"],
        "post_count": len(rows),
        "top_posts": top,
        "agent_actions": {
            "리서치에이전트": "상위 게시물 주제와 출처를 재조사",
            "기획에이전트": "상위 형식을 다음 편성표에 우선 반영",
            "제작에이전트": "첫 2초 후킹과 자막 구조를 상위 게시물 기준으로 개선",
            "게시에이전트": "플랫폼별 게시 시간·제목·해시태그 비교",
            "성과분석에이전트": "조회수보다 저장·공유·팔로워 전환을 함께 평가",
            "품질준법에이전트": "반복 사용 소재의 출처·저작권·광고 위험 재검수",
            "경영관리에이전트": "계정별 투입시간 대비 성과와 수익화 후보 보고",
        },
        "next_cycle": "내일 게시물 분석 후 편성·제작·게시 조건을 다시 조정",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
