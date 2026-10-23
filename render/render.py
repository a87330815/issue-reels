# -*- coding: utf-8 -*-
"""
render.py — 대본 JSON → 1080x1920 릴스

- 커버 프레임은 cover.py의 커버 문법을 그대로 쓴다
- 자막은 번인(인스타 자동자막 미사용)
- 장면 길이는 내레이션 글자 수로 산출하되, TTS 음성이 있으면 실제 길이를 쓴다
- TTS는 edge-tts(ko-KR-HyunsuNeural). 실패하면 무음으로 떨어지고 경고를 남긴다

대본 JSON:
{
  "title": "자동차세 연납",
  "cover": {"image": "bg.jpg", "lines": ["이거 모르면", "<r>1년에 7만원</r>", "그냥 날립니다"], "badge": null},
  "scenes": [
    {"image": "s1.jpg", "narration": "자동차세는 1월에 한 번에 내면 할인됩니다.", "subtitle": "1월에 한 번에 내면 할인"}
  ]
}
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bg  # noqa: E402
import cover  # noqa: E402

W, H, FPS = cover.W, cover.H, 30
# 음성 — 2026-10-23 경상도 사투리 컨셉.
# HyunsuNeural(남성) + 약간 빠른 속도 + 살짝 높은 피치 → 활기찬 동네형 톤.
# 양상국 스타일은 대본(사투리 말투)으로 구현하고, 목소리는 자연스럽게 유지.
# 환경변수로 덮어쓸 수 있게 두되, 바꾸면 반드시 다시 들어보고 판단할 것.
VOICE = os.environ.get("TTS_VOICE", "ko-KR-HyunsuNeural")
TTS_RATE = os.environ.get("TTS_RATE", "+12%")    # 약간 빠르게 (경쾌한 톤)
TTS_PITCH = os.environ.get("TTS_PITCH", "+8Hz")   # 살짝 높여서 활기차게

COVER_HOLD = 2.0          # 커버 노출 시간
CHARS_PER_SEC = 6.5       # TTS 실패 시 길이 추정용
MIN_SCENE, MAX_SCENE = 1.8, 9.0


def estimate_duration(text):
    return max(MIN_SCENE, min(MAX_SCENE, len(text or "") / CHARS_PER_SEC))


async def _tts(text, path):
    import edge_tts
    await edge_tts.Communicate(text, VOICE, rate=TTS_RATE, pitch=TTS_PITCH).save(path)


def synth(text, path):
    """성공하면 True. 네트워크가 막혀 있으면 False로 떨어진다."""
    try:
        asyncio.run(_tts(text, path))
        return os.path.exists(path) and os.path.getsize(path) > 1000
    except Exception as e:
        print(f"  [경고] TTS 실패: {e}")
        return False


def audio_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def subtitle_frame(bg_path, text, fallback=None):
    """장면 이미지 위에 자막을 번인. 커버보다 작고 하단에 둔다.

    이미지가 지정되지 않으면 fallback(생성 배경)을 쓴다. 보도사진을 쓸 수 없으므로
    직접 만든 배경이 기본값이다.
    """
    if bg_path:
        img = cover.cover_crop(bg_path)
    elif fallback is not None:
        img = fallback
    else:
        img = Image.new("RGB", (W, H), (18, 18, 20))
    draw = ImageDraw.Draw(img)
    if not text:
        return img

    max_w = W - cover.SAFE_SIDE * 2
    size = 86
    font = cover._font(size)
    sw = max(3, size // 16)
    lines = cover.wrap_runs(draw, cover.parse_runs(text), font, sw, max_w)

    lh = int(size * 1.25)
    y = H - cover.SAFE_BOTTOM - lh * len(lines)
    for runs in lines:
        total = sum(draw.textlength(t, font=font) for t, _ in runs)
        x = (W - total) / 2
        for t, c in runs:
            draw.text((x, y), t, font=font, fill=cover.COLORS[c],
                      stroke_width=sw, stroke_fill=cover.STROKE)
            x += draw.textlength(t, font=font)
        y += lh
    return img


def build(script_path, out_path):
    with open(script_path, encoding="utf-8") as f:
        sc = json.load(f)

    work = tempfile.mkdtemp(prefix="reel_")
    segments, warnings = [], []

    # 1. 커버
    c = sc["cover"]
    canvas = cover.cover_crop(c["image"]) if c.get("image") else bg.make_for_script(sc)
    cov = cover.draw_cover(canvas, c["lines"], badge=c.get("badge"))
    cov_png = os.path.join(work, "cover.png")
    cov.save(cov_png)
    segments.append((cov_png, None, COVER_HOLD))

    # 2. 장면
    for i, s in enumerate(sc.get("scenes", [])):
        frame = subtitle_frame(s.get("image"), s.get("subtitle", ""),
                               fallback=bg.make_for_script(sc, scene_index=i))
        fp = os.path.join(work, f"s{i:02d}.png")
        frame.save(fp)

        narration = s.get("narration", "")
        wav = os.path.join(work, f"s{i:02d}.mp3")
        dur, audio = estimate_duration(narration), None
        if narration and synth(narration, wav):
            real = audio_duration(wav)
            if real:
                dur, audio = real + 0.35, wav
        else:
            if narration:
                warnings.append(f"장면 {i}: 음성 없이 추정 길이 {dur:.1f}초")
        segments.append((fp, audio, dur))

    # 3. ffmpeg 합성
    parts = []
    for idx, (img, audio, dur) in enumerate(segments):
        part = os.path.join(work, f"p{idx:02d}.mp4")
        cmd = ["ffmpeg", "-y", "-loop", "1", "-t", f"{dur:.3f}", "-i", img]
        if audio:
            # 라우드니스 정규화 — TTS 원본이 0dBFS까지 치솟아 클리핑이 난다.
            # I=-16 LUFS / TP=-1.5dB 는 소셜 영상 표준값이다.
            cmd += ["-i", audio,
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                    "-c:a", "aac", "-b:a", "128k", "-shortest"]
        else:
            cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=44100", "-c:a", "aac"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
                "-vf", f"scale={W}:{H}", part]
        subprocess.run(cmd, check=True, capture_output=True)
        parts.append(part)

    listing = os.path.join(work, "list.txt")
    with open(listing, "w") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listing,
         "-c", "copy", out_path],
        check=True, capture_output=True,
    )

    total = sum(d for _, _, d in segments)
    print(f"\n완성: {out_path}  {W}x{H} / {FPS}fps / {total:.1f}초 / 장면 {len(segments)}개")
    for w in warnings:
        print(f"  [경고] {w}")
    if warnings:
        print("  → TTS 미작동. 음성 품질 판정 전에는 발행하지 말 것.")
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("-o", "--out", default="out/reel.mp4")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    build(a.script, a.out)
