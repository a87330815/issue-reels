# -*- coding: utf-8 -*-
"""
queue_next.py — 다음에 올릴 대본을 하나 고른다.

하루 여러 번 예약 발행하려면 "이번 슬롯에 뭘 올릴지"를 사람 없이 정해야 한다.
out/scripts/ 의 대본 중 아직 이 계정에 올리지 않은 것을 오래된 순으로 하나 집는다.

콘텐츠 비율:
  당일 화제 이슈    40%
  생활·지원금·제도  25%
  경제·부동산       20%
  놀라운 사건·화제  15%

계정 기준으로 거르는 이유:
  계정을 옮기면 같은 대본을 새 계정에 다시 올려야 한다. 대본 이름만 보고
  거르면 이전 계정 발행분까지 완료로 세어 새 계정에 아무것도 안 올라간다.
  그래서 발행 기록의 ig_id가 지금 계정과 같은 것만 "완료"로 센다.
  ig_id가 없는 옛 기록은 이전 계정 것으로 보고 완료에서 제외한다.

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
PUBLISHED = os.path.join(ROOT, "out", "published_cards.json")

# 목표 비율 (합 100)
TARGET_RATIO = {
    "당일 화제 이슈":    40,
    "생활·지원금·제도":  25,
    "경제·부동산":       20,
    "놀라운 사건·화제":  15,
}

# 하루 최대 1개 (부동산은 반복되면 지루함)
DAILY_LIMIT = {
    "경제·부동산": 1,
}


def cards_dir_for(stem):
    """대본 이름에 대응하는 카드 디렉터리. news_001 → out/cards_001"""
    return os.path.join(ROOT, "out", "cards_" + stem.replace("news_", "", 1))


def published_stems(ig_id):
    """지금 계정에 이미 올린 대본 이름들."""
    if not os.path.exists(PUBLISHED):
        return set()
    try:
        with open(PUBLISHED, encoding="utf-8") as f:
            items = json.load(f).get("items", [])
    except Exception:
        return set()

    done = set()
    for it in items:
        if ig_id and str(it.get("ig_id") or "") != str(ig_id):
            continue
        src = it.get("script") or ""
        if src:
            done.add(os.path.splitext(os.path.basename(src))[0])
    return done


def published_categories_today(ig_id):
    """오늘 발행한 대본의 카테고리를 세서 일일 한도 체크에 쓴다."""
    from datetime import date
    today = date.today().isoformat()
    if not os.path.exists(PUBLISHED):
        return Counter()
    try:
        with open(PUBLISHED, encoding="utf-8") as f:
            items = json.load(f).get("items", [])
    except Exception:
        return Counter()
    cats = Counter()
    for it in items:
        if ig_id and str(it.get("ig_id") or "") != str(ig_id):
            continue
        ts = it.get("published_at", "")
        if ts[:10] != today:
            continue
        cat = it.get("category", "")
        if cat:
            cats[cat] += 1
    return cats


def load_script_meta(stem):
    """대본 파일에서 meta.category를 읽는다."""
    path = os.path.join(SCRIPTS, f"{stem}.json")
    try:
        with open(path, encoding="utf-8") as f:
            sc = json.load(f)
        return (sc.get("meta") or {}).get("category", "")
    except Exception:
        return ""


def queue(ig_id):
    """올릴 수 있는 대본을 오래된 순으로. 카드가 없는 대본은 뺀다."""
    done = published_stems(ig_id)
    out = []
    for path in sorted(glob.glob(os.path.join(SCRIPTS, "*.json"))):
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem in done:
            continue
        cards = cards_dir_for(stem)
        if not glob.glob(os.path.join(cards, "*.png")):
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
    total_cats = Counter()
    if os.path.exists(PUBLISHED):
        try:
            with open(PUBLISHED, encoding="utf-8") as f:
                items = json.load(f).get("items", [])
            for it in items:
                if ig_id and str(it.get("ig_id") or "") != str(ig_id):
                    continue
                cat = it.get("category", "")
                if cat:
                    total_cats[cat] += 1
        except Exception:
            pass

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
        print(f"발행 완료 {len(done)}건: {', '.join(sorted(done)) or '-'}")
        print(f"대기 {len(q)}건:")
        for stem in q:
            cat = load_script_meta(stem)
            print(f"  {stem} [{cat or '미분류'}]")

        # 비율 현황
        total_cats = Counter()
        if os.path.exists(PUBLISHED):
            try:
                with open(PUBLISHED, encoding="utf-8") as f:
                    items = json.load(f).get("items", [])
                for it in items:
                    if ig_id and str(it.get("ig_id") or "") != str(ig_id):
                        continue
                    cat = it.get("category", "")
                    if cat:
                        total_cats[cat] += 1
            except Exception:
                pass
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
