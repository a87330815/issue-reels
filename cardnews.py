# -*- coding: utf-8 -*-
"""
cardnews.py — 인스타그램 카드뉴스 생성기

1080x1350 (4:5 비율) 카드뉴스 이미지를 생성한다.
커버 + 본문 슬라이드 + 마지막(팔로우 유도) 구성.

사용:
  python cardnews.py out/scripts/news_001.json -o out/cards/
"""
import argparse
import json
import math
import os
import sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1080, 1350  # 인스타 4:5

# ── 폰트 ─────────────────────────────────────────────────
FONT_BLACK = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_MEDIUM = "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"
FONT_REGULAR = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

# ttc 인덱스: KR=1
def font(path, size):
    return ImageFont.truetype(path, size, index=1)

# ── 색상 테마 ─────────────────────────────────────────────
THEMES = {
    "교통":   {"bg": "#0A1628", "accent": "#00D4AA", "accent2": "#00B4D8", "card_bg": "#111D33", "text": "#FFFFFF", "sub": "#94A3B8"},
    "생활":   {"bg": "#0F0A1E", "accent": "#A78BFA", "accent2": "#818CF8", "card_bg": "#1A1230", "text": "#FFFFFF", "sub": "#94A3B8"},
    "돈·물가": {"bg": "#1A1000", "accent": "#FBBF24", "accent2": "#F59E0B", "card_bg": "#261C06", "text": "#FFFFFF", "sub": "#94A3B8"},
    "주거":   {"bg": "#0A1628", "accent": "#60A5FA", "accent2": "#3B82F6", "card_bg": "#111D33", "text": "#FFFFFF", "sub": "#94A3B8"},
    "안전":   {"bg": "#1A0A0A", "accent": "#F87171", "accent2": "#EF4444", "card_bg": "#261010", "text": "#FFFFFF", "sub": "#94A3B8"},
}
DEFAULT_THEME = {"bg": "#0F172A", "accent": "#38BDF8", "accent2": "#0EA5E9", "card_bg": "#1E293B", "text": "#FFFFFF", "sub": "#94A3B8"}


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def get_theme(category):
    t = THEMES.get(category, DEFAULT_THEME)
    return {k: hex_to_rgb(v) if v.startswith("#") else v for k, v in t.items()}


# ── 배경 생성 ─────────────────────────────────────────────
def make_bg(theme, seed=0):
    """그라데이션 + 글로우 배경."""
    img = Image.new("RGB", (W, H), theme["bg"])
    draw = ImageDraw.Draw(img)

    # 상단 글로우
    import numpy as np
    arr = np.full((H, W, 3), theme["bg"], dtype=np.float64)
    # 원형 글로우
    cx, cy = W * 0.7, H * 0.15
    Y, X = np.ogrid[:H, :W]
    dist = np.sqrt((X - cx)**2 + (Y - cy)**2)
    glow = np.exp(-dist**2 / (2 * 300**2))
    for c in range(3):
        arr[:, :, c] += glow * theme["accent"][c] * 0.3

    # 좌하단 글로우
    cx2, cy2 = W * 0.2, H * 0.85
    dist2 = np.sqrt((X - cx2)**2 + (Y - cy2)**2)
    glow2 = np.exp(-dist2**2 / (2 * 350**2))
    for c in range(3):
        arr[:, :, c] += glow2 * theme["accent2"][c] * 0.15

    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    return img.filter(ImageFilter.GaussianBlur(2))


def draw_rounded_rect(draw, xy, radius, fill):
    """모서리 둥근 사각형."""
    x0, y0, x1, y1 = xy
    draw.rectangle([x0 + radius, y0, x1 - radius, y1], fill=fill)
    draw.rectangle([x0, y0 + radius, x1, y1 - radius], fill=fill)
    draw.pieslice([x0, y0, x0 + 2*radius, y0 + 2*radius], 180, 270, fill=fill)
    draw.pieslice([x1 - 2*radius, y0, x1, y0 + 2*radius], 270, 360, fill=fill)
    draw.pieslice([x0, y1 - 2*radius, x0 + 2*radius, y1], 90, 180, fill=fill)
    draw.pieslice([x1 - 2*radius, y1 - 2*radius, x1, y1], 0, 90, fill=fill)


# ── 텍스트 유틸 ───────────────────────────────────────────
def wrap_text(draw, text, fnt, max_w):
    """한글 줄바꿈. 어절 단위."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        bbox = draw.textbbox((0, 0), test, font=fnt)
        if bbox[2] - bbox[0] > max_w and cur:
            lines.append(cur)
            cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


def draw_text_center(draw, text, y, fnt, fill, max_w=None):
    """가운데 정렬 텍스트. 줄바꿈 지원."""
    if max_w:
        lines = wrap_text(draw, text, fnt, max_w)
    else:
        lines = [text]
    lh = fnt.size + 12
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=fnt)
        tw = bbox[2] - bbox[0]
        x = (W - tw) / 2
        draw.text((x, y), line, font=fnt, fill=fill)
        y += lh
    return y


def draw_text_left(draw, text, x, y, fnt, fill, max_w=None):
    """왼쪽 정렬 텍스트."""
    if max_w:
        lines = wrap_text(draw, text, fnt, max_w)
    else:
        lines = [text]
    lh = fnt.size + 14
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=fill)
        y += lh
    return y


# ── 페이지 생성 ───────────────────────────────────────────
def make_cover(script, theme):
    """커버 슬라이드."""
    img = make_bg(theme)
    draw = ImageDraw.Draw(img)

    category = script.get("meta", {}).get("category", "")
    title = script.get("title", "")
    cover_data = script.get("cover", {})
    lines = cover_data.get("lines", [title])

    # 상단 카테고리 뱃지
    if category:
        badge_font = font(FONT_MEDIUM, 28)
        badge_text = f"#{category}"
        bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
        bw = bbox[2] - bbox[0] + 40
        bh = bbox[3] - bbox[1] + 20
        bx = (W - bw) / 2
        by = 180
        draw_rounded_rect(draw, (bx, by, bx + bw, by + bh), 20, (*theme["accent"], 40))
        draw.text((bx + 20, by + 6), badge_text, font=badge_font, fill=theme["accent"])

    # 메인 타이틀 — 커버 lines 사용
    y = H * 0.35
    title_font = font(FONT_BLACK, 88)

    for line in lines:
        # <r>...</r> 빨강, <y>...</y> 노랑 처리
        clean = line.replace("<r>", "").replace("</r>", "").replace("<y>", "").replace("</y>", "")
        is_accent = "<r>" in line or "<y>" in line

        bbox = draw.textbbox((0, 0), clean, font=title_font)
        tw = bbox[2] - bbox[0]
        x = (W - tw) / 2
        color = theme["accent"] if is_accent else theme["text"]
        draw.text((x, y), clean, font=title_font, fill=color)
        y += 110

    # 하단 출처
    attr = script.get("meta", {}).get("attribution", "")
    if attr:
        attr_font = font(FONT_REGULAR, 24)
        draw_text_center(draw, f"출처: {attr}", H - 120, attr_font, theme["sub"])

    # 페이지 번호
    draw_page_num(draw, 1, len(script.get("scenes", [])) + 2, theme)

    return img


def make_scene(script, scene_idx, total_pages, theme):
    """본문 슬라이드."""
    img = make_bg(theme, seed=scene_idx)
    draw = ImageDraw.Draw(img)
    scene = script["scenes"][scene_idx]

    # 상단 제목 바
    title_font = font(FONT_BOLD, 36)
    title = script.get("title", "")
    draw_text_center(draw, title, 80, title_font, theme["sub"])

    # 구분선
    line_y = 140
    lx = W * 0.15
    draw.line([(lx, line_y), (W - lx, line_y)], fill=(*theme["accent"], 80), width=2)

    # 숫자 아이콘
    num_y = 200
    num_size = 120
    cx = W / 2
    draw.ellipse(
        [cx - num_size/2, num_y, cx + num_size/2, num_y + num_size],
        fill=theme["accent"]
    )
    num_font = font(FONT_BLACK, 56)
    num_text = str(scene_idx + 1)
    bbox = draw.textbbox((0, 0), num_text, font=num_font)
    nw = bbox[2] - bbox[0]
    nh = bbox[3] - bbox[1]
    draw.text((cx - nw/2, num_y + num_size/2 - nh/2 - 5), num_text, font=num_font, fill=theme["bg"])

    # 카드 영역
    card_margin = 60
    card_top = 380
    card_bottom = H - 200
    draw_rounded_rect(draw, (card_margin, card_top, W - card_margin, card_bottom), 24, theme["card_bg"])

    # 자막 (핵심 메시지) — 카드 안 상단
    subtitle = scene.get("subtitle", "")
    if subtitle:
        sub_font = font(FONT_BLACK, 52)
        sub_y = card_top + 60
        draw_text_center(draw, subtitle, sub_y, sub_font, theme["text"], max_w=W - card_margin*2 - 60)

    # 나레이션 (설명) — 카드 안 중간
    narration = scene.get("narration", "")
    if narration:
        nar_font = font(FONT_REGULAR, 34)
        nar_y = card_top + 220
        draw_text_center(draw, narration, nar_y, nar_font, theme["sub"], max_w=W - card_margin*2 - 80)

    # 페이지 번호
    draw_page_num(draw, scene_idx + 2, total_pages, theme)

    return img


def make_outro(script, theme, total_pages):
    """마지막 슬라이드 — 팔로우 유도."""
    img = make_bg(theme, seed=99)
    draw = ImageDraw.Draw(img)

    y = H * 0.25

    # 아이콘 대신 큰 체크
    check_font = font(FONT_BLACK, 120)
    draw_text_center(draw, "✓", y, check_font, theme["accent"])

    y += 180
    main_font = font(FONT_BLACK, 56)
    draw_text_center(draw, "도움이 되셨다면", y, main_font, theme["text"])
    y += 80
    draw_text_center(draw, "팔로우 & 저장", y, main_font, theme["accent"])

    y += 120
    sub_font = font(FONT_REGULAR, 32)
    draw_text_center(draw, "매일 알아두면 좋은 생활 정보를", y, sub_font, theme["sub"])
    y += 50
    draw_text_center(draw, "카드뉴스로 전해드립니다", y, sub_font, theme["sub"])

    y += 100
    handle_font = font(FONT_BOLD, 38)
    draw_text_center(draw, "@richup_bm_sw", y, handle_font, theme["accent"])

    draw_page_num(draw, total_pages, total_pages, theme)
    return img


def draw_page_num(draw, current, total, theme):
    """우하단 페이지 번호."""
    pg_font = font(FONT_MEDIUM, 26)
    text = f"{current}/{total}"
    bbox = draw.textbbox((0, 0), text, font=pg_font)
    tw = bbox[2] - bbox[0]
    draw.text((W - tw - 50, H - 60), text, font=pg_font, fill=theme["sub"])


# ── 메인 ─────────────────────────────────────────────────
def generate(script_path, out_dir):
    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    os.makedirs(out_dir, exist_ok=True)
    category = script.get("meta", {}).get("category", "")
    theme = get_theme(category)
    total_pages = len(script.get("scenes", [])) + 2  # cover + scenes + outro

    pages = []

    # 커버
    cover = make_cover(script, theme)
    p = os.path.join(out_dir, "01_cover.png")
    cover.save(p, quality=95)
    pages.append(p)

    # 본문
    for i, _ in enumerate(script.get("scenes", [])):
        scene = make_scene(script, i, total_pages, theme)
        p = os.path.join(out_dir, f"{i+2:02d}_scene.png")
        scene.save(p, quality=95)
        pages.append(p)

    # 아웃트로
    outro = make_outro(script, theme, total_pages)
    p = os.path.join(out_dir, f"{total_pages:02d}_outro.png")
    outro.save(p, quality=95)
    pages.append(p)

    print(f"카드뉴스 {len(pages)}장 생성 → {out_dir}")
    return pages


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("script", help="대본 JSON 경로")
    ap.add_argument("-o", "--out", default="out/cards", help="출력 폴더")
    args = ap.parse_args()
    generate(args.script, args.out)
