# -*- coding: utf-8 -*-
"""
publish.py — 인스타그램 릴스 발행

흐름 (Instagram Content Publishing API):
  1. 컨테이너 생성  POST /{ig_id}/media  media_type=REELS + video_url
  2. 처리 대기      GET /{container_id}?fields=status_code  → FINISHED 까지
  3. 발행           POST /{ig_id}/media_publish  creation_id=...
  4. 지표 수집      GET /{media_id}/insights

중요한 전제 (프로젝트 기준):
  - 프로페셔널(비즈니스·크리에이터) 계정 필수. 개인 계정은 API 발행 불가
  - 영상은 **공개 URL**에 먼저 올라가 있어야 한다. 인스타가 그 주소에서 가져간다
  - 24시간 이동 기준 발행 제한이 있다. 실제 한도는 content_publishing_limit로 조회한다
  - 예약 시각은 UTC. 한국시간 11시 = 02:00 UTC. 이전 시 최다 발생 사고

환경변수:
  IG_USER_ID        인스타그램 비즈니스 계정 ID
  IG_ACCESS_TOKEN   장기 액세스 토큰
  IG_API_HOST       graph.instagram.com (기본) 또는 graph.facebook.com
  IG_API_VERSION    v26.0 (기본)

사용:
  python publish.py --check                    # 계정·토큰·한도 점검
  python publish.py --manifest out/uploaded.json
  python publish.py --video URL --caption "..."
  python publish.py --dry-run --manifest ...   # 발행 직전까지만
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "out")
MANIFEST = os.path.join(OUT_DIR, "uploaded.json")
PUBLISHED = os.path.join(OUT_DIR, "published.json")


def load_env():
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


load_env()

IG_ID = os.environ.get("IG_USER_ID", "")
TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
HOST = os.environ.get("IG_API_HOST", "graph.instagram.com")
VERSION = os.environ.get("IG_API_VERSION", "v21.0")
BASE = f"https://{HOST}/{VERSION}"

# 처리 대기 — 공식 권장은 1분 간격 5분 이내지만,
# 릴스는 길이에 따라 더 걸린다. 간격을 좁히고 상한을 늘렸다.
POLL_INTERVAL = 10
POLL_TIMEOUT = 600

# 자체 안전 한도. 실제 한도는 content_publishing_limit가 알려준다.
SELF_LIMIT = 10


def scrub(text):
    """에러 메시지에 토큰이 실려 나가는 것을 막는다."""
    return text.replace(TOKEN, "***") if TOKEN else text


def api(method, path, _retry=0, **params):
    """Graph API 호출. 토큰은 파라미터로 보낸다."""
    import requests

    url = f"{BASE}/{path.lstrip('/')}"
    params["access_token"] = TOKEN

    try:
        if method == "GET":
            r = requests.get(url, params=params, timeout=30)
        else:
            r = requests.post(url, data=params, timeout=60)
    except Exception as e:
        raise RuntimeError(f"{type(e).__name__}: {scrub(str(e))}") from None

    try:
        body = r.json()
    except ValueError:
        raise RuntimeError(f"HTTP {r.status_code}: {scrub(r.text[:300])}") from None

    if "error" in body:
        err = body["error"]
        code = err.get("code")
        subcode = err.get("error_subcode", "-")
        msg = scrub(err.get("message", ""))
        user_title = err.get("error_user_title", "")
        user_msg = err.get("error_user_msg", "")
        fbtrace = err.get("fbtrace_id", "")
        err_type = err.get("type", "")
        detail = f"[{code}/{subcode}] {msg}"
        if user_title:
            detail += f" | title={user_title}"
        if user_msg:
            detail += f" | user_msg={user_msg}"
        if fbtrace:
            detail += f" | fbtrace={fbtrace}"
        if err_type:
            detail += f" | type={err_type}"
        print(f"    ⚡ API 에러 상세: {detail}")
        # 플랫폼 내부 에러(-1)이면 재시도
        if code == -1 and _retry < 3:
            wait = 30 * (_retry + 1)
            print(f"    ⚠ 플랫폼 에러 (시도 {_retry+1}/3), {wait}초 후 재시도...")
            time.sleep(wait)
            return api(method, path, _retry=_retry + 1, **{k: v for k, v in params.items() if k != "access_token"})
        raise RuntimeError(f"[{code}/{subcode}] {msg}")
    return body


def check():
    """계정·토큰·발행 한도를 점검한다."""
    print("인스타 발행 설정:")
    print(f"  호스트      {HOST}")
    print(f"  API 버전    {VERSION}")
    print(f"  계정 ID     {IG_ID or '(미설정)'}")
    print(f"  액세스 토큰 {'설정됨' if TOKEN else '(미설정)'}")

    if not IG_ID or not TOKEN:
        print("\n[미설정] IG_USER_ID, IG_ACCESS_TOKEN")
        print("\n발급 순서:")
        print("  1. 인스타 계정을 프로페셔널(비즈니스·크리에이터)로 전환")
        print("  2. developers.facebook.com → 앱 생성 → Instagram 제품 추가")
        print("  3. 권한: instagram_business_basic, instagram_business_content_publish")
        print("  4. 장기 토큰 발급 후 GitHub Secrets에 등록")
        return False

    # account_type은 인스타 로그인 API에만 있는 필드다. Meta 앱 경유
    # (graph.facebook.com)로 받은 토큰에서는 없는 필드라 오류가 나므로,
    # 실패하면 공통 필드만으로 한 번 더 시도한다.
    me = None
    for fields in ("id,username,account_type,media_count", "id,username,media_count"):
        try:
            me = api("GET", IG_ID, fields=fields)
            break
        except Exception as e:
            err = e
    if me is None:
        print(f"\n[실패] 계정 조회: {err}")
        return False
    print(f"\n계정 확인: @{me.get('username')} "
          f"({me.get('account_type', '비즈니스')}) · 게시물 {me.get('media_count','?')}개")

    try:
        lim = api("GET", f"{IG_ID}/content_publishing_limit",
                  fields="config,quota_usage")
        d = (lim.get("data") or [{}])[0]
        used = d.get("quota_usage", 0)
        total = (d.get("config") or {}).get("quota_total", "?")
        print(f"발행 한도: 24시간 기준 {used}/{total}건 사용")
    except Exception as e:
        print(f"[경고] 한도 조회 실패: {e}")

    # 토큰 권한 디버그 — media_publish 실패 원인 추적
    try:
        import requests
        # debug_token은 앱 토큰 또는 같은 유저 토큰으로 호출
        dbg = api("GET", "debug_token", input_token=TOKEN)
        td = dbg.get("data", {})
        scopes = td.get("scopes", [])
        granular = td.get("granular_scopes", [])
        app_id = td.get("app_id", "?")
        expires = td.get("expires_at", 0)
        is_valid = td.get("is_valid", "?")
        print(f"\n🔑 토큰 디버그:")
        print(f"  app_id: {app_id}")
        print(f"  valid: {is_valid}")
        print(f"  expires_at: {expires}")
        print(f"  scopes: {scopes}")
        print(f"  granular_scopes: {granular}")
        # 핵심 권한 체크
        needed = {"instagram_content_publish", "instagram_basic",
                  "pages_read_engagement", "pages_show_list"}
        have = set(scopes)
        missing = needed - have
        if missing:
            print(f"  ⚠ 누락 권한: {missing}")
        else:
            print(f"  ✅ 필수 권한 모두 있음")
    except Exception as e:
        print(f"[경고] 토큰 디버그 실패: {e}")

    print("\n설정 완료")
    return True


def quota_left():
    """남은 발행 가능 건수. 조회 실패 시 자체 한도를 쓴다."""
    try:
        lim = api("GET", f"{IG_ID}/content_publishing_limit",
                  fields="config,quota_usage")
        d = (lim.get("data") or [{}])[0]
        used = d.get("quota_usage", 0)
        total = (d.get("config") or {}).get("quota_total", SELF_LIMIT)
        return max(0, total - used)
    except Exception:
        return SELF_LIMIT


def create_container(video_url, caption=None, cover_url=None, share_to_feed=True):
    """릴스 컨테이너를 만든다. 반환값은 컨테이너 ID."""
    params = {"media_type": "REELS", "video_url": video_url}
    if caption:
        params["caption"] = caption
    if cover_url:
        params["cover_url"] = cover_url
    if share_to_feed:
        params["share_to_feed"] = "true"

    res = api("POST", f"{IG_ID}/media", **params)
    return res["id"]


def wait_ready(container_id, timeout=POLL_TIMEOUT):
    """컨테이너가 FINISHED가 될 때까지 기다린다."""
    start = time.time()
    last = None

    while time.time() - start < timeout:
        res = api("GET", container_id, fields="status_code,status")
        code = res.get("status_code")

        if code != last:
            elapsed = int(time.time() - start)
            print(f"    {elapsed:>3}초  {code}")
            last = code

        if code == "FINISHED":
            return True, None
        if code in ("ERROR", "EXPIRED"):
            return False, res.get("status") or code

        time.sleep(POLL_INTERVAL)

    return False, f"타임아웃 ({timeout}초)"


def publish_one(video_url, caption=None, cover_url=None, dry_run=False):
    """영상 1편을 발행한다. 반환값은 미디어 ID 또는 None."""
    print(f"  영상: {video_url}")
    if cover_url:
        print(f"  커버: {cover_url}")
    if caption:
        first = caption.split("\n")[0]
        print(f"  캡션: {first[:50]}{'...' if len(first) > 50 else ''}")

    if dry_run:
        print("  [드라이런] 컨테이너 생성하지 않음")
        return None

    cid = create_container(video_url, caption, cover_url)
    print(f"  컨테이너: {cid}")

    ok, why = wait_ready(cid)
    if not ok:
        raise RuntimeError(f"컨테이너 처리 실패: {why}")

    # media_publish — 실패 시 다른 API 버전/호스트 조합으로 fallback
    global BASE
    original_base = BASE
    combos = [
        (HOST, VERSION),
        ("graph.facebook.com", "v21.0"),
        
        
        ("graph.facebook.com", "v26.0"),
    ]
    # 현재 설정을 맨 앞으로, 중복 제거
    seen = set()
    ordered = []
    for h, v in combos:
        key = (h, v)
        if key not in seen:
            seen.add(key)
            ordered.append(key)

    last_err = None
    for i, (h, v) in enumerate(ordered):
        BASE = f"https://{h}/{v}"
        try:
            res = api("POST", f"{IG_ID}/media_publish", creation_id=cid)
            media_id = res["id"]
            print(f"  발행 완료: {media_id}  (via {h}/{v})")
            return media_id
        except RuntimeError as e:
            last_err = e
            if i < len(ordered) - 1:
                print(f"    media_publish 실패 ({h}/{v}): {e}")
                print(f"    다음 조합으로 시도...")
                time.sleep(5)
    BASE = original_base
    raise last_err


def insights(media_id):
    """발행된 릴스의 지표를 가져온다. 발행 직후에는 대부분 0이다."""
    metrics = "reach,likes,comments,saved,shares,views"
    try:
        res = api("GET", f"{media_id}/insights", metrics=metrics)
        out = {}
        for m in res.get("data", []):
            vals = m.get("values") or [{}]
            out[m["name"]] = vals[0].get("value", 0)
        return out
    except Exception as e:
        return {"error": str(e)}


def build_caption(script):
    """대본 메타에서 캡션을 만든다. 출처 표기는 공공누리 조건이라 필수."""
    lines = []
    title = script.get("title")
    if title:
        lines.append(title)

    # 본문 — 자막을 이어붙인다
    subs = [s.get("subtitle", "") for s in script.get("scenes", []) if s.get("subtitle")]
    body = [s for s in subs if "프로필" not in s and "팔로우" not in s]
    if body:
        lines.append("")
        lines.extend(f"· {s}" for s in body[:4])

    meta = script.get("meta") or {}
    if meta.get("attribution"):
        lines.append("")
        lines.append(f"출처: {meta['attribution']}")

    tags = ["#이슈", "#뉴스", "#정보"]
    cat = meta.get("category")
    if cat:
        # 카테고리를 태그로 쪼갠다. 가운뎃점과 공백 둘 다 끊어야 한다.
        # "당일 화제 이슈"를 그대로 붙이면 인스타가 "#당일"까지만 태그로
        # 읽고 "화제 이슈"는 맨 글자로 남는다.
        for w in reversed(cat.replace("·", " ").split()):
            tags.insert(0, "#" + w)
    # 카테고리에서 쪼갠 태그가 기본 태그와 겹칠 수 있다
    # ("당일 화제 이슈" → #이슈). 순서를 지키면서 중복만 지운다.
    seen, uniq = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    lines.append("")
    lines.append(" ".join(uniq))

    return "\n".join(lines)


def load_manifest(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("items", [])


def record(entries):
    os.makedirs(OUT_DIR, exist_ok=True)
    history = []
    if os.path.exists(PUBLISHED):
        with open(PUBLISHED, encoding="utf-8") as f:
            history = json.load(f).get("items", [])
    history.extend(entries)
    with open(PUBLISHED, "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "items": history,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n발행 기록: {PUBLISHED}")


def test_publish():
    """media_publish 에러 2207085 진단 테스트.
    1) 최근 미디어 목록 확인 (에러나도 게시됐는지 판단용)
    2) 이미지 게시물 시도 (릴스 특정 문제인지 판별)
    3) 릴스 media_publish 재시도 + 에러 후 미디어 목록 재확인
    """
    import requests
    print("=" * 60)
    print("🔬 media_publish 진단 테스트")
    print("=" * 60)

    # 1) 현재 최근 미디어 목록
    print("\n[1/4] 최근 미디어 목록 확인...")
    try:
        recent = api("GET", f"{IG_ID}/media", fields="id,timestamp,media_type,caption", limit=5)
        items = recent.get("data", [])
        print(f"  최근 게시물 {len(items)}개:")
        for it in items:
            cap = (it.get("caption") or "")[:40]
            print(f"    {it['id']} | {it.get('media_type')} | {it.get('timestamp','')} | {cap}")
        before_ids = {it['id'] for it in items}
    except Exception as e:
        print(f"  미디어 목록 조회 실패: {e}")
        before_ids = set()

    # 2) 이미지 게시물 시도 (text만으로)
    print("\n[2/4] 이미지 게시물 테스트...")
    # 1x1 테스트 이미지 (공개 URL 필요)
    test_image_url = "https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/PNG_transparency_demonstration_1.png/280px-PNG_transparency_demonstration_1.png"
    try:
        img_cid = api("POST", f"{IG_ID}/media",
                       image_url=test_image_url,
                       caption="[진단 테스트 - 삭제 예정]")
        img_container_id = img_cid.get("id")
        print(f"  이미지 컨테이너 생성: {img_container_id}")

        # 이미지는 바로 FINISHED
        time.sleep(3)
        try:
            img_pub = api("POST", f"{IG_ID}/media_publish", creation_id=img_container_id)
            print(f"  ✅ 이미지 게시 성공! media_id={img_pub.get('id')}")
            print(f"     → 계정 자체는 정상. 릴스 특정 문제일 가능성.")
        except RuntimeError as e:
            print(f"  ❌ 이미지 게시도 실패: {e}")
            print(f"     → 계정 레벨 제한 확인됨 (2207085는 계정 restriction)")
    except Exception as e:
        print(f"  이미지 컨테이너 생성 실패: {e}")

    # 3) 기존 실패한 컨테이너 재시도 (마지막 실패 컨테이너 ID)
    print("\n[3/4] 기존 컨테이너 media_publish 재시도...")
    last_cid = os.environ.get("TEST_CONTAINER_ID", "17973979964973700")
    print(f"  컨테이너 ID: {last_cid}")
    try:
        # 먼저 상태 확인
        status = api("GET", last_cid, fields="id,status_code,status")
        print(f"  상태: {status}")
    except Exception as e:
        print(f"  컨테이너 상태 조회 실패: {e}")

    try:
        pub = api("POST", f"{IG_ID}/media_publish", creation_id=last_cid)
        print(f"  ✅ 게시 성공! media_id={pub.get('id')}")
    except RuntimeError as e:
        print(f"  ❌ 게시 실패: {e}")

    # 4) 게시 후 미디어 목록 재확인
    print("\n[4/4] 미디어 목록 재확인 (에러에도 게시됐는지)...")
    time.sleep(5)
    try:
        recent2 = api("GET", f"{IG_ID}/media", fields="id,timestamp,media_type,caption", limit=5)
        items2 = recent2.get("data", [])
        after_ids = {it['id'] for it in items2}
        new_ids = after_ids - before_ids
        if new_ids:
            print(f"  🆕 새로 발견된 게시물: {new_ids}")
            print(f"     → 에러 반환에도 불구하고 실제로 게시됨!")
        else:
            print(f"  새 게시물 없음 — 에러가 실제 실패")
        for it in items2:
            cap = (it.get("caption") or "")[:40]
            print(f"    {it['id']} | {it.get('media_type')} | {it.get('timestamp','')} | {cap}")
    except Exception as e:
        print(f"  목록 재확인 실패: {e}")

    print("\n" + "=" * 60)
    print("진단 완료")
    return 0


def main():
    ap = argparse.ArgumentParser(description="인스타그램 릴스 발행")
    ap.add_argument("--manifest", help="업로드 매니페스트 (upload.py 출력)")
    ap.add_argument("--video", help="영상 공개 URL (단건 발행)")
    ap.add_argument("--cover", help="커버 공개 URL")
    ap.add_argument("--caption", help="캡션")
    ap.add_argument("--script", help="대본 JSON — 캡션을 여기서 만든다")
    ap.add_argument("--check", action="store_true", help="설정만 점검")
    ap.add_argument("--test-publish", action="store_true", help="media_publish 진단 테스트")
    ap.add_argument("--dry-run", action="store_true", help="발행 직전까지만")
    ap.add_argument("--limit", type=int, default=1, help="한 번에 발행할 최대 편수")
    args = ap.parse_args()

    if args.check:
        return 0 if check() else 1

    if getattr(args, 'test_publish', False):
        return test_publish()

    if not IG_ID or not TOKEN:
        if not args.dry_run:
            print("[중단] IG_USER_ID / IG_ACCESS_TOKEN 미설정 — --check로 안내를 보세요")
            return 1
        # 드라이런은 발행 직전까지만 보는 것이므로 인증 없이도 끝까지 돌린다.
        # 인스타 설정 전에 앞 구간을 검증하려면 이게 돼야 한다.
        print("[알림] 인스타 인증 정보 미설정 — 드라이런이라 계속 진행합니다")

    # 발행 대상 수집
    jobs = []
    if args.video:
        jobs.append({"video_url": args.video, "cover_url": args.cover,
                     "caption": args.caption, "name": "manual"})
    elif args.manifest or os.path.exists(MANIFEST):
        path = args.manifest or MANIFEST
        for item in load_manifest(path):
            if item.get("verify_failed"):
                print(f"[건너뜀] {item.get('name')}: 공개 접근 확인 실패")
                continue
            jobs.append({
                "video_url": item["video_url"],
                "cover_url": item.get("cover_url"),
                "caption": args.caption,
                "name": item.get("name", "?"),
            })
    else:
        print("[알림] 발행할 대상이 없습니다 (--video 또는 --manifest)")
        return 1

    # 대본에서 캡션 생성
    if args.script and os.path.exists(args.script):
        with open(args.script, encoding="utf-8") as f:
            sc = json.load(f)
        caption = build_caption(sc)
        # 발행 기록에 카테고리를 남긴다. queue_next.py가 주제 비율을 맞출 때
        # 이 값을 센다. 없으면 대본을 다시 열어야 해서 여기서 함께 적는다.
        category = (sc.get("meta") or {}).get("category", "")
        for j in jobs:
            if not j.get("caption"):
                j["caption"] = caption
            j["category"] = category

    # 한도 확인 — 인증이 필요하므로 드라이런에서 인증이 없으면 건너뛴다
    if args.dry_run and (not IG_ID or not TOKEN):
        left = args.limit
    else:
        left = quota_left()
        print(f"남은 발행 가능: {left}건")
        if left <= 0:
            print("[중단] 24시간 발행 한도 소진")
            return 1

    jobs = jobs[:min(args.limit, left)]
    print(f"발행 대상: {len(jobs)}건\n")

    results, failed = [], 0
    for i, job in enumerate(jobs):
        print(f"── {i+1}/{len(jobs)}  {job['name']}")
        try:
            media_id = publish_one(
                job["video_url"], job.get("caption"),
                job.get("cover_url"), dry_run=args.dry_run,
            )
            if media_id:
                results.append({
                    "name": job["name"],
                    "media_id": media_id,
                    "published_at": datetime.now(timezone.utc).isoformat(),
                    "video_url": job["video_url"],
                    # 계정을 옮기면 같은 대본을 새 계정에 다시 올려야 한다.
                    # 어느 계정에 올린 기록인지 남겨 둬야 그 판정이 된다.
                    "ig_id": IG_ID or "",
                    "category": job.get("category", ""),
                    "insights": insights(media_id),
                })
        except Exception as e:
            print(f"  [실패] {e}")
            failed += 1
        print()

    if results:
        record(results)

    print(f"완료: 발행 {len(results)}건 / 실패 {failed}건")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
