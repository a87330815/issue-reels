# -*- coding: utf-8 -*-
"""
queue_next.py — 다음에 올릴 대본을 하나 고른다.

하루 여러 번 예약 발행하려면 "이번 슬롯에 뭘 올릴지"를 사람 없이 정해야 한다.
out/scripts/ 의 대본 중 아직 이 계정에 올리지 않은 것을 오래된 순으로 하나 집는다.

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

ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(ROOT, "out", "scripts")
PUBLISHED = os.path.join(ROOT, "out", "published_cards.json")


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
        # ig_id를 적기 전의 기록은 이전 계정 것이다. 지금 계정 기준으로는
        # 미발행이므로 완료로 세지 않는다.
        if ig_id and str(it.get("ig_id") or "") != str(ig_id):
            continue
        src = it.get("script") or ""
        if src:
            done.add(os.path.splitext(os.path.basename(src))[0])
    return done


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
            continue          # 카드가 아직 안 만들어진 대본은 건너뛴다
        out.append(stem)
    return out


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
        print(f"대기 {len(q)}건: {', '.join(q) or '-'}")
        return

    if not q:
        print("", end="")
        sys.stderr.write("대기열이 비었습니다 — 올릴 대본이 없습니다\n")
        raise SystemExit(1)

    print(q[0])


if __name__ == "__main__":
    main()
