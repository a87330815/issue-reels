# -*- coding: utf-8 -*-
"""부서별 작업 카드 처리기. 계정 규칙을 반영한 초안·검수·승인 상태를 남긴다."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "company" / "queue"
RESULTS = ROOT / "company" / "results"
ACCOUNTS = ROOT / "company" / "accounts.json"

DELIVERABLES = {
    "고객관리팀": ("고객 목록·상담이력·후속 연락 초안", ["개인정보 범위 확인", "후속 연락 일정"]),
    "보험분석팀": ("보장분석 체크리스트·리모델링 검토 항목", ["약관·가입자료 확인", "상품 단정 금지"]),
    "영업지원팀": ("TA 대본·문자·거절 대응 초안", ["고객 동의 여부", "발송 전 검수"]),
    "조직운영팀": ("팀장별 일정·활동·리쿠르팅 후속 과제", ["담당자 지정", "기한 지정"]),
    "교육제작팀": ("교육/아침조회 구성안·발표 대본", ["출처 확인", "발표자 지정"]),
    "마케팅팀": ("계정별 콘텐츠 기획·게시 전 검수·성과분석 항목", ["출처·저작권 확인", "게시 승인"]),
    "경영관리팀": ("목표·매출·비용·업무효율 통합 보고 항목", ["수치 근거 확인", "대표 보고"]),
}

def load_accounts():
    try:
        return json.loads(ACCOUNTS.read_text(encoding="utf-8"))
    except Exception:
        return {"accounts": []}

def account_rules(account_id):
    for account in load_accounts().get("accounts", []):
        if account.get("id") == account_id or account.get("name") == account_id:
            return account
    return {}

def run(department):
    source = QUEUE / department
    cards = sorted(source.glob("*.json")) if source.exists() else []
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = []
    for card_path in cards:
        card = json.loads(card_path.read_text(encoding="utf-8"))
        deliverable, checks = DELIVERABLES.get(department, ("업무 초안", ["내용 검수"]))
        rules = account_rules(card.get("account", ""))
        approvals = list(dict.fromkeys(card.get("approval_required", [])))
        if rules.get("approval_required") and department in {"마케팅팀", "보험분석팀"}:
            approvals.extend(rules["approval_required"])
        out.append({
            "job_id": card["job_id"],
            "department": department,
            "account": card.get("account", "company"),
            "instruction": card.get("instruction", ""),
            "status": "draft_ready",
            "deliverable": deliverable,
            "quality_checks": checks,
            "account_rules_loaded": bool(rules),
            "approval_required": list(dict.fromkeys(approvals)),
            "next_action": "검수 완료 후 승인 대기" if approvals else "검수 후 다음 부서 단계 진행",
            "received_at": datetime.now(timezone.utc).isoformat(),
        })
    (RESULTS / f"{department}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"department": department, "draft_ready": len(out)}, ensure_ascii=False))

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("department required")
    run(sys.argv[1])
