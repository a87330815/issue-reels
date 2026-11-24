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
ACCOUNT_CSV_PATH = os.path.join(OUT_DIR, "account_insights.csv")


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
HOST = os.environ.get("IG_API_HOST", "graph.facebook.com")
VERSION = os.environ.get("IG_API_VERSION", "v26.0")
BASE = f"https://{HOST}/{VERSION}"


def _resolve_page_token():
    """사용자 토큰이면 페이지 토큰으로 변환. 이미 페이지 토큰이면 그대로 반환."""
    global TOKEN, BASE
    if not TOKEN:
        return
    import requests
    # me/accounts 호출 — 사용자 토큰이면 페이지 목록 반환, 페이지 토큰이면 빈 목록
    try:
        r = requests.get(
            f"{BASE}/me/accounts",
            headers={"Authorization": f"Bearer {TOKEN}"},
            timeout=15,
        )
        data = r.json()
        pages = data.get("data", [])
        if pages:
            TOKEN = pages[0]["access_token"]
            print(f"  [토큰] 사용자→페이지 토큰 변환 완료 (페이지: {pages[0].get('name', '?')})")
        else:
            print("  [토큰] 이미 페이지 토큰이거나 페이지 없음 — 그대로 사용")
    except Exception as e:
        print(f"  [토큰] 변환 시도 실패({e}) — 기존 토큰 사용")


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
def check_insights_permission(sample_media_id=None):
    """인사이트 API를 실제 호출해서 권한 확인. me/permissions는 페이지토큰에서 부정확."""
    if not sample_media_id:
        # 샘플 미디어가 없으면 일단 시도
        print("  [인사이트] 샘플 미디어 없음 — 개별 호출 시 확인")
        return True
    try:
        res = api("GET", f"{sample_media_id}/insights", metric="reach")
        # 정상 응답이면 권한 있음
        print("  [인사이트] ✓ 권한 확인됨 (실제 API 호출 성공)")
        return True
    except RuntimeError as e:
        err = str(e)
        if "10" in err or "permission" in err.lower() or "not authorized" in err.lower():
            print(f"  [인사이트] ✗ 권한 없음 — 기본 지표만 수집")
            print(f"    → {err[:120]}")
            return False
        # 다른 에러(미디어 타입 미지원 등)는 권한 문제가 아님
        print(f"  [인사이트] 확인 불확실({err[:80]}) — 개별 호출 시 재시도")
        return True


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
    metrics = "reach,saved,shares,views,total_interactions"
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
    "views",
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


ACCOUNT_FIELDS = [
    "collected_at", "ig_user_id", "username", "followers_count", "media_count",
]


def append_account_snapshot(now):
    """계정 팔로워·게시물 수를 하루 1회 누적 저장한다."""
    today = now[:10]
    if os.path.exists(ACCOUNT_CSV_PATH):
        with open(ACCOUNT_CSV_PATH, encoding="utf-8") as f:
            if any((row.get("collected_at") or "").startswith(today)
                   for row in csv.DictReader(f)):
                print("  [계정] 오늘 팔로워 스냅샷 이미 수집됨")
                return
    try:
        account = api(
            "GET", IG_ID,
            fields="id,username,followers_count,media_count",
        )
    except RuntimeError as e:
        print(f"  [계정] 팔로워 스냅샷 수집 실패: {e}")
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    write_header = not os.path.exists(ACCOUNT_CSV_PATH)
    with open(ACCOUNT_CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ACCOUNT_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow({
            "collected_at": now,
            "ig_user_id": account.get("id", IG_ID),
            "username": account.get("username", ""),
            "followers_count": account.get("followers_count", ""),
            "media_count": account.get("media_count", ""),
        })
    print(
        f"  [계정] @{account.get('username', '?')} | "
        f"팔로워 {account.get('followers_count', '?')} | "
        f"게시물 {account.get('media_count', '?')}"
    )


# ── 메인 ─────────────────────────────────────────────────────
def collect(limit=50):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    already = load_existing_ids()

    # 사용자 토큰이면 페이지 토큰으로 자동 변환
    _resolve_page_token()
    append_account_snapshot(now)

    print(f"미디어 목록 조회 (최대 {limit}개)...")
    media_list = fetch_media_list(limit)
    print(f"  {len(media_list)}개 미디어 발견")

    # 실제 VIDEO/REELS 미디어로 인사이트 권한 확인
    sample_video = next((m for m in media_list if m.get("media_type") in ("VIDEO", "REELS")), None)
    sample_id = sample_video["id"] if sample_video else None
    has_insights_perm = check_insights_permission(sample_id)

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
            "views": ins.get("views", ""),
            "total_interactions": ins.get("total_interactions", ""),
        }
        rows.append(row)
        views = ins.get("views", "?")
        reach = ins.get("reach", "?")
        print(f"  ✓ {mid} | {mtype} | 조회 {views} | 도달 {reach} | 좋아요 {m.get('like_count',0)}")

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
