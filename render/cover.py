# -*- coding: utf-8 -*-
"""
cover.py — 릴스 커버 렌더러

이슈매거진 커버 문법을 옮긴 것:
  - 굵은 흰색 고딕(Noto Sans CJK KR Black) + 검은 외곽선
  - 포인트 단어만 빨강/노랑
  - 텍스트는 하단 정렬(기본), 상단은 비움
  - 인스타 UI 세이프존 준수

마크업:
  <r>...</r>  빨강 강조
  <y>...</y>  노랑 강조
  그 외는 흰색
"""
import re
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1080, 1920

# 인스타 UI 세이프존 (프로젝트 기준)
SAFE_TOP, SAFE_BOTTOM, SAFE_SIDE = 320, 520, 90

FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
FONT_INDEX = 1  # Noto Sans CJK KR Black

COLORS = {
    "w": (255, 255, 255),
    "r": (255, 59, 48),
    "y": (255, 214, 0),
}
STROKE = (0, 0, 0)

TAG_RE = re.compile(r"<([ry])>(.*?)</\1>", re.S)


def parse_runs(line):
    """'<r>7만원</r> 날립니다' -> [('7만원','r'), (' 날립니다','w')]"""
    runs, pos = [], 0
    for m in TAG_RE.finditer(line):
        if m.start() > pos:
            runs.append((line[pos:m.start()], "w"))
        runs.append((m.group(2), m.group(1)))
        pos = m.end()
    if pos < len(line):
        runs.append((line[pos:], "w"))
    return [(t, c) for t, c in runs if t]


def _font(size):
    return ImageFont.truetype(FONT_PATH, size, index=FONT_INDEX)


def _run_width(draw, runs, font, stroke_w):
    return sum(draw.textlength(t, font=font) for t, _ in runs) + stroke_w * 2


# 150pt가 기준 크기. 줄이 길면 폰트를 줄이는 대신 줄바꿈한다.
BASE_SIZE = 150
MIN_SIZE = 110
MAX_LINES = 4


def wrap_runs(draw, runs, font, stroke_w, max_w):
    """runs 한 줄을 단어 단위로 쪼개 max_w에 맞는 여러 줄로 만든다. 색 태그는 유지."""
    tokens = []  # (word, color, 앞에 공백이 있었는지)
    for text, color in runs:
        parts = text.split(" ")
        for i, wd in enumerate(parts):
            if wd == "":
                continue
            tokens.append((wd, color, i > 0 or bool(tokens)))

    lines, cur = [], []
    for wd, color, sp in tokens:
        trial = cur + ([(" ", color)] if (cur and sp) else []) + [(wd, color)]
        if cur and _run_width(draw, trial, font, stroke_w) > max_w:
            lines.append(cur)
            cur = [(wd, color)]
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def layout(draw, lines, max_w):
    """BASE_SIZE로 줄바꿈해 본다. 줄이 너무 많거나 한 단어가 안 들어가면 그때만 축소."""
    size = BASE_SIZE
    while size >= MIN_SIZE:
        f = _font(size)
        sw = max(3, size // 16)
        out, ok = [], True
        for raw in lines:
            wrapped = wrap_runs(draw, parse_runs(raw), f, sw, max_w)
            if any(_run_width(draw, w, f, sw) > max_w for w in wrapped):
                ok = False
                break
            out.extend(wrapped)
        if ok and len(out) <= MAX_LINES:
            return out, size, f, sw
        size -= 4

    f = _font(MIN_SIZE)
    sw = max(3, MIN_SIZE // 16)
    out = []
    for raw in lines:
        out.extend(wrap_runs(draw, parse_runs(raw), f, sw, max_w))
    return out, MIN_SIZE, f, sw


def draw_cover(bg, lines, align="bottom", line_gap=1.18, badge=None):
    """
    bg    : PIL.Image (1080x1920로 커버 크롭됨)
    lines : 마크업 포함 문자열 리스트 (2~3줄 권장)
    align : 'bottom' | 'center'
    badge : 상단 소형 라벨 (예: '11월 1일 시행') 또는 None
    """
    img = bg.convert("RGB").copy()
    draw = ImageDraw.Draw(img)

    max_w = W - SAFE_SIDE * 2
    lines_runs, size, font, sw = layout(draw, lines, max_w)

    lh = int(size * line_gap)
    block_h = lh * len(lines)

    if align == "center":
        y = (H - block_h) // 2
    else:
        y = H - SAFE_BOTTOM - block_h

    # 텍스트 뒤쪽을 눌러 대비 확보 (사진이 밝아도 글자가 뜬다)
    scrim = Image.new("L", (W, H), 0)
    sd = ImageDraw.Draw(scrim)
    sd.rectangle([0, y - int(size * 0.55), W, y + block_h + int(size * 0.35)], fill=150)
    scrim = scrim.filter(ImageFilter.GaussianBlur(70))
    img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, scrim)
    draw = ImageDraw.Draw(img)

    if badge:
        bf = _font(46)
        bw = draw.textlength(badge, font=bf)
        bx, by = SAFE_SIDE, y - int(size * 0.95)
        draw.rounded_rectangle(
            [bx - 22, by - 14, bx + bw + 22, by + 62], radius=12, fill=COLORS["r"]
        )
        draw.text((bx, by), badge, font=bf, fill=(255, 255, 255))

    for runs in lines_runs:
        x = SAFE_SIDE
        for text, color in runs:
            draw.text(
                (x, y), text, font=font, fill=COLORS[color],
                stroke_width=sw, stroke_fill=STROKE,
            )
            x += draw.textlength(text, font=font)
        y += lh

    return img


def cover_crop(src_path):
    """원본 이미지를 1080x1920으로 꽉 채워 크롭."""
    im = Image.open(src_path).convert("RGB")
    sw, sh = im.size
    scale = max(W / sw, H / sh)
    im = im.resize((int(sw * scale + 0.5), int(sh * scale + 0.5)), Image.LANCZOS)
    nw, nh = im.size
    return im.crop(((nw - W) // 2, (nh - H) // 2, (nw - W) // 2 + W, (nh - H) // 2 + H))
