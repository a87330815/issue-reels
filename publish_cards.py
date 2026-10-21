# -*- coding: utf-8 -*-
"""
publish_cards.py — 카드뉴스 캐러셀 발행

여러 장을 한 게시물로 올리는 캐러셀 흐름 (publish.py의 릴스와 별개):

  1. 장별 컨테이너   POST /{ig_id}/media  image_url=... is_carousel_item=true
  2. 캐러셀 컨테이너 POST /{ig_id}/media  media_type=CAROUSEL children=... caption=...
  3. 발행            POST /{ig_id}/media_publish  creation_id=...

주의할 점 둘:
  - 인스타는 PNG를 받지 않는다. 올리기 전에 JPEG로 바꾼다.
  - image_url은 인스타 서버가 직접 가져간다. 공개 주소여야 해서
    upload.py의 공개 미디어 저장소에 먼저 올린다.

사용:
  python publish_cards.py --check
  python publish_cards.py out/cards_002 --script out/scripts/news_002.json   # 준비만 (기본)
  python publish_cards.py out/cards_002 --script out/scripts/news_002.json --publish
"""
import argparse
import glob
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone

from PIL import Image

import publish as P
import upload as U

MAX_ITEMS = 10          # 캐러셀 상한
OUT_DIR = "out"
PUBLISHED = os.path.join(OUT_DIR, "published_cards.json")


# ── 카드 준비 ────────────────────────
def card_files(card_dir):
    """카드 PNG를 슬라이드 순서대로 모은다."""
    files = sorted(glob.glob(os.path.join(card_dir, "*.png")))
    if not files:
        raise SystemExit(f"카드 이미지가 없습니다: {card_dir}")
    if len(files) > MAX_ITEMS:
        print(f"  경고: {len(files)}장 → 캐러셀 상한 {MAX_ITEMS}장까지만 올립니다")
        files = files[:MAX_ITEMS]
    return files


def to_jpeg(png_path, out_dir):
    """인스타는 JPEG만 받는다. 4:5 비율(1080x1350)은 그대로 통과한다."""
    im = Image.open(png_path).convert("RGB")
    name = os.path.splitext(os.path.basename(png_path))[0] + ".jpg"
    dst = os.path.join(out_dir, name)
    im.save(dst, "JPEG", quality=92, optimize=True)
    return dst


def build_caption(script):
    """캡션. 출처 표기는 공공누리 조건이라 필수이고,
    사진이 CC BY면 저작자 표기도 라이선스 조건이라 함께 넣는다."""
    meta = script.get("meta") or {}
    lines = []

    title = script.get("title")
    if title:
        lines.append(title)

    subs = [s.get("subtitle", "") for s in script.get("scenes", []) if s.get("subtitle")]
    body = [s for s in subs
            if "프로필" not in s and "팔로우" not in s and s.strip() != (title or "").strip()]
    if body:
        lines.append("")
        lines.extend(f"· {s}" for s in body[:5])

    lines.append("")
    lines.append("저장해두고 필요할 때 꺼내 보세요.")

    if meta.get("attribution"):
        lines.append("")
        lines.append(f"출처: {meta['attribution']}")

    tags = ["#생활정보", "#알아두면좋은정보", "#정책정보", "#꿀팁"]
    cat = meta.get("category")
    if cat:
        tags.insert(0, "#" + cat.replace("·", "").replace(" ", ""))
    lines.append("")
    lines.append(" ".join(tags))

    return "\n".join(lines)


def photo_credits(photo_dir):
    """CC BY 사진의 저작자 표기 문구. 없으면 빈 문자열."""
    mpath = os.path.join(photo_dir or "", "photos.json")
    if not os.path.exists(mpath):
        return ""
    try:
        with open(mpath, encoding="utf-8") as f:
            man = json.load(f)
    except Exception:
        return ""
    seen, parts = set(), []
    for c in man.get("credits", []):
        lic = (c.get("license") or "").upper()
        if lic.startswith(("PUBLIC", "PD", "CC0", "PDM", "NO RESTRICTIONS")):
            continue  # 표기 의무 없음
        key = (c.get("creator"), c.get("source"))
        if key in seen:
            continue
        seen.add(key)
        parts.append(f"{c.get('creator','')} ({c.get('source','')}, {c.get('license','')})")
    return "사진: " + " / ".join(parts) if parts else ""


# ── 발행 ────────────────────────────
def host_images(files, tag):
    """공개 주소로 올리고 URL 목록을 돌려준다."""
    urls = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, f in enumerate(files, 1):
            jpg = to_jpeg(f, tmp)
            size_kb = os.path.getsize(jpg) // 1024
            url = U.gh_upload(jpg, tag)
            ok, detail = U.verify(url)
            mark = "✓" if ok else "✗"
            print(f"  {mark} [{i}/{len(files)}] {os.path.basename(jpg)}  {size_kb}KB  {detail}")
            if not ok:
                raise SystemExit(f"공개 접근 실패 — 인스타가 가져갈 수 없습니다: {url}")
            urls.append(url)
    return urls


def create_items(urls):
    """장별 캐러셀 아이템 컨테이너를 만든다."""
    ids = []
    for i, u in enumerate(urls, 1):
        res = P.api("POST", f"{P.IG_ID}/media", image_url=u, is_carousel_item="true")
        cid = res.get("id")
        print(f"  [{i}/{len(urls)}] 컨테이너 {cid}")
        ids.append(cid)
    return ids


def create_carousel(children, caption):
    res = P.api("POST", f"{P.IG_ID}/media", media_type="CAROUSEL",
                children=",".join(children), caption=caption)
    return res.get("id")


def record(entry):
    os.makedirs(OUT_DIR, exist_ok=True)
    items = []
    if os.path.exists(PUBLISHED):
        try:
            with open(PUBLISHED, encoding="utf-8") as f:
                items = json.load(f).get("items", [])
        except Exception:
            pass
    items.append(entry)
    with open(PUBLISHED, "w", encoding="utf-8") as f:
        json.dump({"updated_at": datetime.now(timezone.utc).isoformat(),
                   "items": items}, f, ensure_ascii=False, indent=2)
    print(f"발행 기록: {PUBLISHED}")


def ensure_ig_id():
    """IG_USER_ID가 없으면 토큰으로 조회해 채운다.

    계정 ID는 비밀값이 아니라 토큰에서 바로 얻을 수 있는 공개 식별자다.
    Secret 등록을 기다릴 이유가 없어 자동으로 해결한다."""
    if P.IG_ID:
        return P.IG_ID
    if not P.TOKEN:
        return ""
    for field in ("user_id", "id"):
        try:
            res = P.api("GET", "me", fields=field)
            v = res.get(field) or res.get("id")
            if v:
                P.IG_ID = str(v)
                print(f"  IG_USER_ID 미설정 → 토큰에서 조회함: {P.IG_ID}")
                return P.IG_ID
        except Exception as e:
            print(f"  IG_USER_ID 조회 실패 ({field}): {e}")
    return ""


def run(card_dir, script_path, photo_dir=None, do_publish=False):
    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    files = card_files(card_dir)
    caption = build_caption(script)
    credit = photo_credits(photo_dir)
    if credit:
        caption += "\n" + credit

    print(f"\n대상: {card_dir}  ({len(files)}장)")
    print(f"대본: {script_path}")
    print("\n--- 캡션 ---")
    print(caption)
    print("--- 캡션 끝 ---\n")

    if not P.TOKEN:
        raise SystemExit("[중단] IG_ACCESS_TOKEN 미설정 — 이 값은 비밀이라 직접 등록해야 합니다")
    if not ensure_ig_id():
        raise SystemExit("[중단] IG_USER_ID를 토큰으로 조회하지 못했습니다 "
                         "(토큰 만료이거나 권한 부족일 수 있습니다)")

    left = P.quota_left()
    print(f"남은 발행 가능: {left}건")
    if left <= 0:
        raise SystemExit("[중단] 24시간 발행 한도 소진")

    tag = "cards-" + os.path.basename(card_dir.rstrip("/"))
    print("\n1) 이미지 공개 호스팅")
    urls = host_images(files, tag)

    print("\n2) 장별 컨테이너 생성")
    children = create_items(urls)

    print("\n3) 캐러셀 컨테이너 생성")
    carousel_id = create_carousel(children, caption)
    print(f"  캐러셀 {carousel_id}")

    ok, err = P.wait_ready(carousel_id)
    if not ok:
        raise SystemExit(f"[중단] 컨테이너 준비 실패: {err}")

    if not do_publish:
        print("\n준비 완료. 실제 발행은 하지 않았습니다 (--publish 를 주면 올라갑니다).")
        print(f"  캐러셀 컨테이너: {carousel_id}")
        return {"status": "prepared", "carousel_id": carousel_id, "urls": urls}

    print("\n4) 발행")
    res = P.api("POST", f"{P.IG_ID}/media_publish", creation_id=carousel_id)
    media_id = res.get("id")
    print(f"  발행 완료: media_id={media_id}")

    entry = {
        "published_at": datetime.now(timezone.utc).isoformat(),
        "media_id": media_id, "card_dir": card_dir, "script": script_path,
        "title": script.get("title"), "count": len(files),
    }
    record(entry)
    return {"status": "published", "media_id": media_id}


def main():
    ap = argparse.ArgumentParser(description="카드뉴스 캐러셀 발행")
    ap.add_argument("card_dir", nargs="?", help="카드 PNG 디렉터리 (예: out/cards_002)")
    ap.add_argument("--script", help="대본 JSON (캡션 생성용)")
    ap.add_argument("--photos", help="사진 디렉터리 (CC BY 저작자 표기용)")
    ap.add_argument("--publish", action="store_true",
                    help="실제로 올린다. 주지 않으면 컨테이너까지만 만들고 멈춘다")
    ap.add_argument("--check", action="store_true", help="설정 점검만")
    a = ap.parse_args()

    if a.check:
        ensure_ig_id()
        ok_ig = P.check()
        print()
        ok_media = U.gh_check()
        # 점검이 실패했는데 단계가 성공으로 보이면, 뒤 단계에서 원인 모를
        # 실패가 난다. 여기서 바로 멈춘다.
        if ok_ig is False or ok_media is False:
            raise SystemExit("[중단] 설정 점검 실패 — 위 안내를 확인하세요")
        return

    if not a.card_dir or not a.script:
        ap.error("card_dir 와 --script 가 필요합니다")

    run(a.card_dir, a.script, a.photos, a.publish)


if __name__ == "__main__":
    main()
