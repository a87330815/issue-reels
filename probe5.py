# -*- coding: utf-8 -*-
"""
probe5.py — 참가격 API 가격 데이터 탐색 (최적화 버전)

전략:
1. 상품 카탈로그에서 첫 페이지(20개) + 랜덤 샘플 가져오기
2. 각 goodId에 대해 날짜 1개만 시도
3. entpId(productEntpCode)로도 시도
4. 날짜 없이도 시도 (혹시 전체 조회 가능한지)
"""
import os, json, datetime as dt, time
import xml.etree.ElementTree as ET
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = os.path.dirname(os.path.abspath(__file__))
_env = os.path.join(ROOT, ".env")
if os.path.exists(_env):
    with open(_env, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

KEY = os.environ.get("DATA_GO_KR_KEY", "")
BASE = "https://apis.data.go.kr/B551919/ProductPriceInfoService"

sess = requests.Session()
retry = Retry(total=3, backoff_factor=3, status_forcelist=[500, 502, 503, 504])
sess.mount("https://", HTTPAdapter(max_retries=retry))

def api(op, params, timeout=45):
    p = {"serviceKey": KEY, "numOfRows": 10, "pageNo": 1, **params}
    try:
        r = sess.get(f"{BASE}/{op}", params=p, timeout=timeout)
        root = ET.fromstring(r.text)
        code = root.findtext(".//resultCode", "")
        msg = root.findtext(".//resultMsg", "")
        items = []
        for item in root.findall(".//item"):
            d = {}
            for ch in item:
                d[ch.tag] = ch.text
            items.append(d)
        return code, msg, items
    except Exception as e:
        return "ERR", str(e)[:80], []

def main():
    if not KEY:
        print("DATA_GO_KR_KEY 없음"); return 1

    # 1. 상품 카탈로그 샘플 (페이지 1, 10, 20, 30)
    print("=== 상품 카탈로그 샘플 ===")
    sample_products = []
    for pg in [1, 10, 20, 30]:
        code, msg, items = api("getProductInfoSvc.do", {"numOfRows": 5, "pageNo": pg})
        for it in items:
            sample_products.append(it)
            print(f"  goodId={it.get('goodId')} entpCode={it.get('productEntpCode')} {it.get('goodName','')[:30]}")
    print(f"샘플 {len(sample_products)}개\n")

    # 2. 날짜 후보 — 최근 금요일 1개 + 목요일 1개 + 오늘
    today = dt.date.today()
    dates = [today.strftime("%Y%m%d")]
    d = today
    for _ in range(14):
        d -= dt.timedelta(days=1)
        if d.weekday() == 4 and len(dates) < 3:  # Friday
            dates.append(d.strftime("%Y%m%d"))
        if d.weekday() == 3 and len(dates) < 4:  # Thursday
            dates.append(d.strftime("%Y%m%d"))
    print(f"날짜 후보: {dates}\n")

    # 3. goodId × 날짜
    print("=== goodId × 날짜 ===")
    hits = []
    for prod in sample_products:
        gid = prod.get("goodId", "")
        for date in dates:
            code, msg, items = api("getProductPriceInfoSvc", {"goodId": gid, "goodInspectDay": date})
            if items:
                print(f"  ✓ goodId={gid} date={date} → {len(items)}건")
                hits.append({"goodId": gid, "date": date, "items": items[:3], "name": prod.get("goodName","")})
                break
            time.sleep(0.3)
        else:
            print(f"  ✗ goodId={gid} ({prod.get('goodName','')[:20]})")

    # 4. entpId × 날짜
    print("\n=== entpId × 날짜 ===")
    entp_ids = list(set(p.get("productEntpCode","") for p in sample_products if p.get("productEntpCode")))
    for eid in entp_ids[:10]:
        for date in dates:
            code, msg, items = api("getProductPriceInfoSvc", {"entpId": eid, "goodInspectDay": date})
            if items:
                print(f"  ✓ entpId={eid} date={date} → {len(items)}건")
                hits.append({"entpId": eid, "date": date, "items": items[:3]})
                break
            time.sleep(0.3)
        else:
            print(f"  ✗ entpId={eid}")

    # 5. goodId만 (날짜 없이)
    print("\n=== goodId만 (날짜 없이) ===")
    for prod in sample_products[:5]:
        gid = prod.get("goodId", "")
        code, msg, items = api("getProductPriceInfoSvc", {"goodId": gid})
        status = f"✓ {len(items)}건" if items else f"✗ code={code} {msg[:40]}"
        print(f"  goodId={gid}: {status}")
        if items:
            hits.append({"goodId": gid, "date": "none", "items": items[:3], "name": prod.get("goodName","")})
        time.sleep(0.3)

    # 결과
    print(f"\n=== 결과 요약: {len(hits)}건 히트 ===")
    if hits:
        print("\n첫 번째 히트의 필드:")
        for k, v in hits[0]["items"][0].items():
            print(f"  {k}: {v}")
        print("\n모든 히트:")
        for h in hits:
            gid = h.get("goodId", h.get("entpId","?"))
            print(f"  {gid} @ {h['date']} → {len(h['items'])}건 {h.get('name','')[:30]}")
    else:
        print("가격 데이터 없음!")
        print("\n디버그: 마지막 응답 code/msg 확인")
        # 한 번 더 raw로 확인
        gid = sample_products[0].get("goodId","35")
        p = {"serviceKey": KEY, "numOfRows": 5, "pageNo": 1, "goodId": gid, "goodInspectDay": dates[0]}
        r = sess.get(f"{BASE}/getProductPriceInfoSvc", params=p, timeout=45)
        print(f"  raw response ({len(r.text)} bytes):")
        print(f"  {r.text[:2000]}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
