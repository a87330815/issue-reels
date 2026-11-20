# -*- coding: utf-8 -*-
"""
publish_tiktok.py — TikTok 릴스(숏폼) 발행

흐름 (TikTok Content Posting API — Direct Post):
  1. 크리에이터 정보 조회  POST /v2/post/publish/creator_info/query/
  2. 발행 초기화          POST /v2/post/publish/video/init/
     - PULL_FROM_URL: 공개 URL에서 TikTok이 가져감
     - FILE_UPLOAD:   upload_url로 직접 업로드
  3. 상태 확인            POST /v2/post/publish/status/fetch/

중요 전제:
  - TikTok 개발자 앱이 Content Posting API 감사(audit)를 통과해야
    PUBLIC_TO_EVERYONE으로 발행 가능. 미통과 시 SELF_ONLY만 됨.
  - PULL_FROM_URL은 도메인/URL 접두사 검증이 필요.
    검증 안 된 도메인이면 FILE_UPLOAD로 폴백.
  - 분당 6회 요청 제한 (유저 토큰 기준).

환경변수:
  TIKTOK_ACCESS_TOKEN   유저 액세스 토큰
  TIKTOK_OPEN_ID        유저 open_id (OAuth 로그인 시 발급)
  TIKTOK_UPLOAD_METHOD  pull 또는 file (기본: pull)

사용:
  python publish_tiktok.py --check
  python publish_tiktok.py --video URL --title "..."
  python publish_tiktok.py --manifest out/uploaded.json
  python publish_tiktok.py --dry-run --manifest ...
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
PUBLISHED_TT = os.path.join(OUT_DIR, "published_tiktok.json")

API_BASE = "https://open.tiktokapis.com/v2"

# 상태 폴링
POLL_INTERVAL = 10
POLL_TIMEOUT = 300


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

TOKEN = os.environ.get("TIKTOK_ACCESS_TOKEN", "")
OPEN_ID = os.environ.get("TIKTOK_OPEN_ID", "")
UPLOAD_METHOD = os.environ.get("TIKTOK_UPLOAD_METHOD", "pull").lower()


def scrub(text):
    """에러 메시지에 토큰이 실려 나가지 않도록."""
    return text.replace(TOKEN, "***") if TOKEN else text


def tt_api(path, body=None):
    """TikTok API 호출. 모든 엔드포인트가 POST + JSON이다."""
    import requests

    url = f"{API_BASE}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    try:
        r = requests.post(url, json=body or {}, headers=headers, timeout=60)
    except Exception as e:
        raise RuntimeError(f"{type(e).__name__}: {scrub(str(e))}") from None

    try:
        resp = r.json()
    except ValueError:
        raise RuntimeError(f"HTTP {r.status_code}: {scrub(r.text[:300])}") from None

    err = resp.get("error", {})
    code = err.get("code", "ok")
    if code != "ok":
        raise RuntimeError(
            f"[{code}] {scrub(err.get('message', ''))} "
            f"(log_id={err.get('log_id', '-')})"
        )
    return resp


def check():
    """계정·토큰 점검. 기본 프로필 조회 후 Direct Post 권한을 별도 확인한다."""
    import requests

    print("틱톡 발행 설정:")
    print(f"  업로드 방식    {UPLOAD_METHOD}")
    print(f"  OPEN_ID       {OPEN_ID[:8] + '...' if OPEN_ID else '(미설정)'}")
    print(f"  액세스 토큰    {'설정됨' if TOKEN else '(미설정)'}")

    if not TOKEN or not OPEN_ID:
        print("\n[미설정] TIKTOK_ACCESS_TOKEN, TIKTOK_OPEN_ID")
        return False

    # user.info.basic으로 OAuth 계정 연결 자체를 확인한다.
    try:
        r = requests.get(
            f"{API_BASE}/user/info/",
            params={"fields": "open_id,display_name,avatar_url"},
            headers={"Authorization": f"Bearer {TOKEN}"},
            timeout=60,
        )
        resp = r.json()
        err = resp.get("error", {})
        if err.get("code", "ok") != "ok":
            raise RuntimeError(
                f"[{err.get('code')}] {scrub(err.get('message', ''))} "
                f"(log_id={err.get('log_id', '-')})"
            )
        user = resp.get("data", {}).get("user", {})
        if user.get("open_id") != OPEN_ID:
            raise RuntimeError("발급 토큰의 open_id가 GitHub Secret과 일치하지 않습니다")
        print("\n✅ OAuth 계정 연결 확인")
        print(f"  계정           {user.get('display_name', '?')}")
    except Exception as e:
        print(f"\n[실패] 기본 프로필 조회: {e}")
        return False

    # Direct Post(video.publish)는 앱 심사 전에는 승인되지 않을 수 있다.
    try:
        resp = tt_api("post/publish/creator_info/query/")
        data = resp.get("data", {})
        privs = data.get("privacy_level_options", [])
        print("\n✅ Direct Post 권한 확인")
        print(f"  공개 옵션       {', '.join(privs)}")
    except Exception as e:
        if "scope_not_authorized" in str(e):
            print("\n⚠️  현재 video.upload(초안 업로드)만 연결됨")
            print("   video.publish는 TikTok 앱 심사 승인 후 사용 가능")
        else:
            print(f"\n[실패] 크리에이터 조회: {e}")
            return False

    print("\n설정 완료")
    return True


def init_post_pull(video_url, title="", privacy="PUBLIC_TO_EVERYONE"):
    """PULL_FROM_URL 방식으로 발행을 초기화한다."""
    body = {
        "post_info": {
            "title": title[:2200] if title else "",
            "privacy_level": privacy,
            "disable_duet": False,
            "disable_stitch": False,
            "disable_comment": False,
            "is_aigc": True,  # AI 생성 콘텐츠 표시
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "video_url": video_url,
        },
    }
    resp = tt_api("post/publish/video/init/", body)
    return resp.get("data", {}).get("publish_id", "")


def init_post_file(video_path, title="", privacy="PUBLIC_TO_EVERYONE"):
    """FILE_UPLOAD 방식으로 발행을 초기화한다."""
    file_size = os.path.getsize(video_path)
    # 단일 청크 (50MB 이하)
    body = {
        "post_info": {
            "title": title[:2200] if title else "",
            "privacy_level": privacy,
            "disable_duet": False,
            "disable_stitch": False,
            "disable_comment": False,
            "is_aigc": True,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": file_size,
            "chunk_size": file_size,
            "total_chunk_count": 1,
        },
    }
    resp = tt_api("post/publish/video/init/", body)
    data = resp.get("data", {})
    publish_id = data.get("publish_id", "")
    upload_url = data.get("upload_url", "")

    if not upload_url:
        raise RuntimeError("upload_url을 받지 못했습니다")

    # 파일 업로드
    import requests
    with open(video_path, "rb") as f:
        video_data = f.read()

    headers = {
        "Content-Type": "video/mp4",
        "Content-Length": str(file_size),
        "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
    }
    r = requests.put(upload_url, data=video_data, headers=headers, timeout=300)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"업로드 실패: HTTP {r.status_code}")

    print(f"    파일 업로드 완료 ({file_size / 1024 / 1024:.1f}MB)")
    return publish_id


def wait_published(publish_id, timeout=POLL_TIMEOUT):
    """발행이 완료될 때까지 상태를 폴링한다."""
    start = time.time()
    last_status = None

    while time.time() - start < timeout:
        try:
            resp = tt_api("post/publish/status/fetch/", {
                "publish_id": publish_id,
            })
        except Exception as e:
            # 일시적 오류는 재시도
            elapsed = int(time.time() - start)
            print(f"    {elapsed:>3}초  상태 조회 실패: {e}")
            time.sleep(POLL_INTERVAL)
            continue

        data = resp.get("data", {})
        status = data.get("status", "PROCESSING")

        if status != last_status:
            elapsed = int(time.time() - start)
            print(f"    {elapsed:>3}초  {status}")
            last_status = status

        if status == "PUBLISH_COMPLETE":
            return True, data.get("publicaly_available_post_id", [""])[0]

        if status == "FAILED":
            fail_reason = data.get("fail_reason", "알 수 없음")
            return False, fail_reason

        time.sleep(POLL_INTERVAL)

    return False, f"타임아웃 ({timeout}초)"


def build_title(script):
    """대본에서 틱톡 제목(캡션)을 만든다. 해시태그 포함."""
    lines = []
    title = script.get("title", "")
    if title:
        lines.append(title)

    # 핵심 자막 2~3줄
    subs = [s.get("subtitle", "") for s in script.get("scenes", [])
            if s.get("subtitle")]
    body = [s for s in subs if "프로필" not in s and "팔로우" not in s]
    if body:
        lines.append("")
        lines.extend(f"· {s}" for s in body[:3])

    meta = script.get("meta") or {}

    # CTA
    lines.append("")
    lines.append("💾 저장하고 나중에 다시 보세요!")
    lines.append("📩 이거 알아야 할 사람한테 보내주세요")

    # 해시태그 — 틱톡 발견성 최적화
    cat = meta.get("category", "")
    _TT_TAGS = {
        "재테크":     ["#재테크", "#돈공부", "#재테크팁", "#돈모으기"],
        "저축·투자":  ["#투자", "#주식", "#재테크", "#주식초보"],
        "보험·연금":  ["#보험", "#연금", "#노후준비", "#보험팁"],
        "세금·절약":  ["#절약", "#세금팁", "#가계부", "#재테크"],
        "돈습관":     ["#돈습관", "#월급관리", "#돈모으기", "#재테크팁"],
        "경제상식":   ["#경제", "#경제상식", "#돈공부", "#재테크"],
    }
    tags = _TT_TAGS.get(cat, ["#재테크", "#돈공부", "#돈모으기"])
    kw = meta.get("trend_keyword", "")
    if kw and len(kw) <= 10:
        tags.insert(0, f"#{kw.replace(' ', '')}")
    tags.append("#쫌봐봐")
    tags.append("#틱톡추천")
    # 중복 제거
    seen, uniq = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    lines.append("")
    lines.append(" ".join(uniq[:10]))

    return "\n".join(lines)


def publish_one(video_url, title="", dry_run=False, video_path=None):
    """영상 1편을 틱톡에 발행한다."""
    print(f"  영상: {video_url or video_path}")
    if title:
        first = title.split("\n")[0]
        print(f"  제목: {first[:50]}{'...' if len(first) > 50 else ''}")

    if dry_run:
        print("  [드라이런] 발행하지 않음")
        return None

    # 크리에이터 정보에서 공개 옵션 확인
    try:
        info = tt_api("post/publish/creator_info/query/")
        privs = info.get("data", {}).get("privacy_level_options", [])
    except Exception:
        privs = ["SELF_ONLY"]

    privacy = "PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in privs else "SELF_ONLY"
    if privacy == "SELF_ONLY":
        print("  ⚠️  공개 발행 불가 — SELF_ONLY로 발행 (앱에서 수동 공개)")

    # 발행 초기화
    method = UPLOAD_METHOD
    try:
        if method == "pull" and video_url:
            print(f"  방식: PULL_FROM_URL")
            publish_id = init_post_pull(video_url, title, privacy)
        elif video_path and os.path.exists(video_path):
            print(f"  방식: FILE_UPLOAD")
            publish_id = init_post_file(video_path, title, privacy)
        elif video_url:
            # file 모드인데 로컬 파일이 없으면 pull로 폴백
            print(f"  방식: PULL_FROM_URL (폴백)")
            publish_id = init_post_pull(video_url, title, privacy)
        else:
            raise RuntimeError("영상 URL 또는 로컬 파일 경로 필요")
    except RuntimeError as e:
        # PULL_FROM_URL 도메인 미검증 시 FILE_UPLOAD로 폴백
        if "url_ownership_unverified" in str(e) and video_path:
            print(f"  ⚠️  도메인 미검증 — FILE_UPLOAD로 폴백")
            publish_id = init_post_file(video_path, title, privacy)
        else:
            raise

    print(f"  publish_id: {publish_id}")

    # 상태 대기
    ok, result = wait_published(publish_id)
    if not ok:
        raise RuntimeError(f"발행 실패: {result}")

    print(f"  ✅ 틱톡 발행 완료: {result}")
    return publish_id


def load_manifest(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("items", [])


def record(entries):
    os.makedirs(OUT_DIR, exist_ok=True)
    history = []
    if os.path.exists(PUBLISHED_TT):
        with open(PUBLISHED_TT, encoding="utf-8") as f:
            history = json.load(f).get("items", [])
    history.extend(entries)
    with open(PUBLISHED_TT, "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "items": history,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n발행 기록: {PUBLISHED_TT}")


def main():
    ap = argparse.ArgumentParser(description="TikTok 숏폼 발행")
    ap.add_argument("--manifest", help="업로드 매니페스트 (upload.py 출력)")
    ap.add_argument("--video", help="영상 공개 URL (단건 발행)")
    ap.add_argument("--video-path", help="로컬 영상 파일 (FILE_UPLOAD용)")
    ap.add_argument("--title", help="제목/캡션")
    ap.add_argument("--script", help="대본 JSON — 제목을 여기서 만든다")
    ap.add_argument("--check", action="store_true", help="설정만 점검")
    ap.add_argument("--dry-run", action="store_true", help="발행 직전까지만")
    ap.add_argument("--limit", type=int, default=1, help="한 번에 발행할 최대 편수")
    args = ap.parse_args()

    if args.check:
        return 0 if check() else 1

    if not TOKEN or not OPEN_ID:
        if not args.dry_run:
            print("[중단] TIKTOK_ACCESS_TOKEN / TIKTOK_OPEN_ID 미설정"
                  " — --check로 안내를 보세요")
            return 1
        print("[알림] 틱톡 인증 미설정 — 드라이런이라 계속 진행합니다")

    # 발행 대상 수집
    jobs = []
    if args.video or args.video_path:
        jobs.append({
            "video_url": args.video,
            "video_path": args.video_path,
            "title": args.title,
            "name": "manual",
        })
    elif args.manifest or os.path.exists(MANIFEST):
        path = args.manifest or MANIFEST
        for item in load_manifest(path):
            if item.get("verify_failed"):
                print(f"[건너뜀] {item.get('name')}: 공개 접근 확인 실패")
                continue
            jobs.append({
                "video_url": item.get("video_url"),
                "video_path": item.get("local_path"),
                "title": args.title,
                "name": item.get("name", "?"),
            })
    else:
        print("[알림] 발행할 대상이 없습니다 (--video 또는 --manifest)")
        return 1

    # 대본에서 제목 생성
    if args.script and os.path.exists(args.script):
        with open(args.script, encoding="utf-8") as f:
            sc = json.load(f)
        title = build_title(sc)
        category = (sc.get("meta") or {}).get("category", "")
        for j in jobs:
            if not j.get("title"):
                j["title"] = title
            j["category"] = category

    jobs = jobs[:args.limit]
    print(f"발행 대상: {len(jobs)}건\n")

    results, failed = [], 0
    for i, job in enumerate(jobs):
        print(f"── {i+1}/{len(jobs)}  {job['name']}")
        try:
            publish_id = publish_one(
                job.get("video_url"),
                job.get("title", ""),
                dry_run=args.dry_run,
                video_path=job.get("video_path"),
            )
            if publish_id:
                results.append({
                    "name": job["name"],
                    "publish_id": publish_id,
                    "published_at": datetime.now(timezone.utc).isoformat(),
                    "video_url": job.get("video_url", ""),
                    "platform": "tiktok",
                    "category": job.get("category", ""),
                })
        except Exception as e:
            print(f"  [실패] {e}")
            failed += 1
        print()

        # 분당 6회 제한 — 연속 발행 시 안전 간격
        if i < len(jobs) - 1:
            time.sleep(12)

    if results:
        record(results)

    print(f"완료: 발행 {len(results)}건 / 실패 {failed}건")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
