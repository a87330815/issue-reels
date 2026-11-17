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
import hashlib
import json
import os
import random
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
COLLECTED = os.path.join(ROOT, "out", "collected.json")
SCRIPT_DIR = os.path.join(ROOT, "out", "scripts")
FUN_TOPICS = os.path.join(ROOT, "fun_topics.yml")
TIPS_TOPICS = os.path.join(ROOT, "tips_topics.yml")
PERF_HINTS = os.path.join(ROOT, "data", "perf_hints.json")


def load_perf_hints():
    """성과 힌트 로드. 없으면 빈 dict."""
    try:
        with open(PERF_HINTS, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

ALLOWED_CATEGORIES = {"재테크", "저축·투자", "보험·연금", "세금·절약", "돈습관", "경제상식"}
BLOCKED_KEYWORDS = {"연예", "아이돌", "정치", "국회", "대통령", "스포츠", "축구", "야구", "부동산", "아파트", "분양", "청약", "전세", "월세", "주택", "집값"}

# ── 커버 제약 ──────────────────────────────────────────────
MAX_COVER_CHARS = 24          # 커버 전체 글자 수
MAX_COVER_LINES = 4           # 최대 줄 수
CHARS_PER_LINE = 6            # 줄당 권장 글자 수 (150pt 기준)

# ── 릴스 포맷 5종 ──────────────────────────────────────────
FORMATS = ["숫자훅", "제도변경", "오해정정", "체크리스트", "비교분석"]

# ── 돈습관·공감 포맷 5종 ────────────────────────────────────
FUN_FORMATS = ["돈공감", "돈TMI", "세대공감", "소비습관", "월급공감"]

# ── 절약·꿀팁 포맷 5종 ───────────────────────────────────
TIPS_FORMATS = ["절약팁", "세금팁", "투자입문", "보험팁", "연금팁"]


# ═══════════════════════════════════════════════════════════
#  유틸
# ═══════════════════════════════════════════════════════════

def strip_markup(text):
    """<r>...</r>, <y>...</y> 태그를 벗긴 순수 텍스트."""
    return re.sub(r"</?[ry]>", "", text)


def hook_fit(text, limit=10):
    """단어 경계를 지키면서 limit자 이내로 자른다.

    기본값이 6자였을 때 "평당 3.0억"이 "평당"으로 잘려 숫자가 사라졌다.
    숫자가 카드의 핵심이라 그러면 카드 자체가 무의미해진다. 커버 총량은
    validate_cover가 24자로 막으므로 여기서까지 좁게 자를 이유가 없다.
    """
    words = text.split()
    result = ""
    for w in words:
        if len(result) + len(w) + (1 if result else 0) > limit:
            break
        result = result + " " + w if result else w
    if result:
        return result
    # 첫 단어부터 limit을 넘으면 통째로 돌려준다. 잘라서 뜻을 잃느니
    # 길게 두고 validate_cover가 거르게 한다.
    return text


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


_CATEGORY_BADGE = {
    "재테크": "재테크", "저축·투자": "투자",
    "보험·연금": "보험", "세금·절약": "절약",
    "돈습관": "돈습관", "경제상식": "경제",
}

def _category_badge(cat):
    """카테고리에 맞는 커버 뱃지 텍스트. 없으면 None."""
    return _CATEGORY_BADGE.get(cat)


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
    # 공공데이터·아파트 수집은 폐기했다.
    return []

def analyze_price(items):
    # 공공데이터·상품가격 수집은 폐기했다.
    return []


def extract_angles(items):
    """RSS 뉴스만 사용한다. 레거시 데이터 분석기는 호출하지 않는다."""
    return []


def load_trends(path=None):
    """트렌드 데이터(out/trends.json)를 로드한다."""
    if path is None:
        path = os.path.join(ROOT, "out", "trends.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items", [])
    print(f"트렌드 데이터 로드: {len(items)}건 ({data.get('collected_at', '?')})")
    return items


def trends_to_angles(trend_items):
    """트렌드 아이템을 스토리 앵글로 변환한다.

    트렌드는 키워드만 있으므로 LLM이 사실을 확인하고 새 문장을 써야 한다.
    여기서는 LLM에 넘길 앵글 구조만 만든다.
    """
    angles = []
    for item in trend_items:
        keyword = item["keyword"]
        category = item.get("category", "경제상식")
        snippet = item.get("snippet", "")
        news_title = item.get("news_title", "")

        # 카테고리별 포맷 매핑
        fmt_map = {
            "재테크": "숫자훅",
            "저축·투자": "비교분석",
            "보험·연금": "체크리스트",
            "세금·절약": "제도변경",
            "돈습관": "오해정정",
            "경제상식": "숫자훅",
        }
        fmt = fmt_map.get(category, "숫자훅")

        summary = f"'{keyword}' 관련 트렌드"
        if news_title:
            summary += f" — {news_title}"

        angles.append({
            "type": fmt,
            "hook": keyword,  # hook_fit()이 커버 생성 시 적절히 자른다
            "summary": summary,
            "source": "google_trends",
            "category": category,
            "items": [],  # 트렌드는 원본 데이터가 없음 — LLM이 사실을 직접 구성
            "trend_keyword": keyword,
            "trend_snippet": snippet,
            "trend_news_title": news_title,
            "data": {
                "source": "google_trends",
                "category": category,
            },
        })
    return angles


# ═══════════════════════════════════════════════════════════
#  템플릿 모드 — 규칙 기반 대본 생성
# ═══════════════════════════════════════════════════════════

# ── 카테고리별 내레이션 오프너 (첫 장면 첫 문장) ────────────
# "이거 모르고 지나가면 손해다"만 쓰면 피드가 복사본처럼 보인다.
# 카테고리에 따라 다른 오프너를 랜덤 선택한다.
NARRATION_OPENERS = {
    "default": [
        "이거 모르고 지나가면 손해다.",
        "이거 그냥 넘어가면 나중에 후회한다.",
        "지금 안 보면 나만 모르고 지나간다.",
    ],
    "재테크": [
        "이거 모르면 매달 돈이 샌다.",
        "지금 안 하면 10년 뒤에 후회한다.",
        "부자들은 다 이렇게 하고 있다.",
        "이거 하나 바꿨더니 통장 잔고가 달라졌다.",
    ],
    "저축·투자": [
        "통장에 돈이 안 모이는 이유가 있다.",
        "이걸 알고 나면 돈 넣는 방식이 바뀐다.",
        "은행이 절대 안 알려주는 것이 있다.",
    ],
    "보험·연금": [
        "보험료 매달 나가는데 보장은 제대로 되고 있습니까.",
        "이거 모르면 나중에 보험금 못 받는다.",
        "국민연금만 믿으면 노후가 위험하다.",
    ],
    "세금·절약": [
        "이거 모르고 지나가면 세금 더 낸다.",
        "연말정산 때 돌려받는 사람은 이걸 한다.",
        "매달 나가는 돈 중에 줄일 수 있는 게 있다.",
    ],
    "돈습관": [
        "부자와 가난한 사람의 차이는 습관이다.",
        "돈 모으는 사람은 이걸 절대 안 한다.",
        "월급 받자마자 이것부터 해야 한다.",
    ],
    "경제상식": [
        "이거 모르면 경제 뉴스가 안 읽힌다.",
        "당장 내 지갑에 영향 가는 얘기다.",
        "이거 한 번 알면 돈이 보인다.",
    ],
}


def _pick_opener(category="default"):
    """카테고리에 맞는 내레이션 오프너를 랜덤 선택한다."""
    openers = NARRATION_OPENERS.get(category, NARRATION_OPENERS["default"])
    return random.choice(openers)


TEMPLATES = {
    "숫자훅": {
        "cover_pattern": [
            lambda a: ["방금 나온", f"<r>{hook_fit(a.get('hook',''))}</r>", "실화입니다"],
            lambda a: [f"<r>{hook_fit(a.get('hook',''))}</r>", "이거 실환가요"],
            lambda a: ["이번 달", f"<r>{hook_fit(a.get('hook',''))}</r>", "거래 떴습니다"],
            lambda a: [f"<r>{hook_fit(a.get('hook',''))}</r>", "이게 말이 되나"],
            lambda a: [f"<r>{hook_fit(a.get('hook',''))}</r>", "숫자 보고 놀랐다"],
            lambda a: ["지금 확인 안 하면", f"<r>{hook_fit(a.get('hook',''))}</r>"],
        ],
        "narration_pattern": "{opener} {summary}. 수치로 확인해보자.",
        "scene_count": 5,
    },
    "시행일훅": {
        "cover_pattern": [
            lambda a: ["이거 안 하면", f"<r>과태료 나옵니다</r>"],
            lambda a: ["다음 달부터", "<r>이게 바뀝니다</r>"],
            lambda a: [f"<r>{hook_fit(a.get('hook',''))}</r>", "곧 시작됩니다"],
            lambda a: ["마감 임박", f"<r>{hook_fit(a.get('hook',''))}</r>"],
        ],
        "narration_pattern": "{opener} {summary}. 시행일 전에 꼭 확인해라.",
        "scene_count": 5,
    },
    "오해정정": {
        "cover_pattern": [
            lambda a: [f"{hook_fit(a.get('hook',''))}", "<y>다 틀렸습니다</y>"],
            lambda a: ["이거 반대로", "<y>알고 계셨죠</y>"],
            lambda a: [f"<r>{hook_fit(a.get('hook',''))}</r>", "진실은 이겁니다"],
            lambda a: ["다들 속고 있다", f"<y>{hook_fit(a.get('hook',''))}</y>"],
        ],
        "narration_pattern": "{opener} {summary} 다들 잘못 알고 있다. 사실은 이렇다.",
        "scene_count": 5,
    },
    "체크리스트": {
        "cover_pattern": [
            lambda a: ["반드시 확인", f"<r>{hook_fit(a.get('hook',''))}</r>"],
            lambda a: [f"<r>{hook_fit(a.get('hook',''))}</r>", "놓치면 손해다"],
            lambda a: ["이거 다 확인했나", f"<r>{hook_fit(a.get('hook',''))}</r>"],
        ],
        "narration_pattern": "{opener} {summary} 꼭 체크해야 할 거 정리해봤다.",
        "scene_count": 5,
    },
    "물가": {
        "cover_pattern": [
            lambda a: [f"<r>{hook_fit(a.get('hook',''))}</r>", "어디서 사야 할까"],
            lambda a: ["장보기 전에", f"<r>{hook_fit(a.get('hook',''))}</r>", "확인하세요"],
            lambda a: [f"<r>{hook_fit(a.get('hook',''))}</r>", "가격이 미쳤다"],
        ],
        "narration_pattern": "{opener} {summary}. 소비자원 참가격 조사 결과다.",
        "scene_count": 5,
    },
    "지역한정": {
        "cover_pattern": [
            lambda a: [f"{hook_fit(a.get('hook',''))}", "<y>얼마에 팔렸나</y>"],
            lambda a: ["우리 동네", f"<r>{hook_fit(a.get('hook',''))}</r>"],
            lambda a: [f"{hook_fit(a.get('hook',''))}", "<r>이번 달 기록</r>"],
            lambda a: ["이 동네 지금", f"<r>{hook_fit(a.get('hook',''))}</r>"],
            lambda a: [f"{hook_fit(a.get('hook',''))}", "<y>실거래가 공개</y>"],
        ],
        "narration_pattern": "{opener} {summary}. 국토부에 신고된 실거래 금액이다.",
        "scene_count": 5,
    },
}


def _region_to_en(region):
    """지역명을 영문 키워드로 변환한다."""
    mapping = {
        "강남": "Gangnam Seoul", "서초": "Seocho Seoul",
        "반포": "Banpo Seoul", "압구정": "Apgujeong Seoul",
        "잠실": "Jamsil Seoul", "송파": "Songpa Seoul",
        "용산": "Yongsan Seoul", "성수": "Seongsu Seoul",
        "여의도": "Yeouido Seoul", "목동": "Mokdong Seoul",
        "해운대": "Haeundae Busan", "명지": "Myeongji Busan",
        "수영": "Suyeong Busan", "부산진": "Busanjin Busan",
        "분당": "Bundang Seongnam", "판교": "Pangyo Seongnam",
        "수성": "Suseong Daegu", "마포": "Mapo Seoul",
        "연수": "Yeonsu Incheon", "유성": "Yuseong Daejeon",
        "김해": "Gimhae city", "진주": "Jinju city",
        "강서": "Gangseo Busan", "덕양": "Goyang city",
        "세종": "Sejong city", "광교": "Gwanggyo Suwon",
    }
    for kr, en in mapping.items():
        if kr in region:
            return en
    return "Korea city"


def _angle_region(angle):
    """앵글에서 지역명을 추출한다."""
    data = angle.get("data", {})
    if isinstance(data, dict):
        r = data.get("region", "")
        if r:
            return r
    items = angle.get("items", [])
    if items and isinstance(items[0], dict):
        return items[0].get("region", items[0].get("dong", ""))
    return ""


def _scene_image_keyword(angle, scene_type="intro"):
    """앵글에 맞는 이미지 검색 키워드를 반환한다 (영문 — Openverse/Wikimedia용)."""
    fmt = angle.get("type", "")
    region = _angle_region(angle)
    region_en = _region_to_en(region)

    if fmt == "지역한정":
        if scene_type == "intro":
            return f"{region_en} apartment skyline"
        return f"{region_en} residential area aerial"
    elif fmt == "숫자훅":
        if scene_type == "intro":
            return f"{region_en} luxury apartment"
        return "real estate market price chart"
    elif fmt == "오해정정":
        if scene_type == "intro":
            return "new vs old apartment building korea"
        return "construction crane building site korea"
    elif fmt == "체크리스트":
        return "checklist document pen desk"
    elif fmt == "시행일훅":
        return "government building law document korea"
    elif fmt == "물가":
        good = angle.get("data", {}).get("good", "")
        kw_map = {
            "삼겹살": "korean pork belly meat market",
            "우유": "milk bottles dairy store",
            "신라면": "korean ramen noodles grocery",
            "배추": "napa cabbage korean market",
            "대파": "green onion scallion market",
            "삼양라면": "korean instant noodles grocery store",
        }
        if good in kw_map:
            return kw_map[good]
        if scene_type == "intro":
            return "korean grocery market fresh food"
        return "supermarket shopping cart groceries"
    return f"{region_en} apartment building"


def _scene_image_keyword_item(item):
    """개별 거래 항목에 맞는 이미지 키워드를 반환한다 (영문)."""
    amount = item.get("amount", 0)
    if isinstance(amount, str):
        amount = int(amount.replace(",", "").strip() or 0)
    region = item.get("region", item.get("dong", ""))
    region_en = _region_to_en(region)

    if amount >= 100000:  # 10억 이상
        return f"{region_en} luxury high rise apartment"
    elif amount >= 30000:  # 3억 이상
        return f"{region_en} modern apartment residential"
    return f"{region_en} apartment building"


def _build_context_scene(angle):
    """앵글의 전체 데이터를 분석하는 맥락 요약 문장을 만든다."""
    items = angle.get("items", [])
    fmt = angle.get("type", "")

    if not items or not isinstance(items[0], dict):
        return None

    src = items[0].get("source", "")
    if src != "molit_apt_trade":
        return None

    # 평균가 계산
    amounts = []
    for item in items:
        a = item.get("amount", 0)
        if isinstance(a, str):
            a = int(a.replace(",", "").strip() or 0)
        if a > 0:
            amounts.append(a)

    if not amounts:
        return None

    avg = sum(amounts) / len(amounts)
    hi = max(amounts)
    lo = min(amounts)

    def _price(v):
        if v >= 10000:
            return f"{v/10000:.1f}억원"
        return f"{v:,.0f}만원"

    region = items[0].get("region", "")

    if fmt == "지역한정":
        return (
            f"{region} 이번 달 거래를 종합하면, "
            f"평균 거래가는 {_price(avg)}, "
            f"최고가 {_price(hi)}, 최저가 {_price(lo)}입니다. "
            f"총 {len(amounts)}건이 신고되었습니다."
        )
    elif fmt == "숫자훅":
        if len(amounts) >= 2:
            return (
                f"이번에 확인된 {len(amounts)}건의 거래에서 "
                f"가격 차이가 {_price(hi - lo)}까지 벌어졌습니다. "
                f"평균 {_price(avg)} 수준입니다."
            )
    elif fmt == "오해정정":
        # 신축 vs 구축 비교 맥락
        new_prices = []
        old_prices = []
        import datetime
        cur_year = datetime.datetime.now().year
        for item in items:
            by = item.get("build_year", 0)
            try:
                by = int(by)
            except (TypeError, ValueError):
                continue
            a = item.get("amount", 0)
            if isinstance(a, str):
                a = int(a.replace(",", "").strip() or 0)
            if by >= cur_year - 5:
                new_prices.append(a)
            else:
                old_prices.append(a)
        if new_prices and old_prices:
            diff = sum(new_prices)/len(new_prices) - sum(old_prices)/len(old_prices)
            return (
                f"신축(5년 이내)과 구축의 평균 가격 차이는 {_price(abs(int(diff)))}입니다. "
                f"신축 평균 {_price(int(sum(new_prices)/len(new_prices)))}, "
                f"구축 평균 {_price(int(sum(old_prices)/len(old_prices)))}."
            )

    # 기본 맥락
    if len(amounts) >= 2:
        return (
            f"총 {len(amounts)}건 거래 중 평균가는 {_price(avg)}, "
            f"최고 {_price(hi)}에서 최저 {_price(lo)}까지 분포합니다."
        )
    return None


def _format_item_narration(item, idx=0, total=0, angle_data=None):
    """수집 항목을 자연스러운 내레이션 문장으로 변환한다.

    idx: 이 항목이 장면에서 몇 번째인지 (0-based)
    total: 같은 앵글의 전체 항목 수
    angle_data: 앵글의 data dict (맥락 비교용)
    """
    src = item.get("source", "")

    if src == "molit_apt_trade":
        region = item.get("region", item.get("dong", ""))
        apt = item.get("apt", "")
        area_raw = item.get("area", "")
        amount_raw = item.get("amount", 0)
        if isinstance(amount_raw, str):
            amount_raw = int(amount_raw.replace(",", "").strip() or 0)
        억 = amount_raw / 10000
        floor = item.get("floor", "")
        build_year = item.get("build_year", "")

        if 억 >= 1:
            price_str = f"{억:.1f}억원"
        else:
            price_str = f"{amount_raw:,}만원"

        # 면적을 평수로도 표시 (더 직관적)
        try:
            area_m2 = float(area_raw)
            py = area_m2 / 3.3058
            area_desc = f"전용 {area_m2:.0f}㎡({py:.0f}평)"
        except (TypeError, ValueError):
            area_desc = f"전용 {area_raw}㎡"

        # 평당가 계산
        per_py_str = ""
        try:
            area_m2 = float(area_raw)
            if area_m2 > 10:
                per_py = amount_raw / (area_m2 / 3.3058)
                if per_py >= 10000:
                    per_py_str = f" 평당 {per_py/10000:.1f}억"
                else:
                    per_py_str = f" 평당 {per_py:,.0f}만원"
        except (TypeError, ValueError):
            pass

        # 건축연도 표시
        age_str = ""
        try:
            if build_year and int(build_year) > 0:
                import datetime
                age = datetime.datetime.now().year - int(build_year)
                if age <= 5:
                    age_str = f" {int(build_year)}년 준공 신축"
                elif age <= 15:
                    age_str = f" {int(build_year)}년 준공({age}년차)"
                else:
                    age_str = f" {int(build_year)}년 준공"
        except (TypeError, ValueError):
            pass

        # 장면 순서에 따라 톤을 달리한다
        if idx == 0:
            narration = (
                f"{region} {apt}, {area_desc} {floor}층이 "
                f"{price_str}에 실거래 신고됐습니다.{per_py_str}.{age_str}"
            )
        elif idx == 1:
            narration = (
                f"같은 동네 {apt}도 주목할 만합니다. "
                f"{area_desc} {floor}층, 거래가 {price_str}.{per_py_str}"
            )
        else:
            narration = (
                f"{apt} {area_desc} {floor}층 — {price_str} 거래.{per_py_str}"
            )

        # 마침표 정리 (연속 마침표, 빈 정보 제거)
        narration = narration.replace("..", ".").replace(". .", ".").strip()
        if narration.endswith("."):
            pass
        else:
            narration += "."

        return narration, short_subtitle(f"{region} {apt} {price_str}")

    # 기타 소스 — key-value 나열
    parts = [f"{v}" for k, v in item.items()
             if k not in ("source", "category", "attribution", "key",
                          "q_LAWD_CD", "q_DEAL_YMD", "deal_year",
                          "deal_month", "deal_day", "deal_type",
                          "build_year", "region") and v]
    detail = " ".join(str(p) for p in parts[:4])
    return detail, short_subtitle(detail)


# ═══════════════════════════════════════════════════════════
#  사투리 변환 — dialect.py가 맡는다
# ═══════════════════════════════════════════════════════════
#
# 2026-11-10. 여기 있던 _to_dialect()를 지웠다. 표준어 어미를 기계적으로
# 맞바꾸고("합니다"→"한다") 끝에 "아이가"를 붙이는 함수였는데, 그 결과가
# 그대로 dialect.py로 넘어갔다. dialect.py는 "합니다 / 입니다 / 했습니다"
# 같은 표준어 어미를 보고 문장을 다시 쓰는데, 그 어미가 이미 사라진
# 상태였으니 어미 규칙도 안 걸리고 LLM도 문장을 고쳐 쓸 수 없었다.
# 발행된 대본이 "표준어 문장 + 아이가"로 남은 이유다.
#
# 이제 scriptgen은 표준어 대본까지만 만들고, 사투리는 발행 직전
# dialect.py 한 곳에서만 입힌다. 어휘 사전과 어미 규칙도 그쪽에 있다.

def template_generate(angle):
    """템플릿 기반으로 대본 하나를 만든다."""
    fmt = angle["type"]
    tpl = TEMPLATES.get(fmt, TEMPLATES["숫자훅"])

    # 커버 카피 생성 — 제약 통과할 때까지 시도
    #
    # 앞서는 항상 0번 패턴에서 멈춰서, 패턴을 여러 개 둬도 모든 카드가 같은
    # 문구로 나왔다. 하루 3건씩 올리면 피드가 복사본처럼 보인다.
    # 훅에서 뽑은 고정 값으로 시작 위치를 돌려 카드마다 다른 문구가 걸리게
    # 하되, 같은 앵글은 늘 같은 문구가 나오도록 해시를 쓴다(재생성해도 동일).
    patterns = tpl["cover_pattern"]
    start = 0
    if len(patterns) > 1:
        seed = hashlib.md5(angle.get("hook", "").encode("utf-8")).hexdigest()
        start = int(seed[:8], 16) % len(patterns)

    cover_lines = None
    for i in range(len(patterns)):
        candidate = patterns[(start + i) % len(patterns)](angle)
        v = validate_cover(candidate)
        if v is True:
            cover_lines = candidate
            break
    if not cover_lines:
        # 최후 폴백: 훅만 사용
        hook_short = hook_fit(angle.get("hook", "확인하세요"), 12)
        cover_lines = [f"<r>{hook_short}</r>"]

    # 내레이션 — 카테고리에 맞는 오프너 선택
    angle.setdefault("opener", _pick_opener(angle.get("category", "default")))
    narration_intro = tpl["narration_pattern"].format(**angle)

    # 장면 구성
    scenes = []

    # 인트로 — 주제 이미지
    intro_keyword = _scene_image_keyword(angle, "intro")
    scenes.append({
        "image": None,
        "photo_query": intro_keyword,
        "narration": narration_intro,
        "subtitle": short_subtitle(angle.get("short") or angle.get("summary") or narration_intro),
    })

    # 데이터 기반 장면 (scene_count - 2: 인트로 1장 + CTA 1장 제외)
    items = angle.get("items", [])
    max_data_scenes = tpl["scene_count"] - 2
    for i, item in enumerate(items[:max_data_scenes]):
        if isinstance(item, dict):
            narration, subtitle = _format_item_narration(item, idx=i, total=len(items), angle_data=angle.get("data"))
            img_kw = _scene_image_keyword_item(item)
        else:
            narration = str(item)
            subtitle = narration[:30]
            img_kw = "부동산 아파트"
        scenes.append({
            "image": None,
            "photo_query": img_kw,
            "narration": narration,
            "subtitle": subtitle,
        })

    # 맥락 요약 장면 — 전체 데이터를 한 문장으로 분석
    context_narration = _build_context_scene(angle)
    if context_narration:
        scenes.append({
            "image": None,
            "photo_query": _scene_image_keyword(angle, "context"),
            "narration": context_narration,
            "subtitle": short_subtitle(context_narration),
        })

    # 마무리 장면 — 댓글·공유·팔로우 유도. 댓글이 많아야 알고리즘이 밀어준다.
    _cta_comment = [
        # 댓글 유도 질문형 (사투리)
        "니는 이거 어떻게 생각하노? 댓글로 알려주이소.",
        "이거 맞다 싶으면 '맞다' 댓글 달아주이소.",
        "니 생각은 어떤교? 솔직하게 댓글 남겨주이소.",
        "이거 몰랐다 싶은 사람 '헐' 달아주이소.",
        "공감되면 🔥 댓글 한 번만 남겨주이소.",
    ]
    _cta_action = [
        "주변에 모르는 사람 있으면 공유해주이소. 팔로우하면 매일 정리해드립니다.",
        "이거 나만 알기 아깝습니다. 공유 한 번 눌러주이소.",
        "도움 됐으면 저장하고 친구한테 보내주이소.",
    ]
    _cta_narration = random.choice(_cta_comment) + " " + random.choice(_cta_action)
    _cta_subtitle = "댓글 · 공유 · 팔로우"
    scenes.append({
        "image": None,
        "photo_query": "share forward social media phone",
        "narration": _cta_narration,
        "subtitle": _cta_subtitle,
    })

    # 사투리는 여기서 입히지 않는다. 발행 직전 dialect.py가 대본 전체를
    # 한 번에 고쳐 쓴다 (내레이션·자막·커버 모두).

    # badge — 시행일이면 날짜, 아니면 카테고리 라벨
    badge = None
    if fmt == "시행일훅":
        badge = angle.get("data", {}).get("date_label")
    if not badge:
        badge = _category_badge(angle.get("category", ""))

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
        "title": angle.get("hook", "재테크"),
        "cover": {
            "image": None,
            "photo_query": _scene_image_keyword(angle, "intro"),
            "lines": cover_lines,
            "summary": angle.get("summary") or narration_intro,
            "badge": badge,
        },
        "scenes": scenes,
        "meta": {
            "format": fmt,
            "source": source_id,
            "category": category,
            "attribution": attribution,
            "chart": angle.get("chart"),
            "tone": "경상도",
            "perf_hints": load_perf_hints(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ═══════════════════════════════════════════════════════════
#  LLM 모드 — Anthropic Claude API
# ═══════════════════════════════════════════════════════════

LLM_SYSTEM = """당신은 재테크·돈 정보 릴스 계정 "쫌봐봐"의 대본 작가입니다.
돈 관련 데이터와 트렌드를 받아서, 스크롤을 멈추게 하는 릴스 대본을 씁니다.

## 계정 정체성
"쫌봐봐"는 20~40대 직장인·자영업자에게 돈 버는 법, 절약하는 법, 지키는 법을 알려주는 계정입니다.
어려운 금융 용어를 쉽게 풀어주고, "이거 나도 해야겠다"는 행동을 이끌어내는 것이 목표입니다.

## 훅이 전부입니다
릴스는 첫 1초에 승부가 납니다.

나쁜 훅 — 공지사항처럼 씀:
  "2026년 연말정산 변경 안내"
  "예금 금리 비교"
좋은 훅 — 손해 볼 것 같아서 멈추게 함:
  "이거 모르면 <r>연 50만원</r> 날립니다"
  "월급 300인데 <r>1억</r> 모은 방법"
좋은 훅 — 오해를 깨뜨려서 멈추게 함:
  "적금이 <r>손해</r>인 이유"
  "보험 3개 이상이면 <r>돈 버리는</r> 겁니다"

원칙:
- 읽는 사람의 **돈·시간·손해**에 바로 연결하세요
- 숫자는 가장 센 것 하나만. 금액이면 월 단위로 체감되게 바꾸세요
- 질문형("~일까요?")은 약합니다. 단정하세요
- "안내" "소식" "발표" 같은 공지 단어는 쓰지 마세요
- 커버만 읽어도 **무슨 돈 얘기**인지 즉시 알 수 있어야 합니다

## 커버 제약 — 반드시 지킬 것
- 태그 제외 **전체 24자 이내**
- 한 줄 약 6자, **최대 4줄**
- `<r>빨강</r>` 또는 `<y>노랑</y>` 강조를 **최소 1개** 넣되, 가장 센 부분 하나에만
- 나머지는 흰색
- 24자를 넘기면 글자가 줄어들어 힘이 빠집니다. 짧을수록 강합니다

## 포맷 5종 — 데이터에 맞는 것을 고르세요
- `숫자훅` — 충격적인 금액·수익률·절약액이 있을 때
- `제도변경` — 시행일이 있는 세금·연금·보험 제도 변경
- `오해정정` — "다들 이렇게 아는데 사실은 돈 손해". 금융 통념 깨기
- `체크리스트` — 확인할 항목이 여럿일 때 (보험 점검, 연말정산 준비 등)
- `비교분석` — A vs B 비교 (적금 vs ETF, 종신보험 vs 정기보험 등)

## 내레이션
- "~입니다/~습니다" 체. 반말 금지
- 장면당 1~2문장. 짧게 끊으세요
- 본문은 정확히 **5장면**. 표지와 고정 마무리를 더해 카드뉴스가 총 7장이 되게 하세요
- 첫 장면 첫 문장은 아래 오프너 중 카테고리에 맞는 것을 하나 고르세요:
  - 재테크/투자: "이거 모르면 매달 돈이 샌다." "지금 안 하면 10년 뒤에 후회한다."
  - 보험/연금: "보험료 매달 나가는데 보장은 제대로 되고 있습니까." "국민연금만 믿으면 노후가 위험하다."
  - 세금/절약: "이거 모르고 지나가면 세금 더 낸다." "매달 나가는 돈 중에 줄일 수 있는 게 있다."
  - 돈습관: "부자와 가난한 사람의 차이는 습관이다." "월급 받자마자 이것부터 해야 한다."
  매번 같은 오프너를 쓰지 마세요. 카테고리 안에서 돌려 쓰세요.
- 첫 장면이 커버의 훅을 바로 받아야 합니다. 뜸 들이지 마세요
- 수치는 읽기 쉽게: 월 단위 금액, 연 단위 수익률로. "230000원"이 아니라 "23만원"
- 마지막 다섯 번째 장면은 핵심 정리 + **DM 유도 질문 + 공유 유도 한 줄**을 반드시 넣으세요
  예: "본인 상황에 맞는 방법이 궁금하면 '정보' 댓글 남겨주세요. 주변에 모르는 사람 있으면 공유해주세요"
  팔로우 유도는 별도 고정 마무리 페이지에서 처리합니다
- 카테고리는 재테크, 저축·투자, 보험·연금, 세금·절약, 돈습관, 경제상식 중 하나만 사용하세요
- 연예·정치·스포츠·부동산 주제는 절대 생성하지 마세요

## 말투 — 표준어로 쓰세요. 사투리 변환은 dialect.py가 맡습니다

**내레이션과 자막을 전부 표준어 "~입니다/~습니다" 체로 쓰세요.**
여기서 사투리를 흉내내지 마세요. 발행 직전에 dialect.py가 부산·경남
사투리로 문장을 다시 씁니다. 여기서 미리 "~다 아이가"를 붙여 버리면
표준어 어미가 사라져 dialect.py가 걸 자리가 없어지고, 결과물은
"표준어 문장 + 아이가"로 남습니다.

- "~다 아이가", "~카더라", "~거든", "~하이소", "뭐라카노", "야야야" 같은
  사투리 어미·감탄사를 쓰지 마세요. 사투리 어휘도 넣지 마세요
- 대신 문장을 짧게 끊으세요. 짧은 문장일수록 사투리로 옮길 때 자연스럽습니다
- 숫자·날짜·기관명·제도명·고유명사는 그대로 두세요
- 비아냥·비하·거친 욕설 금지. 친한 동네 형이 알려주는 톤은 유지합니다

### 예시
나쁜 예: "적금 넣지 마라. 돈 날린다 아이가."  (사투리를 미리 넣음)
좋은 예: "적금만 넣으면 오히려 손해입니다. 이유를 알려드리겠습니다."

## 자막
- **22자 이내**. 내레이션을 그대로 넣지 마세요
- 핵심 명사구만. 어미를 자르지 마세요
- 숫자 중간에서 끊기지 않게

## 절대 금지
- 특정 종목·펀드를 지목해 투자 판단을 유도하는 것
- 데이터에 없는 수치를 지어내는 것. 받은 값만 쓰세요
- "확정 수익" "원금 보장" 같은 금융 과장 표현
- 연예·정치·스포츠 주제를 섞는 것

## 사진 검색어 (photo_query)
카드 배경으로 깔 사진을 무료 사진 사이트에서 찾는 데 쓰는 **영문 검색어**입니다.
- 2~8개 영단어. 명사 위주 (예: "korean won bills savings piggy bank")
- 그 장면을 한 장의 사진으로 보여준다면 무엇이 찍혀 있을지를 쓰세요
- 추상 개념(policy, benefit, increase)은 사진으로 안 찍힙니다. 눈에 보이는 사물·장소·행동으로 바꾸세요
- 한국적 맥락이 중요하면 korea/korean을 넣으세요
- 인물 얼굴이 크게 나오는 검색어는 피하세요
- 장면마다 서로 다른 사진 구도를 지정하세요. 같은 검색어를 반복하지 마세요
- 재테크 주제: 한국 화폐, 통장, 계산기, 카드, 그래프 등 돈과 관련된 시각 소재를 쓰세요

## 시의성 — "오늘 왜 이게 중요한가"를 반드시 녹이세요
- 커버 또는 첫 장면에 "오늘", "방금", "X월 X일" 같은 시간 앵커를 넣으세요
- "이번 주", "어제" 등 시의적 표현이 스크롤 정지율을 높입니다
- 시행일·발표일이 있으면 반드시 커버 badge에 넣으세요

## 독창성 — AI 생성 티를 줄이세요 (인스타 Originality Score 대응)
- 기사 제목이나 보도자료 문장을 그대로 가져오지 마세요
- 받은 데이터를 **자기만의 시각**으로 재해석하세요: "왜 이게 내 돈에 중요한가"를 한 줄로
- 다른 릴스에서 흔히 쓰는 틀 대신, 스토리라인을 만드세요
- title을 절대 뉴스 헤드라인 그대로 쓰지 마세요. 우리 계정 톤으로 바꾸세요

## 캡션 키워드 (meta.keywords)
- meta 안에 `"keywords"` 배열을 넣으세요 (자연어 문장 형태, 3~5개)
- 인스타 검색에서 발견될 수 있는 **자연어 키워드 구문**이어야 합니다
- 예: ["재테크 초보 시작법", "월급 관리 방법", "돈 모으는 습관"]
- 해시태그("#")를 쓰지 마세요. 순수 자연어로 쓰세요
- 이 키워드는 캡션 본문에 자동 삽입됩니다

## 응답 형식
JSON만 출력하세요. 설명도 코드블록도 붙이지 마세요.

{
  "title": "제목",
  "format": "숫자훅",
  "cover": {
    "lines": ["적금만 넣으면", "<r>손해</r>인", "진짜 이유"],
    "badge": null,
    "photo_query": "korean won bills calculator savings"
  },
  "scenes": [
    {"narration": "...", "subtitle": "...", "photo_query": "..."},
    {"narration": "...", "subtitle": "...", "photo_query": "..."},
    {"narration": "...", "subtitle": "...", "photo_query": "..."}
  ],
  "meta": {
    "category": "저축·투자",
    "keywords": ["적금 대신 투자", "재테크 초보", "돈 불리는 방법"]
  }
}

badge는 시행일처럼 날짜를 박아야 할 때만 문자열로, 아니면 null."""


def _call_anthropic(api_key, prompt, model=None, system=None):
    import requests as req
    model_id = model or os.environ.get("LLM_MODEL", "") or "claude-haiku-4-5"
    resp = req.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key,
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": model_id,
              "max_tokens": 2048,
              "system": system or LLM_SYSTEM,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=90,
    )
    if not resp.ok:
        body = resp.text[:500]
        raise RuntimeError(f"{resp.status_code} {resp.reason}: {body}")
    return resp.json()["content"][0]["text"].strip()


def _call_openai(api_key, prompt, model=None, system=None):
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
              "messages": [{"role": "system", "content": system or LLM_SYSTEM},
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


# ═══════════════════════════════════════════════════════════
#  돈습관·공감 모드 — fun_topics.yml 로드 + LLM 프롬프트
# ═══════════════════════════════════════════════════════════

FUN_LLM_SYSTEM = """당신은 인스타그램 릴스 계정 "쫌봐봐"의 대본 작가입니다.
돈 쓰는 습관, 월급 공감, 소비 패턴 등 **돈습관·공감** 콘텐츠를 씁니다.

## 핵심 — "맞아 맞아 나도 그래!" 공감이 전부입니다
돈 관련 공감 콘텐츠는 저장·공유율이 높습니다.
- 누구나 한 번쯤 겪은 돈 관련 순간을 포착하세요
- 의외의 돈 TMI는 "몰랐는데 알고 보니" 놀라움을 주세요
- 가르치려 들지 마세요. 같이 공감하는 톤입니다

## 커버 제약 — 반드시 지킬 것
- 태그 제외 **전체 24자 이내**
- 한 줄 약 6자, **최대 4줄**
- `<r>빨강</r>` 또는 `<y>노랑</y>` 강조를 **최소 1개** 넣되, 가장 센 부분 하나에만
- 짧을수록 강합니다. "나만 그래?" "실화냐" 같은 짧은 훅이 좋습니다

## 포맷 5종
- `돈공감` — "나만 이러나?" 월급·지출 공감형
- `돈TMI` — "이거 알면 돈이 보인다" 의외의 금융 사실
- `세대공감` — 세대별 돈 쓰는 방식 차이 공감
- `소비습관` — 소비 패턴 자가진단, "이러면 돈 모은다/샌다"
- `월급공감` — 월급날, 통장 잔고, 카드값 등 직장인 공감

## 내레이션
- 장면당 1~2문장. 짧게 끊으세요
- 전체 **3~5장면**
- 첫 장면은 커버의 훅을 바로 받아야 합니다
- 마지막 장면은 **댓글 유도 질문 + 공유·팔로우 유도** ("여러분은 어떻게 하시나요? 댓글로 알려주세요. 공유하면 친구도 공감할 겁니다. 팔로우하면 매일 올려드립니다")

## 말투 — 표준어로 쓰세요. 사투리 변환은 dialect.py가 맡습니다
- 내레이션과 자막을 전부 표준어 "~입니다/~습니다" 체로 쓰세요
- "~다 아이가", "~카더라", "~거든", "야야야" 같은 사투리 표현을 미리 넣지
  마세요. 넣으면 표준어 어미가 사라져 dialect.py가 문장을 고쳐 쓸 수 없습니다
- 대신 문장을 짧게 끊으세요. 짧을수록 사투리로 옮길 때 자연스럽습니다
- 숫자·날짜·기관명·고유명사는 그대로 두세요

## 자막
- **22자 이내**. 핵심 명사구만

## 절대 금지
- 특정 금융상품·브랜드 비교·광고
- 가짜 통계나 지어낸 수치
- 너무 교훈적이거나 설교조

## 사진 검색어 (photo_query)
- 2~4개 영단어. 명사 위주
- 그 장면을 한 장의 사진으로 보여준다면 무엇이 찍혀 있을지
- 인물 얼굴이 크게 나오는 검색어는 피하세요

## 응답 형식
JSON만 출력하세요. 설명도 코드블록도 붙이지 마세요.

{
  "title": "제목",
  "format": "월급공감",
  "cover": {
    "lines": ["월급 들어오고", "<r>3일</r> 뒤", "통장 상태"],
    "badge": null,
    "photo_query": "empty wallet payday"
  },
  "scenes": [
    {"narration": "...", "subtitle": "...", "photo_query": "..."},
    {"narration": "...", "subtitle": "...", "photo_query": "..."},
    {"narration": "...", "subtitle": "...", "photo_query": "..."}
  ]
}

badge는 null로 두세요 (돈습관·공감에는 날짜 배지 불필요)."""


# ── 절약·꿀팁 LLM 시스템 프롬프트 ──────────────────────────
TIPS_LLM_SYSTEM = """당신은 인스타그램 릴스 계정 "쫌봐봐"의 대본 작가입니다.
실용적인 **절약·재테크 꿀팁** 콘텐츠를 씁니다.

## 핵심 — "와 이거 진짜 되네!" 하는 순간을 만드세요
사람들이 저장하는 이유는 "나중에 써먹어야지"입니다.
- 당장 오늘부터 쓸 수 있는 구체적인 돈 절약·투자 방법을 알려주세요
- 금액·수익률·절약액 등 숫자로 효과를 보여주세요
- 왜 효과가 있는지 한 줄로 이유를 붙이면 신뢰도가 올라갑니다

## 커버 제약 — 반드시 지킬 것
- 태그 제외 **전체 24자 이내**
- 한 줄 약 6자, **최대 4줄**
- `<r>빨강</r>` 또는 `<y>노랑</y>` 강조를 **최소 1개** 넣되, 가장 센 부분 하나에만
- 핵심 효과(금액, 수익률 등)를 강조하면 클릭률이 높습니다

## 포맷 5종
- `절약팁` — 돈 아끼는 구체적인 방법 (월 ○만 원 절약)
- `세금팁` — 연말정산·세금 환급·공제 꿀팁
- `투자입문` — 초보자도 시작할 수 있는 투자 첫걸음
- `보험팁` — 보험료 줄이기, 보장 점검 방법
- `연금팁` — 국민연금·퇴직연금·개인연금 활용법

## 내레이션
- 장면당 1~2문장. 짧게 끊으세요
- 전체 **3~5장면**
- 첫 장면은 커버의 훅을 바로 받아야 합니다
- 구체적인 방법을 순서대로 알려주세요
- 마지막 장면은 **댓글 유도 질문 + 공유·팔로우 유도** ("이거 해본 사람? 댓글로 알려주세요. 도움 됐으면 친구한테 공유해주세요. 팔로우하면 매일 돈 되는 팁 올려드립니다")

## 말투 — 표준어로 쓰세요. 사투리 변환은 dialect.py가 맡습니다
- 내레이션과 자막을 전부 표준어 "~입니다/~습니다" 체로 쓰세요
- "~다 아이가", "~카더라", "~거든", "야야야" 같은 사투리 표현을 미리 넣지
  마세요. 넣으면 표준어 어미가 사라져 dialect.py가 문장을 고쳐 쓸 수 없습니다
- 대신 문장을 짧게 끊으세요. 짧을수록 사투리로 옮길 때 자연스럽습니다
- 숫자·날짜·기관명·고유명사는 그대로 두세요

## 자막
- **22자 이내**. 핵심 명사구만

## 절대 금지
- 특정 종목·펀드를 지목해 투자 판단을 유도하는 것
- 가짜 통계나 지어낸 수치
- "확정 수익" "원금 보장" 같은 금융 과장 표현

## 사진 검색어 (photo_query)
- 2~4개 영단어. 명사 위주
- 그 장면을 한 장의 사진으로 보여준다면 무엇이 찍혀 있을지
- 인물 얼굴이 크게 나오는 검색어는 피하세요

## 응답 형식
JSON만 출력하세요. 설명도 코드블록도 붙이지 마세요.

{
  "title": "제목",
  "format": "절약팁",
  "cover": {
    "lines": ["이것만 하면", "<r>월 5만원</r>", "절약"],
    "badge": null,
    "photo_query": "korean won savings calculator"
  },
  "scenes": [
    {"narration": "...", "subtitle": "...", "photo_query": "..."},
    {"narration": "...", "subtitle": "...", "photo_query": "..."},
    {"narration": "...", "subtitle": "...", "photo_query": "..."}
  ]
}

badge는 null로 두세요 (절약·꿀팁에는 날짜 배지 불필요)."""


def load_fun_topics(path=None):
    """fun_topics.yml에서 돈습관·공감 주제 시드를 로드한다."""
    path = path or FUN_TOPICS
    if not os.path.exists(path):
        print(f"[오류] 돈습관·공감 주제 파일 없음: {path}")
        return []
    try:
        import yaml
    except ImportError:
        # PyYAML 없으면 간단한 파서로 대체
        return _load_fun_topics_simple(path)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    seeds = data.get("seeds", [])
    print(f"돈습관·공감 주제 로드: {len(seeds)}개")
    return seeds


def _load_fun_topics_simple(path):
    """PyYAML 없을 때 간단하게 시드만 파싱한다."""
    seeds = []
    current = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("- topic:"):
                if current.get("topic"):
                    seeds.append(current)
                current = {"topic": stripped.split(":", 1)[1].strip().strip('"')}
            elif stripped.startswith("angle:") and current:
                current["angle"] = stripped.split(":", 1)[1].strip().strip('"')
            elif stripped.startswith("format:") and current:
                current["format"] = stripped.split(":", 1)[1].strip().strip('"')
    if current.get("topic"):
        seeds.append(current)
    print(f"돈습관·공감 주제 로드: {len(seeds)}개 (simple parser)")
    return seeds


def fun_topics_to_angles(seeds):
    """돈습관·공감 시드를 앵글 리스트로 변환한다."""
    import random
    angles = []
    for seed in seeds:
        angles.append({
            "type": seed.get("format", "돈공감"),
            "hook": seed.get("angle", seed["topic"]),
            "summary": seed.get("angle", seed["topic"]),
            "short": seed["topic"],
            "fun_topic": seed["topic"],
            "fun_angle": seed.get("angle", ""),
            "category": "돈습관",
            "source": "fun_topics",
            "items": [],
        })
    random.shuffle(angles)
    return angles


def _build_fun_prompt(angle):
    """돈습관·공감 주제 기반 LLM 프롬프트를 생성한다."""
    topic = angle.get("fun_topic", angle.get("hook", ""))
    hint = angle.get("fun_angle", "")
    fmt = angle.get("type", "돈공감")

    return f"""아래 주제로 **돈습관·공감** 릴스 대본 1편을 써주세요.

주제: {topic}
앵글 힌트: {hint}
추천 포맷: {fmt}

**규칙:**
1. 이 주제에서 사람들이 "맞아 맞아!" 할 돈 관련 공감 포인트를 찾으세요
2. 돈TMI이면 의외의 금융 사실을 하나 넣되, 지어내지 마세요
3. 돈공감이면 누구나 겪어봤을 구체적인 돈 관련 상황을 묘사하세요
4. 커버는 24자 이내. "나만 그래?" "실화냐" 같은 짧은 공감 훅이 좋습니다
5. 표준어 "~입니다" 체로 쓰세요 (사투리 변환은 dialect.py가 합니다)
6. photo_query에 영문 키워드를 넣어주세요

카테고리: 돈습관"""


# ── 절약·꿀팁 주제 로드/변환 ──────────────────────────────
def load_tips_topics(path=None):
    """tips_topics.yml에서 절약·꿀팁 주제 시드를 로드한다."""
    path = path or TIPS_TOPICS
    if not os.path.exists(path):
        print(f"[오류] 절약·꿀팁 주제 파일 없음: {path}")
        return []
    try:
        import yaml
    except ImportError:
        return _load_tips_topics_simple(path)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    seeds = data.get("seeds", [])
    print(f"절약·꿀팁 주제 로드: {len(seeds)}개")
    return seeds


def _load_tips_topics_simple(path):
    """PyYAML 없을 때 간단하게 시드만 파싱한다."""
    seeds = []
    current = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("- topic:"):
                if current.get("topic"):
                    seeds.append(current)
                current = {"topic": stripped.split(":", 1)[1].strip().strip('"')}
            elif stripped.startswith("angle:") and current:
                current["angle"] = stripped.split(":", 1)[1].strip().strip('"')
            elif stripped.startswith("format:") and current:
                current["format"] = stripped.split(":", 1)[1].strip().strip('"')
    if current.get("topic"):
        seeds.append(current)
    print(f"절약·꿀팁 주제 로드: {len(seeds)}개 (simple parser)")
    return seeds


def tips_to_angles(seeds):
    """절약·꿀팁 시드를 앵글 리스트로 변환한다."""
    import random
    angles = []
    for seed in seeds:
        angles.append({
            "type": seed.get("format", "절약팁"),
            "hook": seed.get("angle", seed["topic"]),
            "summary": seed.get("angle", seed["topic"]),
            "short": seed["topic"],
            "tip_topic": seed["topic"],
            "tip_angle": seed.get("angle", ""),
            "category": "세금·절약",
            "source": "tips_topics",
            "items": [],
        })
    random.shuffle(angles)
    return angles


def _build_tips_prompt(angle):
    """절약·꿀팁 주제 기반 LLM 프롬프트를 생성한다."""
    topic = angle.get("tip_topic", angle.get("hook", ""))
    hint = angle.get("tip_angle", "")
    fmt = angle.get("type", "절약팁")

    return f"""아래 주제로 **절약·재테크 꿀팁** 릴스 대본 1편을 써주세요.

주제: {topic}
앵글 힌트: {hint}
추천 포맷: {fmt}

**규칙:**
1. 당장 써먹을 수 있는 구체적인 돈 절약·투자 방법을 알려주세요
2. 금액·수익률·절약액 등 숫자로 효과를 보여주세요
3. 왜 효과가 있는지 한 줄 이유를 붙이세요
4. 커버는 24자 이내. 핵심 효과(금액, 수익률 등)를 강조하세요
5. 표준어 "~입니다" 체로 쓰세요 (사투리 변환은 dialect.py가 합니다)
6. photo_query에 영문 키워드를 넣어주세요

카테고리: 세금·절약"""


def _build_trend_prompt(angle):
    """트렌드 키워드 기반 LLM 프롬프트를 생성한다."""
    keyword = angle.get("trend_keyword", angle.get("hook", ""))
    snippet = angle.get("trend_snippet", "")
    news_title = angle.get("trend_news_title", "")
    category = angle.get("category", "경제상식")

    context_parts = [f"키워드: {keyword}"]
    if news_title:
        context_parts.append(f"관련 뉴스 제목: {news_title}")
    if snippet:
        context_parts.append(f"관련 요약: {snippet}")

    return f"""아래 트렌드 키워드로 릴스 대본 1편을 써주세요.

{chr(10).join(context_parts)}
카테고리: {category}
추천 포맷: {angle['type']}

**중요: 사실 확인 및 저작권 규칙**
1. 키워드에서 핵심 사실(누가, 무엇을, 언제, 얼마)만 추출하세요
2. 뉴스 기사의 문장을 그대로 쓰지 마세요. 완전히 새로운 문장으로 작성하세요
3. 확인되지 않은 사실은 쓰지 마세요. 모르면 일반적인 사실로 대체하세요
4. 사진은 직접 촬영한 것만 사용합니다. photo_query에 영문 키워드를 넣어주세요
5. 출처 표시: "Google Trends"

커버는 24자 이내입니다. 카테고리에 따라 훅의 톤을 다르게 하세요:
- 재테크/투자: "돈·수익·손해"에 연결. 사람들이 무엇을 놓치고 있는지.
- 세금/절약: "절약액·환급액"에 연결. 모르면 손해 보는 느낌.
- 보험/연금: "보장·노후"에 연결. 지금 안 하면 위험한 느낌.
- 돈습관/경제상식: "공감·의외성"에 연결. "나만 그런 거 아니지?" 느낌.

6. 커버 또는 첫 장면에 "오늘", "방금", "X월 X일" 같은 시간 앵커를 넣으세요
7. meta 안에 "keywords" 배열(자연어 검색 키워드 3~5개)을 넣으세요. "#" 없이 순수 자연어로."""


def llm_generate(angle, api_key, provider="anthropic"):
    """LLM으로 대본을 생성한다. provider는 anthropic | openai."""
    import requests as req

    # 돈습관·공감 / 절약·꿀팁 / 트렌드 / 공공데이터에 따라 프롬프트·시스템 분기
    is_fun = bool(angle.get("fun_topic"))
    is_tips = bool(angle.get("tip_topic"))

    if is_fun:
        prompt = _build_fun_prompt(angle)
    elif is_tips:
        prompt = _build_tips_prompt(angle)
    elif angle.get("trend_keyword"):
        prompt = _build_trend_prompt(angle)
    else:
        prompt = f"""아래 공공데이터로 릴스 대본 1편을 써주세요.

분석 요약: {angle['summary']}
추천 포맷: {angle['type']} (데이터에 더 맞는 포맷이 있으면 바꿔도 됩니다)
출처: {angle.get('items', [{}])[0].get('attribution', '공공데이터포털') if angle.get('items') else '공공데이터포털'}

원본 데이터:
{json.dumps(angle.get('items', [])[:5], ensure_ascii=False, indent=2)[:2000]}

커버는 24자 이내입니다. 이 수치를 보고 사람들이 무엇을 손해 본다고 느낄지,
또는 무엇을 놓치고 있다고 느낄지에서 출발하세요."""

    # 성과 힌트를 프롬프트에 주입
    hints = load_perf_hints()
    if hints.get("avg_views") and hints.get("top_captions"):
        perf_ctx = (
            f"\n\n[성과 참고] 최근 평균 조회수 {hints['avg_views']}회, "
            f"인게이지먼트율 {hints.get('avg_engagement_rate', 0)}%. "
            f"잘 된 콘텐츠: {', '.join(hints['top_captions'][:3])}. "
            f"이 패턴을 참고해 더 자극적인 훅을 만드세요."
        )
        prompt += perf_ctx

    system = TIPS_LLM_SYSTEM if is_tips else (FUN_LLM_SYSTEM if is_fun else LLM_SYSTEM)
    if provider == "openai":
        text = _call_openai(api_key, prompt, system=system)
    else:
        text = _call_anthropic(api_key, prompt, system=system)

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
    if is_fun:
        source_id = "fun_topics"
        category = "돈습관"
        attribution = "자체 제작"
    elif is_tips:
        source_id = "tips_topics"
        category = "세금·절약"
        attribution = "자체 제작"
    elif angle.get("trend_keyword"):
        source_id = "google_trends"
        category = angle.get("category", "경제상식")
        attribution = "Google Trends"
    else:
        first_item = angle.get("items", [{}])[0] if angle.get("items") else {}
        source_id = first_item.get("source", "") if isinstance(first_item, dict) else ""
        category = first_item.get("category", "") if isinstance(first_item, dict) else ""
        attribution = first_item.get("attribution", "") if isinstance(first_item, dict) else ""

    def _pq(d):
        """photo_query 정리 — 영문 2~8단어만 통과시킨다 (없으면 None → 키워드 매핑 폴백)."""
        q = (d.get("photo_query") or "").strip()
        if not q or not re.fullmatch(r"[A-Za-z0-9 ,'-]{3,100}", q):
            return None
        words = q.split()
        return " ".join(words[:8]) if 2 <= len(words) else None

    scenes = []
    for s in result.get("scenes", []):
        scenes.append({
            "image": None,
            "narration": s["narration"],
            "subtitle": short_subtitle(s.get("subtitle") or s["narration"]),
            "photo_query": _pq(s),
        })

    return {
        "title": result.get("title", angle.get("hook", "재테크")),
        "cover": {
            "image": None,
            "lines": lines,
            "summary": result["cover"].get("summary") or result.get("summary") or "",
            "badge": result["cover"].get("badge") or _category_badge(category),
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
    ap.add_argument("--trends", default=os.path.join(ROOT, "out", "trends.json"),
                    help="트렌드 데이터 경로 (없으면 무시)")
    ap.add_argument("--trends-only", action="store_true",
                    help="트렌드 데이터만으로 생성 (수집 데이터 불필요)")
    ap.add_argument("--fun", action="store_true",
                    help="돈습관·공감 콘텐츠 생성 (fun_topics.yml 기반, LLM 필수)")
    ap.add_argument("--fun-topics", default=FUN_TOPICS,
                    help="돈습관·공감 주제 시드 파일 경로")
    ap.add_argument("--tips", action="store_true",
                    help="절약·꿀팁 콘텐츠 생성 (tips_topics.yml 기반, LLM 필수)")
    ap.add_argument("--tips-topics", default=TIPS_TOPICS,
                    help="절약·꿀팁 주제 시드 파일 경로")
    args = ap.parse_args()

    # 돈습관·공감 모드: fun_topics.yml만 사용
    if args.fun:
        seeds = load_fun_topics(args.fun_topics)
        if not seeds:
            print("[오류] 돈습관·공감 주제가 없습니다")
            sys.exit(1)
        angles = fun_topics_to_angles(seeds)
        print(f"돈습관·공감 앵글 {len(angles)}개 준비")
    elif args.tips:
        seeds = load_tips_topics(args.tips_topics)
        if not seeds:
            print("[오류] 절약·꿀팁 주제가 없습니다")
            sys.exit(1)
        angles = tips_to_angles(seeds)
        print(f"절약·꿀팁 앵글 {len(angles)}개 준비")
    else:
        # 수집 데이터 + 트렌드 데이터 합산
        angles = []
        if not args.trends_only:
            if os.path.exists(args.input):
                items = load_collected(args.input)
                angles.extend(extract_angles(items))
            else:
                print(f"[알림] 수집 데이터 없음: {args.input}")

        # 트렌드 앵글 추가
        trend_items = load_trends(args.trends)
        if trend_items:
            trend_angles = trends_to_angles(trend_items)
            angles.extend(trend_angles)
            print(f"트렌드 앵글 {len(trend_angles)}개 추가")

    if args.count == 0:
        print("생성 수 0 — 건너뜀")
        return 0

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
    elif args.fun or args.tips:
        label = "돈습관·공감" if args.fun else "절약·꿀팁"
        print(f"[오류] {label} 모드는 LLM이 필수입니다 (ANTHROPIC_API_KEY 또는 OPENAI_API_KEY 설정 필요)")
        sys.exit(1)
    elif not args.template:
        print("[알림] ANTHROPIC_API_KEY / OPENAI_API_KEY 없음 → 템플릿 모드로 전환")

    # 앵글 다양화: type(포맷)과 source(소스/카테고리) 모두 겹치지 않게 선택.
    # 3개 게시물이 전부 아파트 같은 중복을 방지한다.
    selected_angles = []
    used_types = set()
    used_sources = set()
    # 1차: type + source 모두 새로운 것 우선
    for angle in angles:
        if len(selected_angles) >= args.count:
            break
        src = angle.get("data", {}).get("source", angle.get("source", ""))
        if angle["type"] not in used_types and src not in used_sources:
            selected_angles.append(angle)
            used_types.add(angle["type"])
            if src:
                used_sources.add(src)
    # 2차: source만이라도 새로운 것
    for angle in angles:
        if len(selected_angles) >= args.count:
            break
        src = angle.get("data", {}).get("source", angle.get("source", ""))
        if angle not in selected_angles and src not in used_sources:
            selected_angles.append(angle)
            if src:
                used_sources.add(src)
    # 3차: 그래도 모자라면 남은 것에서 채움
    for angle in angles:
        if len(selected_angles) >= args.count:
            break
        if angle not in selected_angles:
            selected_angles.append(angle)

    # 생성
    scripts = []
    for i, angle in enumerate(selected_angles):
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
            if angle.get("fun_topic") or angle.get("tip_topic"):
                label = "돈습관·공감" if angle.get("fun_topic") else "절약·꿀팁"
                print(f"  [건너뜀] {label}은 LLM 전용 — 템플릿 폴백 불가")
                continue
            script = template_generate(angle)
            print("  ✓ 템플릿 생성 완료")

        # 최종 검증 — 허용 분야·금지 주제·7장 구조
        category = (script.get("meta") or {}).get("category", "").strip()
        if category not in ALLOWED_CATEGORIES:
            print(f"  [제외] 허용하지 않는 카테고리: {category}")
            continue
        # 금지어 검사: 나레이션·커버 텍스트만 대상 (뉴스 출처·사진 쿼리 제외)
        _text_parts = []
        for sc in script.get("scenes", []):
            _text_parts.append(sc.get("narration", ""))
            _text_parts.append(sc.get("text", ""))
        cover = script.get("cover") or {}
        _text_parts.extend(cover.get("lines", []))
        _text_parts.append(cover.get("subtitle", ""))
        _check_text = " ".join(_text_parts)
        if any(word in _check_text for word in BLOCKED_KEYWORDS):
            print("  [제외] 연예·정치·스포츠·부동산 계열 금지어 포함")
            continue
        if len(script.get("scenes", [])) != 5:
            print(f"  [제외] 본문 장면은 정확히 5개여야 합니다: {len(script.get('scenes', []))}개")
            continue

        # 카드뉴스 사진은 표지+본문 5장 모두 구체적인 서로 다른 검색어가 필수다.
        photo_queries = [(script.get("cover") or {}).get("photo_query", "").strip()]
        photo_queries += [(s.get("photo_query") or "").strip() for s in script.get("scenes", [])]
        if any(not q for q in photo_queries):
            print("  [제외] 표지 또는 본문에 photo_query가 없습니다")
            continue
        normalized_queries = [re.sub(r"[^a-z]+", " ", q.lower()).strip() for q in photo_queries]
        if len(set(normalized_queries)) != len(normalized_queries):
            print("  [제외] 카드뉴스 장면 사이에 중복 photo_query가 있습니다")
            continue
        if category in {"재테크", "저축·투자", "보험·연금", "세금·절약", "경제상식"}:
            korea_anchor = re.compile(r"\b(korea|korean|seoul|bank of korea|national assembly)\b", re.I)
            if any(not korea_anchor.search(q) for q in photo_queries):
                print("  [제외] 한국 경제·정치 사진 검색어에 한국 맥락이 빠졌습니다")
                continue

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
        prefix = "fun_" if args.fun else ("tips_" if args.tips else "")
        for i, sc in enumerate(scripts):
            fname = f"{today}_{prefix}{i+1:02d}_{sc['meta']['format']}.json"
            path = os.path.join(args.out, fname)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(sc, f, ensure_ascii=False, indent=2)
            print(f"\n저장: {path}")

    print(f"\n완료: {len(scripts)}편 생성")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
