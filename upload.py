# -*- coding: utf-8 -*-
"""
upload.py — 오브젝트 스토리지 업로더

렌더된 mp4와 커버 jpg를 공개 URL로 올린다.
인스타그램 Graph API가 video_url·cover_url에서 파일을 가져가므로
**공개 접근 가능한 URL이 필수**다. 서명 URL은 쓰지 않는다
(인스타 측 처리 지연으로 만료되는 사고가 난다).

백엔드: S3 호환 API 하나로 R2·S3·B2를 모두 커버한다.
  Cloudflare R2  — 권장. 이그레스 무료, 10GB 무료
  AWS S3         — endpoint 비우면 자동
  Backblaze B2   — S3 호환 엔드포인트 사용

환경변수:
  S3_ENDPOINT      https://<account>.r2.cloudflarestorage.com  (S3면 비움)
  S3_BUCKET        버킷 이름
  S3_ACCESS_KEY    액세스 키
  S3_SECRET_KEY    시크릿 키
  S3_PUBLIC_BASE   공개 URL 베이스 (예: https://pub-xxxx.r2.dev)
  S3_REGION        리전 (R2는 auto)

사용:
  python upload.py out/reel.mp4                      # 파일 1개
  python upload.py out/reel.mp4 --cover out/cover.jpg
  python upload.py --batch out/rendered              # 폴더 전체
  python upload.py --check                           # 설정 점검
"""
import argparse
import glob
import json
import mimetypes
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "out")
MANIFEST = os.path.join(OUT_DIR, "uploaded.json")


def load_env():
    """같은 폴더의 .env에서 키를 읽는다. PC 실행용."""
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

ENDPOINT = os.environ.get("S3_ENDPOINT", "").rstrip("/")
BUCKET = os.environ.get("S3_BUCKET", "")
ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "")
SECRET_KEY = os.environ.get("S3_SECRET_KEY", "")
PUBLIC_BASE = os.environ.get("S3_PUBLIC_BASE", "").rstrip("/")
REGION = os.environ.get("S3_REGION", "auto")


def check_config():
    """설정 점검. 빠진 항목을 알려준다."""
    required = {
        "S3_BUCKET": BUCKET,
        "S3_ACCESS_KEY": ACCESS_KEY,
        "S3_SECRET_KEY": SECRET_KEY,
        "S3_PUBLIC_BASE": PUBLIC_BASE,
    }
    missing = [k for k, v in required.items() if not v]

    print("스토리지 설정:")
    print(f"  엔드포인트  {ENDPOINT or '(AWS S3 기본)'}")
    print(f"  버킷        {BUCKET or '(미설정)'}")
    print(f"  공개 베이스 {PUBLIC_BASE or '(미설정)'}")
    print(f"  리전        {REGION}")
    print(f"  액세스 키   {'설정됨' if ACCESS_KEY else '(미설정)'}")
    print(f"  시크릿 키   {'설정됨' if SECRET_KEY else '(미설정)'}")

    if missing:
        print(f"\n[미설정] {', '.join(missing)}")
        print("\nCloudflare R2 설정 순서:")
        print("  1. dash.cloudflare.com → R2 → 버킷 생성")
        print("  2. 버킷 Settings → Public Access → r2.dev 도메인 활성화")
        print("  3. R2 → Manage API Tokens → 토큰 생성 (Object Read & Write)")
        print("  4. 발급된 값을 GitHub Secrets에 등록")
        return False

    print("\n설정 완료")
    return True


def client():
    """S3 호환 클라이언트. boto3가 R2·S3·B2를 모두 처리한다."""
    import boto3
    from botocore.config import Config

    kwargs = {
        "aws_access_key_id": ACCESS_KEY,
        "aws_secret_access_key": SECRET_KEY,
        "region_name": REGION,
        # R2는 체크섬 헤더를 거부한다. 레거시 방식으로 고정.
        "config": Config(
            signature_version="s3v4",
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    }
    if ENDPOINT:
        kwargs["endpoint_url"] = ENDPOINT
    return boto3.client("s3", **kwargs)


def object_key(path, prefix=None):
    """업로드 경로. 날짜 폴더로 나눠 덮어쓰기를 막는다."""
    name = os.path.basename(path)
    day = datetime.now().strftime("%Y/%m/%d")
    return f"{prefix or 'reels'}/{day}/{name}"


def public_url(key):
    return f"{PUBLIC_BASE}/{key}"


def upload_one(s3, path, prefix=None):
    """파일 하나를 올리고 공개 URL을 돌려준다."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    key = object_key(path, prefix)
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    size = os.path.getsize(path)

    with open(path, "rb") as f:
        s3.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=f,
            ContentType=ctype,
            # 인스타가 가져갈 때까지는 캐시를 길게 둘 이유가 없다
            CacheControl="public, max-age=86400",
        )

    url = public_url(key)
    print(f"  {os.path.basename(path)}  {size/1024/1024:.1f}MB  →  {url}")
    return url


def verify(url):
    """올린 URL이 실제로 공개 접근되는지 확인한다.

    인스타는 이 주소에서 파일을 가져간다. 여기서 403이 나면
    발행 단계에서 원인을 찾기 어려운 실패가 난다. 미리 잡는다.
    """
    import requests

    try:
        r = requests.head(url, timeout=15, allow_redirects=True)
        if r.status_code == 200:
            return True, f"{r.status_code} {r.headers.get('content-type','')}"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def save_manifest(entries):
    """업로드 결과를 기록한다. 발행 단계가 이 파일을 읽는다."""
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump({
            "uploaded_at": datetime.now().astimezone().isoformat(),
            "items": entries,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n매니페스트: {MANIFEST}")


def main():
    ap = argparse.ArgumentParser(description="오브젝트 스토리지 업로더")
    ap.add_argument("files", nargs="*", help="올릴 파일")
    ap.add_argument("--cover", help="커버 이미지 (단일 업로드 시)")
    ap.add_argument("--batch", help="폴더 전체 업로드 (mp4 + 같은 이름 jpg)")
    ap.add_argument("--prefix", default="reels", help="오브젝트 키 프리픽스")
    ap.add_argument("--check", action="store_true", help="설정만 점검")
    ap.add_argument("--no-verify", action="store_true", help="공개 접근 확인 건너뜀")
    args = ap.parse_args()

    if args.check:
        return 0 if check_config() else 1

    if not check_config():
        print("\n[중단] 스토리지 설정이 끝나야 업로드할 수 있습니다")
        return 1

    # 올릴 대상 수집
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

    s3 = client()
    print(f"\n업로드 {len(targets)}건:")

    entries, failed = [], 0
    for video, cover in targets:
        try:
            entry = {"name": os.path.splitext(os.path.basename(video))[0]}
            entry["video_url"] = upload_one(s3, video, args.prefix)
            if cover:
                entry["cover_url"] = upload_one(s3, cover, args.prefix)
            entries.append(entry)
        except Exception as e:
            print(f"  [실패] {os.path.basename(video)}: {type(e).__name__}: {e}")
            failed += 1

    # 공개 접근 확인
    if entries and not args.no_verify:
        print("\n공개 접근 확인:")
        for e in entries:
            for field in ("video_url", "cover_url"):
                if field not in e:
                    continue
                ok, why = verify(e[field])
                mark = "OK " if ok else "-- "
                print(f"  {mark} {field}: {why}")
                if not ok:
                    e["verify_failed"] = True

    if entries:
        save_manifest(entries)

    print(f"\n완료: 성공 {len(entries)}건 / 실패 {failed}건")
    blocked = [e for e in entries if e.get("verify_failed")]
    if blocked:
        print(f"[경고] 공개 접근 실패 {len(blocked)}건 — 버킷 Public Access 설정을 확인하세요")
        print("       이 상태로 발행하면 인스타가 파일을 가져가지 못합니다")
        return 1
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
