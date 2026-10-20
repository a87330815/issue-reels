# -*- coding: utf-8 -*-
"""
scriptgen.py — 대본 생성기

수집된 공공데이터(out/collected.json)를 읽어
render.py가 소비하는 대본 JSON 3편을 생성한다.

두 가지 모드:
  1. LLM 모드 (기본) — Anthropic Claude API로 카피·내레이션 생성
  2. 템플릿 모드 (--template) — API 없이 규칙 기반 생성 (폴백)

사용:
  python scriptgen.py                        # LLM 모드, 3편 생성
  python scriptgen.py --template             # 템플릿 모드
  python scriptgen.py -n 5                   # 5편 생성
  python scriptgen.py --out out/scripts      # 출력 경로 지정

대본 JSON 포맷 (render.py 호환):
{
  "title": "자동차세 연납",
  "cover": {"image": null, "lines": ["이거 모르면", "<r>1년에 7만원</r>", "그냥 날립니다"], "badge": null},
  "scenes": [
    {"image": null, "narration": "...", "subtitle": "..."}
  ],
  "meta": {
    "format": "숫자훅",
    "source": "molit_apt_trade",
    "category": "주거",
    "attribution": "공공데이터포털 · 국토교통부",
    "generated_at": "..."
  }
}
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
COLLECTED = os.path.join(ROOT, "out", "collected.json")
SCRIPT_DIR = os.path.join(ROOT, "out", "scripts")

# ── 커버 제약 ──────────────────────────────────────────────
MAX_COVER_CHARS = 24          # 커버 전체 글자 수
MAX_COVER_LINES = 4           # 최대 줄 수
CHARS_PER_LINE = 6            # 줄당 권장 글자 수 (150pt 기준)

# ── 릴스 포맷 5종 ──────────────────────────────────────────
FORMATS = ["시행일훅", "숫자훅", "오해정정", "체크리스트", "지역한정"]


# ═══════════════════════════════════════════════════════════
#  유틸
# ═══════════════════════════════════════════════════════════

def strip_markup(text):
    """<r>...</r>, <y>...</y> 태그를 벗긴 순수 텍스트."""
    return re.sub(r"</?[ry]>", "", text)


def hook_fit(text, limit=6):
    """단어 경계를 지키면서 limit자 이내로 자른다."""
    words = text.split()
    result = ""
    for w in words:
        if len(result) + len(w) + (1 if result else 0) > limit:
            break
        result = result + " " + w if result else w
    return result or text[:limit]


def cover_char_count(lines):
    """커버 라인 리스트의 총 글자 수 (태그 제외)."""
    return sum(len(strip_markup(l)) for l in lines)


def validate_cover(lines):
    """커버 제약 검증. 통과하면 True, 아니면 사유 문자열."""
    total = cover_char_count(lines)
    if total > MAX_COVER_CHARS:
        return f"글자 수 초과: {total}/{MAX_COVER_CHARS}"
    if len(lines) > MAX_COVER_LINES:
        return f"줄 수 초과: {len(lines)}/{MAX_COVER_LINES}"
    return True


def load_collected(path=COLLECTED):
    """수집 데이터 로드."""
    if not os.path.exists(path):
        print(f"[오류] 수집 데이터 없음: {path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items", [])
    if not items:
        print("[오류] 수집된 항목이 0건")
        sys.exit(1)
    print(f"수집 데이터 로드: {len(items)}건 ({data.get('collected_at', '?')})")
    return items


# ═══════════════════════════════════════════════════════════
#  데이터 분석 — 수집 데이터에서 스토리 앵글 추출
# ═══════════════════════════════════════════════════════════

def analyze_apt_trade(items):
    """아파트 실거래가 데이터에서 스토리 앵글을 뽑는다."""
    angles = []

    # 금액을 숫자로
    def parse_amount(s):
        try:
            return int(str(s).replace(",", "").strip())
        except (ValueError, TypeError):
            return 0

    by_region = {}
    for it in items:
        if it.get("source") != "molit_apt_trade":
            continue
        region = it.get("dong", "")
        amt = parse_amount(it.get("amount", 0))
        area = it.get("area", "")
        apt = it.get("apt", "")
        if not region or not amt:
            continue
        by_region.setdefault(region, []).append({
            "apt": apt, "amount": amt, "area": area, "source": "molit_apt_trade",
            "floor": it.get("floor", ""),
            "category": "주거", "attribution": "공공데이터포털 · 국토교통부",
            "deal_year": it.get("deal_year", ""),
            "deal_month": it.get("deal_month", ""),
        })

    if not by_region:
        return angles

    # 앵글 1: 최고가 거래
    all_deals = []
    for region, deals in by_region.items():
        for d in deals:
            d["region"] = region
            all_deals.append(d)

    all_deals.sort(key=lambda x: x["amount"], reverse=True)
    top = all_deals[0]
    top_억 = top["amount"] / 10000
    angles.append({
        "type": "숫자훅",
        "hook": f"{top_억:.0f}억 아파트",
        "data": top,
        "summary": f"{top['region']} {top['apt']} {top['area']}㎡ {top_억:.1f}억 거래",
        "items": [top],
    })

    # 앵글 2: 지역별 평균가 비교
    region_avg = {}
    for region, deals in by_region.items():
        amounts = [d["amount"] for d in deals]
        region_avg[region] = sum(amounts) / len(amounts)
    if len(region_avg) >= 2:
        sorted_regions = sorted(region_avg.items(), key=lambda x: x[1], reverse=True)
        hi_name, hi_avg = sorted_regions[0]
        lo_name, lo_avg = sorted_regions[-1]
        diff = (hi_avg - lo_avg) / 10000
        angles.append({
            "type": "숫자훅",
            "hook": f"{diff:.0f}억 차이",
            "data": {"hi": hi_name, "lo": lo_name, "diff_억": round(diff, 1)},
            "summary": f"{hi_name} 평균 {hi_avg/10000:.1f}억 vs {lo_name} 평균 {lo_avg/10000:.1f}억",
            "items": all_deals[:5],
        })

    # 앵글 3: 지역 한정 — 거래 건수 많은 지역
    busiest = max(by_region.items(), key=lambda x: len(x[1]))
    angles.append({
        "type": "지역한정",
        "hook": f"{busiest[0]} {len(busiest[1])}건 거래",
        "data": {"region": busiest[0], "count": len(busiest[1])},
        "summary": f"{busiest[0]}에서 이번 달 {len(busiest[1])}건 거래",
        "items": busiest[1][:5],
    })

    return angles


def analyze_price(items):
    """생필품 가격 데이터에서 스토리 앵글을 뽑는다."""
    price_items = [it for it in items if it.get("source") == "kca_product_price"]
    if not price_items:
        return []
    # 가격 데이터가 들어오면 여기서 앵글 추출
    return [{
        "type": "숫자훅",
        "hook": "생필품 가격",
        "data": {},
        "summary": f"생필품 가격 데이터 {len(price_items)}건",
        "items": price_items[:5],
    }]


def extract_angles(items):
    """모든 소스에서 스토리 앵글을 모은다."""
    angles = []
    angles.extend(analyze_apt_trade(items))
    angles.extend(analyze_price(items))
    # 소스 추가 시 여기에 analyze_xxx 추가
    return angles


# ═══════════════════════════════════════════════════════════
#  템플릿 모드 — 규칙 기반 대본 생성
# ═══════════════════════════════════════════════════════════

TEMPLATES = {
    "숫자훅": {
        "cover_pattern": [
            lambda a: ["방금 나온", f"<r>{hook_fit(a.get('hook',''))}</r>", "실화입니다"],
            lambda a: [f"<r>{hook_fit(a.get('hook',''))}</r>", "이거 실환가요"],
            lambda a: ["이번 달", f"<r>{hook_fit(a.get('hook',''))}</r>", "거래 떴습니다"],
        ],
        "narration_pattern": "최근 공공데이터를 분석한 결과, {summary}. 구체적인 수치를 보여드리겠습니다.",
        "scene_count": 3,
    },
    "시행일훅": {
        "cover_pattern": [
            lambda a: ["이거 안 하면", f"<r>과태료 나옵니다</r>"],
            lambda a: ["다음 달부터", "<r>이게 바뀝니다</r>"],
        ],
        "narration_pattern": "{summary}. 시행일 전에 꼭 확인하세요.",
        "scene_count": 3,
    },
    "오해정정": {
        "cover_pattern": [
            lambda a: [f"{hook_fit(a.get('hook',''))}", "<y>다 틀렸습니다</y>"],
            lambda a: ["이거 반대로", "<y>알고 계셨죠</y>"],
        ],
        "narration_pattern": "많은 분들이 {summary}에 대해 잘못 알고 계십니다. 사실은 이렇습니다.",
        "scene_count": 3,
    },
    "체크리스트": {
        "cover_pattern": [
            lambda a: ["반드시 확인", f"<r>{hook_fit(a.get('hook',''))}</r>"],
        ],
        "narration_pattern": "{summary}와 관련해서 꼭 체크해야 할 사항들을 정리했습니다.",
        "scene_count": 4,
    },
    "지역한정": {
        "cover_pattern": [
            lambda a: [f"{hook_fit(a.get('hook',''))}", "<r>주민만 해당</r>"],
            lambda a: [f"{hook_fit(a.get('hook',''))}", "<y>확인하세요</y>"],
        ],
        "narration_pattern": "{summary}. 해당 지역에 거주하시는 분들은 꼭 확인하세요.",
        "scene_count": 3,
    },
}


def _format_item_narration(item):
    """수집 항목을 자연스러운 내레이션 문장으로 변환한다."""
    src = item.get("source", "")

    if src == "molit_apt_trade":
        region = item.get("region", item.get("dong", ""))
        apt = item.get("apt", "")
        area = item.get("area", "")
        amount_raw = item.get("amount", 0)
        if isinstance(amount_raw, str):
            amount_raw = int(amount_raw.replace(",", "").strip() or 0)
        억 = amount_raw / 10000
        floor = item.get("floor", "")
        if 억 >= 1:
            price_str = f"{억:.1f}억원"
        else:
            price_str = f"{amount_raw:,}만원"
        narration = f"{region} {apt} {area}제곱미터, {floor}층이 {price_str}에 거래되었습니다."
        subtitle = f"{region} {apt} {price_str}"
        return narration, subtitle[:30]

    # 기타 소스 — key-value 나열
    parts = [f"{v}" for k, v in item.items()
             if k not in ("source", "category", "attribution", "key",
                          "q_LAWD_CD", "q_DEAL_YMD", "deal_year",
                          "deal_month", "deal_day", "deal_type",
                          "build_year", "region") and v]
    detail = " ".join(str(p) for p in parts[:4])
    return detail, detail[:30]


def template_generate(angle):
    """템플릿 기반으로 대본 하나를 만든다."""
    fmt = angle["type"]
    tpl = TEMPLATES.get(fmt, TEMPLATES["숫자훅"])

    # 커버 카피 생성 — 제약 통과할 때까지 시도
    cover_lines = None
    for pattern_fn in tpl["cover_pattern"]:
        candidate = pattern_fn(angle)
        v = validate_cover(candidate)
        if v is True:
            cover_lines = candidate
            break
    if not cover_lines:
        # 최후 폴백: 훅만 사용
        hook_short = hook_fit(angle.get("hook", "확인하세요"), 12)
        cover_lines = [f"<r>{hook_short}</r>"]

    # 내레이션
    narration_intro = tpl["narration_pattern"].format(**angle)

    # 장면 구성
    scenes = []
    scenes.append({
        "image": None,
        "narration": narration_intro,
        "subtitle": narration_intro[:30],
    })

    # 데이터 기반 장면
    for i, item in enumerate(angle.get("items", [])[:tpl["scene_count"] - 1]):
        if isinstance(item, dict):
            narration, subtitle = _format_item_narration(item)
        else:
            narration = str(item)
            subtitle = narration[:30]
        scenes.append({
            "image": None,
            "narration": narration,
            "subtitle": subtitle,
        })

    # 마무리 장면
    scenes.append({
        "image": None,
        "narration": "더 자세한 내용은 프로필 링크를 확인해주세요. 팔로우하시면 매일 알려드립니다.",
        "subtitle": "프로필 링크 확인 · 팔로우",
    })

    # badge
    badge = None
    if fmt == "시행일훅":
        badge = angle.get("data", {}).get("date_label")

    # 소스 정보
    all_items = angle.get("items", [])
    first_item = all_items[0] if all_items else {}
    if isinstance(first_item, dict):
        source_id = first_item.get("source", "")
        category = first_item.get("category", angle.get("data", {}).get("category", ""))
        attribution = first_item.get("attribution", "")
    else:
        source_id, category, attribution = "", "", ""

    return {
        "title": angle.get("hook", "이슈"),
        "cover": {
            "image": None,
            "lines": cover_lines,
            "badge": badge,
        },
        "scenes": scenes,
        "meta": {
            "format": fmt,
            "source": source_id,
            "category": category,
            "attribution": attribution,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ═══════════════════════════════════════════════════════════
#  LLM 모드 — Anthropic Claude API
# ═══════════════════════════════════════════════════════════

LLM_SYSTEM = """당신은 인스타그램 이슈 릴스 계정의 대본 작가입니다.
공공데이터를 기반으로 짧은 릴스 대본을 만듭니다.

## 반드시 지킬 규칙

### 커버 카피
- 전체 24자 이내 (태그 제외)
- 줄당 약 6자, 최대 4줄
- <r>빨강 강조</r> 또는 <y>노랑 강조</y> 태그 사용 (최소 1개)
- 나머지는 흰색
- "이거 모르면 1년에 7만원 날립니다" 같은 훅 스타일

### 릴스 포맷 5종
1. 시행일훅 — "X월 X일부터 이게 바뀝니다"
2. 숫자훅 — 충격적 숫자로 시작
3. 오해정정 — "다들 이렇게 알고 있는데 사실은..."
4. 체크리스트 — "반드시 확인할 3가지"
5. 지역한정 — "XX 주민만 해당"

### 내레이션
- 반말 금지, "~입니다/~습니다" 체
- 장면당 1~2문장, 짧고 명확하게
- 전체 3~5장면
- 마지막 장면은 항상 "프로필 링크 확인 · 팔로우" CTA

### 자막
- 내레이션의 핵심만 30자 이내로 압축

### 절대 금지
- 언론사 기사 표현 사용
- 정치적 내용
- 연예·스포츠 소재
- 특정 개인 식별

## 응답 형식
반드시 아래 JSON만 출력하세요. 설명이나 마크다운 코드블록 없이 순수 JSON만.

{
  "title": "제목",
  "format": "숫자훅",
  "cover": {
    "lines": ["첫째 줄", "<r>강조 줄</r>", "셋째 줄"],
    "badge": null
  },
  "scenes": [
    {"narration": "...", "subtitle": "..."},
    {"narration": "...", "subtitle": "..."},
    {"narration": "...", "subtitle": "..."}
  ]
}"""


def llm_generate(angle, api_key):
    """Anthropic API로 대본을 생성한다."""
    import requests as req

    prompt = f"""다음 공공데이터 분석 결과로 릴스 대본 1편을 만들어주세요.

포맷: {angle['type']}
요약: {angle['summary']}
데이터:
{json.dumps(angle.get('items', [])[:5], ensure_ascii=False, indent=2)[:2000]}

커버 카피는 반드시 24자 이내, 줄당 6자 이내로 만들어주세요."""

    resp = req.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-haiku-5-5",
            "max_tokens": 1024,
            "system": LLM_SYSTEM,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    text = resp.json()["content"][0]["text"].strip()

    # JSON 추출 (코드블록 감싸져 있을 수도 있음)
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    result = json.loads(text)

    # 커버 검증
    lines = result["cover"]["lines"]
    v = validate_cover(lines)
    if v is not True:
        print(f"  [경고] LLM 커버 제약 위반: {v} → 템플릿 폴백")
        return None

    # render.py 호환 포맷으로 변환
    first_item = angle.get("items", [{}])[0] if angle.get("items") else {}
    source_id = first_item.get("source", "") if isinstance(first_item, dict) else ""
    category = first_item.get("category", "") if isinstance(first_item, dict) else ""
    attribution = first_item.get("attribution", "") if isinstance(first_item, dict) else ""

    scenes = []
    for s in result.get("scenes", []):
        scenes.append({
            "image": None,
            "narration": s["narration"],
            "subtitle": s.get("subtitle", s["narration"][:30]),
        })

    return {
        "title": result.get("title", angle.get("hook", "이슈")),
        "cover": {
            "image": None,
            "lines": lines,
            "badge": result["cover"].get("badge"),
        },
        "scenes": scenes,
        "meta": {
            "format": result.get("format", angle["type"]),
            "source": source_id,
            "category": category,
            "attribution": attribution,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ═══════════════════════════════════════════════════════════
#  메인
# ═══════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="대본 생성기")
    ap.add_argument("-n", "--count", type=int, default=3, help="생성할 대본 수 (기본 3)")
    ap.add_argument("--template", action="store_true", help="템플릿 모드 (LLM 미사용)")
    ap.add_argument("--input", default=COLLECTED, help="수집 데이터 경로")
    ap.add_argument("--out", default=SCRIPT_DIR, help="출력 디렉토리")
    ap.add_argument("--dry-run", action="store_true", help="생성만 하고 파일 저장 안 함")
    args = ap.parse_args()

    items = load_collected(args.input)
    angles = extract_angles(items)

    if not angles:
        print("[오류] 스토리 앵글 추출 실패 — 수집 데이터에 분석 가능한 항목 없음")
        sys.exit(1)

    print(f"스토리 앵글 {len(angles)}개 추출")
    for i, a in enumerate(angles):
        print(f"  {i+1}. [{a['type']}] {a['hook']}")

    # LLM API 키 확인
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    use_llm = not args.template and api_key
    if not args.template and not api_key:
        print("[알림] ANTHROPIC_API_KEY 없음 → 템플릿 모드로 전환")

    # 생성
    scripts = []
    for i, angle in enumerate(angles[:args.count]):
        print(f"\n── 대본 {i+1}/{min(args.count, len(angles))} [{angle['type']}] {angle['hook']}")

        script = None
        if use_llm:
            try:
                script = llm_generate(angle, api_key)
                if script:
                    print("  ✓ LLM 생성 완료")
            except Exception as e:
                print(f"  [경고] LLM 실패: {e}")

        if not script:
            script = template_generate(angle)
            print("  ✓ 템플릿 생성 완료")

        # 최종 검증
        v = validate_cover(script["cover"]["lines"])
        if v is not True:
            print(f"  [오류] 커버 제약 위반: {v}")
            continue

        cover_text = " / ".join(script["cover"]["lines"])
        char_count = cover_char_count(script["cover"]["lines"])
        print(f"  커버: {cover_text} ({char_count}자)")
        print(f"  장면: {len(script['scenes'])}개")

        scripts.append(script)

    if not scripts:
        print("\n[오류] 생성된 대본 없음")
        sys.exit(1)

    # 저장
    if not args.dry_run:
        os.makedirs(args.out, exist_ok=True)
        today = datetime.now().strftime("%Y%m%d")
        for i, sc in enumerate(scripts):
            fname = f"{today}_{i+1:02d}_{sc['meta']['format']}.json"
            path = os.path.join(args.out, fname)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(sc, f, ensure_ascii=False, indent=2)
            print(f"\n저장: {path}")

    print(f"\n완료: {len(scripts)}편 생성")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
