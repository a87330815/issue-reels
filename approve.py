# -*- coding: utf-8 -*-
"""
approve.py — 대본 승인 처리

승인된 대본을 out/approved/로 이동하고,
미승인 시 에버그린 뱅크에서 대체 대본을 가져온다.

사용:
  python approve.py approved.json          # 승인 결과 파일 처리
  python approve.py --auto                 # 전체 자동 승인 (테스트용)
  python approve.py --fallback             # 에버그린 뱅크에서 1편 선택

에버그린 뱅크:
  evergreen/ 폴더에 시즌·시기 무관하게 쓸 수 있는 대본을 보관.
  당일 대본이 전부 거절되면 여기서 자동 대체.
"""
import argparse
import glob
import json
import os
import random
import shutil
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPT_DIR = os.path.join(ROOT, "out", "scripts")
APPROVED_DIR = os.path.join(ROOT, "out", "approved")
EVERGREEN_DIR = os.path.join(ROOT, "evergreen")


def approve_from_file(path):
    """승인 결과 JSON(approve.html에서 다운로드한 것)을 처리한다."""
    with open(path, encoding="utf-8") as f:
        approved = json.load(f)

    if not isinstance(approved, list):
        approved = [approved]

    os.makedirs(APPROVED_DIR, exist_ok=True)
    count = 0
    for sc in approved:
        fname = sc.get("_filename", f"approved_{count:02d}.json")
        # _filename 제거
        sc.pop("_filename", None)
        out = os.path.join(APPROVED_DIR, fname)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(sc, f, ensure_ascii=False, indent=2)
        print(f"  승인: {fname}")
        count += 1

    print(f"\n총 {count}편 승인 → {APPROVED_DIR}")
    return count


def auto_approve():
    """out/scripts/의 모든 대본을 자동 승인한다."""
    jsons = sorted(glob.glob(os.path.join(SCRIPT_DIR, "*.json")))
    if not jsons:
        print("[알림] 승인할 대본 없음")
        return 0

    os.makedirs(APPROVED_DIR, exist_ok=True)
    count = 0
    for src in jsons:
        fname = os.path.basename(src)
        dst = os.path.join(APPROVED_DIR, fname)
        shutil.copy2(src, dst)
        print(f"  자동 승인: {fname}")
        count += 1

    print(f"\n총 {count}편 자동 승인")
    return count


def fallback():
    """에버그린 뱅크에서 대본 1편을 가져온다."""
    if not os.path.isdir(EVERGREEN_DIR):
        print("[알림] 에버그린 뱅크 없음 — evergreen/ 폴더를 만들고 대본을 넣어주세요")
        return 0

    jsons = sorted(glob.glob(os.path.join(EVERGREEN_DIR, "*.json")))
    if not jsons:
        print("[알림] 에버그린 뱅크가 비어 있음")
        return 0

    pick = random.choice(jsons)
    os.makedirs(APPROVED_DIR, exist_ok=True)

    today = datetime.now().strftime("%Y%m%d")
    fname = f"{today}_evergreen_{os.path.basename(pick)}"
    dst = os.path.join(APPROVED_DIR, fname)
    shutil.copy2(pick, dst)
    print(f"  에버그린 대체: {os.path.basename(pick)} → {fname}")
    return 1


def main():
    ap = argparse.ArgumentParser(description="대본 승인 처리")
    ap.add_argument("file", nargs="?", help="승인 결과 JSON")
    ap.add_argument("--auto", action="store_true", help="전체 자동 승인")
    ap.add_argument("--fallback", action="store_true", help="에버그린 뱅크에서 대체")
    args = ap.parse_args()

    if args.auto:
        count = auto_approve()
    elif args.fallback:
        count = fallback()
    elif args.file:
        count = approve_from_file(args.file)
    else:
        # 기본: 자동 승인 시도, 없으면 에버그린
        count = auto_approve()
        if count == 0:
            print("대본 없음 → 에버그린 뱅크 폴백")
            count = fallback()

    if count == 0:
        print("\n[경고] 승인된 대본 0편 — 오늘 발행 불가")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
