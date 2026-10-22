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


def short_subtitle(text, limit=22):
    """자막을 짧게 줄인다. 숫자나 단어 중간에서 끊기지 않도록 어절 경계를 지킨다.

    릴스 자막은 한눈에 읽혀야 하므로 문장을 그대로 넣지 않는다.
    """
    text = (text or "").strip().rstrip(".")
    if len(text) <= limit:
        return text
    out = ""
    for word in text.split():
        if len(out) + len(word) + (1 if out else 0) > limit:
            break
        out = out + " " + word if out else word
    return out or text[:limit]


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
    # 커버 배경의 데이터 레이어용 — 상위 5건 금액(억)
    top_chart = [round(d["amount"] / 10000, 1) for d in all_deals[:5]]
    angles.append({
        "type": "숫자훅",
        "hook": f"{top_억:.0f}억 아파트",
        "data": top,
        "summary": f"{top['region']} {top['apt']} {top['area']}㎡ {top_억:.1f}억 거래",
        "short": f"{top['region']} {top_억:.1f}억 거래",
        "items": [top],
        "chart": {"values": top_chart, "style": "bars"},
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
            "short": f"{hi_name} vs {lo_name}",
            "items": all_deals[:5],
            "chart": {
                "values": [round(v / 10000, 1) for _, v in sorted_regions[:5]],
                "style": "bars",
            },
        })

    # 앵글 3: 지역 한정 — 거래 건수 많은 지역
    busiest = max(by_region.items(), key=lambda x: len(x[1]))
    angles.append({
        "type": "지역한정",
        "hook": f"{busiest[0]} {len(busiest[1])}건 거래",
        "data": {"region": busiest[0], "count": len(busiest[1])},
        "summary": f"{busiest[0]}에서 이번 달 {len(busiest[1])}건 거래",
        "short": f"{busiest[0]} {len(busiest[1])}건 거래",
        "items": busiest[1][:5],
        "chart": {
            "values": [round(d["amount"] / 10000, 1) for d in busiest[1][:5]],
            "style": "bars",
        },
    })

    # 아래 앵글들은 버퍼 때문에 있다. 해외 IP 차단이 간헐적이라 뚫린 날
    # 며칠치를 만들어둬야 하는데, 위 3개만으로는 하루치밖에 안 나온다.
    # 같은 데이터에서 성격이 다른 이야기를 뽑아 대기열을 채운다.

    # 앵글 4: 동네별 최고가 — "우리 동네 제일 비싼 집"은 지역마다 다른 이야기다
    # 앞 앵글이 이미 쓴 동네는 건너뛴다. 같은 동네 이야기가 연달아 올라가면
    # 하루치를 벌어놓고도 피드가 똑같아 보인다.
    used_regions = {top.get("region"), busiest[0]}
    by_count = sorted(by_region.items(), key=lambda x: len(x[1]), reverse=True)
    for region, deals in by_count[:8]:
        if len(deals) < 5 or region in used_regions:
            continue
        used_regions.add(region)
        best = max(deals, key=lambda d: d["amount"])
        top5 = sorted(deals, key=lambda d: d["amount"], reverse=True)[:5]
        angles.append({
            "type": "지역한정",
            "hook": f"{region} 최고 {best['amount']/10000:.0f}억",
            "data": best,
            "summary": f"{region} 최고가 {best['apt']} {best['area']}㎡ "
                       f"{best['amount']/10000:.1f}억",
            "short": f"{region} 최고 {best['amount']/10000:.1f}억",
            "items": top5,
            "chart": {"values": [round(d["amount"]/10000, 1) for d in top5],
                      "style": "bars"},
        })

    # 앵글 5: 평당가 — 총액이 아니라 면적당 가격. 작은 집이 더 비쌀 수 있다는
    # 점이 직관과 어긋나서 반응이 온다.
    per_area = []
    for d in all_deals:
        try:
            a = float(d.get("area") or 0)
        except (TypeError, ValueError):
            a = 0
        if a > 10:                      # 면적 이상치 제외
            # 1평 = 3.3058㎡
            per_area.append((d["amount"] / (a / 3.3058), d))
    if per_area:
        per_area.sort(key=lambda x: x[0], reverse=True)
        pv, pd_ = per_area[0]
        angles.append({
            "type": "숫자훅",
            "hook": f"평당 {pv/10000:.1f}억",
            "data": pd_,
            "summary": f"{pd_['region']} {pd_['apt']} 평당 {pv/10000:.2f}억 "
                       f"(전용 {pd_['area']}㎡)",
            "short": f"{pd_['region']} 평당 {pv/10000:.1f}억",
            "items": [d for _, d in per_area[:5]],
            "chart": {"values": [round(v/10000, 2) for v, _ in per_area[:5]],
                      "style": "bars"},
        })

    # 앵글 6: 신축 프리미엄 — 건축연도로 갈리는 가격 차
    new_b, old_b = [], []
    for d in all_deals:
        try:
            y = int(d.get("build_year") or 0)
        except (TypeError, ValueError):
            continue
        if y >= 2020:
            new_b.append(d["amount"])
        elif 0 < y <= 2005:
            old_b.append(d["amount"])
    if len(new_b) >= 5 and len(old_b) >= 5:
        na, oa = sum(new_b)/len(new_b), sum(old_b)/len(old_b)
        if na > oa:
            angles.append({
                "type": "숫자훅",
                "hook": f"신축이 {(na-oa)/10000:.0f}억 비싸",
                "data": {"new_avg": round(na/10000, 1), "old_avg": round(oa/10000, 1),
                         "new_n": len(new_b), "old_n": len(old_b)},
                "summary": f"2020년 이후 신축 평균 {na/10000:.1f}억 vs "
                           f"2005년 이전 평균 {oa/10000:.1f}억",
                "short": f"신축 {na/10000:.1f}억 vs 구축 {oa/10000:.1f}억",
                "items": all_deals[:5],
                "chart": {"values": [round(na/10000, 1), round(oa/10000, 1)],
                          "style": "bars"},
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
        "narration_pattern": "{summary}. 수치로 확인해보겠습니다.",
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
        return narration, short_subtitle(f"{region} {apt} {price_str}")

    # 기타 소스 — key-value 나열
    parts = [f"{v}" for k, v in item.items()
             if k not in ("source", "category", "attribution", "key",
                          "q_LAWD_CD", "q_DEAL_YMD", "deal_year",
                          "deal_month", "deal_day", "deal_type",
                          "build_year", "region") and v]
    detail = " ".join(str(p) for p in parts[:4])
    return detail, short_subtitle(detail)


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
        "subtitle": short_subtitle(angle.get("short") or angle.get("summary") or narration_intro),
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
            "chart": angle.get("chart"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ═══════════════════════════════════════════════════════════
#  LLM 모드 — Anthropic Claude API
# ═══════════════════════════════════════════════════════════

LLM_SYSTEM = """당신은 이슈 릴스 계정의 대본 작가입니다.
공공데이터 수치를 받아서, 스크롤을 멈추게 하는 릴스 대본을 씁니다.

## 훅이 전부입니다
릴스는 첫 1초에 승부가 납니다. 커버를 보고 "어? 뭐지?" 하지 않으면 그냥 넘어갑니다.

나쁜 훅 — 공지사항처럼 씀:
  "2026년 자동차세 연납 할인 안내"
  "아파트 실거래가 발표"
좋은 훅 — 손해 볼 것 같아서 멈추게 함:
  "이거 모르면 1년에 7만원 날립니다"
  "<r>23억</r> 실화입니다"

원칙:
- 읽는 사람의 **돈·시간·손해**에 바로 연결하세요
- 숫자는 가장 센 것 하나만. 여러 개 넣으면 아무것도 안 남습니다
- 질문형("~일까요?")은 약합니다. 단정하세요
- "안내" "소식" "발표" 같은 공지 단어는 쓰지 마세요

## 커버 제약 — 반드시 지킬 것
- 태그 제외 **전체 24자 이내**
- 한 줄 약 6자, **최대 4줄**
- `<r>빨강</r>` 또는 `<y>노랑</y>` 강조를 **최소 1개** 넣되, 가장 센 부분 하나에만
- 나머지는 흰색
- 24자를 넘기면 글자가 줄어들어 힘이 빠집니다. 짧을수록 강합니다

## 포맷 5종 — 데이터에 맞는 것을 고르세요
- `시행일훅` — 시행일이 있는 제도 변경. "X월 X일부터 바뀝니다"
- `숫자훅` — 충격적인 수치가 있을 때
- `오해정정` — 통념과 데이터가 어긋날 때. "다들 이렇게 아는데 사실은"
- `체크리스트` — 확인할 항목이 여럿일 때
- `지역한정` — 특정 지역에만 해당할 때

## 내레이션
- "~입니다/~습니다" 체. 반말 금지
- 장면당 1~2문장. 짧게 끊으세요
- 전체 **3~5장면**
- 첫 장면이 커버의 훅을 바로 받아야 합니다. 뜸 들이지 마세요
- 수치는 읽기 쉽게: "230000만원"이 아니라 "23억원", "84.99제곱미터"가 아니라 "84제곱미터"
- 마지막 장면은 항상 팔로우 유도

## 말투 — 경상도 사투리 (계정 컨셉)
계정 이름이 "쫌봐봐"이고 경상도 말투가 컨셉입니다. 본문(body)은 사투리로 씁니다.

- 어미를 경상도식으로: "~입니다/~습니다" → "~다", "~한다", "~된다", "~라"
  (예: "금지됩니다" → "금지다", "확대됩니다" → "더 늘린다", "설치하세요" → "깔아둬라")
- 한 장면에 "~다 아이가", "~제" 같은 표현을 **최대 한 번만**. 남발하면 느끼해집니다
- 난해한 방언 어휘는 쓰지 마세요. 전국 팔로워가 읽습니다.
  어미와 리듬으로 경상도를 내고, 단어는 표준어를 씁니다
- **숫자·날짜·기관명·제도명은 절대 바꾸지 마세요.** 말투만 바꿉니다
  ("8월 28일", "최대 50배", "문화체육관광부"는 그대로)
- 비아냥·반말 명령조는 금지. 친한 동네 형이 알려주는 톤입니다

## 자막
- **22자 이내**. 내레이션을 그대로 넣지 마세요
- 핵심 명사구만. 어미를 자르지 마세요
- 숫자 중간에서 끊기지 않게

## 절대 금지
- 언론사 기사 표현을 가져다 쓰는 것
- 정치, 연예, 스포츠
- 특정 개인·단지를 지목해 투자 판단을 유도하는 것
- 데이터에 없는 수치를 지어내는 것. 받은 값만 쓰세요

## 사진 검색어 (photo_query)
카드 배경으로 깔 사진을 무료 사진 사이트에서 찾는 데 쓰는 **영문 검색어**입니다.
- 2~4개 영단어. 명사 위주 (예: "high speed train station", "tax documents calculator")
- 그 장면을 한 장의 사진으로 보여준다면 무엇이 찍혀 있을지를 쓰세요
- 추상 개념(policy, benefit, increase)은 사진으로 안 찍힙니다. 눈에 보이는 사물·장소·행동으로 바꾸세요
- 한국적 맥락이 중요하면 korea/korean을 넣으세요 (예: "korea train station platform")
- 인물 얼굴이 크게 나오는 검색어는 피하세요

## 응답 형식
JSON만 출력하세요. 설명도 코드블록도 붙이지 마세요.

{
  "title": "제목",
  "format": "숫자훅",
  "cover": {
    "lines": ["방금 나온", "<r>23억</r>", "실화입니다"],
    "badge": null,
    "photo_query": "seoul apartment buildings skyline"
  },
  "scenes": [
    {"narration": "...", "subtitle": "...", "photo_query": "..."},
    {"narration": "...", "subtitle": "...", "photo_query": "..."},
    {"narration": "...", "subtitle": "...", "photo_query": "..."}
  ]
}

badge는 시행일처럼 날짜를 박아야 할 때만 문자열로, 아니면 null."""


def _call_anthropic(api_key, prompt, model=None):
    import requests as req
    resp = req.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key,
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": model or os.environ.get("LLM_MODEL", "claude-haiku-5-5"),
              "max_tokens": 1024,
              "system": LLM_SYSTEM,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"].strip()


def _call_openai(api_key, prompt, model=None):
    """OpenAI(ChatGPT) 계정으로도 돌릴 수 있게 한다.
    대본 JSON만 받아야 하므로 response_format을 json_object로 고정한다."""
    import requests as req
    resp = req.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}",
                 "content-type": "application/json"},
        json={"model": model or os.environ.get("LLM_MODEL", "gpt-4o-mini"),
              "max_tokens": 1024,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": LLM_SYSTEM},
                           {"role": "user", "content": prompt}]},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def llm_provider():
    """어느 API를 쓸지 고른다.
    LLM_PROVIDER로 못박을 수 있고, 없으면 설정된 키를 보고 정한다."""
    forced = os.environ.get("LLM_PROVIDER", "").strip().lower()
    anth = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    oai = os.environ.get("OPENAI_API_KEY", "").strip()
    if forced == "openai" and oai:
        return "openai", oai
    if forced == "anthropic" and anth:
        return "anthropic", anth
    if anth:
        return "anthropic", anth
    if oai:
        return "openai", oai
    return None, None


def llm_generate(angle, api_key, provider="anthropic"):
    """LLM으로 대본을 생성한다. provider는 anthropic | openai."""
    import requests as req

    prompt = f"""아래 공공데이터로 릴스 대본 1편을 써주세요.

분석 요약: {angle['summary']}
추천 포맷: {angle['type']} (데이터에 더 맞는 포맷이 있으면 바꿔도 됩니다)
출처: {angle.get('items', [{}])[0].get('attribution', '공공데이터포털') if angle.get('items') else '공공데이터포털'}

원본 데이터:
{json.dumps(angle.get('items', [])[:5], ensure_ascii=False, indent=2)[:2000]}

커버는 24자 이내입니다. 이 수치를 보고 사람들이 무엇을 손해 본다고 느낄지,
또는 무엇을 놓치고 있다고 느낄지에서 출발하세요."""

    if provider == "openai":
        text = _call_openai(api_key, prompt)
    else:
        text = _call_anthropic(api_key, prompt)

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

    def _pq(d):
        """photo_query 정리 — 영문 2~6단어만 통과시킨다 (없으면 None → 키워드 매핑 폴백)."""
        q = (d.get("photo_query") or "").strip()
        if not q or not re.fullmatch(r"[A-Za-z0-9 ,'-]{3,60}", q):
            return None
        words = q.split()
        return " ".join(words[:6]) if 2 <= len(words) else None

    scenes = []
    for s in result.get("scenes", []):
        scenes.append({
            "image": None,
            "narration": s["narration"],
            "subtitle": short_subtitle(s.get("subtitle") or s["narration"]),
            "photo_query": _pq(s),
        })

    return {
        "title": result.get("title", angle.get("hook", "이슈")),
        "cover": {
            "image": None,
            "lines": lines,
            "badge": result["cover"].get("badge"),
            "photo_query": _pq(result.get("cover", {})),
        },
        "scenes": scenes,
        "meta": {
            "format": result.get("format", angle["type"]),
            "source": source_id,
            "category": category,
            "attribution": attribution,
            "chart": angle.get("chart"),
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

    # LLM 공급자 결정 (Anthropic / OpenAI 중 설정된 쪽)
    provider, api_key = llm_provider()
    use_llm = not args.template and bool(api_key)
    if use_llm:
        model = os.environ.get("LLM_MODEL", "기본값")
        print(f"[LLM] {provider} (모델: {model})")
    elif not args.template:
        print("[알림] ANTHROPIC_API_KEY / OPENAI_API_KEY 없음 → 템플릿 모드로 전환")

    # 생성
    scripts = []
    for i, angle in enumerate(angles[:args.count]):
        print(f"\n── 대본 {i+1}/{min(args.count, len(angles))} [{angle['type']}] {angle['hook']}")

        script = None
        if use_llm:
            try:
                script = llm_generate(angle, api_key, provider)
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
