# -*- coding: utf-8 -*-
"""
news_collect.py — 이슈 뉴스 수집기

네이버 뉴스 RSS + 주요 언론사 RSS로 실시간 이슈를 수집한다.
수집 결과는 out/news.json으로 저장.

사용:
  python news_collect.py                    # 기본 카테고리 수집
  python news_collect.py --category 경제    # 특정 카테고리
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from html import unescape
import xml.etree.ElementTree as ET

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "out")
SEEN_FILE = os.path.join(OUT_DIR, "news_seen.json")

# ── 네이버 뉴스 RSS (공개, 키 불필요) ─────────────────────
# sid1: 100=정치, 101=경제, 102=사회, 103=생활/문화, 104=세계, 105=IT/과학
NAVER_RSS = {
    "경제": "https://news.google.com/rss/search?q=한국+경제&hl=ko&gl=KR&ceid=KR:ko",
    "사회": "https://news.google.com/rss/search?q=한국+사회+이슈&hl=ko&gl=KR&ceid=KR:ko",
    "생활": "https://news.google.com/rss/search?q=생활+정보+꿀팁&hl=ko&gl=KR&ceid=KR:ko",
    "부동산": "https://news.google.com/rss/search?q=부동산+아파트+전세&hl=ko&gl=KR&ceid=KR:ko",
    "재테크": "https://news.google.com/rss/search?q=재테크+투자+저축&hl=ko&gl=KR&ceid=KR:ko",
}

# 언론사 표현 필터 (저작권 보호)
PRESS_RE = re.compile(
    r"무단\s*전재|재배포\s*금지|저작권자|[가-힣]{2,4}\s*기자"
    r"|\b(YTN|KBS|MBC|SBS|JTBC)\b"
)

# HTML 태그 제거
TAG_RE = re.compile(r"<[^>]+>")


def clean_text(text):
    """HTML 태그 제거, 엔티티 디코딩, 공백 정리."""
    text = TAG_RE.sub("", unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def article_key(title, link):
    """중복 판정용 해시."""
    base = f"{title}|{link}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=1)


def fetch_rss(url, category, timeout=15):
    """RSS 피드를 파싱해 기사 리스트를 반환."""
    articles = []
    try:
        r = requests.get(url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (issue-reels-bot/1.0)"
        })
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"  [경고] RSS 실패 ({category}): {e}")
        return articles

    for item in root.findall(".//item"):
        title = clean_text(item.findtext("title", ""))
        link = (item.findtext("link", "") or "").strip()
        desc = clean_text(item.findtext("description", ""))
        pub_date = (item.findtext("pubDate", "") or "").strip()

        if not title or len(title) < 10:
            continue
        # 언론사 표현 필터
        if PRESS_RE.search(desc):
            desc = ""  # 본문에서 언론사 표현만 제거, 제목은 유지

        articles.append({
            "title": title,
            "link": link,
            "description": desc[:300],  # 300자로 제한
            "pub_date": pub_date,
            "category": category,
        })

    return articles


def fetch_news_via_search(query, category, timeout=15):
    """Google News RSS 검색으로 뉴스 수집."""
    url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=ko&gl=KR&ceid=KR:ko"
    return fetch_rss(url, category, timeout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", default=None, help="특정 카테고리만 수집")
    ap.add_argument("--max", type=int, default=20, help="카테고리당 최대 기사 수")
    args = ap.parse_args()

    categories = {args.category: NAVER_RSS[args.category]} if args.category and args.category in NAVER_RSS else NAVER_RSS

    seen = load_seen()
    all_articles = []
    dropped = 0

    for cat, url in categories.items():
        print(f"  [{cat}] 수집 중...")
        articles = fetch_rss(url, cat)
        count = 0
        for art in articles:
            if count >= args.max:
                break
            k = article_key(art["title"], art["link"])
            if k in seen:
                continue
            # 제목에 언론사 표현이 있으면 폐기
            if PRESS_RE.search(art["title"]):
                dropped += 1
                continue
            seen.add(k)
            art["key"] = k
            all_articles.append(art)
            count += 1
        print(f"    → {count}건 수집")

    # 저장
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "news.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "items": all_articles,
        }, f, ensure_ascii=False, indent=2)
    save_seen(seen)

    print(f"\n수집 완료: {len(all_articles)}건 · 폐기 {dropped}건 → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
