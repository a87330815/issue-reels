# -*- coding: utf-8 -*-
"""
cardnews.py — 인스타그램 카드뉴스 생성기 v3

1080x1350 (4:5) 카드뉴스. 참고: @newneek.official 스타일
- 커버: 훅 타이틀 3줄 + 카테고리 태그
- 본문: 상단 비주얼(번호+제목+아이콘 영역) + 하단 상세 텍스트
- 아웃트로: 팔로우 CTA
"""
import argparse, json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1080, 1350

FONT_BLACK = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
FONT_BOLD  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_MED   = "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"
FONT_REG   = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

def font(path, size):
    return ImageFont.truetype(path, size, index=1)

# ── 테마 ────────────────────────
THEMES = {
    "교통":    {"bg1": (10,22,40),  "bg2": (5,15,30),   "acc": (0,212,170),  "acc2": (0,180,216)},
    "생활":    {"bg1": (15,10,30),  "bg2": (10,5,25),    "acc": (167,139,250),"acc2": (129,140,248)},
    "돈·물가": {"bg1": (26,16,0),   "bg2": (20,12,0),    "acc": (251,191,36), "acc2": (245,158,11)},
    "주거":    {"bg1": (10,22,40),  "bg2": (5,15,30),    "acc": (96,165,250), "acc2": (59,130,246)},
    "안전":    {"bg1": (26,10,10),  "bg2": (20,5,5),     "acc": (248,113,113),"acc2": (239,68,68)},
}
DEF = {"bg1": (15,23,42), "bg2": (10,18,35), "acc": (56,189,248), "acc2": (14,165,233)}

def get_t(cat):
    return THEMES.get(cat, DEF)

WHITE = (255,255,255)
GRAY  = (176,190,197)
DARK  = (20,20,25)

# ── 배경 ────────────────────────
def make_bg(t, seed=0):
    a = np.full((H,W,3), t["bg1"], dtype=np.float64)
    Y, X = np.ogrid[:H,:W]
    for cx,cy,color,s in [
        (W*(0.75+seed*0.03%0.2), H*0.15, t["acc"], 300),
        (W*(0.2+seed*0.04%0.2), H*0.85, t["acc2"], 340),
    ]:
        d = np.sqrt((X-cx)**2+(Y-cy)**2)
        g = np.exp(-d**2/(2*s**2))
        for c in range(3):
            a[:,:,c] += g * color[c] * 0.2
    return Image.fromarray(np.clip(a,0,255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2))

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

def wrap(draw, text, fnt, max_w):
    words = list(text)
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

def text_center(draw, text, y, fnt, fill, max_w=W-120):
    lines = wrap_words(draw, text, fnt, max_w)
    lh = fnt.size + 14
    for l in lines:
        bb = draw.textbbox((0,0), l, font=fnt)
        draw.text(((W-(bb[2]-bb[0]))/2, y), l, font=fnt, fill=fill)
        y += lh
    return y

def dots(draw, cur, total, t):
    r = 7
    gap = 18
    tw = total * r*2 + (total-1)*gap
    sx = (W-tw)/2
    y = H-50
    for i in range(total):
        cx = sx + i*(r*2+gap) + r
        fill = t["acc"] if i+1==cur else (*GRAY, 80)
        draw.ellipse([cx-r,y-r,cx+r,y+r], fill=fill)


# ── 커버 ────────────────────────
def make_cover(sc, t):
    img = make_bg(t)
    d = ImageDraw.Draw(img)
    cat = sc.get("meta",{}).get("category","")
    lines = sc.get("cover",{}).get("lines",[sc.get("title","")])

    # 카테고리 태그
    if cat:
        tf = font(FONT_MED, 30)
        tag = f"# {cat}"
        bb = d.textbbox((0,0), tag, font=tf)
        tw, th = bb[2]-bb[0]+40, bb[3]-bb[1]+24
        bx = (W-tw)/2
        by = 180
        rounded_rect(d, (bx, by, bx+tw, by+th), 20, (*t["acc"], 40))
        d.text((bx+20, by+8), tag, font=tf, fill=t["acc"])

    # 메인 타이틀
    y = H * 0.30
    tf = font(FONT_BLACK, 88)
    for line in lines:
        clean = line.replace("<r>","").replace("</r>","").replace("<y>","").replace("</y>","")
        is_acc = "<r>" in line or "<y>" in line
        bb = d.textbbox((0,0), clean, font=tf)
        x = (W-(bb[2]-bb[0]))/2
        d.text((x, y), clean, font=tf, fill=t["acc"] if is_acc else WHITE)
        y += 110

    # 하단 장식선
    y2 = H - 200
    d.line([(W*0.25, y2), (W*0.75, y2)], fill=(*t["acc"], 50), width=2)

    # 출처
    attr = sc.get("meta",{}).get("attribution","")
    if attr:
        af = font(FONT_REG, 22)
        text_center(d, f"출처: {attr}", H-160, af, GRAY)

    # 스와이프 힌트
    sf = font(FONT_REG, 26)
    text_center(d, "👉 밀어서 자세히 보기", H-100, sf, (*t["acc"],180))

    dots(d, 1, len(sc.get("scenes",[]))+2, t)
    return img


# ── 본문 슬라이드 ────────────────
def make_scene(sc, idx, total, t):
    img = make_bg(t, seed=idx+1)
    d = ImageDraw.Draw(img)
    scene = sc["scenes"][idx]
    details = scene.get("details", [])
    cat = sc.get("meta",{}).get("category","")

    # ── 상단 비주얼 영역 (0 ~ 480px) ──
    # 큰 번호
    num = str(idx + 1)
    nf = font(FONT_BLACK, 200)
    nb = d.textbbox((0,0), num, font=nf)
    nx = 70
    ny = 40
    # 번호를 accent 반투명으로
    overlay = Image.new("RGBA", (W, H), (0,0,0,0))
    od = ImageDraw.Draw(overlay)
    od.text((nx, ny), num, font=nf, fill=(*t["acc"], 60))
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"))
    d = ImageDraw.Draw(img)

    # 소제목
    sub = scene.get("subtitle", "")
    sf = font(FONT_BLACK, 54)
    sub_lines = wrap_words(d, sub, sf, W - 160)
    sy = 120
    for sl in sub_lines:
        d.text((80, sy), sl, font=sf, fill=WHITE)
        sy += 68

    # narration (요약)
    nar = scene.get("narration", "")
    nrf = font(FONT_REG, 32)
    ny2 = max(sy + 20, 260)
    if nar:
        nar_lines = wrap_words(d, nar, nrf, W - 160)
        for nl in nar_lines:
            d.text((80, ny2), nl, font=nrf, fill=GRAY)
            ny2 += 46

    # 제목 타이틀 바
    bar_y = ny2 + 30
    d.line([(60, bar_y), (W-60, bar_y)], fill=(*t["acc"], 80), width=3)
    title_f = font(FONT_MED, 24)
    d.text((80, bar_y + 12), sc.get("title",""), font=title_f, fill=(*t["acc"],160))

    # ── 하단 상세 영역 ──
    card_top = bar_y + 50
    card_margin = 40
    card_bottom = H - 80  # 항상 하단까지

    if details:
        detail_f = font(FONT_MED, 38)
        bold_f = font(FONT_BOLD, 40)
        text_x = card_margin + 75
        avail_w = W - text_x - card_margin - 20

        # 카드 배경
        card_bg = tuple(max(0, c+12) for c in t["bg1"])
        rounded_rect(d, (card_margin, card_top, W-card_margin, card_bottom), 24, card_bg)

        # 좌측 accent 바
        d.rectangle([card_margin, card_top+24, card_margin+5, card_bottom-24], fill=t["acc"])

        # 아이템 간격 균등 배분
        n = len(details)
        usable_h = card_bottom - card_top - 60  # 상하 패딩 30씩
        slot_h = usable_h // n

        for i, det in enumerate(details):
            by = card_top + 30 + i * slot_h

            # 번호 원
            cr = 22
            cx = card_margin + 40
            cy = by + 20
            d.ellipse([cx-cr, cy-cr, cx+cr, cy+cr], fill=t["acc"])
            nf2 = font(FONT_BOLD, 26)
            nt = str(i+1)
            nb2 = d.textbbox((0,0), nt, font=nf2)
            d.text((cx-(nb2[2]-nb2[0])//2, cy-(nb2[3]-nb2[1])//2-1), nt, font=nf2, fill=DARK)

            # 텍스트
            dl = wrap_words(d, det, detail_f, avail_w)
            ty = by + 4
            for j, line in enumerate(dl):
                if j == 0 and (":" in line or "：" in line):
                    sep = ":" if ":" in line else "："
                    parts = line.split(sep, 1)
                    d.text((text_x, ty), parts[0]+sep, font=bold_f, fill=WHITE)
                    bw = d.textbbox((0,0), parts[0]+sep, font=bold_f)[2]
                    if len(parts) > 1:
                        d.text((text_x+bw+6, ty), parts[1].strip(), font=detail_f, fill=GRAY)
                else:
                    d.text((text_x, ty), line, font=detail_f, fill=WHITE if j==0 else GRAY)
                ty += 56

            # 구분선 (마지막 아이템 제외)
            if i < n - 1:
                sep_y = card_top + 30 + (i+1) * slot_h - 8
                d.line([(text_x, sep_y), (W-card_margin-30, sep_y)], fill=(*GRAY,40), width=1)

    dots(d, idx+2, total, t)
    return img


# ── 아웃트로 ────────────────────
def make_outro(sc, t, total):
    img = make_bg(t, seed=99)
    d = ImageDraw.Draw(img)

    # 체크
    cy = int(H * 0.22)
    cr = 80
    cx = W // 2
    d.ellipse([cx-cr, cy-cr, cx+cr, cy+cr], fill=t["acc"])
    pts = [(cx-35,cy+5),(cx-10,cy+30),(cx+40,cy-25)]
    d.line(pts[:2], fill=DARK, width=10)
    d.line(pts[1:], fill=DARK, width=10)

    y = cy + cr + 60
    f1 = font(FONT_BLACK, 52)
    text_center(d, "도움이 되셨다면", y, f1, WHITE)
    y += 80
    text_center(d, "팔로우 & 저장 해주세요", y, f1, t["acc"])

    y += 110
    f2 = font(FONT_REG, 32)
    text_center(d, "매일 알아두면 좋은 생활 정보를", y, f2, GRAY)
    y += 50
    text_center(d, "카드뉴스로 전해드립니다", y, f2, GRAY)

    y += 80
    cw, ch = 480, 90
    cx2 = (W-cw)//2
    card_bg = tuple(max(0,c+15) for c in t["bg1"])
    rounded_rect(d, (cx2, y, cx2+cw, y+ch), 24, card_bg)
    hf = font(FONT_BOLD, 36)
    handle = "@richup_bm_sw"
    hb = d.textbbox((0,0), handle, font=hf)
    d.text(((W-(hb[2]-hb[0]))//2, y+24), handle, font=hf, fill=t["acc"])

    y += ch + 60
    sf = font(FONT_REG, 28)
    labels = ["♥ 좋아요", "💬 댓글", "📌 저장"]
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
