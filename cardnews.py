# -*- coding: utf-8 -*-
"""
cardnews.py — 인스타그램 카드뉴스 생성기 v4

1080x1350 (4:5) 카드뉴스. 뉴닉(@newneek.official) 스타일 참고
- 밝은 배경 + 상단 대형 비주얼(그래픽) + 컬러 태그 + 문단형 본문
- 슬라이드마다 다른 비주얼 패턴
"""
import argparse, json, math, os, sys, random
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1080, 1350

FONT_BLACK = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
FONT_BOLD  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_MED   = "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"
FONT_REG   = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_LIGHT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Light.ttc"

def font(path, size):
    return ImageFont.truetype(path, size, index=1)

# ── 테마 (밝은 배경 + 포인트 컬러) ────
THEMES = {
    "교통":    {"bg": (245,248,255), "card": (230,240,255), "acc": (0,120,200),  "acc2": (0,90,180),  "tag_bg": (220,238,255), "tag_fg": (0,100,180)},
    "생활":    {"bg": (250,245,255), "card": (240,230,255), "acc": (130,80,220),  "acc2": (100,60,200),"tag_bg": (235,225,255), "tag_fg": (110,60,200)},
    "돈·물가": {"bg": (255,250,240), "card": (255,245,225), "acc": (200,150,0),   "acc2": (180,130,0), "tag_bg": (255,243,210), "tag_fg": (170,120,0)},
    "주거":    {"bg": (240,248,255), "card": (225,240,255), "acc": (50,130,220),  "acc2": (30,100,200),"tag_bg": (215,235,255), "tag_fg": (40,110,200)},
    "안전":    {"bg": (255,245,245), "card": (255,235,235), "acc": (220,60,60),   "acc2": (200,40,40), "tag_bg": (255,225,225), "tag_fg": (200,50,50)},
}
DEF = {"bg": (245,248,252), "card": (230,238,248), "acc": (50,140,220), "acc2": (30,110,200), "tag_bg": (220,235,255), "tag_fg": (40,120,200)}

def get_t(cat):
    return THEMES.get(cat, DEF)

DARK  = (30, 30, 35)
GRAY  = (120, 125, 135)
LGRAY = (180, 185, 195)
WHITE = (255, 255, 255)

# ── 유틸 ────────────────────────
def rounded_rect(draw, xy, r, fill):
    x0,y0,x1,y1 = xy
    r = min(r, (x1-x0)//2, (y1-y0)//2)
    if r < 1:
        draw.rectangle(xy, fill=fill)
        return
    draw.rectangle([x0+r,y0,x1-r,y1], fill=fill)
    draw.rectangle([x0,y0+r,x1,y1-r], fill=fill)
    draw.pieslice([x0,y0,x0+2*r,y0+2*r], 180, 270, fill=fill)
    draw.pieslice([x1-2*r,y0,x1,y0+2*r], 270, 360, fill=fill)
    draw.pieslice([x0,y1-2*r,x0+2*r,y1], 90, 180, fill=fill)
    draw.pieslice([x1-2*r,y1-2*r,x1,y1], 0, 90, fill=fill)

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
    if cur: lines.append(cur)
    return lines

def wrap_char(draw, text, fnt, max_w):
    lines, cur = [], ""
    for ch in text:
        test = cur + ch
        if draw.textbbox((0,0), test, font=fnt)[2] > max_w and cur:
            lines.append(cur)
            cur = ch
        else:
            cur = test
    if cur: lines.append(cur)
    return lines

def text_center(draw, text, y, fnt, fill, max_w=W-120):
    lines = wrap_words(draw, text, fnt, max_w)
    lh = fnt.size + 14
    for l in lines:
        bb = draw.textbbox((0,0), l, font=fnt)
        draw.text(((W-(bb[2]-bb[0]))/2, y), l, font=fnt, fill=fill)
        y += lh
    return y

def dots(draw, cur, total, t):
    r = 6
    gap = 16
    tw = total * r*2 + (total-1)*gap
    sx = (W-tw)/2
    y = H-45
    for i in range(total):
        cx = sx + i*(r*2+gap) + r
        fill = t["acc"] if i+1==cur else (*LGRAY, 120)
        draw.ellipse([cx-r,y-r,cx+r,y+r], fill=fill)

# ── 비주얼 패턴 생성 (사진 대신) ──────
def visual_pattern_circles(img, t, seed):
    """큰 원 + 작은 원들 패턴"""
    d = ImageDraw.Draw(img, "RGBA")
    rng = random.Random(seed)
    # 대형 원
    cx, cy = W//2 + rng.randint(-100, 100), 320 + rng.randint(-40, 40)
    r = rng.randint(180, 240)
    d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(*t["acc"], 35))
    r2 = r - 30
    d.ellipse([cx-r2, cy-r2, cx+r2, cy+r2], fill=(*t["acc"], 25))
    # 장식 원들
    for _ in range(rng.randint(5, 9)):
        sx = rng.randint(60, W-60)
        sy = rng.randint(60, 550)
        sr = rng.randint(15, 60)
        alpha = rng.randint(15, 40)
        color = t["acc"] if rng.random() > 0.4 else t["acc2"]
        d.ellipse([sx-sr, sy-sr, sx+sr, sy+sr], fill=(*color, alpha))
    return img

def visual_pattern_blocks(img, t, seed):
    """둥근 사각형 블록 패턴"""
    d = ImageDraw.Draw(img, "RGBA")
    rng = random.Random(seed)
    positions = [(100, 120, 420, 380), (500, 80, 780, 340),
                 (620, 300, 950, 520), (60, 350, 380, 540)]
    rng.shuffle(positions)
    for i, (x0,y0,x1,y1) in enumerate(positions[:rng.randint(2,4)]):
        ox, oy = rng.randint(-30,30), rng.randint(-30,30)
        alpha = rng.randint(18, 40)
        color = t["acc"] if i % 2 == 0 else t["acc2"]
        rounded_rect(d, (x0+ox, y0+oy, x1+ox, y1+oy), rng.randint(24,48), (*color, alpha))
    # 작은 장식
    for _ in range(rng.randint(3,6)):
        sx = rng.randint(60, W-60)
        sy = rng.randint(80, 520)
        sw = rng.randint(30, 80)
        sh = rng.randint(30, 80)
        rounded_rect(d, (sx, sy, sx+sw, sy+sh), 12, (*t["acc2"], rng.randint(12,30)))
    return img

def visual_pattern_lines(img, t, seed):
    """대각선/곡선 패턴"""
    d = ImageDraw.Draw(img, "RGBA")
    rng = random.Random(seed)
    # 큰 대각 스트라이프
    for i in range(rng.randint(4,7)):
        y_start = rng.randint(60, 500)
        thickness = rng.randint(40, 100)
        alpha = rng.randint(15, 35)
        color = t["acc"] if i % 2 == 0 else t["acc2"]
        pts = []
        for x in range(0, W+10, 10):
            y = y_start + x * rng.uniform(0.2, 0.6) + math.sin(x/100)*30
            pts.append((x, y))
        for x in range(W, -10, -10):
            y = y_start + thickness + x * rng.uniform(0.2, 0.6) + math.sin(x/100)*30
            pts.append((x, y))
        if len(pts) >= 3:
            d.polygon(pts, fill=(*color, alpha))
    # 장식 점
    for _ in range(rng.randint(6,12)):
        sx = rng.randint(40, W-40)
        sy = rng.randint(60, 530)
        sr = rng.randint(4, 12)
        d.ellipse([sx-sr, sy-sr, sx+sr, sy+sr], fill=(*t["acc"], rng.randint(30,60)))
    return img

def visual_pattern_grid(img, t, seed):
    """도트 그리드 + 강조 영역"""
    d = ImageDraw.Draw(img, "RGBA")
    rng = random.Random(seed)
    # 큰 강조 영역
    cx, cy = W//2 + rng.randint(-150, 150), 300 + rng.randint(-50, 50)
    rw, rh = rng.randint(200, 350), rng.randint(150, 250)
    rounded_rect(d, (cx-rw, cy-rh, cx+rw, cy+rh), 40, (*t["acc"], 22))
    # 도트 그리드
    gap = rng.randint(50, 70)
    dr = rng.randint(4, 7)
    for x in range(gap, W-gap//2, gap):
        for y in range(80, 560, gap):
            dist = math.sqrt((x-cx)**2 + (y-cy)**2)
            alpha = max(8, min(50, int(60 - dist/10)))
            d.ellipse([x-dr, y-dr, x+dr, y+dr], fill=(*t["acc2"], alpha))
    return img

VISUAL_PATTERNS = [visual_pattern_circles, visual_pattern_blocks, visual_pattern_lines, visual_pattern_grid]

# ── 커버 ────────────────────────
def make_cover(sc, t):
    img = Image.new("RGB", (W, H), t["bg"])
    d = ImageDraw.Draw(img, "RGBA")
    cat = sc.get("meta",{}).get("category","")
    lines = sc.get("cover",{}).get("lines",[sc.get("title","")])

    # 상단 비주얼
    visual_pattern_circles(img, t, seed=42)
    d = ImageDraw.Draw(img, "RGBA")

    # 카테고리 태그 (상단)
    if cat:
        tf = font(FONT_BOLD, 28)
        tag = f"# {cat}"
        bb = d.textbbox((0,0), tag, font=tf)
        tw, th = bb[2]-bb[0]+36, bb[3]-bb[1]+20
        bx = (W-tw)/2
        by = 160
        rounded_rect(d, (bx, by, bx+tw, by+th), 20, t["tag_bg"])
        d.text((bx+18, by+7), tag, font=tf, fill=t["tag_fg"])

    # 메인 타이틀
    y = H * 0.42
    tf = font(FONT_BLACK, 80)
    for line in lines:
        clean = line.replace("<r>","").replace("</r>","").replace("<y>","").replace("</y>","")
        is_acc = "<r>" in line or "<y>" in line
        bb = d.textbbox((0,0), clean, font=tf)
        x = (W-(bb[2]-bb[0]))/2
        d.text((x, y), clean, font=tf, fill=t["acc"] if is_acc else DARK)
        y += 100

    # 부제
    sub = sc.get("title","")
    if sub:
        sf = font(FONT_REG, 32)
        y += 20
        text_center(d, sub, y, sf, GRAY)

    # 하단 장식
    y2 = H - 180
    d.line([(W*0.3, y2), (W*0.7, y2)], fill=(*t["acc"], 60), width=2)

    # 출처
    attr = sc.get("meta",{}).get("attribution","")
    if attr:
        af = font(FONT_REG, 20)
        text_center(d, f"출처: {attr}", H-140, af, LGRAY)

    # 스와이프
    sf = font(FONT_MED, 24)
    text_center(d, "👉 밀어서 자세히 보기", H-90, sf, t["acc"])

    dots(d, 1, len(sc.get("scenes",[]))+2, t)
    return img

# ── 본문 슬라이드 ────────────────
def make_scene(sc, idx, total, t):
    img = Image.new("RGB", (W, H), t["bg"])
    scene = sc["scenes"][idx]
    cat = sc.get("meta",{}).get("category","")

    # 슬라이드마다 다른 비주얼 패턴
    pattern = VISUAL_PATTERNS[idx % len(VISUAL_PATTERNS)]
    pattern(img, t, seed=idx*17+7)
    d = ImageDraw.Draw(img, "RGBA")

    # ── 상단 영역: 큰 숫자 워터마크 ──
    num = f"0{idx+1}"
    nf = font(FONT_BLACK, 260)
    nb = d.textbbox((0,0), num, font=nf)
    nx = W - (nb[2]-nb[0]) - 60
    d.text((nx, 30), num, font=nf, fill=(*t["acc"], 25))

    # ── 중간: 컬러 태그 + 소제목 ──
    subtitle = scene.get("subtitle", "")
    emoji = scene.get("emoji", "")
    tag_text = f" {emoji} {subtitle} " if emoji else f" {subtitle} "

    tag_f = font(FONT_BOLD, 34)
    tag_bb = d.textbbox((0,0), tag_text, font=tag_f)
    tag_w = tag_bb[2] - tag_bb[0] + 40
    tag_h = tag_bb[3] - tag_bb[1] + 24
    tag_x = 70
    tag_y = 600

    rounded_rect(d, (tag_x, tag_y, tag_x+tag_w, tag_y+tag_h), 16, t["tag_bg"])
    d.text((tag_x+20, tag_y+8), tag_text, font=tag_f, fill=t["tag_fg"])

    # ── 하단: 본문 텍스트 (문단형) ──
    body = scene.get("body", "")
    # fallback: details가 있으면 합쳐서 body로
    if not body:
        details = scene.get("details", [])
        narration = scene.get("narration", "")
        if narration:
            body = narration + " "
        body += " ".join(details)

    body_f = font(FONT_REG, 34)
    body_x = 70
    body_y = tag_y + tag_h + 35
    body_max_w = W - 140
    body_lh = 54

    body_lines = wrap_char(d, body, body_f, body_max_w)
    for line in body_lines:
        if body_y > H - 80:
            break
        d.text((body_x, body_y), line, font=body_f, fill=DARK)
        body_y += body_lh

    # 출처 (하단)
    attr = sc.get("meta",{}).get("attribution","")
    if attr:
        af = font(FONT_LIGHT, 20)
        src_y = H - 70
        d.text((70, src_y), f"출처: {attr}", font=af, fill=LGRAY)

    dots(d, idx+2, total, t)
    return img

# ── 아웃트로 ────────────────────
def make_outro(sc, t, total):
    img = Image.new("RGB", (W, H), t["bg"])
    d = ImageDraw.Draw(img, "RGBA")

    # 장식
    visual_pattern_grid(img, t, seed=999)
    d = ImageDraw.Draw(img, "RGBA")

    # 체크 원
    cy = int(H * 0.25)
    cr = 70
    cx = W // 2
    d.ellipse([cx-cr, cy-cr, cx+cr, cy+cr], fill=t["acc"])
    pts = [(cx-30, cy+5), (cx-8, cy+25), (cx+35, cy-20)]
    d.line(pts[:2], fill=WHITE, width=8)
    d.line(pts[1:], fill=WHITE, width=8)

    y = cy + cr + 50
    f1 = font(FONT_BLACK, 48)
    text_center(d, "도움이 되셨다면", y, f1, DARK)
    y += 75
    text_center(d, "팔로우 & 저장 해주세요!", y, f1, t["acc"])

    y += 100
    f2 = font(FONT_REG, 30)
    text_center(d, "매일 알아두면 좋은 생활 정보를", y, f2, GRAY)
    y += 46
    text_center(d, "카드뉴스로 전해드립니다", y, f2, GRAY)

    # 핸들 카드
    y += 70
    cw, ch = 440, 80
    cx2 = (W-cw)//2
    rounded_rect(d, (cx2, y, cx2+cw, y+ch), 20, t["tag_bg"])
    hf = font(FONT_BOLD, 34)
    handle = "@richup_bm_sw"
    hb = d.textbbox((0,0), handle, font=hf)
    d.text(((W-(hb[2]-hb[0]))//2, y+20), handle, font=hf, fill=t["acc"])

    # CTA 버튼들
    y += ch + 50
    labels = ["♥ 좋아요", "💬 댓글", "📌 저장"]
    sf = font(FONT_MED, 26)
    for i, lb in enumerate(labels):
        lx = W//4*(i+1) - 50
        d.text((lx, y), lb, font=sf, fill=GRAY)

    dots(d, total, total, t)
    return img

# ── 메인 ────────────────────────
def generate(script_path, out_dir):
    with open(script_path, encoding="utf-8") as f:
        sc = json.load(f)
    os.makedirs(out_dir, exist_ok=True)
    cat = sc.get("meta",{}).get("category","")
    t = get_t(cat)
    total = len(sc.get("scenes",[]))+2
    pages = []

    p = os.path.join(out_dir, "01_cover.png")
    make_cover(sc, t).save(p, quality=95); pages.append(p)

    for i in range(len(sc.get("scenes",[]))):
        p = os.path.join(out_dir, f"{i+2:02d}_scene.png")
        make_scene(sc, i, total, t).save(p, quality=95); pages.append(p)

    p = os.path.join(out_dir, f"{total:02d}_outro.png")
    make_outro(sc, t, total).save(p, quality=95); pages.append(p)

    print(f"카드뉴스 {len(pages)}장 생성 → {out_dir}")
    return pages

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("-o","--out", default="out/cards")
    a = ap.parse_args()
    generate(a.script, a.out)
