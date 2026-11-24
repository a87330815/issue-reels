# -*- coding: utf-8 -*-
"""부서별 worker 결과를 비서실장 통합보고로 집계한다."""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "company" / "results"
OUT = ROOT / "company" / "executive_report.json"
MD = ROOT / "company" / "executive_report.md"

items = []
for path in sorted(RESULTS.glob("*.json")):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items.extend(data if isinstance(data, list) else [data])
    except Exception as exc:
        items.append({"department": path.stem, "status": "error", "error": type(exc).__name__})

state = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "total_tasks": len(items),
    "queued": sum(1 for x in items if x.get("status") == "queued"),
    "received": sum(1 for x in items if x.get("status") == "received"),
    "draft_ready": sum(1 for x in items if x.get("status") == "draft_ready"),
    "completed": sum(1 for x in items if x.get("status") == "completed"),
    "failed": sum(1 for x in items if x.get("status") == "failed"),
    "approval_required": sorted({a for x in items for a in x.get("approval_required", [])}),
    "departments": items,
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
lines = [
    "# 비서실장 통합 업무보고",
    "",
    f"- 생성시각: {state['generated_at']}",
    f"- 전체 작업: {state['total_tasks']}건",
    f"- 수신: {state['received']}건 · 초안완료: {state['draft_ready']}건 · 완료: {state['completed']}건 · 실패: {state['failed']}건",
    "",
    "## 부서별 현황",
    "",
    "| 부서 | 상태 | 승인 필요 |",
    "|---|---|---|",
]
for x in items:
    approval = ", ".join(x.get("approval_required", [])) or "-"
    lines.append(f"| {x.get('department','-')} | {x.get('status','-')} | {approval} |")
if state["approval_required"]:
    lines += ["", "## 지점장 승인 필요", "", "- " + ", ".join(state["approval_required"])]
else:
    lines += ["", "## 지점장 승인 필요", "", "- 없음"]
MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(json.dumps(state, ensure_ascii=False, indent=2))
