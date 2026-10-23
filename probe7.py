# -*- coding: utf-8 -*-
"""
probe7.py — 참가격 API 조사일자 탐색

"올바른 조사일자가 아닙니다" → 조사일(매주 특정 요일)을 찾아야 한다.
1. goodInspectDay를 최근 30일간 하루씩 돌리며 시도
2. 응답 달라지는 날짜 = 조사일
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


def call(op, extra, timeout=20):
    p = {"serviceKey": KEY, "numOfRows": 5, "pageNo": 1, **extra}
    try:
        r = sess.get(f"{BASE}/{op}", params=p, timeout=timeout)
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)[:200]


def main():
    if not KEY:
        print("DATA_GO_KR_KEY 없음"); return 1

    today = dt.date.today()
    gid = "246"  # 돼지고기 삼겹살

    # 1. 최근 60일간 하루씩 조사일 탐색
    print(f"=== 1. goodId={gid} 조사일 탐색 (최근 60일) ===")
    hit_dates = []
    for delta in range(0, 60):
        d = today - dt.timedelta(days=delta)
        ds = d.strftime("%Y%m%d")
        status, text = call("getProductPriceInfoSvc", {"goodId": gid, "goodInspectDay": ds})
        has_items = "<item>" in text
        is_bad_date = "조사일자" in text
        if has_items:
            print(f"  ✓ {ds} ({d.strftime('%a')}): 히트! len={len(text)}")
            hit_dates.append(ds)
            # 첫 히트만 상세 출력
            if len(hit_dates) == 1:
                print(f"  응답: {text[:2000]}")
                try:
                    r = ET.fromstring(text)
                    for it in r.findall(".//item"):
                        print("  === 가격 필드 ===")
                        for ch in it:
                            print(f"    {ch.tag}: {ch.text}")
                        break
                except:
                    pass
            if len(hit_dates) >= 5:
                break
        elif not is_bad_date:
            # 에러도 아니고 빈 응답도 아닌 경우
            print(f"  ? {ds}: status={status} len={len(text)} text={text[:200]}")
        time.sleep(0.3)

    if hit_dates:
        print(f"\n조사일 발견: {hit_dates}")
        # 요일 패턴 확인
        for ds in hit_dates:
            d = dt.datetime.strptime(ds, "%Y%m%d").date()
            print(f"  {ds} = {d.strftime('%A')}")
    else:
        print("\n60일간 조사일 없음. 다른 goodId 시도:")
        for gid2 in ["224", "553", "35", "302"]:
            for delta in [0, 1, 2, 3, 4, 5, 6, 7, 14, 21]:
                d = today - dt.timedelta(days=delta)
                ds = d.strftime("%Y%m%d")
                status, text = call("getProductPriceInfoSvc", {"goodId": gid2, "goodInspectDay": ds})
                if "<item>" in text:
                    print(f"  ✓ goodId={gid2} {ds}: 히트!")
                    print(f"  {text[:1000]}")
                    return 0
                time.sleep(0.3)

    print("\n완료")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
