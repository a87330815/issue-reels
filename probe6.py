# -*- coding: utf-8 -*-
"""
probe6.py — 참가격 API 가격 조회 엔드포인트 심층 탐색

probe5에서 카탈로그는 성공했지만 가격 조회가 빈 응답.
날짜 포맷, 파라미터 조합, 다양한 goodId를 시도한다.
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
    p = {"serviceKey": KEY, "numOfRows": 10, "pageNo": 1, **extra_params}
    try:
        r = sess.get(f"{BASE}/{op}", params=p, timeout=timeout)
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)[:200]


def main():
    if not KEY:
        print("DATA_GO_KR_KEY 없음"); return 1

    today = dt.date.today()

    # 날짜 포맷 변형
    date_formats = []
    for delta in range(0, 14):
        d = today - dt.timedelta(days=delta)
        date_formats.append(d.strftime("%Y%m%d"))
    # 최근 금요일들
    d = today
    for _ in range(14):
        if d.weekday() == 4:
            date_formats.append(d.strftime("%Y%m%d"))
        d -= dt.timedelta(days=1)
    date_formats = list(dict.fromkeys(date_formats))  # dedup preserve order

    # 인기 상품 ID들
    good_ids = ["246", "224", "553", "237", "302", "935", "50", "35"]

    print("=== 1. 다양한 날짜 x goodId 조합 ===")
    hit = False
    for gid in good_ids[:3]:
        for date_val in date_formats[:7]:
            # 다양한 파라미터명 시도
            combos = [
                {"goodId": gid, "goodInspectDay": date_val},
                {"goodId": gid, "goodInspectDay": date_val, "type": "json"},
            ]
            for params in combos:
                status, text = raw_call("getProductPriceInfoSvc", params)
                has_items = "<item>" in text or '"item"' in text
                if has_items:
                    print(f"  ✓✓✓ 히트! goodId={gid} params={params}")
                    print(f"  응답: {text[:1500]}")
                    hit = True
                    break
                time.sleep(0.3)
            if hit:
                break
        if hit:
            break

    if not hit:
        print("  기본 조합 전부 빈 응답")

    # 2. 날짜 없이 numOfRows 크게
    print("\n=== 2. 날짜 없이 대량 조회 ===")
    for gid in good_ids[:3]:
        status, text = raw_call("getProductPriceInfoSvc", {"goodId": gid, "numOfRows": 100})
        has_items = "<item>" in text
        print(f"  goodId={gid}: status={status} items={has_items} len={len(text)}")
        if has_items:
            print(f"  응답: {text[:1500]}")
            break
        # 빈 응답이면 XML 전체 출력 (디버깅)
        if status == 200 and len(text) < 500:
            print(f"  전체 응답: {text}")
        time.sleep(0.5)

    # 3. 다른 서비스 오퍼레이션 탐색
    print("\n=== 3. 서비스 오퍼레이션 탐색 ===")
    ops = [
        "getProductPriceList",
        "getProductPriceList.do",
        "getProductPriceDetailSvc",
        "getProductPriceDetailSvc.do",
        "getProductDayPriceInfoSvc",
        "getProductDayPriceInfoSvc.do",
        "getProductWeekPriceInfoSvc",
        "getProductWeekPriceInfoSvc.do",
        "getProductMonthPriceInfoSvc",
        "getProductMonthPriceInfoSvc.do",
        "getProductAreaPriceInfoSvc",
        "getProductAreaPriceInfoSvc.do",
        "getProductEntpPriceInfoSvc",
        "getProductEntpPriceInfoSvc.do",
    ]
    for op in ops:
        status, text = raw_call(op, {"goodId": "246"})
        has_items = "<item>" in text
        is_error = "폐기" in text or "ERROR" in text
        print(f"  {op}: status={status} items={has_items} err={is_error} len={len(text)}")
        if has_items:
            print(f"  ✓✓✓ 히트!")
            print(f"  응답: {text[:1500]}")
            # 파싱
            try:
                r = ET.fromstring(text)
                for it in r.findall(".//item"):
                    print("  === 가격 필드 ===")
                    for ch in it:
                        print(f"    {ch.tag}: {ch.text}")
                    break
            except:
                pass
            break
        time.sleep(0.5)

    # 4. 카탈로그에서 가격 필드가 있는지 확인
    print("\n=== 4. 카탈로그 상세 필드 재확인 ===")
    status, text = raw_call("getProductInfoSvc.do", {"numOfRows": 5, "pageNo": 1})
    if status == 200:
        try:
            r = ET.fromstring(text)
            for it in r.findall(".//item")[:2]:
                print("  === 카탈로그 아이템 ===")
                for ch in it:
                    print(f"    {ch.tag}: {ch.text}")
        except:
            print(f"  파싱 실패: {text[:300]}")

    print("\n완료")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
