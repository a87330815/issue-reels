# -*- coding: utf-8 -*-
"""
cardnews.py — 인스타그램 카드뉴스 생성기 v5

1080x1350 (4:5) 카드뉴스
- 강렬한 그래디언트 배경 + 큰 이모지 아이콘
- 굵고 큰 텍스트 + 눈에 띄는 색상 조합
"""
import argparse, json, math, os, sys, random
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1080, 1350

FONT_BLACK = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
FONT_BOLD  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_MED   = "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"
FONT_REG   = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_EMOJI = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"

def font(path, size):
    return ImageFont.truetype(path, size, index=1)

_emoji_cache = {}

def render_emoji(emoji, size):
    """컬러 이모지를 RGBA 이미지로 렌더링 (NotoColorEmoji는 109px 고정 → 리사이즈)"""
    key = (emoji, size)
    if key in _emoji_cache:
        return _emoji_cache[key]
    try:
        ef = ImageFont.truetype(FONT_EMOJI, 109)
        tmp = Image.new("RGBA", (180, 180), (0, 0, 0, 0))
        td = ImageDraw.Draw(tmp)
        td.text((20, 20), emoji, font=ef, embedded_color=True)
        bb = tmp.getbbox()
        if not bb:
            return None
        cropped = tmp.crop(bb)
        ratio = size / max(cropped.width, cropped.height)
        out = cropped.resize(
            (max(1, int(cropped.width * ratio)), max(1, int(cropped.height * ratio))),
            Image.LANCZOS,
        )
        _emoji_cache[key] = out
        return out
    except Exception:
        return None

def paste_emoji(img, emoji, cx, cy, size, opacity=255):
    """이모지를 이미지 중앙 좌표에 붙이기"""
    em = render_emoji(emoji, size)
    if em is None:
        return
    if opacity < 255:
        em = em.copy()
        alpha = em.getchannel("A").point(lambda v: int(v * opacity / 255))
        em.putalpha(alpha)
    img.paste(em, (int(cx - em.width // 2), int(cy - em.height // 2)), em)

# ── 비비드 테마 ────────────────────
THEMES = {
    "교통": {
        "grad1": (0, 82, 212),    "grad2": (67, 198, 255),
        "accent": (255, 220, 0),  "accent2": (255, 140, 0),
        "tag_bg": (255, 220, 0),  "tag_fg": (0, 60, 150),
        "emojis": ["🚄","📅","💺","📱","🚆","🛤️"],
    },
    "생활": {
        "grad1": (131, 58, 180),  "grad2": (253, 29, 29),
        "accent": (255, 255, 100),"accent2": (255, 200, 50),
        "tag_bg": (255, 255, 100),"tag_fg": (100, 30, 140),
        "emojis": ["🚫","💰","📢","🎫","🎵","🎤"],
    },
    "돈·물가": {
        "grad1": (15, 82, 56),    "grad2": (44, 160, 28),
        "accent": (255, 230, 50), "accent2": (255, 180, 0),
        "tag_bg": (255, 230, 50), "tag_fg": (10, 70, 40),
        "emojis": ["💵","🧾","🏦","✅","💰","📊"],
    },
    "주거": {
        "grad1": (30, 60, 120),   "grad2": (0, 172, 238),
        "accent": (255, 200, 50), "accent2": (255, 150, 0),
        "tag_bg": (255, 200, 50), "tag_fg": (20, 50, 100),
        "emojis": ["🏠","📋","🔑","💡","🏗️","📐"],
    },
    "안전": {
        "grad1": (180, 20, 30),   "grad2": (255, 100, 50),
        "accent": (255, 255, 100),"accent2": (255, 220, 0),
        "tag_bg": (255, 255, 100),"tag_fg": (150, 10, 20),
        "emojis": ["🚨","⚠️","🛡️","📞","🆘","🔒"],
    },
}
DEF_THEME = {
    "grad1": (30, 60, 180),   "grad2": (0, 200, 200),
    "accent": (255, 220, 50), "accent2": (255, 160, 0),
    "tag_bg": (255, 220, 50), "tag_fg": (20, 50, 140),
    "emojis": ["📌","💡","✨","📋","🔍","📊"],
}

WHITE = (255, 255, 255)
DARK  = (20, 20, 25)

def get_t(cat):
    return THEMES.get(cat, DEF_THEME)

# ── 유틸 ────────────────────────
def rounded_rect(draw, xy, r, fill):
    """네이티브 rounded_rectangle 사용 (모서리 이중 블렌딩 아티팩트 없음)"""
    x0, y0, x1, y1 = (int(v) for v in xy)
    r = int(min(r, (x1-x0)//2, (y1-y0)//2))
    draw.rounded_rectangle([x0, y0, x1, y1], radius=max(0, r), fill=fill)

def overlay_layer():
    """반투명 도형을 그릴 별도 RGBA 레이어 생성"""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    return layer, ImageDraw.Draw(layer)

def composite(img, layer):
    """RGBA 레이어를 RGB 베이스에 1회 합성 (이중 블렌딩 방지)"""
    base = img.convert("RGBA")
    base.alpha_composite(layer)
    return base.convert("RGB")

def gradient_bg(c1, c2, direction="vertical"):
    """강렬한 그래디언트 배경 생성"""
    arr = np.zeros((H, W, 3), dtype=np.uint8)
    for i in range(H):
        t = i / H
        # ease-in-out for smoother gradient
        t2 = t * t * (3 - 2 * t)
        for c in range(3):
            arr[i, :, c] = int(c1[c] * (1 - t2) + c2[c] * t2)
    return Image.fromarray(arr)

def gradient_bg_diagonal(c1, c2):
    """대각선 그래디언트"""
    arr = np.zeros((H, W, 3), dtype=np.uint8)
    for i in range(H):
        for j in range(W):
            t = (i/H * 0.6 + j/W * 0.4)
            t = min(1.0, max(0.0, t))
            t2 = t * t * (3 - 2 * t)
            for c in range(3):
                arr[i, j, c] = int(c1[c] * (1-t2) + c2[c] * t2)
    return Image.fromarray(arr)

def draw_glow_circles(ld, seed=0):
    """오버레이 레이어에 빛나는 원형 장식 그리기"""
    rng = random.Random(seed)
    for _ in range(rng.randint(4, 8)):
        cx = rng.randint(0, W)
        cy = rng.randint(0, H)
        r = rng.randint(80, 300)
        alpha = rng.randint(14, 34)
        ld.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(255, 255, 255, alpha))

def wrap_char(draw, text, fnt, max_w):
    lines, cur = [], ""
    for ch in text:
        test = cur + ch
        if draw.textbbox((0,0), test, font=fnt)[2] > max_w and cur:
            lines.append(cur)
            cur = ch
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines

def wrap_words(draw, text, fnt, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textbbox((0,0), test, font=fnt)[2] > max_w and cur:
            lines.append(cur)
            cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines

def text_center_white(draw, text, y, fnt, max_w=W-120):
    lines = wrap_words(draw, text, fnt, max_w)
    lh = fnt.size + 16
    for l in lines:
        bb = draw.textbbox((0,0), l, font=fnt)
        draw.text(((W-(bb[2]-bb[0]))/2, y), l, font=fnt, fill=WHITE)
        y += lh
    return y

def dots(draw, cur, total, t):
    r = 7
    gap = 18
    tw = total * r*2 + (total-1)*gap
    sx = (W-tw)/2
    y = H - 45
    for i in range(total):
        cx = sx + i*(r*2+gap) + r
        fill = t["accent"] if i+1 == cur else (255, 255, 255, 100)
        draw.ellipse([cx-r, y-r, cx+r, y+r], fill=fill)

def draw_big_emoji(draw, emoji, cx, cy, size):
    """이모지를 큰 텍스트로 그리기"""
    try:
        ef = font(FONT_BLACK, size)
        bb = draw.textbbox((0, 0), emoji, font=ef)
        ew, eh = bb[2]-bb[0], bb[3]-bb[1]
        draw.text((cx - ew//2, cy - eh//2), emoji, font=ef, fill=WHITE)
    except:
        pass

# ── 커버 ────────────────────────
def make_cover(sc, t):
    img = gradient_bg_diagonal(t["grad1"], t["grad2"])

    # 1단계: 반투명 장식을 오버레이 레이어에 그려 1회 합성
    layer, ld = overlay_layer()
    draw_glow_circles(ld, seed=42)
    img = composite(img, layer)

    # 2단계: 이모지 붙이기
    main_emoji = t.get("emojis", ["📌"])[0]
    paste_emoji(img, main_emoji, W//2, 300, 190)

    # 3단계: 불투명 요소 직접 그리기
    d = ImageDraw.Draw(img, "RGBA")
    cat = sc.get("meta", {}).get("category", "")
    lines = sc.get("cover", {}).get("lines", [sc.get("title", "")])

    # 상단 카테고리 뱃지
    if cat:
        tf = font(FONT_BOLD, 30)
        bb = d.textbbox((0,0), cat, font=tf)
        tw, th = bb[2]-bb[0]+56, bb[3]-bb[1]+30
        bx = (W-tw)//2
        by = 120
        rounded_rect(d, (bx, by, bx+tw, by+th), 25, t["tag_bg"])
        d.text((bx+28, by+9), cat, font=tf, fill=t["tag_fg"])

    # 메인 타이틀 — 매우 큰 텍스트
    y = 480
    tf_big = font(FONT_BLACK, 86)
    for line in lines:
        clean = line.replace("<r>","").replace("</r>","").replace("<y>","").replace("</y>","")
        is_acc = "<r>" in line or "<y>" in line
        bb = d.textbbox((0,0), clean, font=tf_big)
        x = (W-(bb[2]-bb[0]))//2
        color = t["accent"] if is_acc else WHITE
        d.text((x+3, y+4), clean, font=tf_big, fill=(0, 0, 0, 90))
        d.text((x, y), clean, font=tf_big, fill=color)
        y += 108

    # 부제
    sub = sc.get("title", "")
    if sub:
        sf = font(FONT_MED, 34)
        y += 26
        bb = d.textbbox((0,0), sub, font=sf)
        d.text(((W-(bb[2]-bb[0]))//2, y), sub, font=sf, fill=(255, 255, 255, 215))

    # 하단 구분선
    d.line([(W*0.25, H-180), (W*0.75, H-180)], fill=(255, 255, 255, 90), width=2)

    # 출처
    attr = sc.get("meta", {}).get("attribution", "")
    if attr:
        af = font(FONT_REG, 22)
        txt = f"출처: {attr}"
        bb = d.textbbox((0,0), txt, font=af)
        d.text(((W-(bb[2]-bb[0]))//2, H-145), txt, font=af, fill=(255, 255, 255, 150))

    # 스와이프 안내 (이모지 + 텍스트 분리 렌더)
    sf = font(FONT_BOLD, 28)
    swipe = "밀어서 자세히 보기"
    bb = d.textbbox((0,0), swipe, font=sf)
    sx = (W - (bb[2]-bb[0]) - 46)//2
    paste_emoji(img, "👉", sx + 17, H-82, 34)
    d = ImageDraw.Draw(img, "RGBA")
    d.text((sx + 46, H-95), swipe, font=sf, fill=t["accent"])

    dots(d, 1, len(sc.get("scenes", []))+2, t)
    return img

# ── 본문 슬라이드 ────────────────
def make_scene(sc, idx, total, t):
    scene = sc["scenes"][idx]

    # 슬라이드마다 색조를 살짝 변형
    r = random.Random(idx * 31 + 7)
    shift = r.randint(-20, 20)
    c1 = tuple(max(0, min(255, v + shift)) for v in t["grad1"])
    c2 = tuple(max(0, min(255, v - shift)) for v in t["grad2"])
    img = gradient_bg(c1, c2)

    # 본문 준비 (카드 높이 계산용)
    body = scene.get("body", "")
    if not body:
        narration = scene.get("narration", "")
        body = (narration + " " if narration else "") + " ".join(scene.get("details", []))

    measure = ImageDraw.Draw(img)
    body_f = font(FONT_REG, 38)
    subtitle = scene.get("subtitle", "")
    tag_f = font(FONT_BOLD, 38)

    card_margin = 50
    body_max_w = W - card_margin*2 - 90
    body_lh = 60
    body_lines = wrap_char(measure, body, body_f, body_max_w)

    tag_bb = measure.textbbox((0,0), subtitle, font=tag_f)
    tag_w = tag_bb[2]-tag_bb[0] + 56
    tag_h = tag_bb[3]-tag_bb[1] + 30

    # 카드 높이를 내용에 맞춰 계산 → 하단은 항상 H-80에 고정, 상단을 역산
    content_h = 40 + tag_h + 38 + len(body_lines)*body_lh + 20 + 46
    card_bottom = H - 80
    card_y = max(400, card_bottom - content_h)

    # 1단계: 반투명 요소(장식 + 숫자 + 카드)를 한 레이어에 그려 1회 합성
    layer, ld = overlay_layer()
    draw_glow_circles(ld, seed=idx*17 + 3)

    num = f"{idx+1:02d}"
    nf = font(FONT_BLACK, 300)
    nb = ld.textbbox((0,0), num, font=nf)
    ld.text((W - (nb[2]-nb[0]) - 40, 10), num, font=nf, fill=(255, 255, 255, 46))

    rounded_rect(ld, (card_margin, card_y, W-card_margin, card_bottom), 32, (0, 0, 0, 115))
    img = composite(img, layer)

    # 2단계: 상단 큰 이모지
    emoji = scene.get("emoji", "")
    if emoji:
        paste_emoji(img, emoji, W//2 - 70, card_y//2 + 30, 240)

    # 3단계: 불투명 요소
    d = ImageDraw.Draw(img, "RGBA")

    tag_x = card_margin + 45
    tag_y = card_y + 40
    rounded_rect(d, (tag_x, tag_y, tag_x+tag_w, tag_y+tag_h), 16, t["tag_bg"])
    d.text((tag_x+28, tag_y+9), subtitle, font=tag_f, fill=t["tag_fg"])

    body_x = card_margin + 45
    body_y = tag_y + tag_h + 38
    for line in body_lines:
        if body_y > card_bottom - 70:
            break
        d.text((body_x, body_y), line, font=body_f, fill=WHITE)
        body_y += body_lh

    # 출처
    attr = sc.get("meta", {}).get("attribution", "")
    if attr:
        af = font(FONT_REG, 20)
        d.text((card_margin+45, card_bottom-38), f"출처: {attr}", font=af, fill=(255, 255, 255, 135))

    dots(d, idx+2, total, t)
    return img

# ── 아웃트로 ────────────────────
def make_outro(sc, t, total):
    img = gradient_bg(t["grad2"], t["grad1"])

    layer, ld = overlay_layer()
    draw_glow_circles(ld, seed=999)
    cw, ch = 470, 94
    handle_y = 905
    rounded_rect(ld, ((W-cw)//2, handle_y, (W+cw)//2, handle_y+ch), 26, (0, 0, 0, 105))
    img = composite(img, layer)

    d = ImageDraw.Draw(img, "RGBA")

    # 큰 체크마크
    cy, cr, cx = 290, 92, W//2
    d.ellipse([cx-cr, cy-cr, cx+cr, cy+cr], fill=t["accent"])
    d.line([(cx-42, cy+4), (cx-10, cy+36)], fill=t["tag_fg"], width=12)
    d.line([(cx-10, cy+36), (cx+46, cy-28)], fill=t["tag_fg"], width=12)

    y = cy + cr + 64
    f1 = font(FONT_BLACK, 54)
    for txt, col in [("도움이 되셨다면", WHITE), ("팔로우 & 저장 해주세요!", t["accent"])]:
        bb = d.textbbox((0,0), txt, font=f1)
        d.text(((W-(bb[2]-bb[0]))//2, y), txt, font=f1, fill=col)
        y += 80

    y += 24
    f2 = font(FONT_MED, 32)
    for txt in ["매일 알아두면 좋은 생활 정보를", "카드뉴스로 전해드립니다"]:
        bb = d.textbbox((0,0), txt, font=f2)
        d.text(((W-(bb[2]-bb[0]))//2, y), txt, font=f2, fill=(255, 255, 255, 210))
        y += 50

    # 핸들
    hf = font(FONT_BOLD, 38)
    handle = "@richup_bm_sw"
    hb = d.textbbox((0,0), handle, font=hf)
    d.text(((W-(hb[2]-hb[0]))//2, handle_y+24), handle, font=hf, fill=t["accent"])

    # CTA (이모지 + 텍스트 분리 렌더)
    y = handle_y + ch + 62
    labels = [("❤️", "좋아요"), ("💬", "댓글"), ("📌", "저장")]
    sf = font(FONT_BOLD, 28)
    for i, (em, lb) in enumerate(labels):
        bb = d.textbbox((0,0), lb, font=sf)
        lx = W//4*(i+1) - (bb[2]-bb[0] + 44)//2
        paste_emoji(img, em, lx + 16, y + 18, 32)
        d = ImageDraw.Draw(img, "RGBA")
        d.text((lx + 44, y), lb, font=sf, fill=(255, 255, 255, 215))

    dots(d, total, total, t)
    return img

# ── 메인 ────────────────────────
def generate(script_path, out_dir):
    with open(script_path, encoding="utf-8") as f:
        sc = json.load(f)
    os.makedirs(out_dir, exist_ok=True)
    cat = sc.get("meta", {}).get("category", "")
    t = get_t(cat)
    total = len(sc.get("scenes", [])) + 2
    pages = []

    p = os.path.join(out_dir, "01_cover.png")
    make_cover(sc, t).save(p, quality=95)
    pages.append(p)

    for i in range(len(sc.get("scenes", []))):
        p = os.path.join(out_dir, f"{i+2:02d}_scene.png")
        make_scene(sc, i, total, t).save(p, quality=95)
        pages.append(p)

    p = os.path.join(out_dir, f"{total:02d}_outro.png")
    make_outro(sc, t, total).save(p, quality=95)
    pages.append(p)

    print(f"카드뉴스 {len(pages)}장 생성 → {out_dir}")
    return pages

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("-o", "--out", default="out/cards")
    a = ap.parse_args()
    generate(a.script, a.out)
