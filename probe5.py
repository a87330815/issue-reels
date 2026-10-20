# -*- coding: utf-8 -*-
"""
probe5.py — 참가격 API 엔드포인트 탐색

목표: 올바른 가격 조회 엔드포인트와 파라미터 조합을 찾기
"""
import os, datetime as dt, time
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
retry = Retry(total=2, backoff_factor=2, status_forcelist=[500, 502, 503])
sess.mount("https://", HTTPAdapter(max_retries=retry))

def raw_call(op, extra_params, timeout=20):
    p = {"serviceKey": KEY, "numOfRows": 5, "pageNo": 1, **extra_params}
    try:
        r = sess.get(f"{BASE}/{op}", params=p, timeout=timeout)
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)[:200]

def main():
    if not KEY:
        print("DATA_GO_KR_KEY 없음"); return 1

    # 1. 상품 카탈로그에서 첫 상품 가져오기
    print("=== 1. 상품 카탈로그 조회 ===")
    status, text = raw_call("getProductInfoSvc.do", {"numOfRows": 2, "pageNo": 1})
    print(f"  status={status} len={len(text)}")
    if status != 200:
        print(f"  카탈로그 조회 실패: {text[:300]}")
        return 1

    root = ET.fromstring(text)
    products = []
    for item in root.findall(".//item"):
        d = {ch.tag: ch.text for ch in item}
        products.append(d)
        print(f"  goodId={d.get('goodId')} name={d.get('goodName','')[:30]}")
        # 모든 필드 출력 (첫 번째만)
        if len(products) == 1:
            print("  === 전체 필드 ===")
            for k, v in d.items():
                print(f"    {k}: {v}")

    if not products:
        print("카탈로그 조회 실패!")
        print(f"  raw: {text[:500]}")
        return 1

    gid = products[0].get("goodId", "35")

    # 최근 금요일
    today = dt.date.today()
    d = today
    for _ in range(7):
        if d.weekday() == 4: break
        d -= dt.timedelta(days=1)
    friday = d.strftime("%Y%m%d")

    # 2. 가격 조회 엔드포인트 변형 테스트
    print(f"\n=== 2. 가격 엔드포인트 탐색 (goodId={gid}, date={friday}) ===")

    endpoints = [
        ("getProductPriceInfoSvc", {"goodId": gid, "goodInspectDay": friday}),
        ("getProductPriceInfoSvc.do", {"goodId": gid, "goodInspectDay": friday}),
        ("getProductPriceInfo", {"goodId": gid, "goodInspectDay": friday}),
        ("getProductPriceInfo.do", {"goodId": gid, "goodInspectDay": friday}),
        # goodInspectDay 없이
        ("getProductPriceInfoSvc", {"goodId": gid}),
        ("getProductPriceInfoSvc.do", {"goodId": gid}),
        # 다른 파라미터명 시도
        ("getProductPriceInfoSvc", {"goodId": gid, "inspectDay": friday}),
        ("getProductPriceInfoSvc.do", {"goodId": gid, "inspectDay": friday}),
        ("getProductPriceInfoSvc", {"goodId": gid, "searchDate": friday}),
        # entpId로
        ("getProductPriceInfoSvc", {"entpId": products[0].get("productEntpCode",""), "goodInspectDay": friday}),
        ("getProductPriceInfoSvc.do", {"entpId": products[0].get("productEntpCode",""), "goodInspectDay": friday}),
    ]

    for ep, params in endpoints:
        status, text = raw_call(ep, params)
        has_items = "<item>" in text
        has_limit = "LIMITED_NUMBER" in text or "요청제한" in text

        if has_limit:
            print(f"  ⚠ {ep} params={params}: 일일 한도 초과! 중단")
            break

        print(f"  {ep} params={list(params.keys())}: status={status} items={has_items} len={len(text)}")
        if has_items:
            print(f"  ✓✓✓ 히트! 응답:")
            print(f"  {text[:800]}")
            # 파싱
            r = ET.fromstring(text)
            for it in r.findall(".//item"):
                print("  === 가격 필드 ===")
                for ch in it:
                    print(f"    {ch.tag}: {ch.text}")
                break
            return 0
        elif status != 200:
            print(f"  raw: {text[:200]}")

        time.sleep(1)

    # 3. 서비스 목록 자체를 조회
    print(f"\n=== 3. 서비스 루트 탐색 ===")
    for path in ["", "/", "?type=json"]:
        try:
            r = sess.get(f"{BASE}{path}", params={"serviceKey": KEY}, timeout=15)
            print(f"  path='{path}': status={r.status_code} len={len(r.text)}")
            print(f"  {r.text[:500]}")
        except Exception as e:
            print(f"  path='{path}': ERROR {e}")
        time.sleep(0.5)

    print("\n가격 데이터를 찾지 못했습니다.")
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
