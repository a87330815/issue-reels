# -*- coding: utf-8 -*-
"""부서 worker 공통 실행기. 현재는 작업 수신·상태 기록 계약을 검증한다."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "company" / "queue"
RESULTS = ROOT / "company" / "results"

def run(department):
    source = QUEUE / department
    cards = sorted(source.glob("*.json")) if source.exists() else []
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = []
    for card_path in cards:
        with open(card_path, encoding="utf-8") as f:
            card = json.load(f)
        result = {
            "job_id": card["job_id"],
            "department": department,
            "status": "received",
            "next_action": "worker implementation pending",
            "approval_required": card.get("approval_required", []),
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        out.append(result)
    with open(RESULTS / f"{department}.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps({"department": department, "received": len(out)}, ensure_ascii=False))

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("department required")
    run(sys.argv[1])
