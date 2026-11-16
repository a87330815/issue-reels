# -*- coding: utf-8 -*-
"""
insights.py — 인스타그램 릴스 인사이트 수집

매일 실행하여 각 릴스의 조회수·도달·저장·공유·좋아요·댓글 수를 CSV로 누적 저장한다.
GitHub Actions cron으로 돌리고, CSV는 커밋하여 추적한다.

사용:
  python insights.py                  # 최근 미디어 인사이트 수집
  python insights.py --limit 50       # 최대 50개 미디어
  python insights.py --check          # 설정 점검만

환경변수:
  IG_USER_ID        인스타그램 비즈니스 계정 ID
  IG_ACCESS_TOKEN   장기 액세스 토큰
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "data")
CSV_PATH = os.path.join(OUT_DIR, "insights.csv")


# ── publish.py의 api() 재사용 ──────────────────────────────────
def _load_env():
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

_load_env()

IG_ID = os.environ.get("IG_USER_ID", "")
TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
HOST = os.environ.get("IG_API_HOST", "graph.instagram.com")
VERSION = os.environ.get("IG_API_VERSION", "v26.0")
BASE = f"https://{HOST}/{VERSION}"


def scrub(text):
    return text.replace(TOKEN, "***") if TOKEN else text


def api(method, path, **params):
    import requests
    url = f"{BASE}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    try:
        if method == "GET":
            r = requests.get(url, params=params, headers=headers, timeout=30)
        else:
            r = requests.post(url, data=params, headers=headers, timeout=60)
    except Exception as e:
        raise RuntimeError(f"{type(e).__name__}: {scrub(str(e))}") from None
    try:
        body = r.json()
    except ValueError:
        raise RuntimeError(f"HTTP {r.status_code}: {scrub(r.text[:300])}") from None
    if "error" in body:
        err = body["error"]
        raise RuntimeError(
            f"[{err.get('code')}/{err.get('error_subcode','-')}] "
            f"{scrub(err.get('message', ''))}"
        )
    return body


# ── 미디어 목록 가져오기 ─────────────────────────────────────
def check_insights_permission():
    """instagram_manage_insights 권한이 있는지 확인."""
    try:
        res = api("GET", "me/permissions")
        perms = {p["permission"] for p in res.get("data", []) if p.get("status") == "granted"}
        has_insights = "instagram_manage_insights" in perms or "instagram_business_manage_insights" in perms
        has_pages = "pages_read_engagement" in perms
        if not has_insights:
            print("  [권한 없음] instagram_manage_insights — 인사이트(도달·저장·공유) 수집 불가")
            print("  → developers.facebook.com → 앱 → 권한 → instagram_manage_insights 추가 필요")
        if not has_pages:
            print("  [권한 없음] pages_read_engagement")
        return has_insights
    except Exception:
        return True  # 확인 실패 시 일단 시도


def fetch_media_list(limit=50):
    """최근 미디어 목록. 페이징으로 limit개까지 수집."""
    items = []
    fields = "id,caption,timestamp,media_type,permalink,like_count,comments_count"
    params = {"fields": fields, "limit": min(limit, 50)}
    path = f"{IG_ID}/media"

    while len(items) < limit:
        res = api("GET", path, **params)
        for m in res.get("data", []):
            items.append(m)
            if len(items) >= limit:
                break
        paging = res.get("paging", {})
        next_url = paging.get("next")
        if not next_url:
            break
        # next URL에서 after 커서 추출
        import urllib.parse
        parsed = urllib.parse.urlparse(next_url)
        qs = urllib.parse.parse_qs(parsed.query)
        after = qs.get("after", [None])[0]
        if not after:
            break
        params["after"] = after

    return items


# ── 개별 미디어 인사이트 ─────────────────────────────────────
def fetch_insights(media_id, media_type="VIDEO"):
    """릴스/비디오 인사이트. 이미지는 지원 메트릭이 다르다."""
    # 릴스(REELS/VIDEO)용 메트릭
    metrics = "reach,saved,shares,plays,total_interactions"
    try:
        res = api("GET", f"{media_id}/insights", metric=metrics)
        out = {}
        for m in res.get("data", []):
            vals = m.get("values") or [{}]
            out[m["name"]] = vals[0].get("value", 0)
        return out
    except RuntimeError as e:
        # 이미지/카루셀은 일부 메트릭 미지원 → 빈 dict
        return {"error": str(e)}


# ── CSV 관리 ─────────────────────────────────────────────────
CSV_FIELDS = [
    "collected_at",     # 수집 시각 (UTC)
    "media_id",
    "media_type",
    "permalink",
    "caption_preview",  # 캡션 앞 60자
    "timestamp",        # 게시 시각
    "like_count",
    "comments_count",
    "reach",
    "saved",
    "shares",
    "plays",
    "total_interactions",
]


def load_existing_ids():
    """이미 오늘 수집한 media_id 세트 (중복 방지)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ids = set()
    if not os.path.exists(CSV_PATH):
        return ids
    with open(CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("collected_at", "").startswith(today):
                ids.add(row.get("media_id"))
    return ids


def append_rows(rows):
    os.makedirs(OUT_DIR, exist_ok=True)
    write_header = not os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


# ── 메인 ─────────────────────────────────────────────────────
def collect(limit=50):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    already = load_existing_ids()

    has_insights_perm = check_insights_permission()

    print(f"미디어 목록 조회 (최대 {limit}개)...")
    media_list = fetch_media_list(limit)
    print(f"  {len(media_list)}개 미디어 발견")

    rows = []
    for m in media_list:
        mid = m["id"]
        if mid in already:
            print(f"  [건너뜀] {mid} (오늘 이미 수집)")
            continue

        mtype = m.get("media_type", "")
        caption = (m.get("caption") or "")[:60].replace("\n", " ")

        # 인사이트 조회 (릴스/비디오만, 권한 있을 때)
        ins = {}
        if mtype in ("VIDEO", "REELS") and has_insights_perm:
            ins = fetch_insights(mid, mtype)
            if "error" in ins:
                # 첫 번째 오류만 출력
                if not hasattr(collect, '_insight_err_shown'):
                    print(f"  [경고] 인사이트 권한 부족 — 기본 지표만 수집")
                    collect._insight_err_shown = True
                ins = {}

        row = {
            "collected_at": now,
            "media_id": mid,
            "media_type": mtype,
            "permalink": m.get("permalink", ""),
            "caption_preview": caption,
            "timestamp": m.get("timestamp", ""),
            "like_count": m.get("like_count", 0),
            "comments_count": m.get("comments_count", 0),
            "reach": ins.get("reach", ""),
            "saved": ins.get("saved", ""),
            "shares": ins.get("shares", ""),
            "plays": ins.get("plays", ""),
            "total_interactions": ins.get("total_interactions", ""),
        }
        rows.append(row)
        plays = ins.get("plays", "?")
        reach = ins.get("reach", "?")
        print(f"  ✓ {mid} | {mtype} | 조회 {plays} | 도달 {reach} | 좋아요 {m.get('like_count',0)}")

    if rows:
        append_rows(rows)
        print(f"\n{len(rows)}개 미디어 인사이트 저장 → {CSV_PATH}")
    else:
        print("\n새로 수집할 데이터 없음")

    return rows


def check():
    print("인사이트 수집 설정 점검:")
    print(f"  IG_USER_ID     = {IG_ID or '(미설정)'}")
    print(f"  IG_ACCESS_TOKEN = {'설정됨' if TOKEN else '(미설정)'}")
    if not IG_ID or not TOKEN:
        print("\n[오류] 환경변수 미설정")
        return False
    try:
        me = api("GET", IG_ID, fields="id,username,media_count")
        print(f"  계정: @{me.get('username')} (게시물 {me.get('media_count','?')}개)")
        print("\n설정 OK")
        return True
    except Exception as e:
        print(f"\n[오류] {e}")
        return False


def main():
    ap = argparse.ArgumentParser(description="인스타그램 릴스 인사이트 수집")
    ap.add_argument("--limit", type=int, default=50, help="수집할 최대 미디어 수")
    ap.add_argument("--check", action="store_true", help="설정 점검만")
    ap.add_argument("--force", action="store_true", help="오늘 데이터 삭제 후 재수집")
    args = ap.parse_args()

    if args.force and os.path.exists(CSV_PATH):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        import io
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        kept = [lines[0]] + [l for l in lines[1:] if not l.startswith(today)]
        with open(CSV_PATH, "w", encoding="utf-8") as f:
            f.writelines(kept)
        print(f"[force] 오늘({today}) 데이터 삭제 완료 ({len(lines)-len(kept)}건)")

    if args.check:
        sys.exit(0 if check() else 1)

    if not IG_ID or not TOKEN:
        print("[오류] IG_USER_ID, IG_ACCESS_TOKEN 환경변수 필요")
        sys.exit(1)

    collect(args.limit)


if __name__ == "__main__":
    main()
