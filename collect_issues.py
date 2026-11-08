# -*- coding: utf-8 -*-
"""최근 이슈 RSS 수집기."""
import argparse, hashlib, html, json, os, re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import requests
import xml.etree.ElementTree as ET

BLOCKED_ISSUES = re.compile(r"(4명의\s*엄마|엄마만\s*4명|결혼지옥|오은영\s*리포트)", re.I)\n\nFEEDS = {
    "국내 정치": [
        ("대통령실", "https://www.president.go.kr/rss"),
        ("국회", "https://www.assembly.go.kr/portal/rss/rss.do"),
    ],
    "해외 정치": [
        ("Reuters", "https://feeds.reuters.com/reuters/worldNews"),
        ("AP", "https://apnews.com/rss"),
        ("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ],
    "연예": [
        ("연예뉴스", "https://www.sportsseoul.com/rss/entertainment"),
        ("방송뉴스", "https://www.tvreport.co.kr/feed"),
    ],
    "해외 연예": [
        ("Variety", "https://variety.com/feed/"),
        ("Deadline", "https://deadline.com/feed/"),
        ("Billboard", "https://www.billboard.com/feed/"),
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
        desc=text(item.findtext("description"))
        out.append({"title":title,"summary":desc[:1000],"url":link,
                    "published_at":date.isoformat(),"category":category,
                    "source":source,"source_type":"rss"})
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--hours",type=int,default=24)
    ap.add_argument("--limit",type=int,default=5)
    args=ap.parse_args()
    cutoff=datetime.now(timezone.utc)-timedelta(hours=args.hours)
    all_items=[]
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
