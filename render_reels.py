# -*- coding: utf-8 -*-
"""
render_reels.py — 카드뉴스 이미지 + TTS → 릴스 영상(mp4) 합성

사용:
  python render_reels.py out/scripts/news_001.json
  python render_reels.py out/scripts/news_001.json --cards out/cards_001 --voice ko-KR-HyunsuMultilingualNeural
  python render_reels.py out/scripts/news_001.json --no-tts   # 이미지만으로 영상 (무음)
"""
import argparse
import asyncio
import json
import glob
import os
import subprocess
import sys
import tempfile

# 양상국 스타일 남성 목소리 (기본)
DEFAULT_VOICE = "ko-KR-HyunsuMultilingualNeural"
# 장면당 기본 표시 시간 (TTS 없을 때)
DEFAULT_DURATION = 4.0
# 커버·아웃트로 최소 표시 시간
MIN_COVER_SEC = 3.0
# 페이드 전환
FADE_MS = 300
# 출력 해상도 (9:16 세로 릴스)
W, H = 1080, 1920


def load_script(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def card_images(card_dir):
    """카드 PNG를 순서대로."""
    files = sorted(glob.glob(os.path.join(card_dir, "*.png")))
    if not files:
        raise SystemExit(f"카드 이미지가 없습니다: {card_dir}")
    return files


def narrations(script):
    """대본에서 나레이션 텍스트 추출. 커버는 제목, 아웃트로는 고정 멘트."""
    texts = []
    # 커버
    texts.append(script.get("title", ""))
    # 본문 장면
    for sc in script.get("scenes", []):
        texts.append(sc.get("narration", sc.get("subtitle", "")))
    return texts


# 피치 올림 배수 (+1반음 = 2^(1/12) ≈ 1.059)
PITCH = 1.059


def post_process_voice(src, dst):
    """TTS 출력에 양상국 스타일 후처리: 피치만 올리고 속도는 그대로 둔다."""
    # asetrate는 피치와 속도를 함께 올린다. atempo로 속도를 되돌리지 않으면
    # 말이 빨라져 부자연스러워진다. 앞서 이 보정이 빠져 있었다.
    af = (
        f"asetrate=44100*{PITCH},aresample=44100,"   # 피치 +1반음 (속도도 함께 빨라짐)
        f"atempo={1 / PITCH:.4f},"                    # 빨라진 속도를 원래대로 되돌림
        "equalizer=f=2800:t=h:w=1200:g=1.5,"          # 중고음 살짝 강조
        "equalizer=f=180:t=h:w=80:g=-1,"              # 저음 미세 조정
        "loudnorm=I=-16:TP=-1.5:LRA=11"               # 음량 정규화
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-af", af, "-c:a", "libmp3lame", "-q:a", "2", dst],
        capture_output=True, check=True
    )


async def generate_tts(texts, voice, out_dir, style=True):
    """edge-tts로 각 장면 나레이션 mp3 생성. 파일 경로와 길이를 반환."""
    import edge_tts

    results = []
    for i, text in enumerate(texts):
        if not text.strip():
            results.append(None)
            continue
        raw_mp3 = os.path.join(out_dir, f"narr_raw_{i:02d}.mp3")
        mp3 = os.path.join(out_dir, f"narr_{i:02d}.mp3")
        comm = edge_tts.Communicate(text, voice)
        await comm.save(raw_mp3)
        # 양상국 스타일 후처리
        if style:
            try:
                post_process_voice(raw_mp3, mp3)
                print(f"  후처리 적용 [{i+1}/{len(texts)}]")
            except Exception as e:
                print(f"  후처리 실패, 원본 사용: {e}")
                os.replace(raw_mp3, mp3)
        else:
            os.replace(raw_mp3, mp3)
        # 길이 측정
        dur = get_duration(mp3)
        results.append({"path": mp3, "duration": dur})
        print(f"  TTS [{i+1}/{len(texts)}] {dur:.1f}초  {text[:30]}...")
    return results


def get_duration(media_path):
    """ffprobe로 미디어 길이(초) 반환."""
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", media_path],
        capture_output=True, text=True
    )
    return float(r.stdout.strip()) if r.stdout.strip() else DEFAULT_DURATION


def build_video(card_files, tts_results, output_path, tmp_dir):
    """카드 이미지 + TTS 오디오 → 세로 릴스 mp4."""
    segments = []

    for i, card in enumerate(card_files):
        # 각 장면의 표시 시간 결정
        if tts_results and i < len(tts_results) and tts_results[i]:
            dur = max(tts_results[i]["duration"] + 0.8, MIN_COVER_SEC)
            audio = tts_results[i]["path"]
        else:
            dur = DEFAULT_DURATION
            audio = None

        seg_path = os.path.join(tmp_dir, f"seg_{i:02d}.mp4")

        # 4:5 카드를 9:16에 넣으면 위아래가 크게 빈다. 같은 이미지를 꽉 채워
        # 블러 처리한 뒤 배경으로 깔고, 그 위에 원본 카드를 얹는다.
        vf = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H},gblur=sigma=28,eq=brightness=-0.12[bg];"
              f"[0:v]scale={W}:-1[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p")

        # 이미지를 9:16(1080x1920)에 맞춤
        if audio:
            cmd = ["ffmpeg", "-y", "-loop", "1", "-i", card,
                   "-i", audio, "-t", f"{dur:.2f}",
                   "-filter_complex", vf, "-r", "30",
                   "-c:a", "aac", "-b:a", "128k", "-shortest",
                   "-c:v", "libx264", "-preset", "fast", "-crf", "23", seg_path]
        else:
            cmd = ["ffmpeg", "-y", "-loop", "1", "-i", card,
                   "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                   "-t", f"{dur:.2f}",
                   "-filter_complex", vf, "-r", "30",
                   "-c:a", "aac", "-shortest",
                   "-c:v", "libx264", "-preset", "fast", "-crf", "23", seg_path]

        subprocess.run(cmd, capture_output=True, check=True)
        segments.append(seg_path)
        print(f"  세그먼트 [{i+1}/{len(card_files)}] {dur:.1f}초")

    # concat
    list_file = os.path.join(tmp_dir, "concat.txt")
    with open(list_file, "w") as f:
        for s in segments:
            f.write(f"file '{s}'\n")

    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
           "-c:v", "libx264", "-preset", "fast", "-crf", "23",
           "-c:a", "aac", "-b:a", "128k",
           "-movflags", "+faststart",
           output_path]
    subprocess.run(cmd, capture_output=True, check=True)

    total_dur = get_duration(output_path)
    size_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"\n  ✓ 릴스 완성: {output_path}")
    print(f"    길이: {total_dur:.1f}초  /  크기: {size_mb:.1f}MB")
    return output_path


def main():
    ap = argparse.ArgumentParser(description="카드뉴스 → 릴스 영상 합성")
    ap.add_argument("script", help="대본 JSON")
    ap.add_argument("--cards", help="카드 이미지 디렉터리 (미지정 시 자동 추론)")
    ap.add_argument("--voice", default=DEFAULT_VOICE, help="TTS 음성")
    ap.add_argument("--no-tts", action="store_true", help="TTS 없이 무음 영상")
    ap.add_argument("--no-style", action="store_true",
                    help="양상국 스타일 후처리 없이 원본 TTS 사용")
    ap.add_argument("--require-tts", action="store_true",
                    help="TTS가 실패하면 무음으로 넘어가지 않고 중단한다")
    ap.add_argument("-o", "--out", help="출력 mp4 경로")
    a = ap.parse_args()

    script = load_script(a.script)
    stem = os.path.splitext(os.path.basename(a.script))[0]

    # 카드 디렉터리 추론
    if a.cards:
        card_dir = a.cards
    else:
        card_dir = os.path.join("out", "cards_" + stem.replace("news_", "", 1))

    cards = card_images(card_dir)
    print(f"대본: {a.script}")
    print(f"카드: {card_dir} ({len(cards)}장)")
    print(f"음성: {a.voice}")

    # 출력 경로
    out_dir = os.path.join("out", "reels")
    os.makedirs(out_dir, exist_ok=True)
    output = a.out or os.path.join(out_dir, f"{stem}.mp4")

    with tempfile.TemporaryDirectory() as tmp:
        # TTS 생성
        tts_results = None
        if not a.no_tts:
            print("\n1) TTS 생성")
            texts = narrations(script)
            try:
                tts_results = asyncio.run(generate_tts(texts, a.voice, tmp,
                                                       style=not a.no_style))
            except Exception as e:
                # 무음으로 조용히 넘어가면 음성 없는 영상이 완성본처럼 나온다.
                if a.require_tts:
                    raise SystemExit(f"[중단] TTS 실패: {e}")
                print(f"  [경고] TTS 실패: {e}")
                print("  → 무음 영상으로 전환")
                tts_results = None
            else:
                if a.require_tts and not any(tts_results or []):
                    raise SystemExit("[중단] TTS 결과가 비었습니다")

        # 영상 합성
        print(f"\n{'2' if not a.no_tts else '1'}) 영상 합성")
        build_video(cards, tts_results, output, tmp)


if __name__ == "__main__":
    main()
