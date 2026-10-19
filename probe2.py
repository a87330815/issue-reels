# -*- coding: utf-8 -*-
"""
probe2.py — 가격 조회 파라미터 탐색기

getProductPriceInfoSvc가 "올바른 조사일자가 아닙니다"를 돌려준다.
조사일자 파라미터의 이름과 형식을 모르므로, 후보 조합을 순서대로 시도해
성공하는 조합을 찾아 출력한다. 성공하면 즉시 멈춘다.
"""
import os
import datetime as dt
import xml.dom.minidom as minidom

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))

# .env에서 인증키 로딩
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

# 조사일자 파라미터 이름 후보
DATE_PARAMS = [
    "goodInspectDay", "examinDate", "iDate", "inspectDay",
    "examinDe", "surveyDate", "goodInspectDate", "stdDay",
]

# 보조 식별자 (문서상 업체아이디/상품아이디 중 하나 필수)
IDS = [
    {"entpId": "10"},
]


def recent_dates(weeks=8):
    """참가격은 주간 조사다. 최근 몇 주의 목·금요일만 훑어 요청 수를 아낀다."""
    today = dt.date.today()
    out = []
    for back in range(0, weeks * 7):
        d = today - dt.timedelta(days=back)
        if d.weekday() in (3, 4):   # 목, 금
            out.append(d.strftime("%Y%m%d"))
    return out


def redact(text):
    return text.replace(KEY, "***REDACTED***") if KEY else text


def pretty(text):
    try:
        return minidom.parseString(text).toprettyxml(indent="  ")[:6000]
    except Exception:
        return text[:6000]


def result_msg(text):
    try:
        doc = minidom.parseString(text)
        nodes = doc.getElementsByTagName("resultMsg")
        if nodes and nodes[0].firstChild:
            return nodes[0].firstChild.nodeValue
    except Exception:
        pass
    return ""


def main():
    if not KEY:
        print("DATA_GO_KR_KEY 없음")
        return 1
    os.makedirs(OUT, exist_ok=True)

    dates = recent_dates()
    tried = 0
    seen_msgs = {}

    print("조사일자 파라미터 탐색 시작...\n")

    for dparam in DATE_PARAMS:
        for ids in IDS:
            # 각 파라미터명마다 최근 날짜를 훑는다
            for date in dates:
                p = {"serviceKey": KEY, "numOfRows": 10, "pageNo": 1, dparam: date}
                p.update(ids)
                tried += 1
                try:
                    r = requests.get(URL, params=p, timeout=15)
                except Exception as e:
                    print(f"  요청 실패: {type(e).__name__}")
                    continue

                msg = result_msg(r.text)

                # 성공 판정: item이 들어있으면 성공
                if "<item>" in r.text:
                    print(f"\n*** 성공 ***")
                    print(f"  날짜 파라미터 : {dparam}")
                    print(f"  조사일자      : {date}")
                    print(f"  식별자        : {ids}")
                    print(f"  시도 횟수     : {tried}")
                    path = os.path.join(OUT, "price_success.xml")
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(redact(pretty(r.text)))
                    with open(os.path.join(OUT, "price_params.txt"), "w", encoding="utf-8") as f:
                        f.write(f"date_param={dparam}\ndate={date}\nids={ids}\n")
                    print(f"  저장          : {path}")
                    return 0

                # 메시지가 바뀌면 파라미터명은 맞고 값이 문제라는 신호
                if msg and msg not in seen_msgs:
                    seen_msgs[msg] = (dparam, date, dict(ids))
                    print(f"  [{dparam}] {date} {ids} -> {msg}")

                # "조사일자" 에러가 아니면 파라미터명이 먹힌 것 — 날짜만 더 훑는다
                if msg and "조사일자" not in msg:
                    break

    print(f"\n성공 조합 없음. 총 {tried}회 시도.")
    print("\n관찰된 응답 메시지:")
    for msg, ctx in seen_msgs.items():
        print(f"  {msg}   <- {ctx}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
