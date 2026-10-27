# -*- coding: utf-8 -*-
"""
dialect.py — 표준어 대본을 경상도(부산·경남) 사투리로 바꾼다.

앞서 쓰던 방식은 표준어 문장 끝에 "아이가"만 붙이는 식이었다. 그러면
뼈대가 표준어로 남아 사투리로 들리지 않는다. 사투리는 어미가 아니라
어휘와 문장 구조에서 드러나므로, LLM에 어휘·어미 자료를 주고 문장을
처음부터 다시 쓰게 한다.

사용:
  python dialect.py out/scripts/20261027_12_숫자훅.json           # 덮어쓰기
  python dialect.py out/scripts/..._숫자훅.json -o out/x.json     # 다른 경로로
  python dialect.py out/scripts/..._숫자훅.json --dry-run         # 미리보기
"""
import argparse
import json
import os
import re
import sys

# ── 어휘 사전 ────────────────────────────────────────────────────────
# 표준어 → 사투리. LLM 프롬프트의 참고 자료로 넣고, LLM을 못 쓸 때는
# 규칙 변환에도 쓴다. 규칙 변환은 어디까지나 폴백이다.
VOCAB = {
    "매우": "억수로", "아주": "억수로", "엄청": "억수로", "really": "억수로",
    "굉장히": "디게", "되게": "디게", "너무": "디게",
    "빨리": "퍼뜩", "얼른": "퍼뜩", "어서": "퍼뜩",
    "조금": "쪼매", "약간": "쪼매", "살짝": "쪼매",
    "전부": "마카", "모두": "마카", "다들": "마카",
    "진짜": "참말로", "정말": "참말로",
    "왜": "와", "무엇": "머", "뭐": "머", "무슨": "먼",
    "그래서": "그래가", "그러니까": "그라이까", "그런데": "근데",
    "하지만": "근데", "그리고": "글고",
    "이것": "이거", "그것": "그거", "저것": "저거",
    "힘들다": "애먹는다", "고생하다": "쎄가 빠지다",
    "대단하다": "억수로 잘한다", "놀랍다": "까무러치겠다",
    "시끄럽다": "시끄럽데이", "난리다": "난리났다",
    "괜찮다": "갠찮다", "어떻게": "우째", "어떡해": "우짜노",
    "아이": "아아", "사람들": "사람들",
    "아주머니": "아지매", "아저씨": "아재",
}

# ── 어미 규칙 ────────────────────────────────────────────────────────
# 정규식 → 치환. 긴 것부터 적용해야 짧은 규칙이 먼저 먹지 않는다.
ENDINGS = [
    (r"했습니다\.", "했다 아이가."),
    (r"합니다\.", "한다 아이가."),
    (r"입니다\.", "이라예."),
    (r"됩니다\.", "된다 아이가."),
    (r"하세요\.", "하이소."),
    (r"해주세요\.", "해주이소."),
    (r"보세요\.", "보이소."),
    (r"주세요\.", "주이소."),
    (r"했다고 합니다\.", "했다 카더라."),
    (r"한다고 합니다\.", "한다 카더라."),
    (r"라고 합니다\.", "라 카더라."),
    (r"고 한다\.", "고 카더라."),
    (r"있습니다\.", "있다 아이가."),
    (r"없습니다\.", "없다 아이가."),
    (r"이다\.", "인기라."),
    (r"이었다\.", "이었데이."),
    (r"였다\.", "였데이."),
    (r"했다\.", "했데이."),
    (r"한다\.", "한다 아이가."),
    (r"있다\.", "있데이."),
    (r"됐다\.", "됐데이."),
    (r"\?$", "노?"),
]

# ── LLM 프롬프트 ─────────────────────────────────────────────────────
DIALECT_SYSTEM = """너는 부산·경남 토박이다. 주어진 표준어 문장을 경상도 사투리로 자연스럽게 고쳐 쓴다.

핵심 원칙:
1. 어미만 바꾸지 마라. 표준어 문장 끝에 "아이가"만 붙이면 사투리가 아니다.
   문장 전체를 경상도 사람이 말하듯 처음부터 다시 써라.
2. 어휘를 바꿔라. 사투리는 어미보다 단어에서 드러난다.
   억수로(매우), 디게(굉장히), 퍼뜩(빨리), 쪼매(조금), 마카(전부),
   참말로(정말), 우째(어떻게), 우짜노(어떡해), 와(왜), 머(뭐),
   애먹다(힘들다), 까무러치다(놀랍다), 난리났다, 아지매, 아재
3. 어미는 다양하게 섞어라. 한 가지만 반복하면 어색하다.
   ~아이가 / ~카더라 / ~데이 / ~는기라 / ~라예 / ~이소 / ~노? / ~나?
   "아이가"를 모든 문장에 쓰지 마라. 서너 문장에 한 번이면 충분하다.
4. 뉴스 헤드라인 문체를 버려라. "~기록", "~폭발", "~전환" 같은
   명사형 종결은 표준어 신문 문체다. 말하듯이 풀어 써라.
5. 고유명사(사람 이름, 그룹명, 숫자, 날짜)는 절대 바꾸지 마라.
6. <r>, </r>, <y>, </y> 같은 태그는 위치 그대로 유지해라.

출력은 입력과 같은 JSON 구조로만. 설명하지 마라."""


def _call_anthropic(api_key, prompt, model=None):
    import requests as req
    resp = req.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key,
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": model or os.environ.get("LLM_MODEL", "claude-haiku-5-5"),
              "max_tokens": 2048,
              "system": DIALECT_SYSTEM,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"].strip()


def _extract_json(text):
    """LLM이 코드펜스를 둘러 보낼 때가 있어 JSON 부분만 끊어낸다."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("JSON을 찾을 수 없습니다")
    return json.loads(text[start:end + 1])


def rule_convert(text):
    """LLM 없이 쓰는 폴백. 어휘와 어미를 기계적으로 바꾼다.

    기계 변환만으로는 문장 구조가 표준어로 남는다. 어디까지나
    API 키가 없을 때의 임시 수단이다.
    """
    if not text or not text.strip():
        return text
    out = text
    for std, dia in VOCAB.items():
        out = re.sub(rf"(?<![가-힣]){re.escape(std)}(?![가-힣])", dia, out)
    for pat, rep in ENDINGS:
        out = re.sub(pat, rep, out)
    return out


def collect_targets(script):
    """대본에서 사투리로 바꿀 텍스트만 뽑는다.

    고유명사가 들어간 photo_query나 meta는 건드리지 않는다.
    """
    payload = {"cover_lines": script.get("cover", {}).get("lines", []),
               "scenes": []}
    for sc in script.get("scenes", []):
        payload["scenes"].append({
            "subtitle": sc.get("subtitle", ""),
            "narration": sc.get("narration", ""),
            "body": sc.get("body", ""),
        })
    return payload


def apply_result(script, converted):
    """LLM이 돌려준 사투리 텍스트를 원본 대본에 써넣는다."""
    lines = converted.get("cover_lines")
    if lines and isinstance(lines, list):
        script.setdefault("cover", {})["lines"] = lines
    for sc, new in zip(script.get("scenes", []), converted.get("scenes", [])):
        for key in ("subtitle", "narration", "body"):
            val = new.get(key)
            # 원래 비어 있던 필드를 LLM이 채워 넣으면 레이아웃이 틀어진다.
            if val and sc.get(key, ""):
                sc[key] = val
            elif val and key == "narration":
                sc[key] = val
    return script


def convert(script, api_key=None):
    """대본을 사투리로 바꿔 돌려준다. API 키가 없으면 규칙 변환."""
    targets = collect_targets(script)

    if api_key:
        prompt = ("아래 JSON의 모든 텍스트를 경상도 사투리로 고쳐 써라.\n"
                  "같은 구조의 JSON으로만 답해라.\n\n"
                  + json.dumps(targets, ensure_ascii=False, indent=2))
        try:
            converted = _extract_json(_call_anthropic(api_key, prompt))
            print("  ✓ LLM 사투리 변환 완료")
            return apply_result(script, converted)
        except Exception as e:
            print(f"  ✗ LLM 변환 실패 ({e}) → 규칙 변환으로 전환")

    print("  · 규칙 기반 변환 (LLM 없음 — 품질이 낮습니다)")
    cover = script.get("cover", {}).get("lines", [])
    if cover:
        script["cover"]["lines"] = [rule_convert(l) for l in cover]
    for sc in script.get("scenes", []):
        for key in ("subtitle", "narration", "body"):
            if sc.get(key):
                sc[key] = rule_convert(sc[key])
    return script


def main():
    ap = argparse.ArgumentParser(description="대본을 경상도 사투리로 변환")
    ap.add_argument("script", help="대본 JSON")
    ap.add_argument("-o", "--out", help="출력 경로 (기본: 원본 덮어쓰기)")
    ap.add_argument("--dry-run", action="store_true", help="저장하지 않고 미리보기")
    ap.add_argument("--no-llm", action="store_true", help="규칙 변환만 사용")
    a = ap.parse_args()

    with open(a.script, encoding="utf-8") as f:
        script = json.load(f)

    before = collect_targets(script)
    api_key = None if a.no_llm else os.environ.get("ANTHROPIC_API_KEY", "").strip()
    script = convert(script, api_key or None)
    after = collect_targets(script)

    print(f"\n{'─' * 54}")
    print("커버")
    for b, c in zip(before["cover_lines"], after["cover_lines"]):
        print(f"  {b}\n  → {c}")
    for i, (b, c) in enumerate(zip(before["scenes"], after["scenes"]), 1):
        print(f"\n장면 {i}")
        for key, label in (("subtitle", "소제목"), ("narration", "나레이션")):
            if b[key] or c[key]:
                print(f"  {label}: {b[key]}\n        → {c[key]}")
    print("─" * 54)

    if a.dry_run:
        print("\n(--dry-run: 저장하지 않았습니다)")
        return

    out = a.out or a.script
    with open(out, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
