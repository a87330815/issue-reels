# -*- coding: utf-8 -*-
"""
probe3.py — 가격 조회 식별자 탐색

probe2에서 날짜 파라미터는 goodInspectDay로 확정됐고, 20261016이 유효 날짜로
"ok"를 돌려줬다. 다만 entpId=10에는 해당 날짜 데이터가 없어 item이 비었다.
이제 식별자(업체/상품)를 바꿔가며 실제 가격 레코드가 들어오는 조합을 찾는다.
"""
import os
import datetime as dt
import xml.dom.minidom as minidom

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
URL = "https://apis.data.go.kr/B551919/ProductPriceInfoService/getProductPriceInfoSvc"
OUT = os.path.join(ROOT, "probe_out")

DATE_PARAM = "goodInspectDay"

# probe_out에서 확인된 실제 ID들
ENTP_IDS = ["786", "10", "12", "13", "15", "16", "17", "19", "20", "21", "33"]
GOOD_IDS = ["35", "104", "217", "523", "536", "538", "50", "265", "246", "247"]


def candidate_dates(weeks=6):
    """최근 몇 주의 목·금요일. probe2에서 20261016(목)이 ok였다."""
    today = dt.date.today()
    out = []
    for back in range(0, weeks * 7):
        d = today - dt.timedelta(days=back)
        if d.weekday() in (3, 4):
            out.append(d.strftime("%Y%m%d"))
    return out


def redact(text):
    return text.replace(KEY, "***REDACTED***") if KEY else text


def pretty(text):
    try:
        return minidom.parseString(text).toprettyxml(indent="  ")[:8000]
    except Exception:
        return text[:8000]


def result_msg(text):
    try:
        doc = minidom.parseString(text)
        nodes = doc.getElementsByTagName("resultMsg")
        if nodes and nodes[0].firstChild:
            return nodes[0].firstChild.nodeValue
    except Exception:
        pass
    return ""


def try_call(params, label):
    try:
        r = requests.get(URL, params=params, timeout=15)
    except Exception as e:
        print(f"  {label} -> 요청실패 {type(e).__name__}")
        return None
    if "<item>" in r.text:
        print(f"\n*** 데이터 있음: {label} ***")
        return r.text
    msg = result_msg(r.text)
    print(f"  {label} -> {msg or '(빈 응답)'}")
    return None


def save(text, params):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "price_success.xml"), "w", encoding="utf-8") as f:
        f.write(redact(pretty(text)))
    shown = {k: v for k, v in params.items() if k != "serviceKey"}
    with open(os.path.join(OUT, "price_params.txt"), "w", encoding="utf-8") as f:
        f.write(repr(shown) + "\n")
    print(f"저장: {os.path.join(OUT, 'price_success.xml')}")
    print(f"성공 파라미터: {shown}")


def main():
    if not KEY:
        print("DATA_GO_KR_KEY 없음")
        return 1
    os.makedirs(OUT, exist_ok=True)

    dates = candidate_dates()
    base = {"serviceKey": KEY, "numOfRows": 20, "pageNo": 1}

    # 1단계: 날짜만 주고 식별자 없이 — 전체 조회가 되는지
    print("=== 1단계: 날짜만 ===")
    for date in dates[:6]:
        p = dict(base, **{DATE_PARAM: date})
        t = try_call(p, f"{date} (식별자 없음)")
        if t:
            save(t, p)
            return 0

    # 2단계: 날짜 × goodId
    print("\n=== 2단계: 날짜 x goodId ===")
    for date in dates[:4]:
        for gid in GOOD_IDS:
            p = dict(base, **{DATE_PARAM: date, "goodId": gid})
            t = try_call(p, f"{date} goodId={gid}")
            if t:
                save(t, p)
                return 0

    # 3단계: 날짜 × entpId
    print("\n=== 3단계: 날짜 x entpId ===")
    for date in dates[:4]:
        for eid in ENTP_IDS:
            p = dict(base, **{DATE_PARAM: date, "entpId": eid})
            t = try_call(p, f"{date} entpId={eid}")
            if t:
                save(t, p)
                return 0

    print("\n데이터 있는 조합 없음.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
