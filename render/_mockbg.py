# -*- coding: utf-8 -*-
"""샘플용 가짜 배경 생성기. 실제 운영에서는 직접 촬영/제작 이미지로 교체."""
import numpy as np
from PIL import Image, ImageFilter

W, H = 1080, 1920


def make(seed, top, bottom, blobs=7):
    rng = np.random.default_rng(seed)
    yy = np.linspace(0, 1, H)[:, None]
    base = np.zeros((H, W, 3), np.float64)
    for c in range(3):
        base[:, :, c] = top[c] * (1 - yy) + bottom[c] * yy

    # 부드러운 덩어리로 사진 같은 명암 변화를 만든다
    for _ in range(blobs):
        cx, cy = rng.uniform(0, W), rng.uniform(0, H)
        r = rng.uniform(200, 650)
        amp = rng.uniform(-45, 45)
        X, Y = np.meshgrid(np.arange(W), np.arange(H))
        g = np.exp(-(((X - cx) ** 2 + (Y - cy) ** 2) / (2 * r ** 2)))
        base += (g * amp)[:, :, None]

    base += rng.normal(0, 5, (H, W, 3))  # 필름 그레인

    # 비네팅
    X, Y = np.meshgrid(np.linspace(-1, 1, W), np.linspace(-1, 1, H))
    base *= (1 - 0.38 * np.clip(X ** 2 + Y ** 2, 0, 1))[:, :, None]

    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    return img.filter(ImageFilter.GaussianBlur(1.2))
