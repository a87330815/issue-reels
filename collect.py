# -*- coding: utf-8 -*-
"""
collect.py — 공공데이터 API 수집기

sources.yml에 정의된 소스에서 데이터를 수집한다.
게이트 3종: (1) 라이선스 (2) 언론사 표현 필터 (3) 중복 제거

사용법:
  python collect.py                     # 전체 소스 수집
  python collect.py --source price      # 특정 소스만
  python collect.py --check             # 소스 상태 확인만
"""
import argparse, hashlib, json, os, re, sys, time
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

import requests
import yaml
import xml.etree.ElementTree as ET
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).parent
OUT = ROOT / "out"

# ── .env 로드 ────────────────────────────────────────────────────────
_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# ── HTTP 세션 ─────────────────────────────────────────────────────────
sess = requests.Session()
retry = Retry(total=2, backoff_factor=2, status_forcelist=[500, 502, 503])
sess.mount("https://", HTTPAdapter(max_retries=retry))

# ── 게이트 1: 라이선스 ───────────────────────────────────────────────
ALLOWED_LICENSES = {"1", "open"}

def check_license(src: dict) -> bool:
    """공공누리 제1유형 또는 이용허락범위 제한 없음만 허용."""
    lic = str(src.get("license", "unknown"))
    return lic in ALLOWED_LICENSES

# ── 게이트 2: 언론사 표현 필터 ────────────────────────────────────────
MEDIA_PATTERNS = re.compile(
    r"(기자\s*[=:]|특파원|©|ⓒ|무단\s*전재|재배포\s*금지|저작권자)", re.I
)

def has_media_expression(text: str) -> bool:
    return bool(MEDIA_PATTERNS.search(text))

# ── 게이트 3: 중복 제거 ──────────────────────────────────────────────
def item_key(source_id: str, item: dict) -> str:
    """소스+핵심필드 해시로 중복 판별."""
    vals = "|".join(str(item.get(k, "")) for k in sorted(item.keys())[:5])
    raw = f"{source_id}|{vals}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


# ── 수집기 ────────────────────────────────────────────────────────────

def load_sources() -> dict:
    p = ROOT / "sources.yml"
    if not p.exists():
        print(f"[오류] sources.yml 없음: {p}")
        sys.exit(1)
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def collect_price(src: dict, api_key: str) -> list:
    """참가격 — 생필품 가격 정보 수집."""
    base = src["base_url"]
    ep = src["endpoint"]
    goods = src.get("goods", [])
    tag = src.get("xml_item_tag", "item")
    fmap = src.get("field_map", {})

    # 최근 14일 중 조사일 탐색
    today = date.today()
    items = []

    for g in goods:
        gid = g["id"]
        gname = g["name"]
        found = False

        for delta in range(0, 14):
            d = today - timedelta(days=delta)
            ds = d.strftime("%Y%m%d")
            params = {
                "serviceKey": api_key,
                "numOfRows": src["params"].get("numOfRows", 100),
                "pageNo": 1,
                "goodId": gid,
                "goodInspectDay": ds,
            }
            try:
                r = sess.get(f"{base}/{ep}", params=params, timeout=20)
            except Exception as e:
                print(f"  [경고] {gname}: {e}")
                continue

            text = r.text
            if f"<{tag}>" not in text and "<item>" not in text:
                continue  # 이 날짜에 데이터 없음

            # goodPriceVO → item 치환 후 파싱
            text = text.replace(tag, "item")
            try:
                root = ET.fromstring(text)
            except ET.ParseError:
                continue

            xml_items = root.findall(".//item")
            if not xml_items:
                continue

            found = True
            for xi in xml_items:
                row = {"source": "price_daily_necessities", "category": src["category"],
                       "attribution": src["attribution"]}
                for xml_tag, field in fmap.items():
                    val = xi.findtext(xml_tag)
                    if val:
                        row[field] = val.strip()
                # 필수 필드 체크
                if row.get("product_name") and row.get("price"):
                    items.append(row)

            print(f"  {gname}: 조사일 {ds}, {len(xml_items)}건")
            break  # 가장 최근 조사일 데이터만

        if not found:
            print(f"  {gname}: 최근 14일 데이터 없음")
        time.sleep(0.3)

    return items


def collect_molit(src: dict, api_key: str) -> list:
    """국토교통부 아파트 실거래가."""
    base = src["base_url"]
    ep = src["endpoint"]
    fmap = src.get("field_map", {})
    regions = src.get("regions", [])

    today = date.today()
    deal_ymd = today.strftime("%Y%m")
    items = []

    for reg in regions:
        params = {
            "serviceKey": api_key,
            "numOfRows": src["params"].get("numOfRows", 100),
            "pageNo": 1,
            "LAWD_CD": reg["code"],
            "DEAL_YMD": deal_ymd,
        }
        try:
            r = sess.get(f"{base}/{ep}", params=params, timeout=20)
            root = ET.fromstring(r.content)
        except Exception as e:
            print(f"  [경고] {reg['name']}: {e}")
            continue

        xml_items = root.findall(".//item")
        for xi in xml_items:
            row = {"source": "molit_apt_trade", "category": src["category"],
                   "attribution": src["attribution"],
                   "q_LAWD_CD": reg["code"], "q_DEAL_YMD": deal_ymd}
            for xml_tag, field in fmap.items():
                val = xi.findtext(xml_tag)
                if val:
                    row[field] = val.strip()
            if row.get("apt") and row.get("amount"):
                items.append(row)

        print(f"  {reg['name']}: {len(xml_items)}건")
        time.sleep(0.5)

    return items


def collect_kma(src: dict, api_key: str) -> list:
    """기상청 단기예보."""
    base = src["base_url"]
    ep = src["endpoint"]
    fmap = src.get("field_map", {})
    stations = src.get("stations", [])

    today = date.today()
    # 단기예보 base_date/base_time — 가장 최근 발표시각 사용
    base_date = today.strftime("%Y%m%d")
    base_time = "0500"  # 05시 발표

    items = []
    for st in stations:
        params = {
            "serviceKey": api_key,
            "numOfRows": src["params"].get("numOfRows", 1000),
            "pageNo": 1,
            "dataType": "JSON",
            "base_date": base_date,
            "base_time": base_time,
            "nx": st["nx"],
            "ny": st["ny"],
        }
        try:
            r = sess.get(f"{base}/{ep}", params=params, timeout=20)
            data = r.json()
        except Exception as e:
            print(f"  [경고] {st['name']}: {e}")
            continue

        body = data.get("response", {}).get("body", {})
        json_items = body.get("items", {}).get("item", [])
        count = 0
        for ji in json_items:
            row = {"source": "kma_forecast", "category": src["category"],
                   "attribution": src["attribution"], "station": st["name"]}
            for api_field, field in fmap.items():
                val = ji.get(api_field)
                if val is not None:
                    row[field] = str(val)
            # TMP(기온), POP(강수확률), SKY(하늘상태)만 관심
            cat = ji.get("category", "")
            if cat in ("TMP", "POP", "SKY", "TMN", "TMX", "PTY"):
                items.append(row)
                count += 1

        print(f"  {st['name']}: {count}건 (필터링)")
        time.sleep(0.3)

    return items


COLLECTORS = {
    "price_daily_necessities": collect_price,
    "molit_apt_trade": collect_molit,
    "kma_forecast": collect_kma,
}


def main():
    ap = argparse.ArgumentParser(description="공공데이터 API 수집기")
    ap.add_argument("--source", help="특정 소스만 수집 (키 부분매칭)")
    ap.add_argument("--check", action="store_true", help="소스 상태 확인만")
    args = ap.parse_args()

    sources = load_sources()

    if args.check:
        print("=== 소스 상태 ===")
        for sid, src in sources.items():
            lic = src.get("license", "unknown")
            key_env = src.get("key_env", "")
            has_key = "✓" if os.environ.get(key_env) else "✗"
            gate = "허용" if check_license(src) else "폐기"
            collector = "✓" if sid in COLLECTORS else "미구현"
            print(f"  {sid}: 라이선스={lic}({gate}) 키={key_env}({has_key}) 수집기={collector}")
        return 0

    # 이전 수집 결과에서 중복키 로드
    seen_file = OUT / "seen.json"
    seen = set()
    if seen_file.exists():
        try:
            seen = set(json.loads(seen_file.read_text()))
        except Exception:
            pass

    all_items = []
    OUT.mkdir(exist_ok=True)

    for sid, src in sources.items():
        # 소스 필터
        if args.source and args.source not in sid:
            continue

        print(f"\n=== {src['name']} ({sid}) ===")

        # 게이트 1: 라이선스
        if not check_license(src):
            print(f"  ✗ 라이선스 폐기 (license={src.get('license')})")
            continue

        # API 키 확인
        key_env = src.get("key_env", "")
        api_key = os.environ.get(key_env, "")
        if not api_key:
            print(f"  ✗ API 키 없음 ({key_env})")
            continue

        # 수집기 확인
        collector = COLLECTORS.get(sid)
        if not collector:
            print(f"  ✗ 수집기 미구현")
            continue

        try:
            items = collector(src, api_key)
        except Exception as e:
            print(f"  [오류] {e}")
            continue

        # 게이트 2: 언론사 표현 필터
        clean = []
        filtered = 0
        for item in items:
            text = " ".join(str(v) for v in item.values())
            if has_media_expression(text):
                filtered += 1
                continue
            clean.append(item)

        if filtered:
            print(f"  언론사 표현 필터: {filtered}건 폐기")

        # 게이트 3: 중복 제거
        unique = []
        for item in clean:
            k = item_key(sid, item)
            if k not in seen:
                seen.add(k)
                item["key"] = k
                unique.append(item)

        dupes = len(clean) - len(unique)
        if dupes:
            print(f"  중복 제거: {dupes}건")

        print(f"  → {len(unique)}건 수집")
        all_items.extend(unique)

    # 결과 저장
    result = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "items": all_items,
    }
    out_path = OUT / "collected.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    seen_file.write_text(json.dumps(list(seen)), encoding="utf-8")

    print(f"\n총 {len(all_items)}건 → {out_path}")
    return 0 if all_items else 1


if __name__ == "__main__":
    raise SystemExit(main())
