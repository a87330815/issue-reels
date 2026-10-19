# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import cover, _mockbg

OUT = os.path.join(os.path.dirname(__file__), "..", "out")
os.makedirs(OUT, exist_ok=True)

SAMPLES = [
    dict(
        name="01_숫자훅",
        bg=(3, (72, 92, 130), (18, 22, 38)),
        lines=["이거 모르면", "<r>1년에 7만원</r>", "그냥 날립니다"],
        badge=None, align="bottom",
    ),
    dict(
        name="02_오해정정",
        bg=(11, (120, 86, 64), (28, 20, 18)),
        lines=["실업급여", "<y>절반이 탈락</y>", "이유는 이겁니다"],
        badge=None, align="bottom",
    ),
    dict(
        name="03_시행일훅",
        bg=(27, (54, 104, 92), (14, 28, 26)),
        lines=["이거 안 하면", "<r>과태료 20만원</r>"],
        badge="11월 1일 시행", align="bottom",
    ),
]

for s in SAMPLES:
    seed, top, bot = s["bg"]
    bg = _mockbg.make(seed, top, bot)
    img = cover.draw_cover(bg, s["lines"], align=s["align"], badge=s["badge"])
    path = os.path.join(OUT, s["name"] + ".jpg")
    img.save(path, "JPEG", quality=92)
    print(path, img.size)
