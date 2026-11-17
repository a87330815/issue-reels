# -*- coding: utf-8 -*-
"""
collect_trends.py — 트렌드 키워드 수집기

Google Trends Korea RSS + 네이버 실시간 검색어에서 화제 키워드를 수집한다.
API 키 없이 동작한다.

수집 결과는 out/trends.json에 저장되고, scriptgen.py가 이를 읽어
LLM에 넘겨 "사실만 뽑아 완전히 새 문장으로" 대본을 생성한다.

카테고리 자동 분류:
  - 재테크 / 저축·투자 / 보험·연금 / 세금·절약 / 돈습관 / 경제상식

사용:
  python collect_trends.py              # 트렌드 수집 → out/trends.json
  python collect_trends.py --list       # 수집 결과 미리보기
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "out")

# 재테크·돈 정보 외 주제는 제외한다.
EXCLUDE_PATTERNS = [
    r"(연예|아이돌|걸그룹|보이그룹|드라마|예능|컴백|열애)",
    r"(정치|국회|대통령|여당|야당|민주당|국민의힘|탄핵|선거|의원)",
    r"(스포츠|축구|야구|농구|K리그|EPL|올림픽|월드컵|프로야구)",
    r"(부동산|아파트|분양|청약|전세|월세|주택|집값)",
]
EXCLUDE_RE = re.compile("|".join(EXCLUDE_PATTERNS))

# 카테고리 분류 키워드 — 재테크·돈 정보 니치
CATEGORY_RULES = {
    "재테크": [r"(재테크|자산|부자|투자전략|포트폴리오|자산배분|수익률)"],
    "저축·투자": [
        r"(적금|예금|저축|투자|주식|ETF|펀드|채권|배당|금리|이자|증권|코스피|코스닥)",
        r"(ISA|IRP|CMA|MMF|달러|환율|외화|해외투자)",
    ],
    "보험·연금": [
        r"(보험|보장|실손|종신|정기보험|암보험|운전자보험|연금|국민연금|퇴직연금|개인연금)",
    ],
    "세금·절약": [
        r"(세금|연말정산|소득공제|세액공제|부가세|종합소득세|양도세|증여세|상속세)",
        r"(절약|할인|포인트|캐시백|환급|무료|무이자|카드혜택|통신비|구독료)",
    ],
    "돈습관": [r"(월급|가계부|소비|지출|돈관리|통장|카드값|저축습관|재무|용돈|빚|대출상환)"],
    "경제상식": [
        r"(경제|물가|인플레이션|디플레이션|기준금리|한국은행|GDP|환율|무역|수출|수입)",
        r"(금융|은행|신용|신용점수|대출|담보|금융감독원|예금자보호)",
    ],
}


def classify_category(title, snippet=""):
    """키워드와 스니펫으로 카테고리를 분류한다."""
    text = f"{title} {snippet}"
    for cat, patterns in CATEGORY_RULES.items():
        for p in patterns:
            if re.search(p, text):
                return cat
    return None  # 매칭 안 되면 재테크 무관 → 제외 대상


def is_excluded(title, snippet=""):
    """프로젝트 기준에서 제외하는 주제인지 확인."""
    text = f"{title} {snippet}"
    return bool(EXCLUDE_RE.search(text))


def trend_key(title):
    """중복 판정용 키."""
    return hashlib.sha1(title.encode("utf-8")).hexdigest()[:16]


def fetch_google_trends_kr():
    """Google Trends Korea daily trends RSS를 가져온다. API 키 불필요."""
    import requests
    url = "https://trends.google.co.kr/trending/rss?geo=KR"
    items = []
    try:
        r = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible; issue-reels-bot/1.0)"
        })
        r.raise_for_status()

        # RSS XML 파싱 — 간단한 정규식 (의존성 최소화)
        for block in re.findall(r"<item>(.*?)</item>", r.text, re.S):
            title_m = re.search(r"<title>([^<]+)</title>", block)
            traffic_m = re.search(r"<ht:approx_traffic>([^<]+)</ht:approx_traffic>", block)
            news_items = re.findall(r"<ht:news_item_title>([^<]+)</ht:news_item_title>", block)
            news_snippets = re.findall(r"<ht:news_item_snippet>([^<]+)</ht:news_item_snippet>", block)

            if not title_m:
                continue

            title = title_m.group(1).strip()
            traffic = traffic_m.group(1).strip() if traffic_m else ""
            snippet = news_snippets[0] if news_snippets else ""
            news_title = news_items[0] if news_items else ""

            items.append({
                "keyword": title,
                "traffic": traffic,
                "news_title": news_title,
                "snippet": snippet,
                "source_type": "google_trends",
            })
        print(f"  Google Trends: {len(items)}건")
    except Exception as e:
        print(f"  [경고] Google Trends 수집 실패: {e}")
    return items


def fetch_naver_datalab():
    """네이버 DataLab 실시간 검색어 (비공식 — API 키 불필요).
    실패해도 Google Trends가 있으므로 치명적이지 않다."""
    import requests
    items = []
    try:
        # 네이버 실시간 급상승 검색어 (signal 페이지)
        url = "https://datalab.naver.com/keyword/realtimeList.naver"
        r = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (compatible; issue-reels-bot/1.0)",
            "Referer": "https://datalab.naver.com/",
        })
        if r.status_code == 200:
            # JSON 응답에서 키워드 추출
            try:
                data = r.json()
                for rank_item in data.get("data", []):
                    for kw_item in rank_item.get("data", []):
                        keyword = kw_item.get("keyword", "").strip()
                        if keyword:
                            items.append({
                                "keyword": keyword,
                                "traffic": "",
                                "news_title": "",
                                "snippet": "",
                                "source_type": "naver_datalab",
                            })
            except (json.JSONDecodeError, KeyError):
                # HTML 응답일 수도 있음 — 키워드 추출 시도
                keywords = re.findall(r'"keyword"\s*:\s*"([^"]+)"', r.text)
                for kw in keywords[:20]:
                    items.append({
                        "keyword": kw,
                        "traffic": "",
                        "news_title": "",
                        "snippet": "",
                        "source_type": "naver_datalab",
                    })
        print(f"  네이버 DataLab: {len(items)}건")
    except Exception as e:
        print(f"  [알림] 네이버 DataLab 수집 실패 (비필수): {e}")
    return items


def load_seen_trends():
    """이미 처리한 트렌드 키 목록."""
    path = os.path.join(OUT_DIR, "seen_trends.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def save_seen_trends(seen):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "seen_trends.json")
    # 최근 500개만 유지 (오래된 건 다시 수집 가능하도록)
    recent = sorted(seen)[-500:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(recent, f, ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser(description="트렌드 키워드 수집")
    ap.add_argument("--list", action="store_true", help="수집 결과 미리보기")
    args = ap.parse_args()

    print("트렌드 수집 시작")

    # 1. 수집
    raw = []
    raw.extend(fetch_google_trends_kr())
    raw.extend(fetch_naver_datalab())
    # 최근 24시간 RSS 뉴스를 트렌드 후보에 합친다.
    collected_path = os.path.join(OUT_DIR, "collected.json")
    if os.path.exists(collected_path):
        try:
            with open(collected_path, encoding="utf-8") as f:
                for it in json.load(f).get("items", []):
                    raw.append({
                        "keyword": it.get("title", ""),
                        "traffic": "",
                        "news_title": it.get("title", ""),
                        "snippet": it.get("summary", ""),
                        "source_type": "rss_issue",
                        "category": it.get("category", "경제상식"),
                        "url": it.get("url", ""),
                    })
        except Exception as e:
            print(f"  [경고] RSS 후보 병합 실패: {e}")

    if not raw:
        print("\n[경고] 트렌드 수집 결과 0건")
        return 1

    # 2. 중복 제거 (키워드 기준)
    seen_keywords = set()
    deduped = []
    for item in raw:
        kw = item["keyword"]
        if kw in seen_keywords:
            continue
        seen_keywords.add(kw)
        deduped.append(item)

    # 3. 프로젝트 기준 필터 (정치·연예·스포츠 제외)
    filtered = []
    excluded = 0
    for item in deduped:
        if is_excluded(item["keyword"], item.get("snippet", "")):
            excluded += 1
            continue
        filtered.append(item)

    # 4. 카테고리 분류
    for item in filtered:
        item["category"] = item.get("category") or classify_category(
            item["keyword"], item.get("snippet", "")
        )
        item["key"] = trend_key(item["keyword"])

    # 5. 허용 분야만 남기고 RSS 뉴스를 우선한다.
    allowed = {"재테크", "저축·투자", "보험·연금", "세금·절약", "돈습관", "경제상식"}
    filtered = [item for item in filtered if item.get("category") in allowed]
    seen = load_seen_trends()
    new_items = [item for item in filtered if item["key"] not in seen]
    new_items.sort(key=lambda item: (0 if item.get("source_type") == "google_trends" and item.get("news_title") else (1 if item.get("source_type") == "google_news_top" else 2), 0 if item.get("news_title") else 1, item.get("category", ""), item.get("keyword", "")))

    if args.list:
        print(f"\n전체 {len(raw)}건 → 중복제거 {len(deduped)}건 → 필터통과 {len(filtered)}건 → 신규 {len(new_items)}건 (제외 {excluded}건)")
        for item in new_items:
            print(f"  [{item['category']}] {item['keyword']}"
                  f"{' (' + item['traffic'] + ')' if item.get('traffic') else ''}")
        return 0

    # 6. 저장
    for item in new_items:
        seen.add(item["key"])
    save_seen_trends(seen)

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "trends.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "items": new_items,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n트렌드 수집 {len(new_items)}건 · 제외 {excluded}건 → {out}")

    # 카테고리별 집계
    cats = {}
    for item in new_items:
        cats[item["category"]] = cats.get(item["category"], 0) + 1
    for cat, cnt in sorted(cats.items()):
        print(f"  {cat}: {cnt}건")

    return 0


if __name__ == "__main__":
    sys.exit(main())
