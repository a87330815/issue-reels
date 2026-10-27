# -*- coding: utf-8 -*-
"""
cardnews.py — 인스타그램 카드뉴스 생성기 v5

1080x1350 (4:5) 카드뉴스
- 강렬한 그래디언트 배경 + 큰 이모지 아이콘
- 굵고 큰 텍스트 + 눈에 띄는 색상 조합
"""
import argparse, json, math, os, re, sys, random
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

W, H = 1080, 1350

def _pick_font(*names):
    """설치 위치가 배포판마다 달라서 후보 경로를 순서대로 탐색한다.
    못 찾으면 fc-match 로 시스템 전체를 탐색한다."""
    import subprocess, glob as _glob
    roots = ["/usr/share/fonts/opentype/noto", "/usr/share/fonts/truetype/noto",
             "/usr/share/fonts/opentype", "/usr/share/fonts/truetype",
             "/usr/local/share/fonts", os.path.expanduser("~/.fonts")]
    for n in names:
        if os.path.isabs(n) and os.path.exists(n):
            return n
        for r in roots:
            p = os.path.join(r, n)
            if os.path.exists(p):
                return p
        # 하위 디렉터리까지 재귀 탐색
        for r in ["/usr/share/fonts", "/usr/local/share/fonts"]:
            for p in _glob.glob(os.path.join(r, "**", n), recursive=True):
                if os.path.exists(p):
                    return p
    # fc-match 로 Noto Sans CJK 계열 폴백
    try:
        r = subprocess.run(["fc-match", "-f", "%{file}", "Noto Sans CJK KR"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip() and os.path.exists(r.stdout.strip()):
            return r.stdout.strip()
    except Exception:
        pass
    return None

FONT_BLACK = _pick_font("NotoSansCJK-Black.ttc", "NotoSansCJKkr-Black.otf", "NotoSansCJK-Bold.ttc")
FONT_BOLD  = _pick_font("NotoSansCJK-Bold.ttc", "NotoSansCJKkr-Bold.otf")
FONT_MED   = _pick_font("NotoSansCJK-Medium.ttc", "NotoSansCJKkr-Medium.otf", "NotoSansCJK-Regular.ttc")
FONT_REG   = _pick_font("NotoSansCJK-Regular.ttc", "NotoSansCJKkr-Regular.otf")
FONT_EMOJI = _pick_font("NotoColorEmoji.ttf")

_missing = [n for n, v in [("Black", FONT_BLACK), ("Bold", FONT_BOLD),
                           ("Medium", FONT_MED), ("Regular", FONT_REG)] if not v]
if _missing:
    sys.exit("한글 폰트를 찾을 수 없습니다 (%s). "
             "apt-get install fonts-noto-cjk fonts-noto-cjk-extra 로 설치하세요."
             % ", ".join(_missing))

def font(path, size):
    return ImageFont.truetype(path, size, index=1)

_emoji_cache = {}

def render_emoji(emoji, size):
    """컬러 이모지를 RGBA 이미지로 렌더링 (NotoColorEmoji는 109px 고정 → 리사이즈)"""
    if not FONT_EMOJI:
        return None
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

# ── 고정 문구 ──────────────────────
# 계정 말투가 경상도 사투리라, 이름만 사투리고 본문·안내가 표준어면
# 간판과 속이 따로 논다. 고정 문구도 같은 말투로 맞춘다.
# 핸들은 계정이 바뀔 수 있으므로 환경변수로 뺀다.
HANDLE = os.environ.get("IG_HANDLE", "@richup_bm_sw")
BRAND  = os.environ.get("IG_BRAND", "쫌봐봐")
# 브랜드명은 띄어쓰기 없이 그대로 박는다. "쫌 봐봐"로 띄우면 평범한 말이 되고,
# "쫌봐봐"로 붙여야 매 장마다 계정 이름이 그대로 각인된다.
UI = {
    "swipe":    f"옆으로 {BRAND}",
    "outro1":   "도움 됐으면",
    "outro2":   "팔로우하고 저장해두이소",
    "outro_s1": "세상 돌아가는 이야기",
    "outro_s2": f"매일 {BRAND}",
}

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

def load_photos(photo_dir):
    """photos.json 매니페스트를 읽어 슬롯→경로 매핑 반환."""
    if not photo_dir:
        return {}
    mpath = os.path.join(photo_dir, "photos.json")
    if not os.path.exists(mpath):
        return {}
    try:
        with open(mpath, encoding="utf-8") as f:
            man = json.load(f)
    except Exception:
        return {}
    out = {}
    for slot, fname in (man.get("photos") or {}).items():
        p = os.path.join(photo_dir, fname)
        if os.path.exists(p):
            out[slot] = p
    return out

def load_credits(photo_dir):
    """슬롯 → 사진 출처 문구. CC BY 계열은 표기가 라이선스 조건이라 카드에 찍는다."""
    if not photo_dir:
        return {}
    mpath = os.path.join(photo_dir, "photos.json")
    if not os.path.exists(mpath):
        return {}
    try:
        with open(mpath, encoding="utf-8") as f:
            man = json.load(f)
    except Exception:
        return {}
    out = {}
    for c in (man.get("credits") or []):
        lic = (c.get("license") or "").strip()
        creator = (c.get("creator") or "").strip()
        src = (c.get("source") or "").strip()
        # 퍼블릭도메인/CC0는 표기 의무가 없어 생략 (화면을 깨끗하게)
        if re.match(r"^(public domain|pd|cc0|pdm|no restrictions)", lic, re.I):
            continue
        # 뉴스 기사 보도사진은 카드 하단에 출처 줄을 따로 찍지 않는다
        if src == "news_article":
            continue
        parts = [p for p in (creator, src, lic) if p]
        if parts:
            out[c.get("slot", "")] = "사진 " + " / ".join(parts)
    return out

def photo_bg(path, t, darken_top=70, darken_bottom=215, blur=0):
    """사진을 풀블리드 배경으로 깔고, 아래로 갈수록 진해지는 어두운 그래디언트를 덮는다.
    텍스트 가독성을 확보하면서 사진이 그대로 보이게 한다.
    blur를 주면 배경이 차분해져 적합도가 낮은 사진도 덜 튄다."""
    im = Image.open(path).convert("RGB")
    if im.size != (W, H):
        # cover 크롭 (photos.py에서 이미 맞춰 오지만 방어적으로)
        sr, dr = im.width/im.height, W/H
        if sr > dr:
            nh, nw = H, max(W, int(round(H*sr)))
        else:
            nw, nh = W, max(H, int(round(W/sr)))
        im = im.resize((nw, nh), Image.LANCZOS)
        im = im.crop(((nw-W)//2, (nh-H)//2, (nw-W)//2+W, (nh-H)//2+H))

    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    else:
        # 무료 소스는 해상도가 낮아 1080x1350으로 확대하면 물러진다.
        # 언샤프 마스크로 윤곽을 살려 선명하게 보이게 한다.
        im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=125, threshold=3))

    # 채도·대비를 올려 색을 또렷하게
    im = ImageEnhance.Color(im).enhance(1.12)
    im = ImageEnhance.Contrast(im).enhance(1.12)
    im = ImageEnhance.Sharpness(im).enhance(1.3)

    # 세로 어두움 그래디언트 (위는 약하게, 아래로 갈수록 강하게)
    xs = np.linspace(0.0, 1.0, H)
    ease = xs ** 1.6
    ramp = (darken_top + (darken_bottom - darken_top) * ease).astype(np.uint8)
    alpha = np.repeat(ramp[:, None], W, axis=1)

    # 테마 색조를 살짝 섞은 어두운 오버레이
    tint = np.zeros((H, W, 3), dtype=np.uint8)
    base = tuple(int(v*0.35) for v in t["grad1"])
    for c in range(3):
        tint[:, :, c] = base[c]

    ov = np.dstack([tint, alpha])
    overlay = Image.fromarray(ov, mode="RGBA")
    out = im.convert("RGBA")
    out.alpha_composite(overlay)
    return out.convert("RGB")

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

# ── 본문 강조 마크업 ──────────────────
# 본문에 <y>…</y> 를 쓰면 그 구간만 포인트 컬러로 찍어 핵심 수치가 먼저 읽히게 한다.
_MARK_RE = re.compile(r"<(/?)([yr])>")

def parse_marked(text):
    """'<y>1800만원</y>까지' → [('1800만원', True), ('까지', False)]"""
    runs, buf, on = [], "", False
    pos = 0
    for m in _MARK_RE.finditer(text or ""):
        buf += text[pos:m.start()]
        closing = m.group(1) == "/"
        if (not closing) != on:
            if buf:
                runs.append((buf, on))
                buf = ""
            on = not closing
        pos = m.end()
    buf += (text or "")[pos:]
    if buf:
        runs.append((buf, on))
    return runs

# 숫자·영문은 한 덩어리로 묶어 줄 끝에서 쪼개지지 않게 한다.
# 숫자 뒤에 붙는 한글 단위까지 포함해 "10만원", "12월", "2개월"이 통째로 넘어가게 한다.
_TOKEN_RE = re.compile(
    r"[0-9][0-9,.·]*%?[가-힣]*|[A-Za-z][A-Za-z.'-]*|.", re.S)

def wrap_marked(draw, runs, fnt, max_w):
    """강조 구간을 유지한 채 줄바꿈. 줄마다 [(조각, 강조여부)] 반환."""
    lines, cur, cur_w = [], [], 0
    for txt, mark in runs:
        for tok in _TOKEN_RE.findall(txt):
            tw = draw.textlength(tok, font=fnt)
            if cur_w + tw > max_w and cur:
                lines.append(cur)
                cur, cur_w = [], 0
                if tok == " ":      # 줄머리 공백은 버린다
                    continue
            if cur and cur[-1][1] == mark:
                cur[-1] = (cur[-1][0] + tok, mark)
            else:
                cur.append((tok, mark))
            cur_w += tw
    if cur:
        lines.append(cur)
    return lines

def draw_marked_line(draw, line, x, y, fnt, normal, accent):
    """한 줄을 강조 구간별 색으로 이어 그린다."""
    for seg, mark in line:
        draw.text((x, y), seg, font=fnt, fill=accent if mark else normal)
        x += draw.textlength(seg, font=fnt)

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

# 릴스 모드. 영상에서는 넘겨볼 수 없으니 캐러셀용 안내(스와이프 문구·
# 페이지 점)를 그리지 않는다.
REELS = False

def dots(draw, cur, total, t):
    if REELS:
        return
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

# ══════════════════════════════════════════════════════
# 매거진 레이아웃 (이슈 매거진 스타일)
#
# 기존 레이아웃은 사진을 어둡게 덮고 그 위에 흰 글씨를 얹는다. 피드에서
# 축소돼 보일 때 사진도 글자도 함께 죽는 구조다. 매거진 레이아웃은 둘을
# 분리한다 — 위는 사진만, 아래는 흰 바탕에 검은 글씨. 사진은 보정 없이
# 밝게 두고, 글자는 최대 대비로 읽힌다.
# ══════════════════════════════════════════════════════

MAG_INK   = (17, 17, 17)         # 본문 먹색
MAG_BAND  = (168, 240, 232)      # 형광펜 민트
MAG_BAND2 = (255, 235, 59)       # 형광펜 옐로우 (커버 라벨)
PHOTO_H   = 756                  # 본문 슬라이드 사진 밴드 높이

_CASCADE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "assets", "cv", "haarcascade_frontalface_default.xml")
_cascade = None
_face_cache = {}

def face_box(path):
    """가장 큰 얼굴의 (중심x, 중심y, 높이)를 원본 대비 0~1 비율로 돌려준다.
    못 찾으면 None. 보도사진을 가로 밴드로 자를 때 얼굴이 잘리거나 너무 작게
    나오는 걸 막는 용도라, 실패해도 치명적이지 않다 — 호출부가 기본값으로 넘어간다."""
    if path in _face_cache:
        return _face_cache[path]
    result = None
    try:
        global _cascade
        import cv2
        if _cascade is None:
            if not os.path.exists(_CASCADE_PATH):
                _face_cache[path] = None
                return None
            _cascade = cv2.CascadeClassifier(_CASCADE_PATH)
        img = cv2.imread(path)
        if img is not None:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = _cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                              minSize=(40, 40))
            if len(faces):
                x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
                oh, ow = img.shape[0], img.shape[1]
                result = ((x + fw / 2) / ow, (y + fh / 2) / oh, fh / oh)
    except Exception:
        result = None
    _face_cache[path] = result
    return result

# 얼굴이 밴드 높이의 이 비율은 되도록 당겨 자른다. 전신 샷을 그대로 쓰면
# 피드에서 인물이 누군지 안 보여 카드가 밋밋해진다.
FACE_TARGET = 0.30
FACE_MAX_ZOOM = 2.3      # 원본 해상도가 버티는 선까지만. 넘으면 뭉개진다.
FACE_ANCHOR = 0.40       # 얼굴 중심이 밴드에서 차지할 세로 위치

def photo_band(path, w, h, sharpen=True, bias=0.5, face_aware=False):
    """사진을 w×h로 크롭. 어둡게 덮지 않고 밝기를 그대로 둔다.
    face_aware면 얼굴을 찾아 (1) 얼굴이 너무 작으면 당겨 자르고
    (2) 얼굴이 밴드 안에 들어오도록 크롭 지점을 잡는다."""
    im = Image.open(path).convert("RGB")
    ow, oh = im.size
    fb = face_box(path) if face_aware else None

    # 기본 배율 — 밴드를 꽉 채우는 cover 스케일
    s = max(w / ow, h / oh)

    if fb:
        fcx, fcy, fh_r = fb
        face_px = fh_r * oh
        want = (FACE_TARGET * h) / face_px      # 얼굴을 목표 크기로 만드는 배율
        s = max(s, min(want, s * FACE_MAX_ZOOM))

    nw, nh = max(w, int(round(ow * s))), max(h, int(round(oh * s)))
    im = im.resize((nw, nh), Image.LANCZOS)

    if fb:
        fcx, fcy, _ = fb
        left = int(round(fcx * nw - w / 2))
        top = int(round(fcy * nh - h * FACE_ANCHOR))
    else:
        left = (nw - w) // 2
        top = int(round((nh - h) * bias))
    left = max(0, min(nw - w, left))
    top = max(0, min(nh - h, top))
    im = im.crop((left, top, left + w, top + h))
    if sharpen:
        im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=3))
    im = ImageEnhance.Color(im).enhance(1.06)
    im = ImageEnhance.Contrast(im).enhance(1.05)
    return im

def center_marked(draw, line, cy_x, y, fnt, normal, accent):
    """강조 구간을 유지한 채 한 줄을 중앙정렬로 그린다."""
    total = sum(draw.textlength(seg, font=fnt) for seg, _ in line)
    x = cy_x - total / 2
    for seg, mark in line:
        draw.text((x, y), seg, font=fnt, fill=accent if mark else normal)
        x += draw.textlength(seg, font=fnt)

def highlight_text(d, text, cx, y, fnt, band_color, pad_x=22, pad_y=10, ink=MAG_INK):
    """형광펜으로 그은 듯한 밴드를 깔고 그 위에 검은 글씨를 올린다."""
    bb = d.textbbox((0, 0), text, font=fnt)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    x0 = cx - tw / 2 - pad_x
    x1 = cx + tw / 2 + pad_x
    rounded_rect(d, (x0, y - pad_y, x1, y + th + bb[1] + pad_y), 12, band_color)
    d.text((cx - tw / 2 - bb[0], y - bb[1] + bb[1]), text, font=fnt, fill=ink)
    return th + pad_y * 2

def make_cover_mag(sc, t, photo=None, credit=None):
    """커버 — 사진 전면, 하단에 큰 제목. 사진을 가리지 않는다."""
    if photo:
        img = photo_band(photo, W, H).convert("RGB")
        # 글자가 앉을 아래쪽만 어둡게. 위쪽 사진은 건드리지 않는다.
        xs = np.linspace(0.0, 1.0, H)
        ramp = np.clip((xs - 0.46) / 0.54, 0, 1) ** 1.35 * 205
        alpha = np.repeat(ramp.astype(np.uint8)[:, None], W, axis=1)
        tint = np.zeros((H, W, 3), dtype=np.uint8)
        ov = Image.fromarray(np.dstack([tint, alpha]), mode="RGBA")
        base = img.convert("RGBA")
        base.alpha_composite(ov)
        img = base.convert("RGB")
    else:
        img = gradient_bg_diagonal(t["grad1"], t["grad2"])

    d = ImageDraw.Draw(img, "RGBA")
    lines = sc.get("cover", {}).get("lines", [sc.get("title", "")])
    cat = sc.get("meta", {}).get("category", "")

    # 제목을 아래에서부터 쌓아 올린다 — 바닥 여백 고정
    tf = font(FONT_BLACK, 92)
    lh = 112
    clean = [l.replace("<r>", "").replace("</r>", "").replace("<y>", "").replace("</y>", "")
             for l in lines]
    acc = ["<r>" in l or "<y>" in l for l in lines]
    bottom = H - 128
    top = bottom - len(clean) * lh

    # 카테고리 라벨 — 제목 바로 위에 작은 형광 밴드
    if cat:
        lf = font(FONT_BOLD, 32)
        highlight_text(d, cat, W // 2, top - 74, lf, MAG_BAND2, pad_x=20, pad_y=9)

    y = top
    for txt, is_acc in zip(clean, acc):
        bb = d.textbbox((0, 0), txt, font=tf)
        x = (W - (bb[2] - bb[0])) // 2 - bb[0]
        d.text((x, y), txt, font=tf,
               fill=t["accent"] if is_acc else WHITE,
               stroke_width=7, stroke_fill=(0, 0, 0))
        y += lh

    # 브랜드 워드마크 — 좌상단에 작게. 사진을 가리지 않는다.
    if BRAND:
        bf = font(FONT_BLACK, 34)
        d.text((48, 46), BRAND, font=bf, fill=WHITE,
               stroke_width=5, stroke_fill=(0, 0, 0))

    if not REELS:
        sf = font(FONT_BOLD, 27)
        swipe = UI["swipe"]
        bb = d.textbbox((0, 0), swipe, font=sf)
        sx = (W - (bb[2] - bb[0]) - 44) // 2
        paste_emoji(img, "👉", sx + 16, H - 62, 32)
        d = ImageDraw.Draw(img, "RGBA")
        d.text((sx + 44, H - 76), swipe, font=sf, fill=WHITE,
               stroke_width=4, stroke_fill=(0, 0, 0))
    return img

def make_scene_mag(sc, idx, total, t, photo=None, credit=None):
    """본문 — 위는 사진 밴드, 아래는 흰 바탕에 검은 글씨."""
    scene = sc["scenes"][idx]
    img = Image.new("RGB", (W, H), (255, 255, 255))

    if photo:
        # 얼굴을 못 찾으면(옆모습·뒷모습) 위쪽을 남기는 쪽으로 기운다.
        # 보도사진은 인물이 위쪽에 서 있어 중앙 크롭은 거의 항상 머리를 자른다.
        img.paste(photo_band(photo, W, PHOTO_H, bias=0.12, face_aware=True), (0, 0))
    else:
        band = gradient_bg(t["grad1"], t["grad2"]).crop((0, 0, W, PHOTO_H))
        img.paste(band, (0, 0))

    d = ImageDraw.Draw(img, "RGBA")

    body = scene.get("body", "")
    if not body:
        narration = scene.get("narration", "")
        body = (narration + " " if narration else "") + " ".join(scene.get("details", []))

    subtitle = scene.get("subtitle", "")
    cx = W // 2

    # 소제목 — 형광펜 밴드. 길면 줄여서 한 줄에 맞춘다.
    sf = bb_sub = None
    if subtitle:
        size = 44
        while size > 30:
            sf = font(FONT_BLACK, size)
            if d.textlength(subtitle, font=sf) <= W - 150:
                break
            size -= 2
        sf = font(FONT_BLACK, size)
        bb_sub = d.textbbox((0, 0), subtitle, font=sf)

    # 본문 — 검은 굵은 글씨, 중앙정렬. 흰 영역에 맞춰 크기를 자동 조절한다.
    avail = H - PHOTO_H - 80
    sub_h = (bb_sub[3] - bb_sub[1] + 46 + 18) if bb_sub else 0
    for size, lh in ((48, 66), (45, 62), (42, 58), (39, 54), (36, 50), (33, 46)):
        bf = font(FONT_BOLD, size)
        lines = wrap_marked(d, parse_marked(body), bf, W - 130)
        if sub_h + len(lines) * lh <= avail:
            break

    # 글 덩어리를 흰 영역 세로 중앙에 앉힌다 — 아래가 휑하게 비지 않도록
    block_h = sub_h + len(lines) * lh
    y = PHOTO_H + max(40, (H - PHOTO_H - block_h) // 2)

    if subtitle:
        tw, th = bb_sub[2] - bb_sub[0], bb_sub[3] - bb_sub[1]
        rounded_rect(d, (cx - tw / 2 - 24, y - 6, cx + tw / 2 + 24, y + th + bb_sub[1] + 12),
                     14, MAG_BAND)
        d.text((cx - tw / 2 - bb_sub[0], y), subtitle, font=sf, fill=MAG_INK)
        y += th + 46

    for line in lines:
        if y + lh > H - 30:
            break
        center_marked(d, line, cx, y, bf, MAG_INK, (210, 35, 45))
        y += lh
    return img

# ── 커버 ────────────────────────
def make_cover(sc, t, photo=None, credit=None):
    if photo:
        # 커버는 사진을 가장 잘 보여주는 자리. 전체를 어둡게 덮는 대신
        # 제목에 부드러운 그림자를 깔아 대비를 확보한다 (아래 shadow 레이어)
        img = photo_bg(photo, t, darken_top=30, darken_bottom=190)
    else:
        img = gradient_bg_diagonal(t["grad1"], t["grad2"])
        layer, ld = overlay_layer()
        draw_glow_circles(ld, seed=42)
        img = composite(img, layer)

    # 이모지 붙이기 (사진 배경일 땐 조금 작게)
    main_emoji = t.get("emojis", ["📌"])[0]
    paste_emoji(img, main_emoji, W//2, 300, 150 if photo else 190)

    # 3단계: 불투명 요소 직접 그리기
    d = ImageDraw.Draw(img, "RGBA")
    cat = sc.get("meta", {}).get("category", "")
    lines = sc.get("cover", {}).get("lines", [sc.get("title", "")])

    # 브랜드 워드마크 — 캐러셀 첫 장마다 계정 이름을 각인시킨다
    if BRAND:
        bf = font(FONT_BLACK, 38)
        bb = d.textbbox((0,0), BRAND, font=bf)
        bx = (W-(bb[2]-bb[0]))//2
        if photo:
            d.text((bx, 62), BRAND, font=bf, fill=t["accent"],
                   stroke_width=4, stroke_fill=(0, 0, 0))
        else:
            d.text((bx+2, 65), BRAND, font=bf, fill=(0, 0, 0, 80))
            d.text((bx, 62), BRAND, font=bf, fill=t["accent"])

    # 상단 카테고리 뱃지
    if cat:
        tf = font(FONT_BOLD, 30)
        bb = d.textbbox((0,0), cat, font=tf)
        tw, th = bb[2]-bb[0]+56, bb[3]-bb[1]+30
        bx = (W-tw)//2
        by = 136
        rounded_rect(d, (bx, by, bx+tw, by+th), 25, t["tag_bg"])
        d.text((bx+28, by+9), cat, font=tf, fill=t["tag_fg"])

    # 메인 타이틀 — 매우 큰 텍스트
    # 사진을 밝게 두기 위해, 전체 농도를 올리는 대신 글자 뒤에만
    # 부드러운 그림자를 깔아 어떤 배경에서도 읽히게 한다.
    tf_big = font(FONT_BLACK, 94)
    title_y = 480
    placed = []
    for line in lines:
        clean = line.replace("<r>","").replace("</r>","").replace("<y>","").replace("</y>","")
        is_acc = "<r>" in line or "<y>" in line
        bb = d.textbbox((0,0), clean, font=tf_big)
        placed.append(((W-(bb[2]-bb[0]))//2, title_y, clean, is_acc))
        title_y += 116

    if photo:
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        for x, yy, clean, _ in placed:
            sd.text((x, yy + 6), clean, font=tf_big, fill=(0, 0, 0, 190))
        sh = sh.filter(ImageFilter.GaussianBlur(14))
        img = composite(img, sh)
        d = ImageDraw.Draw(img, "RGBA")

    # 외곽선: 사진이 밝거나 포인트 컬러와 색이 겹쳐도 글자가 묻히지 않게 한다
    stroke = dict(stroke_width=5, stroke_fill=(0, 0, 0)) if photo else {}
    for x, yy, clean, is_acc in placed:
        d.text((x, yy), clean, font=tf_big,
               fill=t["accent"] if is_acc else WHITE, **stroke)
    y = title_y

    # 부제
    sub = sc.get("title", "")
    if sub:
        sf = font(FONT_MED, 38)
        y += 26
        bb = d.textbbox((0,0), sub, font=sf)
        d.text(((W-(bb[2]-bb[0]))//2, y), sub, font=sf, fill=(255, 255, 255, 215))

    # 하단 구분선
    d.line([(W*0.25, H-180), (W*0.75, H-180)], fill=(255, 255, 255, 90), width=2)

    # 출처 (+ 사진 크레딧)
    attr = sc.get("meta", {}).get("attribution", "")
    if attr:
        af = font(FONT_REG, 22)
        txt = f"출처: {attr}"
        bb = d.textbbox((0,0), txt, font=af)
        d.text(((W-(bb[2]-bb[0]))//2, H-145), txt, font=af, fill=(255, 255, 255, 150))
    if credit:
        cf = font(FONT_REG, 16)
        bb = d.textbbox((0,0), credit, font=cf)
        d.text(((W-(bb[2]-bb[0]))//2, H-118), credit, font=cf, fill=(255, 255, 255, 110))

    # 스와이프 안내 (이모지 + 텍스트 분리 렌더)
    if not REELS:
        sf = font(FONT_BOLD, 28)
        swipe = UI["swipe"]
        bb = d.textbbox((0,0), swipe, font=sf)
        sx = (W - (bb[2]-bb[0]) - 46)//2
        paste_emoji(img, "👉", sx + 17, H-82, 34)
        d = ImageDraw.Draw(img, "RGBA")
        d.text((sx + 46, H-95), swipe, font=sf, fill=t["accent"])

    dots(d, 1, len(sc.get("scenes", []))+2, t)
    return img

# ── 본문 슬라이드 ────────────────
def make_scene(sc, idx, total, t, photo=None, credit=None):
    scene = sc["scenes"][idx]

    if photo:
        # 본문 글자는 아래 카드 안에 들어가므로 사진 자체는 어둡게 할 이유가 없다.
        # 블러를 빼고 농도를 낮춰 사진이 선명하게 보이게 한다.
        img = photo_bg(photo, t, darken_top=30, darken_bottom=150, blur=0)
    else:
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
    # 한눈에 들어오게: 본문을 키우고 핵심 수치는 포인트 컬러로 분리
    body_f = font(FONT_MED, 46)
    subtitle = scene.get("subtitle", "")
    tag_f = font(FONT_BOLD, 42)

    card_margin = 50
    body_max_w = W - card_margin*2 - 90
    body_lh = 70
    body_lines = wrap_marked(measure, parse_marked(body), body_f, body_max_w)

    tag_bb = measure.textbbox((0,0), subtitle, font=tag_f)
    tag_w = tag_bb[2]-tag_bb[0] + 56
    tag_h = tag_bb[3]-tag_bb[1] + 30

    # 카드 높이를 내용에 맞춰 계산 → 하단은 항상 H-80에 고정, 상단을 역산
    content_h = 40 + tag_h + 38 + len(body_lines)*body_lh + 20 + 46
    card_bottom = H - 80
    card_y = max(400, card_bottom - content_h)

    # 1단계: 반투명 요소(장식 + 숫자 + 카드)를 한 레이어에 그려 1회 합성
    layer, ld = overlay_layer()
    if not photo:
        draw_glow_circles(ld, seed=idx*17 + 3)

    num = f"{idx+1:02d}"
    nf = font(FONT_BLACK, 300)
    nb = ld.textbbox((0,0), num, font=nf)
    ld.text((W - (nb[2]-nb[0]) - 40, 10), num, font=nf,
            fill=(255, 255, 255, 60 if photo else 46))

    # 배경을 밝게 둔 만큼 카드는 더 진하게 깔아 본문 대비를 지킨다
    card_alpha = 195 if photo else 115
    rounded_rect(ld, (card_margin, card_y, W-card_margin, card_bottom), 32, (0, 0, 0, card_alpha))
    img = composite(img, layer)

    # 2단계: 상단 큰 이모지
    emoji = scene.get("emoji", "")
    if emoji:
        paste_emoji(img, emoji, W//2 - 70, card_y//2 + 30, 190 if photo else 240)

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
        draw_marked_line(d, line, body_x, body_y, body_f, WHITE, t["accent"])
        body_y += body_lh

    # 출처 (+ 사진 크레딧)
    attr = sc.get("meta", {}).get("attribution", "")
    if attr:
        af = font(FONT_REG, 20)
        d.text((card_margin+45, card_bottom-38), f"출처: {attr}", font=af, fill=(255, 255, 255, 135))
    if credit:
        cf = font(FONT_REG, 15)
        bb = d.textbbox((0,0), credit, font=cf)
        d.text((W - card_margin - 45 - (bb[2]-bb[0]), card_bottom-34), credit,
               font=cf, fill=(255, 255, 255, 100))

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
    for txt, col in [(UI["outro1"], WHITE), (UI["outro2"], t["accent"])]:
        bb = d.textbbox((0,0), txt, font=f1)
        d.text(((W-(bb[2]-bb[0]))//2, y), txt, font=f1, fill=col)
        y += 80

    y += 24
    f2 = font(FONT_MED, 32)
    for txt in [UI["outro_s1"], UI["outro_s2"]]:
        bb = d.textbbox((0,0), txt, font=f2)
        d.text(((W-(bb[2]-bb[0]))//2, y), txt, font=f2, fill=(255, 255, 255, 210))
        y += 50

    # 핸들
    hf = font(FONT_BOLD, 38)
    handle = HANDLE
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
def generate(script_path, out_dir, photo_dir=None, layout="magazine"):
    with open(script_path, encoding="utf-8") as f:
        sc = json.load(f)
    os.makedirs(out_dir, exist_ok=True)
    cover_fn = make_cover_mag if layout == "magazine" else make_cover
    scene_fn = make_scene_mag if layout == "magazine" else make_scene
    cat = sc.get("meta", {}).get("category", "")
    t = get_t(cat)
    total = len(sc.get("scenes", [])) + 2
    pages = []

    photos = load_photos(photo_dir)
    credits = load_credits(photo_dir)
    if photos:
        print(f"  사진 {len(photos)}장 적용: {', '.join(sorted(photos))}")
    elif photo_dir:
        print("  사진 없음 — 그래디언트 배경으로 생성")

    p = os.path.join(out_dir, "01_cover.png")
    cover_fn(sc, t, photos.get("cover"), credits.get("cover")).save(p, quality=95)
    pages.append(p)

    for i in range(len(sc.get("scenes", []))):
        slot = f"scene{i+1}"
        p = os.path.join(out_dir, f"{i+2:02d}_scene.png")
        scene_fn(sc, i, total, t, photos.get(slot), credits.get(slot)).save(p, quality=95)
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
    ap.add_argument("-p", "--photos", default=None,
                    help="photos.json이 있는 사진 디렉터리 (없으면 그래디언트 배경)")
    ap.add_argument("--reels", action="store_true",
                    help="릴스용. 스와이프 안내와 페이지 점을 빼고 그린다")
    ap.add_argument("--layout", choices=["magazine", "classic"], default="magazine",
                    help="magazine=사진 밴드+흰 바탕 검은 글씨 (기본), classic=기존 어두운 오버레이")
    a = ap.parse_args()
    REELS = a.reels
    generate(a.script, a.out, a.photos, a.layout)
