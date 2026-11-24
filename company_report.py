# -*- coding: utf-8 -*-
"""회사 전체 계정 성과를 하나의 일일 보고서로 통합한다."""
import json
import os
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(ROOT, "company", "accounts.json")
DATA = os.path.join(ROOT, "data")
OUT_JSON = os.path.join(DATA, "company_report.json")
OUT_MD = os.path.join(DATA, "company_report.md")

def fetch_json(repo, path):
    url = f"https://raw.githubusercontent.com/{repo}/main/{path}"
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"status": "waiting", "error": type(exc).__name__}

def n(value, default=0):
    return value if isinstance(value, (int, float)) else default

with open(CONFIG, encoding="utf-8") as f:
    cfg = json.load(f)

now = datetime.now(ZoneInfo(cfg.get("timezone", "Asia/Seoul")))
rows = []
for account in cfg["accounts"]:
    perf = fetch_json(account["repository"], "data/perf_hints.json")
    snap = fetch_json(account["repository"], "data/account_insights.csv")
    rows.append({
        "id": account["id"],
        "name": account["name"],
        "repository": account["repository"],
        "status": perf.get("status", "active"),
        "avg_views": n(perf.get("avg_views")),
        "avg_engagement_rate": n(perf.get("avg_engagement_rate")),
        "followers_growth": n(perf.get("followers_growth")),
        "best_hours_kst": perf.get("best_hours_kst", []),
        "best_categories": perf.get("best_categories", []),
        "best_formats": perf.get("best_formats", []),
        "top_captions": perf.get("top_captions", []),
        "snapshot_available": "error" not in snap,
        "generated_at": perf.get("generated_at", "")
    })

payload = {
    "generated_at": now.isoformat(),
    "analysis_priority": cfg["analysis_priority"],
    "accounts": rows
}
os.makedirs(DATA, exist_ok=True)
with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

lines = [
    "# AI 콘텐츠 자동화 회사 일일 성과보고",
    "",
    f"- 기준시각: {now:%Y-%m-%d %H:%M} KST",
    "- 분석 우선순위: 조회수 → 저장 → 공유 → 팔로워 증가 → 우수 주제/형식",
    "",
    "| 계정 | 상태 | 평균 조회수 | 참여율 | 팔로워 증감 | 최고 시간(KST) |",
    "|---|---:|---:|---:|---:|---|",
]
for r in rows:
    hours = ", ".join(map(str, r["best_hours_kst"])) or "수집 중"
    lines.append(
        f'| {r["name"]} | {r["status"]} | {r["avg_views"]:,} | '
        f'{r["avg_engagement_rate"]:.2f}% | {r["followers_growth"]:+,} | {hours} |'
    )

lines += ["", "## 계정별 성과가 좋은 콘텐츠 유형", ""]
for r in rows:
    lines.append(f'### {r["name"]}')
    if r["status"] == "waiting":
        lines.append("- 첫 분석 데이터 수집 대기")
        lines.append("")
        continue
    cats = r["best_categories"] or []
    fmts = r["best_formats"] or []
    if cats:
        lines.append("- 우수 주제: " + ", ".join(str(x) for x in cats[:3]))
    else:
        lines.append("- 우수 주제: 분류 데이터 축적 중")
    if fmts:
        lines.append("- 우수 형식: " + ", ".join(str(x) for x in fmts[:3]))
    else:
        lines.append("- 우수 형식: 형식 데이터 축적 중")
    if r["top_captions"]:
        lines.append("- 상위 콘텐츠: " + " / ".join(r["top_captions"][:3]))
    lines.append("")

lines += [
    "## 운영 원칙",
    "",
    "- 쫌봐봐의 편성표와 주제 비율은 고정하며 성과분석 결과로 임의 변경하지 않는다.",
    "- 리치업지점은 조회수보다 신뢰·상담·리쿠르팅 연결을 함께 평가한다.",
    "- 게시 실패는 성과로 기록하지 않는다.",
    "- 플랫폼 하나가 실패해도 다른 플랫폼 발행은 계속한다.",
]
with open(OUT_MD, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print(OUT_MD)
