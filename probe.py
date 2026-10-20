# -*- coding: utf-8 -*-
"""
probe.py — 한국소비자원 참가격 API 구조 확인

data.go.kr 명세(데이터 15158701)에서 확인된 사실:
  - getProductPriceInfoSvc    가격. goodInspectDay(필수, **매주 금요일 날짜**) + entpId·goodId(선택)
  - getStandardInfoSvc.do     생필품 기준데이터 (상품 ID → 이름)
  - getStoreInfoSvc.do        판매점 정보 (업체 ID → 이름)

가격 응답은 ID만 주므로 이름을 붙이려면 기준데이터와 조인해야 한다.
이 probe는 세 엔드포인트의 실제 태그명과, 데이터가 있는 금요일을 확인한다.

결과는 probe_out/ 에 쌓이고 워크플로가 api-probe 브랜치로 올린다.
"""
import datetime as dt
import os
import re
import xml.dom.minidom as minidom

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "probe_out")
BASE = "https://apis.data.go.kr/B551919/ProductPriceInfoService"

_env = os.path.join(ROOT, ".env")
if os.path.exists(_env):
    with open(_env, encoding="utf-8", errors="replace") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

KEY = os.environ.get("DATA_GO_KR_KEY", "")


def redact(t):
    return t.replace(KEY, "***REDACTED***") if KEY else t


def pretty(t, limit=14000):
    try:
        return minidom.parseString(t).toprettyxml(indent="  ")[:limit]
    except Exception:
        return t[:limit]


def tag(t, name):
    m = re.search(rf"<{name}>\s*([^<]*?)\s*</{name}>", t)
    return m.group(1) if m else ""


def item_tags(t):
    """첫 item의 태그 이름 목록. field_map을 쓰려면 이게 필요하다."""
    blk = re.search(r"<item>(.*?)</item>", t, re.S)
    if not blk:
        return []
    return list(dict.fromkeys(re.findall(r"<(\w+)>", blk.group(1))))


def summarize(t):
    if "<item>" in t:
        return True, f"총 {tag(t,'totalCount') or '?'}건 · 태그: {', '.join(item_tags(t))}"
    msg = tag(t, "resultMsg") or tag(t, "returnAuthMsg") or tag(t, "errMsg")
    return False, msg or "(빈 응답)"


def call(op, params, label):
    try:
        r = requests.get(f"{BASE}/{op}", params=dict(params, serviceKey=KEY), timeout=20)
    except Exception as e:
        print(f"  {label:<40} 요청실패 {type(e).__name__}")
        return None
    ok, note = summarize(r.text)
    print(f"  {label:<40} {'OK ' if ok else '-- '}{note}")
    return r.text if ok else None


def dump(name, text, params=None):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f"{name}.xml"), "w", encoding="utf-8") as f:
        f.write(redact(pretty(text)))
    if params:
        shown = {k: v for k, v in params.items() if k != "serviceKey"}
        with open(os.path.join(OUT, f"{name}.params.txt"), "w", encoding="utf-8") as f:
            f.write(repr(shown) + "\n")
    print(f"    → probe_out/{name}.xml")


def recent_fridays(n=10):
    """최근 금요일들. 최신 조사분은 아직 공개 전일 수 있어 여러 주를 본다."""
    d = dt.date.today()
    d -= dt.timedelta(days=(d.weekday() - 4) % 7)   # 직전(또는 오늘) 금요일
    return [(d - dt.timedelta(weeks=i)).strftime("%Y%m%d") for i in range(n)]


def main():
    if not KEY:
        print("DATA_GO_KR_KEY 없음 — GitHub Actions에서 돌릴 것")
        return 1
    os.makedirs(OUT, exist_ok=True)
    base = {"numOfRows": 100, "pageNo": 1}

    print("=== 1단계: 기준데이터 (ID → 이름) ===")
    for op in ("getStandardInfoSvc.do", "getStoreInfoSvc.do",
               "getStandardInfoSvc", "getStoreInfoSvc"):
        t = call(op, base, op)
        if t:
            dump(f"info_{op.replace('.do','')}", t, base)

    print("\n=== 2단계: 가격 (금요일) ===")
    fridays = recent_fridays()
    print(f"  시도할 금요일: {', '.join(fridays[:5])} ...")
    hit = None
    for fri in fridays:
        t = call("getProductPriceInfoSvc", dict(base, goodInspectDay=fri),
                 f"goodInspectDay={fri}")
        if t:
            dump("price_success", t, dict(base, goodInspectDay=fri))
            hit = fri
            break

    if not hit:
        print("\n금요일 10주치 모두 데이터 없음. entpId를 함께 줘야 할 수 있다.")
        return 1

    print(f"\n데이터 있는 조사일: {hit}")
    print("field_map 은 probe_out/price_success.xml 의 태그를 그대로 쓰면 된다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
