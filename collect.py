# -*- coding: utf-8 -*-
"""
collect.py — 공공 API 수집기

게이트 3종 (프로젝트 기준):
  1. 공공누리 1유형이 아니면 폐기
  2. 인증키가 없으면 건너뜀
  3. status: dead 소스는 차단

추가로 언론사 표현 필터와 seen.json 중복제거를 거친다.

사용:
  python collect.py --verify          # 소스 상태만 점검
  python collect.py                   # 수집 실행 → out/collected.json
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
SOURCES = os.path.join(ROOT, "sources.yml")
OUT_DIR = os.path.join(ROOT, "out")
SEEN = os.path.join(OUT_DIR, "seen.json")

# 게이트 1 — 공공누리 제1유형, 또는 "이용허락범위 제한 없음"만 통과.
# 제한 없음은 1유형보다 넓으므로 상업적 이용·변형 모두 가능.
# 2유형(상업적 이용 불가)·3유형(변형 불가)·미확인(unknown)은 폐기.
ALLOWED_LICENSE = {"1", "1유형", "kogl-1", "type1", "none", "제한없음"}

# 언론사 표현 필터 — 기사 문장이 섞여 들어오는 것을 막는다
PRESS_PATTERNS = [
    r"무단\s*전재", r"재배포\s*금지",
    # 한글은 \b가 먹지 않으므로 경계 없이 매칭한다
    r"저작권자\s*[\(（]?\s*[cCⓒ©]\s*[\)）]?",
    r"[가-힣]{2,4}\s*기자",
    r"(연합뉴스|뉴시스|뉴스1|조선일보|중앙일보|동아일보|한겨레|경향신문|매일경제|한국경제)",
    r"\b(YTN|KBS|MBC|SBS|JTBC)\b",
]
PRESS_RE = re.compile("|".join(PRESS_PATTERNS))


def load_sources():
    with open(SOURCES, encoding="utf-8") as f:
        return yaml.safe_load(f)["sources"]


def load_seen():
    if os.path.exists(SEEN):
        with open(SEEN, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(SEEN, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=1)


def item_key(item):
    base = f"{item.get('source','')}|{item.get('title','')}|{item.get('date','')}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def has_press_expression(text):
    return bool(PRESS_RE.search(text or ""))


def gate(src):
    """소스 하나를 검사해 (통과여부, 사유)를 돌려준다."""
    if src.get("status") == "dead":
        return False, f"차단(dead): {src.get('reason','폐쇄')}"
    lic = str(src.get("license", "unknown")).lower()
    if lic not in ALLOWED_LICENSE:
        return False, f"폐기(공공누리 미확인/비1유형): license={src.get('license')}"
    env = src.get("key_env")
    if env and not os.environ.get(env):
        return False, f"건너뜀(인증키 없음): {env}"
    return True, "통과"


def fetch(src):
    """실제 호출. field_map이 비어 있으면 아직 매핑 전이므로 수집하지 않는다."""
    if not src.get("field_map"):
        return []
    import requests  # 게이트를 통과한 소스에서만 필요

    params = {"serviceKey": os.environ[src["key_env"]], "returnType": "JSON"}
    r = requests.get(src["endpoint"], params=params, timeout=20)
    r.raise_for_status()
    raw = r.json()

    fm = src["field_map"]
    rows = raw
    for k in fm.get("root", "").split("."):
        if k:
            rows = rows.get(k, [])
    items = []
    for row in rows:
        items.append({
            "source": src["id"],
            "category": src.get("category", ""),
            "title": row.get(fm.get("title", ""), ""),
            "body": row.get(fm.get("body", ""), ""),
            "date": row.get(fm.get("date", ""), ""),
        })
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="소스 상태만 점검하고 끝낸다")
    args = ap.parse_args()

    srcs = load_sources()
    passed, report = [], []
    for s in srcs:
        ok, why = gate(s)
        report.append((s["id"], ok, why))
        if ok:
            passed.append(s)

    width = max(len(r[0]) for r in report)
    for sid, ok, why in report:
        print(f"  {'OK ' if ok else '-- '} {sid:<{width}}  {why}")

    if args.verify:
        print(f"\n통과 {len(passed)} / 전체 {len(srcs)}")
        return 0

    seen = load_seen()
    collected, dropped = [], 0
    for s in passed:
        for item in fetch(s):
            if has_press_expression(item["title"]) or has_press_expression(item["body"]):
                dropped += 1
                continue
            k = item_key(item)
            if k in seen:
                continue
            seen.add(k)
            item["key"] = k
            collected.append(item)

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "collected.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "items": collected,
        }, f, ensure_ascii=False, indent=2)
    save_seen(seen)

    print(f"\n수집 {len(collected)}건 · 언론사표현 폐기 {dropped}건 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
