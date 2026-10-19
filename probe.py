# -*- coding: utf-8 -*-
"""
probe.py — 오픈API 응답 샘플 수집기

field_map을 쓰려면 실제 응답 구조를 봐야 하는데 샌드박스에서 apis.data.go.kr이 막혀 있다.
그래서 Actions에서 이 스크립트를 돌려 원문을 probe_out/에 떨군다.
"""
import os
import sys
import xml.dom.minidom as minidom

import requests

BASE = "https://apis.data.go.kr/B551919/ProductPriceInfoService"
KEY = os.environ.get("DATA_GO_KR_KEY", "")
OUT = "probe_out"

CALLS = [
    ("standard", "/getStandardInfoSvc.do", {"numOfRows": 20, "pageNo": 1}),
    ("product",  "/getProductInfoSvc.do",  {"numOfRows": 20, "pageNo": 1}),
    ("store",    "/getStoreInfoSvc.do",    {"numOfRows": 20, "pageNo": 1}),
    # 가격정보는 업체아이디/상품아이디 중 하나가 필수. product 응답에서 얻은 값으로 재시도한다.
    ("price",    "/getProductPriceInfoSvc", {"numOfRows": 20, "pageNo": 1}),
]


def pretty(text):
    try:
        return minidom.parseString(text).toprettyxml(indent="  ")[:8000]
    except Exception:
        return text[:8000]


def main():
    if not KEY:
        print("DATA_GO_KR_KEY 없음")
        return 1
    os.makedirs(OUT, exist_ok=True)

    for name, path, params in CALLS:
        p = dict(params)
        p["serviceKey"] = KEY
        url = BASE + path
        print(f"\n===== {name}  {path} =====")
        try:
            r = requests.get(url, params=p, timeout=30)
            print(f"HTTP {r.status_code}  {len(r.content)} bytes")
            body = pretty(r.text)
            with open(os.path.join(OUT, f"{name}.xml"), "w", encoding="utf-8") as f:
                f.write(body)
            print(body[:1500])
        except Exception as e:
            print(f"실패: {type(e).__name__}: {e}")
            with open(os.path.join(OUT, f"{name}.error.txt"), "w", encoding="utf-8") as f:
                f.write(f"{type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
