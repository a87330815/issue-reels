# -*- coding: utf-8 -*-
"""
bg.py — 커버·장면 배경 생성기

보도사진·방송캡처를 쓸 수 없으므로(저작권 경계선) 배경을 직접 만든다.
프로젝트 기준의 "직접 만든 이미지·그래픽" 안전영역에 해당한다.

구성:
  1. 카테고리별 색 테마로 깊은 그라데이션
  2. 부드러운 덩어리로 명암 (사진 같은 깊이)
  3. 데이터 레이어 — 수치가 있으면 막대/선으로 그린다. 장식이 아니라 내용이다
  4. 그레인 + 비네팅

같은 대본은 항상 같은 배경이 나온다(제목으로 시드 고정). 재실행해도 결과가 흔들리지 않는다.

사용:
  python render/bg.py --demo          # 카테고리별 샘플을 out/bg_demo/에 렌더
"""
import hashlib
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 1080, 1920

# 텍스트는 하단에 온다(150pt 3~4줄이면 상단이 대략 y=830).
# 데이터 레이어가 글씨와 겹치면 스크림에 눌려 얼룩처럼 보이므로 그 위에서 끝낸다.
DATA_TOP, DATA_BOTTOM = 430, 790

# 카테고리별 색 — (상단, 하단, 포인트)
# 어둡게 깔고 흰 글씨 대비를 확보한다.
# 커버 문법이 빨강(<r>)·노랑(<y>)을 강조색으로 쓴다.
# 배경이 같은 계열이면 강조가 묻히므로, 따뜻한 계열은 충분히 어둡게 깐다.
THEMES = {
    "주거": ((38, 56, 96), (10, 14, 28), (96, 152, 255)),
    "돈·물가": ((64, 44, 18), (14, 10, 6), (255, 176, 58)),
    "물가": ((64, 44, 18), (14, 10, 6), (255, 176, 58)),
    "안전": ((58, 20, 24), (12, 5, 7), (255, 92, 92)),
    "건강": ((58, 20, 24), (12, 5, 7), (255, 92, 92)),
    "교통": ((22, 74, 76), (8, 20, 22), (64, 212, 208)),
    "통계": ((60, 40, 92), (16, 10, 26), (178, 128, 255)),
}
DEFAULT_THEME = ((44, 50, 62), (12, 14, 18), (150, 170, 200))


def theme_for(category):
    for key, val in THEMES.items():
        if category and key in category:
            return val
    return DEFAULT_THEME


def seed_of(text):
    return int(hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:8], 16)


def _gradient(top, bottom):
    yy = np.linspace(0, 1, H)[:, None]
    # 감마를 줘서 아래쪽이 더 빨리 어두워지게 — 하단 텍스트 가독성
    curve = yy ** 0.75
    base = np.zeros((H, W, 3), np.float64)
    for c in range(3):
        base[:, :, c] = top[c] * (1 - curve) + bottom[c] * curve
    return base


def _blobs(base, rng, accent, count=6):
    X, Y = np.meshgrid(np.arange(W), np.arange(H))
    for _ in range(count):
        cx = rng.uniform(-100, W + 100)
        cy = rng.uniform(-100, H * 0.75)
        r = rng.uniform(260, 720)
        amp = rng.uniform(-30, 52)
        g = np.exp(-(((X - cx) ** 2 + (Y - cy) ** 2) / (2 * r ** 2)))
        tint = np.array(accent) / 255.0 if amp > 0 else np.ones(3)
        base += (g * amp)[:, :, None] * tint
    return base


def _finish(base, rng):
    base += rng.normal(0, 4.5, (H, W, 3))          # 그레인
    X, Y = np.meshgrid(np.linspace(-1, 1, W), np.linspace(-1, 1, H))
    base *= (1 - 0.34 * np.clip(X ** 2 + Y ** 2, 0, 1))[:, :, None]   # 비네팅
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    return img.filter(ImageFilter.GaussianBlur(1.0))


def _draw_bars(img, values, labels, accent):
    """막대 그래프. 수치 비교가 한눈에 들어오게 한다."""
    if not values:
        return img
    d = ImageDraw.Draw(img, "RGBA")

    n = min(len(values), 5)
    values, labels = values[:n], (labels or [""] * n)[:n]
    hi = max(values) or 1

    pad = 120
    gap = 26
    bw = (W - pad * 2 - gap * (n - 1)) / n
    floor = DATA_BOTTOM

    for i, v in enumerate(values):
        x0 = pad + i * (bw + gap)
        bh = max(14, (DATA_BOTTOM - DATA_TOP) * (v / hi))
        y0 = floor - bh
        # 막대 — 위는 포인트색, 아래로 갈수록 투명
        for step in range(int(bh)):
            t = step / max(1, bh)
            a = int(225 * (1 - t * 0.75))
            d.rectangle([x0, y0 + step, x0 + bw, y0 + step + 1],
                        fill=(*accent, a))
        # 최고값만 밝게 강조
        if v == hi:
            d.rectangle([x0, y0 - 6, x0 + bw, y0 - 2], fill=(255, 255, 255, 230))
    return img


def _draw_line(img, values, accent):
    """꺾은선. 추세를 보여줄 때 쓴다."""
    if len(values) < 2:
        return img
    d = ImageDraw.Draw(img, "RGBA")
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    pad = 110
    pts = []
    for i, v in enumerate(values):
        x = pad + (W - pad * 2) * i / (len(values) - 1)
        y = DATA_BOTTOM - (DATA_BOTTOM - DATA_TOP) * ((v - lo) / span)
        pts.append((x, y))

    # 아래 면적을 옅게 채워 깊이를 준다
    d.polygon(pts + [(pts[-1][0], DATA_BOTTOM), (pts[0][0], DATA_BOTTOM)],
              fill=(*accent, 46))
    d.line(pts, fill=(*accent, 255), width=7, joint="curve")
    for x, y in pts:
        d.ellipse([x - 9, y - 9, x + 9, y + 9], fill=(255, 255, 255, 235))
    return img


def _draw_grid(img, accent, rng):
    """데이터가 없을 때의 기하 패턴. 비어 보이지 않게만 한다."""
    d = ImageDraw.Draw(img, "RGBA")
    step = 132
    for i in range(0, W + H, step):
        d.line([(i, 0), (i - H, H)], fill=(*accent, 20), width=2)
    cx, cy = rng.uniform(W * 0.25, W * 0.75), rng.uniform(620, 1020)
    for r in range(220, 620, 96):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(*accent, 26), width=3)
    return img


def make(title="", category="", values=None, labels=None, style="auto"):
    """배경 1장을 만든다.

    values 가 있으면 데이터 레이어를 그리고, 없으면 기하 패턴으로 간다.
    style: auto | bars | line | plain
    """
    top, bottom, accent = theme_for(category)
    rng = np.random.default_rng(seed_of(title + category))

    base = _gradient(top, bottom)
    base = _blobs(base, rng, accent)
    img = _finish(base, rng)

    vals = [float(v) for v in (values or []) if v is not None]
    if style == "plain" or (style == "auto" and not vals):
        return _draw_grid(img, accent, rng)
    if style == "line":
        return _draw_line(img, vals, accent)
    # auto는 막대. 순위 데이터를 꺾은선으로 그리면 하락 추세로 잘못 읽힌다
    return _draw_bars(img, vals, labels, accent)


def make_for_script(script, scene_index=None):
    """대본에서 배경을 만든다. 커버는 scene_index=None.

    장면 배경은 커버와 같은 계열이되 시드를 달리해 단조로움을 피한다.
    """
    meta = script.get("meta") or {}
    title = script.get("title", "")
    category = meta.get("category", "")
    data = meta.get("chart") or {}
    values = data.get("values")
    labels = data.get("labels")

    if scene_index is None:
        return make(title, category, values, labels,
                    style=data.get("style", "auto"))
    return make(f"{title}#{scene_index}", category, None, None, style="plain")


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "..", "out", "bg_demo")
    os.makedirs(out, exist_ok=True)
    samples = [
        ("23억 아파트", "주거", [23.0, 18.0, 5.2, 4.1, 3.8], None),
        ("장바구니 물가", "돈·물가", [112, 118, 121, 127, 134, 141], None),
        ("독감 주의보", "안전·건강", None, None),
        ("지하철 요금 인상", "교통", [1400, 1400, 1550, 1550, 1700], None),
        ("인구 통계", "통계", [52.1, 51.8, 51.5, 51.2, 50.9, 50.4], None),
    ]
    for title, cat, vals, labs in samples:
        img = make(title, cat, vals, labs)
        p = os.path.join(out, f"{cat.replace('·','_')}.jpg")
        img.save(p, "JPEG", quality=90)
        print(p, img.size)
