# -*- coding: utf-8 -*-
"""
probe5.py — 참가격 API 가격 데이터 탐색 (최소 요청 버전)

전략: 요청 수를 최소화 (일일 한도 초과 방지)
1. 상품 카탈로그 1페이지(5개)만
2. 각 goodId에 대해 최근 금요일 1개만 시도
3. 한도 초과 감지 시 즉시 중단
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
    p = {"serviceKey": KEY, "numOfRows": 5, "pageNo": 1, **params}
    try:
        r = sess.get(f"{BASE}/{op}", params=p, timeout=timeout)
        root = ET.fromstring(r.text)
        code = root.findtext(".//resultCode", "")
        msg = root.findtext(".//resultMsg", "")
        err = root.findtext(".//errMsg", "")
        ret_msg = root.findtext(".//returnAuthMsg", "")
        # 한도 초과 감지
        if "LIMITED_NUMBER" in (err or "") or "요청제한" in (ret_msg or ""):
            return "LIMIT", "일일 요청 한도 초과", []
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

    # 1. 상품 카탈로그 — 1페이지 5개만
    print("=== 상품 카탈로그 (5개) ===")
    code, msg, products = api("getProductInfoSvc.do", {"numOfRows": 5, "pageNo": 1})
    if code == "LIMIT":
        print("⚠ 일일 요청 한도 초과! 내일 다시 시도하세요."); return 1
    for p in products:
        print(f"  goodId={p.get('goodId')} name={p.get('goodName','')[:40]}")
    print(f"상품 {len(products)}개\n")

    # 2. 최근 금요일 찾기
    today = dt.date.today()
    d = today
    for _ in range(7):
        if d.weekday() == 4:  # Friday
            break
        d -= dt.timedelta(days=1)
    target_date = d.strftime("%Y%m%d")
    print(f"조회 날짜: {target_date}\n")

    # 3. 각 상품 가격 조회 (최대 5건, 한도 초과 시 중단)
    print("=== 가격 조회 ===")
    hits = []
    for prod in products[:5]:
        gid = prod.get("goodId", "")
        code, msg, items = api("getProductPriceInfoSvc", {"goodId": gid, "goodInspectDay": target_date})
        if code == "LIMIT":
            print("⚠ 일일 요청 한도 초과! 중단합니다.")
            break
        if items:
            print(f"  ✓ goodId={gid} → {len(items)}건")
            hits.append({"goodId": gid, "date": target_date, "items": items, "name": prod.get("goodName","")})
        else:
            print(f"  ✗ goodId={gid} code={code} msg={msg[:50]}")
        time.sleep(1)  # 요청 간격 넉넉하게

    # 4. goodId 없이 날짜만으로도 시도 (1건)
    if not hits:
        print("\n=== 날짜만으로 조회 (1건) ===")
        code, msg, items = api("getProductPriceInfoSvc", {"goodInspectDay": target_date})
        if items:
            print(f"  ✓ 날짜만 → {len(items)}건")
            hits.append({"goodId": "all", "date": target_date, "items": items})
        else:
            print(f"  ✗ code={code} msg={msg[:80]}")

    # 5. 결과
    print(f"\n=== 결과 요약: {len(hits)}건 히트 ===")
    if hits:
        print("\n첫 번째 히트 필드:")
        for k, v in hits[0]["items"][0].items():
            print(f"  {k}: {v}")
    else:
        print("가격 데이터 없음!")
        # raw 응답 확인 (1건만)
        if products:
            gid = products[0].get("goodId","")
            p = {"serviceKey": KEY, "numOfRows": 5, "pageNo": 1, "goodId": gid, "goodInspectDay": target_date}
            r = sess.get(f"{BASE}/getProductPriceInfoSvc", params=p, timeout=45)
            print(f"\n디버그 raw ({len(r.text)} bytes):")
            print(f"  {r.text[:1500]}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
