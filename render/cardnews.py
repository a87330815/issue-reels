# -*- coding: utf-8 -*-
"""
cardnews.py — 인스타 카드뉴스(캐러셀) 렌더러

대본 JSON → 1080×1350 이미지 슬라이드 여러 장
  슬라이드 1: 커버 (훅 텍스트 + 배경)
  슬라이드 2~N: 본문 장면 (내레이션 텍스트 + 배경)
  마지막: CTA (팔로우 유도)

사용:
  python render/cardnews.py out/approved/script.json -o out/cardnews/script/
"""
import argparse
import json
import os
import re
import sys
import textwrap

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from bg import theme_for, seed_of
from cover import parse_runs, COLORS, STROKE

W, H = 1080, 1350  # 인스타 캐러셀 권장 4:5

SAFE_TOP = 80
SAFE_BOTTOM = 80
SAFE_SIDE = 80

FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_INDEX = 1

TAG_RE = re.compile(r"<([ry])>(.*?)</\1>", re.S)


def _font(path, size):
    try:
        return ImageFont.truetype(path, size, index=FONT_INDEX)
    except Exception:
        return ImageFont.load_default()


# ── 배경 생성 (bg.py 간소화) ──

def _make_bg(title="", category="", seed_extra=""):
    top, bottom, accent = theme_for(category)
    rng = np.random.default_rng(seed_of(title + category + seed_extra))

    yy = np.linspace(0, 1, H)[:, None]
    curve = yy ** 0.75
    base = np.zeros((H, W, 3), np.float64)
    for c in range(3):
        base[:, :, c] = top[c] * (1 - curve) + bottom[c] * curve

    # blobs
    X, Y = np.meshgrid(np.arange(W), np.arange(H))
    for _ in range(5):
        cx = rng.uniform(-100, W + 100)
        cy = rng.uniform(-100, H * 0.6)
        r = rng.uniform(200, 500)
        amp = rng.uniform(-20, 40)
        g = np.exp(-(((X - cx) ** 2 + (Y - cy) ** 2) / (2 * r ** 2)))
        tint = np.array(accent) / 255.0 if amp > 0 else np.ones(3)
        base += (g * amp)[:, :, None] * tint

    # grain + vignette
    base += rng.normal(0, 3.5, (H, W, 3))
    Xn, Yn = np.meshgrid(np.linspace(-1, 1, W), np.linspace(-1, 1, H))
    base *= (1 - 0.3 * np.clip(Xn ** 2 + Yn ** 2, 0, 1))[:, :, None]

    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    return img.filter(ImageFilter.GaussianBlur(1.0)), accent


# ── 텍스트 그리기 ──

def _draw_cover_text(img, lines):
    """커버 슬라이드: 큰 글씨, 하단 정렬, 외곽선"""
    d = ImageDraw.Draw(img)
    font_size = 120
    font = _font(FONT_PATH, font_size)
    stroke_w = font_size // 16

    # 전체 높이 계산
    line_data = []
    for line in lines:
        runs = parse_runs(line)
        lw = sum(d.textlength(t, font=font) for t, _ in runs)
        line_data.append((runs, lw))

    line_h = int(font_size * 1.35)
    total_h = line_h * len(lines)

    # 하단 정렬
    y_start = H - SAFE_BOTTOM - total_h

    for i, (runs, lw) in enumerate(line_data):
        x = (W - lw) / 2
        y = y_start + i * line_h
        for text, color_key in runs:
            color = COLORS.get(color_key, COLORS["w"])
            d.text((x, y), text, font=font, fill=color,
                   stroke_width=stroke_w, stroke_fill=STROKE)
            x += d.textlength(text, font=font)

    return img


def _draw_body_text(img, narration, subtitle, accent):
    """본문 슬라이드: 제목 + 본문"""
    d = ImageDraw.Draw(img)

    # 제목 (subtitle)
    title_font = _font(FONT_PATH, 64)
    stroke_w = 4

    # 워드랩
    if subtitle:
        wrapped = textwrap.fill(subtitle, width=14)
        lines = wrapped.split("\n")
        y = 200
        for line in lines:
            bbox = d.textbbox((0, 0), line, font=title_font)
            tw = bbox[2] - bbox[0]
            x = (W - tw) / 2
            d.text((x, y), line, font=title_font, fill=COLORS["w"],
                   stroke_width=stroke_w, stroke_fill=STROKE)
            y += 90

    # 구분선
    line_y = 420
    d.rectangle([W // 2 - 160, line_y, W // 2 + 160, line_y + 4],
                fill=(*accent, 200))

    # 본문 (narration)
    if narration:
        body_font = _font(FONT_BOLD, 42)
        wrapped = textwrap.fill(narration, width=20)
        lines = wrapped.split("\n")
        y = 480
        for line in lines:
            bbox = d.textbbox((0, 0), line, font=body_font)
            tw = bbox[2] - bbox[0]
            x = (W - tw) / 2
            d.text((x, y), line, font=body_font, fill=(230, 230, 230),
                   stroke_width=2, stroke_fill=(0, 0, 0))
            y += 62

    return img


def _draw_cta(img, accent):
    """마지막 슬라이드: 팔로우 유도"""
    d = ImageDraw.Draw(img)
    font_big = _font(FONT_PATH, 80)
    font_sub = _font(FONT_BOLD, 40)

    # 팔로우
    text1 = "팔로우 하면"
    text2 = "매일 이슈 정리"
    text3 = "해드립니다"

    y = H // 2 - 160
    for text in [text1, text2, text3]:
        bbox = d.textbbox((0, 0), text, font=font_big)
        tw = bbox[2] - bbox[0]
        x = (W - tw) / 2
        color = COLORS["r"] if text == text2 else COLORS["w"]
        d.text((x, y), text, font=font_big, fill=color,
               stroke_width=5, stroke_fill=STROKE)
        y += 110

    # @계정
    account = "@jjombwabwa"
    bbox = d.textbbox((0, 0), account, font=font_sub)
    tw = bbox[2] - bbox[0]
    d.text(((W - tw) / 2, y + 40), account, font=font_sub,
           fill=(180, 180, 180))

    return img


def _draw_attribution(img, text):
    """출처 표시 — 하단"""
    if not text:
        return img
    d = ImageDraw.Draw(img)
    font = _font(FONT_BOLD, 28)
    bbox = d.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    d.text(((W - tw) / 2, H - 60), f"출처: {text}", font=font,
           fill=(120, 120, 120))
    return img


def _draw_page_indicator(img, current, total):
    """슬라이드 번호 표시 — 우상단"""
    d = ImageDraw.Draw(img)
    font = _font(FONT_BOLD, 30)
    text = f"{current}/{total}"
    d.text((W - 120, 40), text, font=font, fill=(160, 160, 160))
    return img


# ── 메인 ──

def render_cardnews(script_path, out_dir):
    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    os.makedirs(out_dir, exist_ok=True)

    title = script.get("title", "")
    meta = script.get("meta", {})
    category = meta.get("category", "")
    attribution = meta.get("attribution", "")
    cover = script.get("cover", {})
    scenes = script.get("scenes", [])

    # CTA를 제외한 본문 장면 (마지막이 팔로우 유도면 CTA로)
    content_scenes = []
    for s in scenes:
        narr = s.get("narration", "")
        if "팔로우" in narr or "구독" in narr:
            continue
        content_scenes.append(s)

    total_slides = 1 + len(content_scenes) + 1  # 커버 + 본문 + CTA
    slides = []

    # 1. 커버
    bg, accent = _make_bg(title, category, "cover")
    cover_img = _draw_cover_text(bg, cover.get("lines", [title]))
    cover_img = _draw_page_indicator(cover_img, 1, total_slides)
    slides.append(cover_img)

    # 2. 본문 장면
    for i, scene in enumerate(content_scenes):
        bg, accent = _make_bg(title, category, f"scene{i}")
        slide = _draw_body_text(bg, scene.get("narration", ""),
                                scene.get("subtitle", ""), accent)
        slide = _draw_attribution(slide, attribution)
        slide = _draw_page_indicator(slide, i + 2, total_slides)
        slides.append(slide)

    # 3. CTA
    bg, accent = _make_bg(title, category, "cta")
    cta = _draw_cta(bg, accent)
    cta = _draw_page_indicator(cta, total_slides, total_slides)
    slides.append(cta)

    # 저장
    paths = []
    for i, slide in enumerate(slides):
        p = os.path.join(out_dir, f"slide_{i+1:02d}.jpg")
        slide.save(p, "JPEG", quality=92)
        paths.append(p)
        print(f"  {p}  {slide.size[0]}x{slide.size[1]}")

    print(f"\n카드뉴스 {len(slides)}장 완성 → {out_dir}")
    return paths


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("script", help="대본 JSON")
    ap.add_argument("-o", "--out", default=None, help="출력 디렉토리")
    args = ap.parse_args()

    if args.out is None:
        name = os.path.splitext(os.path.basename(args.script))[0]
        args.out = os.path.join("out", "cardnews", name)

    render_cardnews(args.script, args.out)
