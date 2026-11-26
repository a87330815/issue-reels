# -*- coding: utf-8 -*-
"""Final Korean copy gate for generated short-form scripts."""
import json, re, sys
from pathlib import Path

REPLACEMENTS = {
    "안자가 사인": "안전 자산",
    "안자가산": "안전 자산",
    "사인": "사인",  # do not rewrite ordinary words
    "됬": "됐",
    "않되": "안 돼",
    "할수": "할 수",
    "할수있": "할 수 있",
    "되요": "돼요",
    "됬습니다": "됐습니다",
    "있읍니다": "있습니다",
}
# These are not acceptable in a public caption unless explicitly intended.
SUSPICIOUS = ("�", "안자가 사인", "됬", "않되", "되요", "됬습니다")
# Common 부산 endings allowed after dialect pass; the gate rejects accidental
# malformed endings while allowing ordinary standard Korean narration.
BAD_ENDINGS = re.compile(r"(습니더|합니더|했니더|입니더)$")

def text_parts(data):
    out = [data.get("title","")]
    out += (data.get("cover") or {}).get("lines", [])
    out += [(s.get("narration") or "") + " " + (s.get("subtitle") or "") for s in data.get("scenes", [])]
    return out

def main():
    if len(sys.argv) != 2:
        print("usage: proofread.py SCRIPT.json", file=sys.stderr); return 2
    path = Path(sys.argv[1])
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = False
    for key in ("title", "cover", "scenes"):
        pass
    def fix(value):
        nonlocal changed
        for old, new in REPLACEMENTS.items():
            if old in value and old != new:
                value = value.replace(old, new); changed = True
        return value
    data["title"] = fix(data.get("title",""))
    cover = data.get("cover") or {}
    cover["lines"] = [fix(x) for x in cover.get("lines", [])]
    data["cover"] = cover
    for scene in data.get("scenes", []):
        scene["narration"] = fix(scene.get("narration",""))
        scene["subtitle"] = fix(scene.get("subtitle",""))
    parts = text_parts(data)
    joined = " ".join(parts)
    errors = []
    for token in SUSPICIOUS:
        if token in joined: errors.append(f"suspicious token: {token}")
    if BAD_ENDINGS.search(joined): errors.append("북부/경북식 사투리 어미 감지")
    if re.search(r"[A-Za-z]{8,}", joined): errors.append("영문 혼입 문장 감지")
    if len(data.get("scenes", [])) != 5: errors.append("장면 수 5개 아님")
    if errors:
        print("검수 실패:", "; ".join(errors), file=sys.stderr); return 1
    data.setdefault("meta", {})["copy_proofread"] = True
    data["meta"]["proofread_notes"] = "오탈자·금칙 표현·사투리 어미·장면 수 자동 검수"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("검수 통과:", path)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
