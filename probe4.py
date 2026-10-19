# -*- coding: utf-8 -*-
"""
probe4.py — 국토교통부 아파트 매매 실거래가 응답 샘플

참가격과 달리 이쪽은 요청 파라미터가 명확하다.
  LAWD_CD  : 지역코드 5자리 (법정동코드 앞 5자리)
  DEAL_YMD : 계약월 YYYYMM
김해(48250)와 서울 강남(11680)을 최근 몇 달치 받아 구조를 확인한다.
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
URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
OUT = os.path.join(ROOT, "probe_out")

REGIONS = [
    ("48250", "경남 김해시"),
    ("11680", "서울 강남구"),
]


def recent_months(n=3):
    today = dt.date.today().replace(day=1)
    out = []
    for i in range(n):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        out.append(f"{y}{m:02d}")
    return out


def redact(text):
    return text.replace(KEY, "***REDACTED***") if KEY else text


def pretty(text):
    try:
        return minidom.parseString(text).toprettyxml(indent="  ")[:12000]
    except Exception:
        return text[:12000]


def main():
    if not KEY:
        print("DATA_GO_KR_KEY 없음")
        return 1
    os.makedirs(OUT, exist_ok=True)

    found = False
    for code, label in REGIONS:
        for ym in recent_months():
            p = {"serviceKey": KEY, "LAWD_CD": code, "DEAL_YMD": ym,
                 "numOfRows": 30, "pageNo": 1}
            print(f"\n===== {label} {ym} =====")
            try:
                r = requests.get(URL, params=p, timeout=20)
            except Exception as e:
                print(f"  요청실패 {type(e).__name__}")
                continue

            n = r.text.count("<item>")
            print(f"  HTTP {r.status_code}  item {n}건")

            fname = f"apt_{code}_{ym}.xml"
            with open(os.path.join(OUT, fname), "w", encoding="utf-8") as f:
                f.write(redact(pretty(r.text)))
            print(f"  저장 {fname}")

            if n > 0 and not found:
                found = True
                with open(os.path.join(OUT, "apt_success.txt"), "w", encoding="utf-8") as f:
                    f.write(f"LAWD_CD={code}\nDEAL_YMD={ym}\nitems={n}\n")

    print("\n완료." if found else "\n데이터 없음.")
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
