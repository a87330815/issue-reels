# -*- coding: utf-8 -*-
"""
probe4.py — 참가격 API 전체 오퍼레이션 탐색

이전 probe에서 확인된 것:
- getProductPriceInfoSvc: goodInspectDay(금요일) 필수, entpId|goodId 중 하나 필수
- getStandardInfoSvc.do: classCode 필수 → 값을 모름
- getStoreInfoSvc.do: ok 리턴하지만 item 없음

이번에 시도할 것:
1. getProductInfoSvc.do — 상품 목록 조회 (goodId, goodName 등)
2. getStandardInfoSvc.do — classCode를 여러 값으로 시도
3. getStoreInfoSvc.do — 파라미터 변형 시도
4. 성공한 goodId로 getProductPriceInfoSvc 재시도
"""
import os
import sys
import datetime as dt
import xml.dom.minidom as minidom
import json

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
OUT = os.path.join(ROOT, "probe_out")


def redact(text):
    return text.replace(KEY, "***REDACTED***") if KEY else text


def pretty(text):
    try:
        return minidom.parseString(text).toprettyxml(indent="  ")
    except Exception:
        return text


def extract_items(text):
    """XML에서 <item> 요소들의 자식 태그:값을 딕셔너리 리스트로 추출"""
    try:
        doc = minidom.parseString(text)
    except Exception:
        return []
    items = []
    for item in doc.getElementsByTagName("item"):
        d = {}
        for child in item.childNodes:
            if child.nodeType == child.ELEMENT_NODE and child.firstChild:
                d[child.tagName] = child.firstChild.nodeValue
        items.append(d)
    return items


def result_info(text):
    try:
        doc = minidom.parseString(text)
        msg_nodes = doc.getElementsByTagName("resultMsg")
        code_nodes = doc.getElementsByTagName("resultCode")
        total_nodes = doc.getElementsByTagName("totalCount")
        msg = msg_nodes[0].firstChild.nodeValue if msg_nodes and msg_nodes[0].firstChild else ""
        code = code_nodes[0].firstChild.nodeValue if code_nodes and code_nodes[0].firstChild else ""
        total = total_nodes[0].firstChild.nodeValue if total_nodes and total_nodes[0].firstChild else ""
        return code, msg, total
    except Exception:
        return "", "", ""


def call_api(operation, params, label):
    url = f"{BASE}/{operation}"
    p = {"serviceKey": KEY, "numOfRows": 100, "pageNo": 1}
    p.update(params)
    try:
        r = requests.get(url, params=p, timeout=15)
    except Exception as e:
        print(f"  {label} -> 요청실패 {type(e).__name__}")
        return None, ""
    code, msg, total = result_info(r.text)
    items = extract_items(r.text)
    has_data = len(items) > 0
    print(f"  {label} -> code={code} msg={msg} total={total} items={len(items)}")
    if items:
        # 첫 아이템의 키 목록
        print(f"    필드: {list(items[0].keys())}")
        # 첫 3개 출력
        for i, item in enumerate(items[:3]):
            print(f"    [{i}] {item}")
    return items, r.text


def recent_fridays(n=6):
    d = dt.date.today()
    d -= dt.timedelta(days=(d.weekday() - 4) % 7)
    return [(d - dt.timedelta(weeks=i)).strftime("%Y%m%d") for i in range(n)]


def save_result(name, text, items):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f"{name}.xml"), "w", encoding="utf-8") as f:
        f.write(redact(pretty(text)))
    if items:
        with open(os.path.join(OUT, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
    print(f"  -> 저장: {name}")


def main():
    if not KEY:
        print("DATA_GO_KR_KEY 없음")
        return 1
    os.makedirs(OUT, exist_ok=True)

    # ============================================================
    # 1. getProductInfoSvc.do — 상품 목록
    # ============================================================
    print("=" * 60)
    print("1. getProductInfoSvc.do (상품정보 조회)")
    print("=" * 60)

    # 파라미터 없이
    items, text = call_api("getProductInfoSvc.do", {}, "파라미터 없음")
    if items:
        save_result("product_info_noparams", text, items)

    # classCode 시도 (혹시 이것도 classCode가 필요한지)
    for cc in ["01", "02", "03", "1", "2", "3", "10", "100", "001", "생필품"]:
        items, text = call_api("getProductInfoSvc.do", {"classCode": cc}, f"classCode={cc}")
        if items:
            save_result(f"product_info_cc{cc}", text, items)
            break

    # goodId 하나 넣어보기
    items, text = call_api("getProductInfoSvc.do", {"goodId": "35"}, "goodId=35")
    if items:
        save_result("product_info_gid35", text, items)

    # ============================================================
    # 2. getStandardInfoSvc.do — 기준 정보 (classCode 탐색)
    # ============================================================
    print("\n" + "=" * 60)
    print("2. getStandardInfoSvc.do (기준정보 조회)")
    print("=" * 60)

    for cc in ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10",
               "1", "2", "3", "4", "5",
               "100", "200", "300",
               "001", "002", "003",
               "A", "B", "C"]:
        items, text = call_api("getStandardInfoSvc.do", {"classCode": cc}, f"classCode={cc}")
        if items:
            save_result(f"standard_info_cc{cc}", text, items)
            break  # 하나 찾으면 멈춤

    # ============================================================
    # 3. getStoreInfoSvc.do — 판매점 정보
    # ============================================================
    print("\n" + "=" * 60)
    print("3. getStoreInfoSvc.do (판매점 정보)")
    print("=" * 60)

    # 파라미터 없이 (이전에 ok + 0건)
    items, text = call_api("getStoreInfoSvc.do", {}, "파라미터 없음")
    if items:
        save_result("store_info_noparams", text, items)

    # goodId로
    items, text = call_api("getStoreInfoSvc.do", {"goodId": "35"}, "goodId=35")
    if items:
        save_result("store_info_gid35", text, items)

    # entpId로
    for eid in ["786", "10", "1", "100"]:
        items, text = call_api("getStoreInfoSvc.do", {"entpId": eid}, f"entpId={eid}")
        if items:
            save_result(f"store_info_eid{eid}", text, items)
            break

    # ============================================================
    # 4. .do 없는 버전도 시도
    # ============================================================
    print("\n" + "=" * 60)
    print("4. getProductInfoSvc (.do 없이)")
    print("=" * 60)
    items, text = call_api("getProductInfoSvc", {}, "파라미터 없음")
    if items:
        save_result("product_info_nodo", text, items)

    # ============================================================
    # 5. 가격 조회: 날짜만 (entpId/goodId 없이) 대량
    # ============================================================
    print("\n" + "=" * 60)
    print("5. getProductPriceInfoSvc — 날짜만 (식별자 없이)")
    print("=" * 60)
    fridays = recent_fridays(10)
    for date in fridays:
        items, text = call_api("getProductPriceInfoSvc", {"goodInspectDay": date}, f"날짜={date}")
        if items:
            save_result(f"price_dateonly_{date}", text, items)
            break

    print("\n완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
