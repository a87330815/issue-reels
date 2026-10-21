# -*- coding: utf-8 -*-
"""
photos.py — 카드뉴스 배경 사진 수집기

무료·무인증 소스를 우선으로 상업적 이용 가능한 사진을 받아온다.
우선순위:
  1) Unsplash      — UNSPLASH_ACCESS_KEY 가 있을 때만 (품질·적합도 최상)
  2) Openverse     — 키 불필요. CC0/PDM(퍼블릭도메인)만 필터 → 출처표기 의무 없음
  3) Wikimedia     — 키 불필요. 최후 폴백

GitHub Actions 러너에서 실행하는 것을 전제로 한다.
(로컬 컨테이너는 프록시가 외부 이미지 사이트를 차단함)
"""
import io
import json
import os
import re
import sys
import time
import urllib.parse

import requests
from PIL import Image

UA = "issue-reels-cardnews/1.0 (https://github.com/a87330815/issue-reels)"
TIMEOUT = 20
CARD_W, CARD_H = 1080, 1350

# ── 한국어 → 영문 검색어 매핑 ─────────────────
# 소제목/제목에 아래 키가 포함되면 해당 영문 쿼리를 사용한다. 긴 키부터 매칭.
KEYWORD_MAP = {
    # 교통
    "KTX": "ktx high speed train station",
    "SRT": "high speed train platform",
    "코레일": "korea train station platform",
    "열차": "train railway station",
    "기차": "train railway",
    "고속버스": "intercity bus terminal",
    "좌석": "train seats interior",
    "예매": "booking ticket smartphone",
    "승차권": "train ticket",
    "앱": "smartphone app mobile",
    "명절": "travel luggage station crowd",
    # 생활 / 암표
    "암표": "concert crowd stage",
    "콘서트": "concert crowd lights",
    "공연": "concert stage performance",
    "티켓": "event ticket",
    "스포츠": "stadium sports crowd",
    "야구": "baseball stadium",
    "신고": "smartphone report call",
    "포상금": "cash reward money",
    "과징금": "money fine penalty",
    "플랫폼": "laptop online marketplace",
    # 돈 / 물가
    "노란우산": "small business owner shop",
    "공제": "tax documents calculator",
    "소득공제": "tax form calculator",
    "종합소득세": "tax paperwork desk",
    "자영업": "small business owner store",
    "소상공인": "small shop owner counter",
    "퇴직금": "retirement savings money",
    "적립": "savings coins jar",
    "납입": "money savings bank",
    "은행": "bank building finance",
    "절세": "calculator money tax",
    "가입": "signing contract document",
    "이자": "finance chart money",
    # 주거
    "전세": "apartment building keys",
    "월세": "apartment rent keys",
    "청약": "apartment building city",
    "주택": "house residential",
    "아파트": "apartment building",
    "대출": "loan contract signing",
    # 안전
    "화재": "fire safety extinguisher",
    "안전": "safety helmet warning",
    "재난": "emergency alert phone",
    "보험": "insurance documents desk",
}

# 카테고리 기본 쿼리 (키워드 매칭 실패 시)
CATEGORY_MAP = {
    "교통": "train station platform korea",
    "생활": "city street people daily life",
    "돈·물가": "money finance calculator desk",
    "돈": "money finance calculator",
    "주거": "apartment building residential",
    "안전": "safety emergency warning",
}
DEFAULT_QUERY = "city office desk modern"


def build_query(text, category=""):
    """소제목/제목에서 영문 검색어를 뽑는다."""
    t = text or ""
    # 긴 키워드 우선 매칭 (부분 문자열 충돌 방지)
    for k in sorted(KEYWORD_MAP, key=len, reverse=True):
        if k in t:
            return KEYWORD_MAP[k]
    return CATEGORY_MAP.get(category, DEFAULT_QUERY)


# ── 공급자별 검색 ────────────────────────────
def search_unsplash(query, key, n=8):
    """Unsplash — 상업적 이용 자유, 출처표기 의무 없음."""
    url = "https://api.unsplash.com/search/photos"
    params = {"query": query, "per_page": n, "orientation": "portrait",
              "content_filter": "high"}
    r = requests.get(url, params=params, timeout=TIMEOUT,
                     headers={"Authorization": f"Client-ID {key}", "User-Agent": UA})
    r.raise_for_status()
    out = []
    for it in r.json().get("results", []):
        u = (it.get("urls") or {}).get("regular")
        if not u:
            continue
        out.append({
            "url": u,
            "title": (it.get("description") or it.get("alt_description") or ""),
            "source": "Unsplash",
            "creator": ((it.get("user") or {}).get("name") or ""),
            "license": "Unsplash License",
            "page": ((it.get("links") or {}).get("html") or ""),
        })
    return out


def search_openverse(query, n=12):
    """Openverse — 키 불필요.
    cc0/pdm(표기 불필요) + by(표기만 하면 상업적 이용 자유)까지 받아 후보 풀을 넓힌다.
    share-alike·비상업·변경금지는 제외. 비율 제한은 두지 않는다 (cover 크롭으로 흡수)."""
    url = "https://api.openverse.org/v1/images/"
    hdr = {"User-Agent": UA, "Accept": "application/json"}
    r = requests.get(url, timeout=TIMEOUT, headers=hdr,
                     params={"q": query, "license": "cc0,pdm,by",
                             "page_size": n, "mature": "false"})
    if r.status_code == 400:
        # license 조합을 거부하는 경우 표기 불필요 라이선스로만 재시도
        r = requests.get(url, timeout=TIMEOUT, headers=hdr,
                         params={"q": query, "license": "cc0,pdm",
                                 "page_size": n, "mature": "false"})
    r.raise_for_status()
    out = []
    for it in r.json().get("results", []):
        u = it.get("url")
        if not u:
            continue
        out.append({
            "url": u,
            "title": it.get("title") or "",
            "source": it.get("source") or "Openverse",
            "creator": it.get("creator") or "",
            "license": (it.get("license") or "").upper(),
            "page": it.get("foreign_landing_url") or "",
        })
    return out


# 상업적 이용이 가능하고 share-alike 전염성이 없는 라이선스만 허용
_OK_LICENSE = re.compile(
    r"^(public[ -]domain|pd|pdm|cc0|cc[ -]pd|no[ -]restrictions|"
    r"cc[ -]by([ -]\d|$)|attribution([ -]\d|$))", re.I)

def _license_ok(name):
    n = (name or "").strip()
    if not n:
        return False
    # share-alike(전염성), 비상업, 변경금지는 제외
    if re.search(r"([ -]sa\b|share.?alike|[ -]nc\b|noncommercial|non-commercial|"
                 r"[ -]nd\b|noderiv)", n, re.I):
        return False
    return bool(_OK_LICENSE.match(n))


def search_wikimedia(query, n=12):
    """Wikimedia Commons — 키 불필요. 최후 폴백.
    share-alike/비상업/변경금지 라이선스는 제외한다."""
    url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query", "generator": "search", "gsrsearch": f"{query} filetype:bitmap",
        "gsrnamespace": "6", "gsrlimit": str(n), "prop": "imageinfo",
        "iiprop": "url|extmetadata", "iiurlwidth": "1400", "format": "json",
    }
    r = requests.get(url, params=params, timeout=TIMEOUT, headers={"User-Agent": UA})
    r.raise_for_status()
    pages = ((r.json().get("query") or {}).get("pages") or {})
    out = []
    for p in pages.values():
        ii = (p.get("imageinfo") or [{}])[0]
        u = ii.get("thumburl") or ii.get("url")
        if not u:
            continue
        meta = ii.get("extmetadata") or {}
        lic = (meta.get("LicenseShortName") or {}).get("value", "")
        if not _license_ok(lic):
            continue
        out.append({
            "url": u,
            "title": p.get("title") or "",
            "source": "Wikimedia Commons",
            "creator": re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", ""))[:60],
            "license": lic,
            "page": ii.get("descriptionurl") or "",
        })
    return out


# 한국 소비자 대상 카드뉴스에 실리면 곤란한 소재를 제목·출처 URL에서 걸러낸다.
# (예: "korean won" 검색에 북한 원화 지폐가 걸려 김일성 초상이 배경으로 깔린 사례)
_BLOCK_RE = re.compile(
    r"(north[ _-]?korea|dprk|democratic[ _-]people|pyongyang|kim[ _-]il[ _-]sung|"
    r"kim[ _-]jong|juche|nazi|swastika|hitler|isis|taliban|"
    r"corpse|autopsy|funeral|grave|cemetery|protest|riot|war|weapon|gun|rifle)",
    re.I)

def _content_ok(cand):
    hay = " ".join(str(cand.get(k, "")) for k in ("title", "page", "url", "creator"))
    return not _BLOCK_RE.search(hay)


def search_all(query, n=12):
    """공급자를 순서대로 시도해 후보 목록을 만든다.
    앞 공급자 결과가 적으면 뒤 공급자 결과를 이어 붙여 중복 회피 여지를 남긴다."""
    key = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()
    providers = []
    if key:
        providers.append(("unsplash", lambda: search_unsplash(query, key, n)))
    providers.append(("openverse", lambda: search_openverse(query, n)))
    providers.append(("wikimedia", lambda: search_wikimedia(query, n)))

    merged = []
    for name, fn in providers:
        try:
            res = fn()
            kept = [c for c in res if _content_ok(c)]
            dropped = len(res) - len(kept)
            print(f"    [{name}] {len(kept)}건 후보" + (f" (부적합 {dropped}건 제외)" if dropped else ""))
            merged.extend(kept)
        except Exception as e:
            print(f"    [{name}] 실패: {e}")
        # 충분히 모였고 선두 공급자(유료키)면 더 찾지 않는다
        if len(merged) >= n and name == "unsplash":
            break
    return merged


# ── 다운로드 & 크롭 ──────────────────────────
def cover_crop(im, w=CARD_W, h=CARD_H):
    """비율 유지하며 중앙 기준 'cover' 크롭."""
    im = im.convert("RGB")
    src_ratio = im.width / im.height
    dst_ratio = w / h
    if src_ratio > dst_ratio:
        new_h = h
        new_w = max(w, int(round(h * src_ratio)))
    else:
        new_w = w
        new_h = max(h, int(round(w / src_ratio)))
    im = im.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return im.crop((left, top, left + w, top + h))


def download_photo(candidates, out_path, min_px=600, used=None):
    """후보를 순서대로 받아 첫 성공분을 저장. 성공 시 메타 dict 반환.
    used에 이미 쓴 URL을 담아두면 슬라이드 간 사진 중복을 피한다."""
    used = used if used is not None else set()
    for c in candidates:
        if c["url"] in used:
            continue
        try:
            r = requests.get(c["url"], timeout=TIMEOUT,
                             headers={"User-Agent": UA}, stream=True)
            r.raise_for_status()
            data = r.content
            if len(data) < 8000:
                continue
            im = Image.open(io.BytesIO(data))
            if min(im.size) < min_px:
                continue
            cover_crop(im).save(out_path, "JPEG", quality=88)
            used.add(c["url"])
            meta = dict(c)
            meta["file"] = out_path
            return meta
        except Exception as e:
            print(f"    다운로드 실패 ({c.get('url','')[:60]}): {e}")
            continue
    return None


def fetch_for_script(script_path, out_dir):
    """대본 JSON을 읽어 커버 + 각 씬의 배경 사진을 받는다."""
    with open(script_path, encoding="utf-8") as f:
        sc = json.load(f)

    os.makedirs(out_dir, exist_ok=True)
    category = (sc.get("meta") or {}).get("category", "")
    manifest = {"photos": {}, "credits": []}

    # 커버: 제목 기준
    targets = [("cover", sc.get("title", ""), (sc.get("cover") or {}).get("photo_query"))]
    for i, scene in enumerate(sc.get("scenes", [])):
        targets.append((f"scene{i+1}", scene.get("subtitle", ""), scene.get("photo_query")))

    used = set()  # 같은 대본 안에서 사진 중복 방지
    for slot, text, explicit in targets:
        q = explicit or build_query(text, category)
        print(f"  [{slot}] '{text}' → \"{q}\"")
        cands = search_all(q)
        if not cands:
            print(f"    ✗ {slot}: 후보 없음")
            continue
        path = os.path.join(out_dir, f"{slot}.jpg")
        meta = download_photo(cands, path, used=used)
        if meta:
            manifest["photos"][slot] = os.path.basename(path)
            manifest["credits"].append({
                "slot": slot, "query": q, "source": meta["source"],
                "creator": meta["creator"], "license": meta["license"], "page": meta["page"],
            })
            print(f"    ✓ {slot} ← {meta['source']} ({meta['license']})")
        else:
            print(f"    ✗ {slot}: 다운로드 전부 실패")
        time.sleep(0.4)  # 공용 API 예의

    manifest["wanted"] = len(targets)
    manifest["fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    mpath = os.path.join(out_dir, "photos.json")
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"  → {len(manifest['photos'])}/{len(targets)}장 저장, 매니페스트: {mpath}")
    return manifest


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="카드뉴스 배경 사진 수집")
    ap.add_argument("scripts", nargs="+", help="대본 JSON 경로")
    ap.add_argument("-o", "--out", default="out/photos", help="저장 루트")
    a = ap.parse_args()

    total, wanted = 0, 0
    for s in a.scripts:
        stem = os.path.splitext(os.path.basename(s))[0]
        print(f"\n=== {stem} ===")
        try:
            m = fetch_for_script(s, os.path.join(a.out, stem))
            total += len(m["photos"])
            wanted += m.get("wanted", 0)
        except Exception as e:
            print(f"  ✗ {stem} 처리 실패: {e}")

    print(f"\n총 {total}/{wanted}장 수집")
    # 일부만 받아져도 카드 생성은 진행한다 (사진 없는 슬라이드는 그래디언트 폴백)
    if total == 0:
        print("경고: 한 장도 받지 못했습니다. 그래디언트 배경으로 생성됩니다.")
    sys.exit(0)
