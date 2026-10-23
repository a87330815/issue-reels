# -*- coding: utf-8 -*-
"""
probe8.py — 참가격 API 필드 구조 확인

조사일 20261009가 히트 확인됨. 해당 날짜로 상세 필드를 파싱한다.
"""
import os, xml.etree.ElementTree as ET
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

def main():
    if not KEY:
        print("DATA_GO_KR_KEY 없음"); return 1

    # 히트 확인된 조사일
    inspect_day = "20261009"

    # 인기 생필품
    goods = [
        ("246", "돼지고기 삼겹살"),
        ("224", "서울우유 흰우유"),
        ("553", "신라면 5개입"),
        ("302", "배추"),
        ("935", "대파"),
        ("237", "삼양라면 5개입"),
    ]

    for gid, name in goods:
        print(f"\n=== goodId={gid} ({name}) ===")
        p = {
            "serviceKey": KEY,
            "numOfRows": 50,
            "pageNo": 1,
            "goodId": gid,
            "goodInspectDay": inspect_day,
        }
        r = sess.get(f"{BASE}/getProductPriceInfoSvc", params=p, timeout=20)
        print(f"  status={r.status_code} len={len(r.text)}")

        if "<iros.openapi.service.vo.goodPriceVO>" not in r.text and "<item>" not in r.text:
            print(f"  데이터 없음")
            continue

        # XML 파싱 — 참가격은 item 대신 goodPriceVO 사용
        text = r.text
        # goodPriceVO를 item으로 치환해서 파싱
        text = text.replace("iros.openapi.service.vo.goodPriceVO", "item")
        try:
            root = ET.fromstring(text)
        except:
            print(f"  파싱 실패: {r.text[:500]}")
            continue

        items = root.findall(".//item")
        print(f"  아이템 수: {len(items)}")

        for i, item in enumerate(items[:3]):
            print(f"\n  --- 아이템 {i+1} ---")
            for ch in item:
                print(f"    {ch.tag}: {ch.text}")

    print("\n\n=== 요약: field_map 작성용 ===")
    print("응답의 XML 태그 → field_map에 매핑할 필드명")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
