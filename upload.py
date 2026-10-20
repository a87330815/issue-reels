# -*- coding: utf-8 -*-
"""
upload.py — 영상 공개 호스팅

인스타그램 Graph API는 video_url·cover_url에서 **직접 파일을 가져간다**.
그래서 발행 전에 공개 접근 가능한 주소에 올려둬야 한다.

백엔드 2종 (STORAGE_BACKEND로 선택, 기본 github):

  github  — 공개 저장소의 Release에 올린다. 추가 가입·요금 없음.
            주소: https://github.com/<repo>/releases/download/<tag>/<파일>
            MEDIA_REPO     a87330815/issue-reels-media
            MEDIA_TOKEN    해당 저장소 Contents 쓰기 권한 토큰

  s3      — S3 호환 오브젝트 스토리지 (Cloudflare R2·AWS S3·B2).
            S3_ENDPOINT / S3_BUCKET / S3_ACCESS_KEY / S3_SECRET_KEY / S3_PUBLIC_BASE

사용:
  python upload.py --check
  python upload.py --batch out/rendered
  python upload.py out/reel.mp4 --cover out/cover.jpg
"""
import argparse
import glob
import json
import hashlib
import mimetypes
import os
import re
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "out")
MANIFEST = os.path.join(OUT_DIR, "uploaded.json")


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

BACKEND = os.environ.get("STORAGE_BACKEND", "github").lower()

# github 백엔드
MEDIA_REPO = os.environ.get("MEDIA_REPO", "a87330815/issue-reels-media")
MEDIA_TOKEN = os.environ.get("MEDIA_TOKEN", "")

# s3 백엔드
ENDPOINT = os.environ.get("S3_ENDPOINT", "").rstrip("/")
BUCKET = os.environ.get("S3_BUCKET", "")
ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "")
SECRET_KEY = os.environ.get("S3_SECRET_KEY", "")
PUBLIC_BASE = os.environ.get("S3_PUBLIC_BASE", "").rstrip("/")
REGION = os.environ.get("S3_REGION", "auto")


def scrub(text):
    """에러 메시지에 토큰이 실려 나가는 것을 막는다."""
    for secret in (MEDIA_TOKEN, SECRET_KEY, ACCESS_KEY):
        if secret:
            text = text.replace(secret, "***")
    return text


# ═══════════════════════════════════════════════════════════
#  github 백엔드 — 공개 저장소 Release
# ═══════════════════════════════════════════════════════════

GH_API = "https://api.github.com"


def gh(method, url, token, **kw):
    import requests

    headers = kw.pop("headers", {})
    headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    r = requests.request(method, url, headers=headers, timeout=120, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {scrub(r.text[:300])}")
    return r.json() if r.text else {}


README = """# issue-reels-media

릴스 영상 호스팅용 공개 저장소입니다.

인스타그램 Graph API는 `video_url`에 적힌 주소에서 **직접 파일을 가져갑니다**.
비공개 저장소의 릴리스 파일은 인증 없이 받을 수 없어 인스타가 가져가지 못하므로,
이 저장소만 공개로 둡니다. 파이프라인 코드는 비공개 저장소에 있습니다.

영상은 날짜별 Release(`reels-YYYY-MM-DD`)의 자산으로 올라갑니다.
사람이 직접 커밋할 일은 없습니다.
"""


def gh_ensure_initialized():
    """빈 저장소에는 릴리스를 만들 수 없다 (422 Repository is empty).

    릴리스는 커밋을 가리키는 태그가 있어야 만들어지는데, README 없이 만든
    저장소에는 커밋이 하나도 없다. 첫 커밋이 없으면 README를 넣어 만들어준다.
    """
    import base64

    import requests

    headers = {
        "Authorization": f"Bearer {MEDIA_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    r = requests.get(f"{GH_API}/repos/{MEDIA_REPO}/commits",
                     headers=headers, params={"per_page": 1}, timeout=30)
    if r.status_code == 200 and r.json():
        return False

    print("  저장소가 비어 있어 README로 초기화합니다")
    gh("PUT", f"{GH_API}/repos/{MEDIA_REPO}/contents/README.md", MEDIA_TOKEN, json={
        "message": "저장소 초기화 — 릴리스 생성에는 커밋이 최소 1개 필요",
        "content": base64.b64encode(README.encode("utf-8")).decode("ascii"),
    })
    return True


def safe_asset_name(name):
    """릴리스 자산 이름을 ASCII로 정리한다.

    GitHub은 자산 이름의 비ASCII 문자를 임의로 바꾼다. 그래서 한글 파일명을
    그대로 올리면 실제 자산 이름이 달라지고, 조립한 주소가 404가 난다.
    인스타가 가져갈 주소이기도 하니 애초에 ASCII로 맞춘다.
    """
    stem, ext = os.path.splitext(name)
    ascii_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_")
    # 한글만으로 된 이름이면 통째로 날아가므로 해시를 붙여 구분을 남긴다
    if len(ascii_stem.replace("_", "")) < 4:
        digest = hashlib.sha1(stem.encode("utf-8")).hexdigest()[:8]
        ascii_stem = f"{ascii_stem}_{digest}" if ascii_stem else digest
    return ascii_stem + ext.lower()


def gh_release(tag):
    """태그에 해당하는 릴리스를 찾고, 없으면 만든다."""
    import requests

    url = f"{GH_API}/repos/{MEDIA_REPO}/releases/tags/{tag}"
    headers = {
        "Authorization": f"Bearer {MEDIA_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    r = requests.get(url, headers=headers, timeout=30)
    if r.status_code == 200:
        return r.json()

    gh_ensure_initialized()
    return gh("POST", f"{GH_API}/repos/{MEDIA_REPO}/releases", MEDIA_TOKEN, json={
        "tag_name": tag,
        "name": tag,
        "body": "릴스 영상 호스팅. 인스타그램이 이 주소에서 파일을 가져갑니다.",
    })


def gh_upload(path, tag):
    """파일을 릴리스 자산으로 올리고 공개 URL을 돌려준다."""
    rel = gh_release(tag)
    name = safe_asset_name(os.path.basename(path))

    # 같은 이름이 이미 있으면 지우고 다시 올린다 (재실행 대비)
    for asset in rel.get("assets", []):
        if asset["name"] == name:
            gh("DELETE", f"{GH_API}/repos/{MEDIA_REPO}/releases/assets/{asset['id']}",
               MEDIA_TOKEN)
            break

    upload_url = rel["upload_url"].split("{")[0]
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as f:
        res = gh("POST", f"{upload_url}?name={name}", MEDIA_TOKEN,
                 headers={"Content-Type": ctype}, data=f)

    # 주소를 조립하지 말고 API가 돌려준 것을 쓴다.
    # GitHub이 자산 이름을 바꿔도 이 주소는 항상 맞다.
    url = res.get("browser_download_url")
    if url:
        return url
    return f"https://github.com/{MEDIA_REPO}/releases/download/{tag}/{res.get('name', name)}"


def gh_check():
    print("저장소 백엔드: GitHub Release")
    print(f"  미디어 저장소  {MEDIA_REPO}")
    print(f"  토큰           {'설정됨' if MEDIA_TOKEN else '(미설정)'}")

    if not MEDIA_TOKEN:
        print("\n[미설정] MEDIA_TOKEN")
        print("\n발급 순서:")
        print("  1. github.com/settings/personal-access-tokens/new")
        print(f"  2. Repository access → Only select repositories → {MEDIA_REPO}")
        print("  3. Permissions → Contents: Read and write")
        print("  4. 발급된 토큰을 issue-reels 저장소 Secrets에 MEDIA_TOKEN으로 등록")
        return False

    try:
        info = gh("GET", f"{GH_API}/repos/{MEDIA_REPO}", MEDIA_TOKEN)
        vis = "공개" if not info.get("private") else "비공개"
        print(f"  저장소 확인    {info['full_name']} ({vis})")
        if info.get("private"):
            print("\n[경고] 저장소가 비공개입니다. 비공개 저장소의 릴리스 파일은")
            print("       인증 없이 접근할 수 없어 인스타가 영상을 가져가지 못합니다.")
            return False
    except Exception as e:
        print(f"\n[실패] 저장소 접근: {e}")
        return False

    print("\n설정 완료")
    return True


# ═══════════════════════════════════════════════════════════
#  s3 백엔드
# ═══════════════════════════════════════════════════════════

def s3_client():
    import boto3
    from botocore.config import Config

    kwargs = {
        "aws_access_key_id": ACCESS_KEY,
        "aws_secret_access_key": SECRET_KEY,
        "region_name": REGION,
        # R2는 체크섬 헤더를 거부한다
        "config": Config(
            signature_version="s3v4",
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    }
    if ENDPOINT:
        kwargs["endpoint_url"] = ENDPOINT
    return boto3.client("s3", **kwargs)


def s3_upload(path, tag, client=None):
    client = client or s3_client()
    key = f"reels/{tag}/{os.path.basename(path)}"
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as f:
        client.put_object(Bucket=BUCKET, Key=key, Body=f, ContentType=ctype,
                          CacheControl="public, max-age=86400")
    return f"{PUBLIC_BASE}/{key}"


def s3_check():
    print("저장소 백엔드: S3 호환")
    print(f"  엔드포인트   {ENDPOINT or '(AWS S3 기본)'}")
    print(f"  버킷         {BUCKET or '(미설정)'}")
    print(f"  공개 베이스  {PUBLIC_BASE or '(미설정)'}")
    missing = [k for k, v in {
        "S3_BUCKET": BUCKET, "S3_ACCESS_KEY": ACCESS_KEY,
        "S3_SECRET_KEY": SECRET_KEY, "S3_PUBLIC_BASE": PUBLIC_BASE,
    }.items() if not v]
    if missing:
        print(f"\n[미설정] {', '.join(missing)}")
        return False
    print("\n설정 완료")
    return True


# ═══════════════════════════════════════════════════════════
#  공통
# ═══════════════════════════════════════════════════════════

def verify(url):
    """인스타가 가져갈 주소가 실제로 공개 접근되는지 확인한다.

    여기서 막히면 발행 단계에서 원인 찾기 어려운 실패가 난다. 미리 잡는다.
    """
    import requests

    try:
        r = requests.get(url, timeout=20, stream=True, allow_redirects=True)
        r.close()
        if r.status_code == 200:
            return True, f"200 {r.headers.get('content-type','')}"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, f"{type(e).__name__}: {scrub(str(e))}"


def save_manifest(entries):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump({
            "uploaded_at": datetime.now().astimezone().isoformat(),
            "backend": BACKEND,
            "items": entries,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n매니페스트: {MANIFEST}")


def main():
    ap = argparse.ArgumentParser(description="영상 공개 호스팅 업로더")
    ap.add_argument("files", nargs="*", help="올릴 파일")
    ap.add_argument("--cover", help="커버 이미지 (단건)")
    ap.add_argument("--batch", help="폴더 전체 (mp4 + 같은 이름 jpg)")
    ap.add_argument("--tag", help="릴리스 태그 / 경로 (기본: reels-YYYY-MM-DD)")
    ap.add_argument("--check", action="store_true", help="설정만 점검")
    ap.add_argument("--no-verify", action="store_true", help="공개 접근 확인 건너뜀")
    args = ap.parse_args()

    checker = gh_check if BACKEND == "github" else s3_check
    if args.check:
        return 0 if checker() else 1
    if not checker():
        print("\n[중단] 저장소 설정이 끝나야 업로드할 수 있습니다")
        return 1

    tag = args.tag or f"reels-{datetime.now().strftime('%Y-%m-%d')}"

    targets = []
    if args.batch:
        for mp4 in sorted(glob.glob(os.path.join(args.batch, "*.mp4"))):
            jpg = os.path.splitext(mp4)[0] + ".jpg"
            targets.append((mp4, jpg if os.path.exists(jpg) else None))
    else:
        for f in args.files:
            targets.append((f, args.cover))

    if not targets:
        print("[알림] 올릴 파일이 없습니다")
        return 1

    put = gh_upload if BACKEND == "github" else s3_upload
    print(f"\n업로드 {len(targets)}건 (태그 {tag}):")

    entries, failed = [], 0
    for video, cover in targets:
        try:
            e = {"name": os.path.splitext(os.path.basename(video))[0]}
            e["video_url"] = put(video, tag)
            print(f"  {os.path.basename(video)}  "
                  f"{os.path.getsize(video)/1024/1024:.1f}MB  →  {e['video_url']}")
            if cover:
                e["cover_url"] = put(cover, tag)
                print(f"  {os.path.basename(cover)}  →  {e['cover_url']}")
            entries.append(e)
        except Exception as ex:
            print(f"  [실패] {os.path.basename(video)}: {scrub(str(ex))}")
            failed += 1

    if entries and not args.no_verify:
        print("\n공개 접근 확인:")
        for e in entries:
            for field in ("video_url", "cover_url"):
                if field not in e:
                    continue
                ok, why = verify(e[field])
                print(f"  {'OK ' if ok else '-- '} {field}: {why}")
                if not ok:
                    e["verify_failed"] = True

    if entries:
        save_manifest(entries)

    print(f"\n완료: 성공 {len(entries)}건 / 실패 {failed}건")
    blocked = [e for e in entries if e.get("verify_failed")]
    if blocked:
        print(f"[경고] 공개 접근 실패 {len(blocked)}건 — 이 상태로 발행하면")
        print("       인스타가 영상을 가져가지 못합니다")
        return 1
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
