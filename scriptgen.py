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
            # 신축·구축 비교 앵글이 이 값을 본다. 빠져 있어서 그 앵글이
            # 한 번도 만들어지지 않았다.
            "build_year": it.get("build_year", ""),
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
    # 같은 유형이 과반이면 피드가 단조로워진다. 동네별 최고가는 3개까지만
    # 쓰고, 나머지 자리는 아래의 성격이 다른 앵글에 넘긴다.
    used_regions = {top.get("region"), busiest[0]}
    by_count = sorted(by_region.items(), key=lambda x: len(x[1]), reverse=True)
    region_angles = 0
    for region, deals in by_count[:8]:
        if region_angles >= 3:
            break
        if len(deals) < 5 or region in used_regions:
            continue
        used_regions.add(region)
        region_angles += 1
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
        # 차이가 작으면 "신축이 0억 비싸"처럼 뜻 없는 카드가 된다.
        # 1억 이상 벌어질 때만 이야기가 된다.
        if na - oa >= 10000:
            angles.append({
                "type": "오해정정",
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
        "scene_count": 6,
    },
    "시행일훅": {
        "cover_pattern": [
            lambda a: ["이거 안 하면", f"<r>과태료 나옵니다</r>"],
            lambda a: ["다음 달부터", "<r>이게 바뀝니다</r>"],
        ],
        "narration_pattern": "{summary}. 시행일 전에 꼭 확인하세요.",
        "scene_count": 6,
    },
    "오해정정": {
        "cover_pattern": [
            lambda a: [f"{hook_fit(a.get('hook',''))}", "<y>다 틀렸습니다</y>"],
            lambda a: ["이거 반대로", "<y>알고 계셨죠</y>"],
        ],
        "narration_pattern": "많은 분들이 {summary}에 대해 잘못 알고 계십니다. 사실은 이렇습니다.",
        "scene_count": 6,
    },
    "체크리스트": {
        "cover_pattern": [
            lambda a: ["반드시 확인", f"<r>{hook_fit(a.get('hook',''))}</r>"],
        ],
        "narration_pattern": "{summary}와 관련해서 꼭 체크해야 할 사항들을 정리했습니다.",
        "scene_count": 6,
    },
    # 실거래가는 그 동네 주민만 해당하는 정보가 아니라 누구나 보는 시세다.
    # "주민만 해당"은 사실과 어긋나고, 같은 문구가 연달아 나오면 피드가
    # 복사본처럼 보인다. 동네 이름이 들어간 문구를 여러 개 두고 돌려 쓴다.
    "지역한정": {
        "cover_pattern": [
            lambda a: [f"{hook_fit(a.get('hook',''))}", "<y>얼마에 팔렸나</y>"],
            lambda a: ["우리 동네", f"<r>{hook_fit(a.get('hook',''))}</r>"],
            lambda a: [f"{hook_fit(a.get('hook',''))}", "<r>이번 달 기록</r>"],
            lambda a: ["이 동네 지금", f"<r>{hook_fit(a.get('hook',''))}</r>"],
            lambda a: [f"{hook_fit(a.get('hook',''))}", "<y>실거래가 공개</y>"],
        ],
        "narration_pattern": "{summary}. 국토교통부에 신고된 실제 거래 금액입니다.",
        "scene_count": 6,
    },
}


def _scene_image_keyword(angle, scene_type="intro"):
    """앵글에 맞는 이미지 검색 키워드를 반환한다 (영문 — Openverse/Wikimedia용)."""
    fmt = angle.get("type", "")

    if fmt == "지역한정":
        if scene_type == "intro":
            return "korea apartment complex aerial view"
        return "real estate price chart graph"
    elif fmt == "숫자훅":
        if scene_type == "intro":
            return "luxury apartment building korea"
        return "housing price comparison chart"
    elif fmt == "오해정정":
        if scene_type == "intro":
            return "new apartment building modern korea"
        return "old vs new apartment building"
    elif fmt == "체크리스트":
        return "checklist document pen"
    elif fmt == "시행일훅":
        return "government policy law document"
    return "apartment building city skyline"


def _scene_image_keyword_item(item):
    """개별 거래 항목에 맞는 이미지 키워드를 반환한다 (영문)."""
    amount = item.get("amount", 0)
    if isinstance(amount, str):
        amount = int(amount.replace(",", "").strip() or 0)

    # 고가 아파트 vs 일반 아파트
    if amount >= 100000:  # 10억 이상
        return "luxury high rise apartment building"
    elif amount >= 30000:  # 3억 이상
        return "modern apartment building residential"
    return "apartment building korea residential"


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

    # 내레이션
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

    # 마무리 장면
    scenes.append({
        "image": None,
        "photo_query": "follow subscribe social media phone",
        "narration": "오늘 내용이 도움이 되셨다면 팔로우 부탁드립니다. 매일 부동산 이슈를 정리해드립니다.",
        "subtitle": "팔로우 · 매일 업데이트",
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
            "photo_query": _scene_image_keyword(angle, "intro"),
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
