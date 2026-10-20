# -*- coding: utf-8 -*-
"""
probe.py — 한국소비자원 참가격 API 구조 탐색

목적: `sources.yml`의 kca_product_price에 넣을 field_map을 확정한다.
지금 field_map이 비어 있어 이 소스는 게이트는 통과하지만 0건을 돌려준다.
그래서 모든 릴스가 아파트 실거래가 하나로만 만들어지고 있다.

이전 시도(probe3)는 가격 엔드포인트에 ID를 추측해 넣다가 막혔다.
이번에는 순서를 바꾼다:
  1. 부가 엔드포인트(업체·상품 목록)로 **실제 존재하는 ID**를 받는다
  2. 그 ID로 가격을 조회한다
  3. 성공한 응답의 태그 구조를 그대로 덤프한다

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

# 같은 서비스에 붙어 있는 흔한 오퍼레이션들. 어느 것이 열려 있는지 모르니 전부 찔러본다.
OPERATIONS = [
    "getEntpInfoSvc",        # 업체 목록
    "getGoodInfoSvc",        # 상품 목록
    "getProductPriceInfoSvc",  # 가격 (본체)
    "getIntlPriceInfoSvc",
    "getAvgPriceInfoSvc",
]


def redact(text):
    return text.replace(KEY, "***REDACTED***") if KEY else text


def pretty(text, limit=12000):
    try:
        return minidom.parseString(text).toprettyxml(indent="  ")[:limit]
    except Exception:
        return text[:limit]


def tag_of(text, name):
    m = re.search(rf"<{name}>\s*([^<]*?)\s*</{name}>", text)
    return m.group(1) if m else ""


def summarize(text):
    """응답 한 줄 요약. item이 있으면 태그 목록까지."""
    if "<item>" in text:
        block = re.search(r"<item>(.*?)</item>", text, re.S)
        tags = re.findall(r"<(\w+)>", block.group(1)) if block else []
        total = tag_of(text, "totalCount")
        return True, f"item 있음 (총 {total or '?'}건) 태그: {', '.join(dict.fromkeys(tags))}"
    msg = (tag_of(text, "resultMsg") or tag_of(text, "returnAuthMsg")
           or tag_of(text, "errMsg") or "(빈 응답)")
    return False, msg


def call(op, params, label):
    url = f"{BASE}/{op}"
    try:
        r = requests.get(url, params=dict(params, serviceKey=KEY), timeout=20)
    except Exception as e:
        print(f"    {label:<42} 요청실패 {type(e).__name__}")
        return None
    ok, note = summarize(r.text)
    print(f"    {label:<42} {'OK ' if ok else '-- '}{note}")
    return r.text if ok else None


def dump(name, text, params=None):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f"{name}.xml"), "w", encoding="utf-8") as f:
        f.write(redact(pretty(text)))
    if params:
        shown = {k: v for k, v in params.items() if k != "serviceKey"}
        with open(os.path.join(OUT, f"{name}.params.txt"), "w", encoding="utf-8") as f:
            f.write(repr(shown) + "\n")
    print(f"      → probe_out/{name}.xml 저장")


def ids_from(text, *candidates):
    """응답에서 ID로 쓸 만한 값을 뽑는다."""
    for tag in candidates:
        vals = re.findall(rf"<{tag}>\s*([^<]*?)\s*</{tag}>", text)
        vals = [v for v in vals if v]
        if vals:
            return tag, list(dict.fromkeys(vals))
    return None, []


def recent_days(n=21):
    today = dt.date.today()
    return [(today - dt.timedelta(days=i)).strftime("%Y%m%d") for i in range(n)]


def main():
    if not KEY:
        print("DATA_GO_KR_KEY 없음 — 이 probe는 GitHub Actions에서 돌려야 한다")
        return 1
    os.makedirs(OUT, exist_ok=True)
    base = {"numOfRows": 50, "pageNo": 1}

    # ── 1단계: 어떤 오퍼레이션이 열려 있는지 ─────────────────
    print("=== 1단계: 오퍼레이션 탐색 ===")
    alive = {}
    for op in OPERATIONS:
        text = call(op, base, op)
        if text:
            alive[op] = text
            dump(f"op_{op}", text, base)

    # ── 2단계: 목록 API에서 실제 ID 확보 ────────────────────
    print("\n=== 2단계: 유효 ID 확보 ===")
    entp_tag, entp_ids = None, []
    good_tag, good_ids = None, []
    if "getEntpInfoSvc" in alive:
        entp_tag, entp_ids = ids_from(alive["getEntpInfoSvc"], "entpId", "entpCd", "id")
        print(f"  업체 ID {len(entp_ids)}개 ({entp_tag}): {entp_ids[:8]}")
    if "getGoodInfoSvc" in alive:
        good_tag, good_ids = ids_from(alive["getGoodInfoSvc"], "goodId", "goodCd", "id")
        print(f"  상품 ID {len(good_ids)}개 ({good_tag}): {good_ids[:8]}")

    # 가격 엔드포인트가 조건 없이 바로 열렸으면 그걸로 끝
    if "getProductPriceInfoSvc" in alive:
        print("\n가격 엔드포인트가 조건 없이 응답했다. field_map은 op_getProductPriceInfoSvc.xml 참조")
        return 0

    # ── 3단계: 확보한 ID + 날짜로 가격 조회 ──────────────────
    print("\n=== 3단계: 가격 조회 ===")
    dates = recent_days()
    date_params = ["goodInspectDay", "inspectDay", "baseDe", "examinDay"]

    tried = 0
    for dparam in date_params:
        for date in dates[:10]:
            # 식별자 없이
            p = dict(base, **{dparam: date})
            t = call("getProductPriceInfoSvc", p, f"{dparam}={date}")
            tried += 1
            if t:
                dump("price_success", t, p)
                return 0
            # 상품 ID를 붙여서
            for gid in (good_ids or [])[:5]:
                p = dict(base, **{dparam: date, good_tag or "goodId": gid})
                t = call("getProductPriceInfoSvc", p, f"{dparam}={date} {good_tag}={gid}")
                tried += 1
                if t:
                    dump("price_success", t, p)
                    return 0
            if tried > 120:
                break
        if tried > 120:
            break

    print(f"\n{tried}개 조합을 시도했으나 데이터 없음.")
    print("probe_out/ 의 응답을 보고 파라미터 이름을 다시 판단할 것.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
