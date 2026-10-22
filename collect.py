# -*- coding: utf-8 -*-
"""
collect.py — 공공 API 수집기

게이트 3종 (프로젝트 기준):
  1. 공공누리 1유형이 아니면 폐기
  2. 인증키가 없으면 건너뜀
  3. status: dead 소스는 차단

추가로 언론사 표현 필터와 seen.json 중복제거를 거친다.

사용:
  python collect.py --verify          # 소스 상태만 점검
  python collect.py                   # 수집 실행 → out/collected.json
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_env():
    """같은 폴더의 .env에서 인증키를 읽는다. PC 실행용. 이미 환경변수가 있으면 그대로 둔다."""
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


load_env()

SOURCES = os.path.join(ROOT, "sources.yml")
OUT_DIR = os.path.join(ROOT, "out")
SEEN = os.path.join(OUT_DIR, "seen.json")

# 게이트 1 — 공공누리 제1유형, 또는 "이용허락범위 제한 없음"만 통과.
# 제한 없음은 1유형보다 넓으므로 상업적 이용·변형 모두 가능.
# 2유형(상업적 이용 불가)·3유형(변형 불가)·미확인(unknown)은 폐기.
ALLOWED_LICENSE = {"1", "1유형", "kogl-1", "type1", "none", "제한없음"}

# 언론사 표현 필터 — 기사 문장이 섞여 들어오는 것을 막는다
PRESS_PATTERNS = [
    r"무단\s*전재", r"재배포\s*금지",
    # 한글은 \b가 먹지 않으므로 경계 없이 매칭한다
    r"저작권자\s*[\(（]?\s*[cCⓒ©]\s*[\)）]?",
    r"[가-힣]{2,4}\s*기자",
    r"(연합뉴스|뉴시스|뉴스1|조선일보|중앙일보|동아일보|한겨레|경향신문|매일경제|한국경제)",
    r"\b(YTN|KBS|MBC|SBS|JTBC)\b",
]
PRESS_RE = re.compile("|".join(PRESS_PATTERNS))


def load_sources():
    with open(SOURCES, encoding="utf-8") as f:
        return yaml.safe_load(f)["sources"]


def load_seen():
    if os.path.exists(SEEN):
        with open(SEEN, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(SEEN, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=1)


def item_key(item):
    """중복 판정용 키. 소스마다 필드가 다르므로 값 전체를 정렬해 해시한다."""
    parts = [f"{k}={item[k]}" for k in sorted(item) if k not in ("key", "attribution")]
    base = "|".join(parts)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def has_press_expression(text):
    return bool(PRESS_RE.search(text or ""))


def gate(src):
    """소스 하나를 검사해 (통과여부, 사유)를 돌려준다."""
    if src.get("status") == "dead":
        return False, f"차단(dead): {src.get('reason','폐쇄')}"
    lic = str(src.get("license", "unknown")).lower()
    if lic not in ALLOWED_LICENSE:
        return False, f"폐기(공공누리 미확인/비1유형): license={src.get('license')}"
    env = src.get("key_env")
    if env and not os.environ.get(env):
        return False, f"건너뜀(인증키 없음): {env}"
    return True, "통과"


def expand_params(src):
    """소스의 params를 실제 요청 파라미터 조합으로 펼친다.

    리스트 값은 조합으로 펼쳐지고, {last_month}·{this_month}는 실행 시점 기준으로
    치환된다. 국토부 실거래가처럼 지역·월을 돌면서 여러 번 불러야 하는 API를 위한 것.
    """
    import itertools

    raw = src.get("params") or {}
    if not raw:
        return [{}]

    now = datetime.now()
    lm_y, lm_m = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    subs = {
        "{this_month}": f"{now.year}{now.month:02d}",
        "{last_month}": f"{lm_y}{lm_m:02d}",
    }

    keys, choices = [], []
    for k, v in raw.items():
        vals = v if isinstance(v, list) else [v]
        vals = [subs.get(str(x), x) for x in vals]
        keys.append(k)
        choices.append([str(x) for x in vals])

    return [dict(zip(keys, combo)) for combo in itertools.product(*choices)]


def parse_xml_items(text, fm):
    """XML 응답에서 item들을 뽑아 field_map대로 평평한 dict 리스트로 만든다.

    응답이 잘려 있어도 온전한 <item> 블록만 건지도록 정규식으로 읽는다.
    (공공 API 응답이 길면 중간에서 끊겨 오는 경우가 있다.)
    """
    fields = fm.get("fields") or {}
    out = []
    for blk in re.findall(r"<item>(.*?)</item>", text, re.S):
        pairs = dict(re.findall(r"<(\w+)>\s*([^<]*?)\s*</\1>", blk))
        row = {name: pairs.get(tag, "") for name, tag in fields.items()}
        if any(row.values()):
            out.append(row)
    return out


def api_error(text):
    """응답이 에러면 그 메시지를, 정상이면 None을 돌려준다."""
    if "<item>" in text:
        return None
    m = re.search(r"<resultMsg>\s*([^<]*?)\s*</resultMsg>", text)
    if m and m.group(1).upper() not in ("OK", "NORMAL SERVICE.", "NORMAL_SERVICE"):
        return m.group(1)
    m = re.search(r"<returnAuthMsg>\s*([^<]*?)\s*</returnAuthMsg>", text)
    return m.group(1) if m else None


def fetch(src):
    """소스 하나를 실제로 호출한다. field_map이 비어 있으면 아직 매핑 전이라 건너뛴다."""
    fm = src.get("field_map")
    if not fm:
        return []
    import requests  # 게이트를 통과한 소스에서만 필요

    key = os.environ[src["key_env"]]
    items, errors = [], []

    for extra in expand_params(src):
        params = {"serviceKey": key, "numOfRows": src.get("rows", 100), "pageNo": 1}
        params.update(extra)

        # 해외 IP 차단이 간헐적이라 같은 호출이 한 번은 막히고 한 번은 뚫린다.
        # 한 번 실패로 포기하면 수집 전체가 빈손이 되므로 간격을 두고 재시도한다.
        r, last = None, None
        for attempt in range(3):
            try:
                r = requests.get(src["endpoint"], params=params, timeout=25)
                r.raise_for_status()
                break
            except Exception as e:
                # 예외 메시지에 URL이 실리고 URL에는 인증키가 들어 있다. 반드시 지운다.
                last = f"{type(e).__name__}: {str(e).replace(key, '***')}"
                r = None
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))
        if r is None:
            errors.append(f"{extra}: {last}")
            continue

        err = api_error(r.text)
        if err:
            errors.append(f"{extra}: {err}")
            continue

        rows = parse_xml_items(r.text, fm)
        for row in rows:
            row["source"] = src["id"]
            row["category"] = src.get("category", "")
            row["attribution"] = src.get("attribution", "")
            row.update({f"q_{k}": v for k, v in extra.items()})
        items.extend(rows)

    if errors:
        print(f"      경고: {len(errors)}건 실패")
        for e in errors[:3]:
            print(f"        {e}")

    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="소스 상태만 점검하고 끝낸다")
    args = ap.parse_args()

    srcs = load_sources()
    passed, report = [], []
    for s in srcs:
        ok, why = gate(s)
        report.append((s["id"], ok, why))
        if ok:
            passed.append(s)

    width = max(len(r[0]) for r in report)
    for sid, ok, why in report:
        print(f"  {'OK ' if ok else '-- '} {sid:<{width}}  {why}")

    if args.verify:
        print(f"\n통과 {len(passed)} / 전체 {len(srcs)}")
        return 0

    seen = load_seen()
    collected, dropped = [], 0
    for s in passed:
        for item in fetch(s):
            blob = " ".join(str(v) for v in item.values() if isinstance(v, str))
            if has_press_expression(blob):
                dropped += 1
                continue
            k = item_key(item)
            if k in seen:
                continue
            seen.add(k)
            item["key"] = k
            collected.append(item)

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "collected.json")

    # 한국 공공 API는 해외 IP를 간헐적으로 막는다. 러너 IP 대역에 따라
    # 전부 타임아웃이 나는 날이 있고, 그때 빈 결과로 덮어쓰면 멀쩡히 받아둔
    # 수집물이 날아간다. 실제로 685건이 0건으로 지워졌다.
    # 수집이 0건이면 기존 파일을 건드리지 않는다.
    if not collected and os.path.exists(out):
        try:
            with open(out, encoding="utf-8") as f:
                prev = json.load(f).get("items", [])
        except Exception:
            prev = []
        if prev:
            print(f"\n수집 0건 — 기존 {len(prev)}건을 유지합니다 "
                  f"(API 접속 실패로 보입니다. 덮어쓰지 않습니다)")
            return 0

    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "items": collected,
        }, f, ensure_ascii=False, indent=2)
    save_seen(seen)

    print(f"\n수집 {len(collected)}건 · 언론사표현 폐기 {dropped}건 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
