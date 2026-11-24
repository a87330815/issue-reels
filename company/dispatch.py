# -*- coding: utf-8 -*-
"""AI 콘텐츠 자동화 회사 비서실장 오케스트레이터.

한 번의 대표 지시를 부서별 작업 카드로 분해하고,
각 부서 worker가 독립적으로 처리할 수 있는 큐 파일을 만든다.
실제 게시·삭제·결제·계약은 approval_required로 남긴다.
"""
import argparse
import json
import os
import re
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
    found = []
    for dept, words in DEPARTMENTS.items():
        if any(word.lower() in text.lower() for word in words):
            found.append(dept)
    return found or ["마케팅팀", "경영관리팀"]

def approval_flags(text):
    flags = []
    for word in ["게시", "발행", "삭제", "광고비", "결제", "계약", "발송"]:
        if word in text:
            flags.append(word)
    return flags

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instruction")
    ap.add_argument("--account", default="company")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    job_id = f"job-{now:%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"
    departments = choose_departments(args.instruction)
    approvals = approval_flags(args.instruction)
    jobs = []
    for dept in departments:
        card = {
            "job_id": job_id,
            "department": dept,
            "instruction": args.instruction,
            "account": args.account,
            "status": "queued",
            "approval_required": approvals if dept == "마케팅팀" else [],
            "created_at": now.isoformat(),
        }
        path = QUEUE / dept
        path.mkdir(parents=True, exist_ok=True)
        with open(path / f"{job_id}.json", "w", encoding="utf-8") as f:
            json.dump(card, f, ensure_ascii=False, indent=2)
        jobs.append(card)

    state = {
        "job_id": job_id,
        "instruction": args.instruction,
        "departments": departments,
        "approval_required": approvals,
        "status": "queued",
        "created_at": now.isoformat(),
        "jobs": jobs,
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(json.dumps(state, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
