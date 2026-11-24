# -*- coding: utf-8 -*-
"""대표 지시를 계정별·부서별 작업 카드로 분배한다."""
import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "company" / "queue"
STATE = ROOT / "company" / "state.json"
DEPARTMENTS = {
    "고객관리팀": ["고객", "후속", "상담이력", "계약 후"],
    "보험분석팀": ["보장분석", "리모델링", "보험"],
    "영업지원팀": ["TA", "대본", "문자", "거절"],
    "조직운영팀": ["팀장", "리쿠르팅", "실적", "일정"],
    "교육제작팀": ["아침조회", "교육", "문제", "발표"],
    "마케팅팀": ["콘텐츠", "인스타", "유튜브", "틱톡", "페이스북", "조회수", "저장", "공유"],
    "경영관리팀": ["매출", "비용", "목표", "보고서", "효율"],
}

def choose_departments(text):
    found = [dept for dept, words in DEPARTMENTS.items()
             if any(word.lower() in text.lower() for word in words)]
    return found or ["마케팅팀", "경영관리팀"]

def resolve_account(text, requested):
    normalized = text.lower()
    if requested in {"jjombwabwa", "쫌봐봐"} or "쫌봐봐" in text or "jjombwabwa" in normalized:
        return "jjombwabwa"
    if requested in {"richup", "굿리치", "굿리치 리치업지점", "리치업지점"} or "리치업" in text or "굿리치" in text or "richup" in normalized:
        return "richup"
    return "unassigned"

def approval_flags(text):
    return [word for word in ["게시", "발행", "삭제", "광고비", "결제", "계약", "발송"] if word in text]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instruction")
    ap.add_argument("--account", default="unassigned")
    args = ap.parse_args()
    account = resolve_account(args.instruction, args.account)
    now = datetime.now(timezone.utc)
    job_id = f"job-{now:%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"
    departments = choose_departments(args.instruction)
    approvals = approval_flags(args.instruction)
    if account == "unassigned":
        approvals.append("계정 지정")
    jobs = []
    for dept in departments:
        card = {
            "job_id": job_id,
            "department": dept,
            "instruction": args.instruction,
            "account": account,
            "account_status": "identified" if account != "unassigned" else "needs_account_selection",
            "status": "queued" if account != "unassigned" else "needs_account_selection",
            "approval_required": approvals if dept == "마케팅팀" else (["계정 지정"] if account == "unassigned" else []),
            "created_at": now.isoformat(),
        }
        path = QUEUE / dept
        path.mkdir(parents=True, exist_ok=True)
        (path / f"{job_id}.json").write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
        jobs.append(card)
    state = {
        "job_id": job_id,
        "instruction": args.instruction,
        "account": account,
        "account_status": "identified" if account != "unassigned" else "needs_account_selection",
        "departments": departments,
        "approval_required": approvals,
        "status": "queued" if account != "unassigned" else "needs_account_selection",
        "created_at": now.isoformat(),
        "jobs": jobs,
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(state, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
