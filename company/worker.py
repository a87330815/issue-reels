# -*- coding: utf-8 -*-
"""부서별 작업 카드 처리기. 공통 실행기로 초안 산출물과 승인 상태를 남긴다."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "company" / "queue"
RESULTS = ROOT / "company" / "results"

DELIVERABLES = {
    "고객관리팀": "고객 목록·상담이력·후속 연락 초안",
    "보험분석팀": "보장분석 체크리스트·리모델링 검토 항목",
    "영업지원팀": "TA 대본·문자·거절 대응 초안",
    "조직운영팀": "팀장별 일정·활동·리쿠르팅 후속 과제",
    "교육제작팀": "교육/아침조회 구성안·발표 대본",
    "마케팅팀": "계정별 콘텐츠 기획·게시 전 검수·성과분석 항목",
    "경영관리팀": "목표·매출·비용·업무효율 통합 보고 항목",
}

def run(department):
    source = QUEUE / department
    cards = sorted(source.glob("*.json")) if source.exists() else []
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = []
    for card_path in cards:
        card = json.loads(card_path.read_text(encoding="utf-8"))
        approvals = card.get("approval_required", [])
        out.append({
            "job_id": card["job_id"],
            "department": department,
            "account": card.get("account", "company"),
            "instruction": card.get("instruction", ""),
            "status": "received",
            "deliverable": DELIVERABLES.get(department, "업무 초안"),
            "next_action": "초안 생성 및 검수 대기",
            "approval_required": approvals,
            "received_at": datetime.now(timezone.utc).isoformat(),
        })
    (RESULTS / f"{department}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"department": department, "received": len(out)}, ensure_ascii=False))

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("department required")
    run(sys.argv[1])
