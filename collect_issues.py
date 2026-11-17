# -*- coding: utf-8 -*-
"""재테크·돈 정보 RSS 수집기."""
import argparse, hashlib, html, json, os, re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import requests
import xml.etree.ElementTree as ET

# 연예·정치·스포츠·부동산 관련은 제외
EXCLUDE_RE = re.compile(
    r"(연예|아이돌|정치|국회|대통령|스포츠|축구|야구|부동산|아파트|분양|청약|전세|월세|주택|집값)"
)

FEEDS = {
    "재테크": [
        ("한경 재테크", "https://www.hankyung.com/feed/finance"),
        ("매경 재테크", "https://www.mk.co.kr/rss/50200011/"),
    ],
    "저축·투자": [
        ("한경 증권", "https://www.hankyung.com/feed/stock"),
        ("매경 증권", "https://www.mk.co.kr/rss/50200009/"),
    ],
    "보험·연금": [
        ("보험신보", "https://www.insweek.co.kr/rss/allArticle.xml"),
    ],
    "세금·절약": [
        ("한경 세금", "https://www.hankyung.com/feed/economy"),
        ("매경 경제", "https://www.mk.co.kr/rss/50100030/"),
    ],
    "경제상식": [
        ("KBS경제", "https://world.kbs.co.kr/rss/rss_news.htm?lang=k&id=Ec"),
    ],
}

def text(v):
    return re.sub(r"\\s+", " ", html.unescape(v or "")).strip()

def parse_date(v):
    if not v: return None
    from email.utils import parsedate_to_datetime
    try: return parsedate_to_datetime(v).astimezone(timezone.utc)
    except Exception: return None

def key(title, url):
    norm = re.sub(r"[^0-9a-z가-힣]", "", title.lower())
    return hashlib.sha1((norm[:160] + "|" + url.split("?")[0]).encode()).hexdigest()

def read_feed(category, source, url, cutoff):
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent":"issue-reels/2.0"})
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"[경고] {source}: {e}")
        return []
    out=[]
    for item in root.findall(".//item"):
        title=text(item.findtext("title"))
        link=text(item.findtext("link"))
        date=parse_date(item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date"))
        if not title or not link or not date or date < cutoff: continue
        if EXCLUDE_RE.search(title): continue
        desc=text(item.findtext("description"))
        out.append({"title":title,"summary":desc[:1000],"url":link,
                    "published_at":date.isoformat(),"category":category,
                    "source":source,"source_type":"rss"})
    return out


def read_top_news(cutoff):
    """Google News Korea 경제·재테크 뉴스를 수집한다."""
    url = "https://news.google.com/rss/search?q=재테크+절약+세금+투자+연금&hl=ko&gl=KR&ceid=KR:ko"
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent":"Mozilla/5.0 issue-reels/2.0"})
        r.raise_for_status(); root = ET.fromstring(r.content)
    except Exception as e:
        print(f"[경고] Google News 경제뉴스: {e}"); return []
    out=[]
    for item in root.findall(".//item"):
        title=text(item.findtext("title")); link=text(item.findtext("link"))
        date=parse_date(item.findtext("pubDate"))
        if not title or not link or not date or date < cutoff: continue
        if EXCLUDE_RE.search(title): continue
        # 키워드로 세부 카테고리 분류
        if re.search(r"적금|예금|주식|ETF|펀드|채권|배당|금리|증권|투자", title): cat="저축·투자"
        elif re.search(r"보험|실손|연금|퇴직연금|국민연금", title): cat="보험·연금"
        elif re.search(r"세금|연말정산|공제|절약|할인|환급", title): cat="세금·절약"
        elif re.search(r"재테크|자산|수익률|포트폴리오", title): cat="재테크"
        elif re.search(r"월급|가계부|소비|돈관리|저축습관", title): cat="돈습관"
        else: cat="경제상식"
        source = (item.findtext("source") or "Google News").strip()
        out.append({"title":title,"summary":text(item.findtext("description"))[:1000],"url":link,
                    "published_at":date.isoformat(),"category":cat,"source":source,
                    "source_type":"google_news_finance"})
    print(f"Google News 경제뉴스: {len(out)}건")
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--hours",type=int,default=24)
    ap.add_argument("--limit",type=int,default=5)
    args=ap.parse_args()
    cutoff=datetime.now(timezone.utc)-timedelta(hours=args.hours)
    all_items=[]
    all_items.extend(read_top_news(cutoff))
    for cat, feeds in FEEDS.items():
        for source,url in feeds:
            all_items.extend(read_feed(cat,source,url,cutoff))
    seen_url=set(); seen_title=set(); unique=[]
    for x in sorted(all_items,key=lambda z:z["published_at"],reverse=True):
        t=re.sub(r"[^0-9a-z가-힣]","",x["title"].lower())
        if x["url"] in seen_url or t in seen_title: continue
        seen_url.add(x["url"]); seen_title.add(t); x["key"]=key(x["title"],x["url"]); unique.append(x)
    selected=[]
    for cat in FEEDS:
        selected.extend([x for x in unique if x["category"]==cat][:args.limit])
    os.makedirs("out",exist_ok=True)
    with open("out/collected.json","w",encoding="utf-8") as f:
        json.dump({"collected_at":datetime.now(timezone.utc).isoformat(),
                   "window_hours":args.hours,"items":selected},f,ensure_ascii=False,indent=2)
    print(f"최근 {args.hours}시간 RSS {len(all_items)}건 -> 중복 제거 {len(unique)}건 -> 선별 {len(selected)}건")
    return 0 if selected else 1
if __name__=="__main__": raise SystemExit(main())
