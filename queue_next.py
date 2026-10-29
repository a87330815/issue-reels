# -*- coding: utf-8 -*-
"""
queue_next.py — 다음에 올릴 대본을 하나 고른다.

하루 여러 번 예약 발행하려면 "이번 슬롯에 뭘 올릴지"를 사람 없이 정해야 한다.
out/scripts/ 의 대본 중 아직 이 계정에 올리지 않은 것을 오래된 순으로 하나 집는다.

콘텐츠 비율 (2026-10-29 개편):
  화제·이슈    40%
  재미·공감    40%
  생활·꿀팁    15%
  경제·돈       5%
  사회·뉴스     0% (편성 안 함)

"완료"의 기준은 릴스 발행이다 (out/published.json):
  팔로워가 없는 계정에서 카드뉴스 캐러셀은 비팔로워에게 노출되지 않아
  사실상 묻힌다. 계정 포맷을 릴스 전면으로 돌렸으므로, 카드뉴스로 한 번
  나간 대본도 아직 릴스로는 안 나간 것이니 대기열에 남긴다.
  카드뉴스 기록(out/published_cards.json)은 완료 판정에 쓰지 않는다.

계정 기준으로 거르는 이유:
  계정을 옮기면 같은 대본을 새 계정에 다시 올려야 한다. 대본 이름만 보고
  거르면 이전 계정 발행분까지 완료로 세어 새 계정에 아무것도 안 올라간다.
  그래서 발행 기록의 ig_id가 지금 계정과 다른 것은 완료에서 뺀다.

사용:
  python queue_next.py              # 대본 이름(stem) 출력, 없으면 빈 줄 + exit 1
  python queue_next.py --list       # 대기열 전체를 보여준다
"""
import argparse
import glob
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(ROOT, "out", "scripts")
PUBLISHED = os.path.join(ROOT, "out", "published.json")              # 릴스
PUBLISHED_CARDS = os.path.join(ROOT, "out", "published_cards.json")  # 카드뉴스(참고용)

# 목표 비율 (합 100) — 2026-10-29 개편 2차: 연예/정치/세계경제 비중 확대
# 이전: 화제·이슈 40 / 재미·공감 40 / 생활·꿀팁 15 / 경제·돈 5
TARGET_RATIO = {
    "화제·이슈":         20,
    "재미·공감":         20,
    "연예·화제":         15,
    "정치·시사":         15,
    "세계경제":          15,
    "생활·꿀팁":         10,
    "경제·돈":            5,
    # "사회·뉴스":        0,   # 비율 0 — 편성 안 함
}

# 하루 최대 (카테고리가 반복되면 지루함)
DAILY_LIMIT = {
    "경제·돈": 1,
    "정치·시사": 2,
}

# 대본이 붙이는 카테고리 이름을 비율 표의 칸으로 접는다.
CATEGORY_ALIAS = {
    # 기존 → 화제·이슈
    "당일 화제 이슈": "화제·이슈",
    "놀라운 사건·화제": "화제·이슈",
    "트렌드": "화제·이슈",
    # 연예 계열
    "연예": "연예·화제",
    "연예·화제": "연예·화제",
    "엔터테인먼트": "연예·화제",
    # 정치 계열
    "정치": "정치·시사",
    "정치·시사": "정치·시사",
    "시사": "정치·시사",
    # 세계경제 계열
    "세계경제": "세계경제",
    "글로벌경제": "세계경제",
    "국제경제": "세계경제",
    "해외경제": "세계경제",
    # 기존 → 경제·돈
    "주거": "경제·돈",
    "물가": "경제·돈",
    "부동산": "경제·돈",
    "경제·부동산": "경제·돈",
    # 기존 → 생활·꿀팁
    "생활·지원금·제도": "생활·꿀팁",
    "생활": "생활·꿀팁",
    # 재미·공감은 그대로
}


def normalize_category(cat):
    """대본 카테고리를 비율 표의 칸 중 하나로 맞춘다."""
    cat = (cat or "").strip()
    return CATEGORY_ALIAS.get(cat, cat)


def cards_dir_for(stem):
    """대본 이름에 대응하는 카드 디렉터리. news_001 → out/cards_001"""
    return os.path.join(ROOT, "out", "cards_" + stem.replace("news_", "", 1))


def load_script_meta(stem):
    """대본 파일에서 meta.category를 읽어 비율 표 이름으로 맞춘다."""
    path = os.path.join(SCRIPTS, f"{stem}.json")
    try:
        with open(path, encoding="utf-8") as f:
            sc = json.load(f)
        return normalize_category((sc.get("meta") or {}).get("category", ""))
    except Exception:
        return ""


def _load_items(path):
    """발행 기록 파일에서 items를 꺼낸다. 깨져 있으면 빈 목록."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("items", []) or []
    except Exception:
        return []


def _stem_of(item):
    """릴스 기록은 name에, 카드뉴스 기록은 script 경로에 대본 이름이 있다."""
    if item.get("name"):
        return str(item["name"])
    src = item.get("script") or ""
    return os.path.splitext(os.path.basename(src))[0] if src else ""


def reel_records(ig_id):
    """지금 계정에 릴스로 올린 기록을 (대본, 시각, 카테고리)로 정리한다.

    릴스 기록에는 카테고리 필드가 없어 대본 파일에서 읽어 붙인다.
    2026-10-29 이전 기록에는 ig_id가 아예 없는데, 그때까지 쓴 계정이
    지금 계정이라 완료로 센다. 다른 계정 기록만 걸러낸다.
    """
    out = []
    for it in _load_items(PUBLISHED):
        rec = str(it.get("ig_id") or "")
        if ig_id and rec and rec != str(ig_id):
            continue
        stem = _stem_of(it)
        if not stem:
            continue
        out.append({
            "stem": stem,
            "published_at": it.get("published_at", "") or "",
            "category": normalize_category(it.get("category")) \
            or load_script_meta(stem),
        })
    return out


def published_stems(ig_id):
    """지금 계정에 릴스로 이미 올린 대본 이름들."""
    return {r["stem"] for r in reel_records(ig_id)}


def published_categories_today(ig_id):
    """오늘 올린 릴스의 카테고리를 세서 일일 한도 체크에 쓴다."""
    from datetime import date
    today = date.today().isoformat()
    cats = Counter()
    for r in reel_records(ig_id):
        if r["published_at"][:10] != today:
            continue
        if r["category"]:
            cats[r["category"]] += 1
    return cats


def published_category_counts(ig_id):
    """전체 릴스 발행분의 카테고리 집계. 비율 밸런싱의 분모다."""
    cats = Counter()
    for r in reel_records(ig_id):
        if r["category"]:
            cats[r["category"]] += 1
    return cats


def queue(ig_id):
    """올릴 수 있는 대본을 오래된 순으로.

    예전에는 카드 PNG가 이미 있는 대본만 셌다. 카드 생성을 대본마다
    미리 돌리던 때의 전제다. 지금은 발행 직전에 그 대본의 카드만 만들므로
    (publish_daily.yml), 카드가 없다고 빼면 대기열이 통째로 비어 버린다.
    """
    done = published_stems(ig_id)
    out = []
    for path in sorted(glob.glob(os.path.join(SCRIPTS, "*.json"))):
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem in done:
            continue
        # test_trend_01 같은 시험용 대본이 실제 계정에 올라가면 안 된다.
        if stem.startswith("test_") or stem.startswith("sample_"):
            continue
        out.append(stem)
    return out


def pick_balanced(candidates, ig_id):
    """비율 밸런싱으로 다음에 올릴 대본 1개를 고른다.

    전체 발행 히스토리에서 카테고리별 비율을 계산하고,
    목표 비율 대비 가장 부족한 카테고리의 대본을 먼저 올린다.
    """
    if not candidates:
        return None

    # 오늘 카테고리별 발행 수 (일일 한도 체크)
    today_cats = published_categories_today(ig_id)

    # 전체 발행 카테고리 집계
    total_cats = published_category_counts(ig_id)
    total = sum(total_cats.values()) or 1

    # 카테고리별 부족분 계산 (목표 비율 - 실제 비율)
    deficits = {}
    for cat, target_pct in TARGET_RATIO.items():
        actual_pct = (total_cats.get(cat, 0) / total) * 100
        deficits[cat] = target_pct - actual_pct

    # 후보별 점수 매기기 (부족한 카테고리일수록 높은 점수)
    scored = []
    for stem in candidates:
        cat = load_script_meta(stem)

        # 일일 한도 초과 체크
        limit = DAILY_LIMIT.get(cat, 999)
        if today_cats.get(cat, 0) >= limit:
            continue

        score = deficits.get(cat, 0)  # 미분류 카테고리는 0점
        scored.append((score, stem, cat))

    if not scored:
        # 일일 한도로 전부 걸렸으면 그냥 첫 번째 반환
        return candidates[0] if candidates else None

    # 가장 부족한 카테고리의 대본을 선택
    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


def main():
    ap = argparse.ArgumentParser(description="다음에 올릴 대본 고르기")
    ap.add_argument("--list", action="store_true", help="대기열 전체 출력")
    a = ap.parse_args()

    ig_id = os.environ.get("IG_USER_ID", "").strip()
    q = queue(ig_id)

    if a.list:
        done = published_stems(ig_id)
        print(f"계정 {ig_id or '(미지정)'}")
        print(f"릴스 발행 완료 {len(done)}건: {', '.join(sorted(done)) or '-'}")
        cards_only = {_stem_of(it) for it in _load_items(PUBLISHED_CARDS)} - done
        if cards_only:
            print(f"카드뉴스로만 나간 {len(cards_only)}건 (릴스 대기): "
                  f"{', '.join(sorted(cards_only))}")
        print(f"대기 {len(q)}건:")
        for stem in q:
            cat = load_script_meta(stem)
            print(f"  {stem} [{cat or '미분류'}]")

        # 비율 현황
        total_cats = published_category_counts(ig_id)
        total = sum(total_cats.values()) or 1
        print(f"\n카테고리 비율 (목표 vs 실제):")
        for cat, target in TARGET_RATIO.items():
            actual = (total_cats.get(cat, 0) / total) * 100
            print(f"  {cat}: 목표 {target}% / 실제 {actual:.0f}% ({total_cats.get(cat, 0)}건)")
        return

    if not q:
        print("", end="")
        sys.stderr.write("대기열이 비었습니다 — 올릴 대본이 없습니다\n")
        raise SystemExit(1)

    pick = pick_balanced(q, ig_id)
    if not pick:
        print("", end="")
        sys.stderr.write("대기열이 비었습니다 — 일일 한도 초과\n")
        raise SystemExit(1)

    print(pick)


if __name__ == "__main__":
    main()
