# -*- coding: utf-8 -*-
"""
probe5.py — 604개 상품 중 실제 가격 데이터가 있는 goodId 찾기

probe4에서 getProductInfoSvc.do가 604건을 반환함을 확인.
getProductPriceInfoSvc는 entpId 또는 goodId가 필수.
이제 goodId를 순회하며 최근 날짜에 가격 데이터가 있는 상품을 찾는다.
"""
import os, sys, json, datetime as dt
import xml.etree.ElementTree as ET
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
_env = os.path.join(ROOT, ".env")
if os.path.exists(_env):
    with open(_env, encoding="utf-8", errors="replace") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

KEY = os.environ.get("DATA_GO_KR_KEY", "")
BASE = "https://apis.data.go.kr/B551919/ProductPriceInfoService"

def get_all_good_ids():
    """상품 카탈로그에서 모든 goodId+goodName 가져오기"""
    url = f"{BASE}/getProductInfoSvc.do"
    all_items = []
    for page in range(1, 40):  # 604건, 20건씩 = 최대 31페이지
        r = requests.get(url, params={
            "serviceKey": KEY, "numOfRows": 20, "pageNo": page
        }, timeout=15)
        root = ET.fromstring(r.text)
        items = root.findall(".//item")
        if not items:
            break
        for item in items:
            gid = item.findtext("goodId", "")
            name = item.findtext("goodName", "")
            entp = item.findtext("productEntpCode", "")
            if gid:
                all_items.append({"goodId": gid, "goodName": name, "entpCode": entp})
    return all_items

def recent_fridays(n=4):
    today = dt.date.today()
    out = []
    d = today
    while len(out) < n:
        d -= dt.timedelta(days=1)
        if d.weekday() == 4:  # Friday
            out.append(d.strftime("%Y%m%d"))
    return out

def check_price(good_id, dates):
    """goodId에 대해 최근 날짜들로 가격 조회, 첫 번째 성공 반환"""
    url = f"{BASE}/getProductPriceInfoSvc"
    for date in dates:
        try:
            r = requests.get(url, params={
                "serviceKey": KEY, "numOfRows": 5, "pageNo": 1,
                "goodInspectDay": date, "goodId": good_id
            }, timeout=10)
            root = ET.fromstring(r.text)
            items = root.findall(".//item")
            if items:
                # 첫 번째 item의 필드들 추출
                fields = {}
                for child in items[0]:
                    fields[child.tag] = child.text
                return {"date": date, "count": len(items), "fields": fields}
        except Exception as e:
            print(f"  goodId={good_id} date={date} error: {e}")
    return None

def main():
    if not KEY:
        print("DATA_GO_KR_KEY 없음")
        return 1

    print("=== 1단계: 상품 카탈로그 수집 ===")
    products = get_all_good_ids()
    print(f"총 {len(products)}개 상품")

    dates = recent_fridays(4)
    print(f"조회 날짜: {dates}")

    # 2단계: 각 goodId로 가격 조회
    print(f"\n=== 2단계: 가격 데이터 탐색 ({len(products)}개 상품) ===")
    hits = []
    miss = 0
    for i, prod in enumerate(products):
        gid = prod["goodId"]
        result = check_price(gid, dates)
        if result:
            print(f"  ✓ goodId={gid} ({prod['goodName']}) → {result['count']}건 @ {result['date']}")
            hits.append({**prod, **result})
            if len(hits) >= 30:
                print("  ... 30건 수집 완료, 중단")
                break
        else:
            miss += 1
            if miss % 50 == 0:
                print(f"  ... {miss}건 miss (현재 goodId={gid})")

    print(f"\n=== 결과 요약 ===")
    print(f"조회: {i+1}개 / 히트: {len(hits)}개 / 미스: {miss}개")

    if hits:
        print(f"\n첫 번째 히트 필드:")
        for k, v in hits[0]["fields"].items():
            print(f"  {k}: {v}")

        # 상품명 목록
        print(f"\n가격 데이터 있는 상품:")
        for h in hits:
            print(f"  goodId={h['goodId']} {h['goodName']} ({h['count']}건 @ {h['date']})")

        # JSON 저장
        with open("/tmp/probe5_hits.json", "w", encoding="utf-8") as f:
            json.dump(hits, f, ensure_ascii=False, indent=2)
        print(f"\n저장: /tmp/probe5_hits.json")
    else:
        print("가격 데이터 있는 상품 없음!")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
