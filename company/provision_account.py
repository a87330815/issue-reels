# -*- coding: utf-8 -*-
"""신규 고객 계정의 운영 설정과 에이전트 체크리스트를 생성한다."""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "company" / "accounts"

def slugify(value):
    value = re.sub(r"[^0-9A-Za-z가-힣_-]+", "-", value.strip().lower())
    return value.strip("-") or "new-account"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--topic", required=True)
    ap.add_argument("--audience", required=True)
    ap.add_argument("--platforms", default="instagram,facebook,youtube,tiktok")
    ap.add_argument("--ratio", default="")
    ap.add_argument("--goal", default="조회수,저장,공유,팔로워")
    args = ap.parse_args()

    slug = slugify(args.name)
    platforms = [x.strip() for x in args.platforms.split(",") if x.strip()]
    ratio = {}
    if args.ratio:
        for item in args.ratio.split(","):
            key, value = item.split(":", 1)
            ratio[key.strip()] = int(value.strip())

    data = {
        "id": slug,
        "name": args.name,
        "topic": args.topic,
        "audience": args.audience,
        "platforms": platforms,
        "topic_ratio": ratio,
        "goals": [x.strip() for x in args.goal.split(",") if x.strip()],
        "status": "onboarding",
        "agents": [
            "비서실장", "리서치", "기획", "제작",
            "게시", "성과분석", "품질·준법", "경영관리"
        ],
        "approval_required": ["게시", "삭제", "광고비", "계정 연결"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{slug}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    checklist = f"""# {args.name} 신규 계정 온보딩

- 주제: {args.topic}
- 타깃: {args.audience}
- 플랫폼: {", ".join(platforms)}
- 상태: onboarding

## 에이전트 배정

- 비서실장: 고객 지시 접수와 승인관리
- 리서치: {args.topic} 자료 수집
- 기획: 편성표·대본 설계
- 제작: 영상·카드뉴스 제작
- 게시: 플랫폼별 발행 준비
- 성과분석: 조회수·저장·공유·팔로워 분석
- 품질·준법: 출처·저작권·개인정보 검수
- 경영관리: 월간 성과·비용 보고

## 연결 전 확인

- [ ] 고객 소유 계정 확인
- [ ] OAuth/API 인증정보 등록
- [ ] 브랜드 말투·색상 확정
- [ ] 금지 주제 확정
- [ ] 게시 승인자 지정
"""
    (OUT / f"{slug}.md").write_text(checklist, encoding="utf-8")
    print(json.dumps({"account": slug, "config": str(path), "checklist": f"company/accounts/{slug}.md"}, ensure_ascii=False))

if __name__ == "__main__":
    main()
