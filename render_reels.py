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

# edge-tts의 한국어 음성은 셋뿐이고 남성은 둘이다. 실제로 재보니
# Hyunsu가 142Hz, InJoon이 168Hz로 Hyunsu 쪽이 낮다. 이름만 보고
# InJoon을 성우 목소리로 골랐다가 오히려 높아졌다.
DEFAULT_VOICE = "ko-KR-HyunsuMultilingualNeural"
# 대안: ko-KR-InJoonNeural(남, 더 높음), ko-KR-SunHiNeural(여)
# 기본 속도(6자/초)는 또박또박하지만 릴스로는 처진다. 20% 올려
# 7.2자/초로 두면 이슈 전달에 맞는 속도가 되고 길이도 37초대로 줄어든다.
DEFAULT_RATE = "+20%"
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


# 피치 배수. 1보다 작으면 낮아진다. Hyunsu 원본이 142Hz인데 0.88을
# 걸면 125Hz가 되어 남자 성우 구간(110~130Hz)에 들어온다.
PITCH = 0.88


def audio_rate(path):
    """오디오의 실제 샘플레이트. asetrate에 이 값을 써야 한다."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=sample_rate", "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    try:
        return int(r.stdout.strip())
    except ValueError:
        return 24000          # edge-tts 기본값


def post_process_voice(src, dst):
    """남자 성우 톤 후처리.

    성우 목소리는 세 가지가 다르다. 첫째 음이 낮고, 둘째 소리 크기가
    일정하며(컴프레서), 셋째 중저음에 두께가 있고 말소리는 또렷하다.
    피치만 만지면 어린 목소리를 억지로 낮춘 소리가 나므로 함께 잡는다.
    """
    # asetrate는 "이 파일을 이 샘플레이트로 읽으라"는 뜻이라, 원본 레이트를
    # 그대로 넣어야 의도한 배수만큼만 바뀐다. 앞서 24kHz 파일에 44100을
    # 박아 넣어 피치가 1.8배로 치솟았고, 그래서 목소리가 얇게 들렸다.
    sr = audio_rate(src)
    af = (
        f"asetrate={sr}*{PITCH},aresample={sr},"       # 피치 낮춤 (속도도 함께 느려짐)
        f"atempo={1 / PITCH:.4f},"                      # 속도는 원래대로
        "equalizer=f=120:t=h:w=100:g=2.5,"              # 저음 두께 — 성우의 울림
        "equalizer=f=300:t=h:w=200:g=1.5,"              # 중저음 바디감
        "equalizer=f=1000:t=h:w=600:g=-1.5,"            # 답답한 중음 덜어내기
        "equalizer=f=4000:t=h:w=1500:g=2,"              # 자음 또렷하게 (딕션)
        "acompressor=threshold=-18dB:ratio=3:attack=8:release=180:makeup=2,"
        "loudnorm=I=-15:TP=-1.5:LRA=9"                  # 방송 수준 음량·다이내믹
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-af", af, "-c:a", "libmp3lame", "-q:a", "2", dst],
        capture_output=True, check=True
    )


async def generate_tts(texts, voice, out_dir, style=True, rate=DEFAULT_RATE):
    """edge-tts로 각 장면 나레이션 mp3 생성. 파일 경로와 길이를 반환."""
    import edge_tts

    results = []
    for i, text in enumerate(texts):
        if not text.strip():
            results.append(None)
            continue
        raw_mp3 = os.path.join(out_dir, f"narr_raw_{i:02d}.mp3")
        mp3 = os.path.join(out_dir, f"narr_{i:02d}.mp3")
        comm = edge_tts.Communicate(text, voice, rate=rate)
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
    ap.add_argument("--rate", default=DEFAULT_RATE,
                    help="발화 속도 (예: -18%%, +5%%). 느리게 하려면 음수")
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
    print(f"음성: {a.voice} (속도 {a.rate})")

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
                                                       style=not a.no_style,
                                                       rate=a.rate))
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
