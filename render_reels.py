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
import random
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


# 음성마다 원래 음높이가 다르다. 실측치는 Hyunsu 142Hz, InJoon 168Hz,
# SunHi 201Hz다. 성우 구간은 남성 110~130Hz, 여성 180~220Hz이므로
# 남성은 피치를 내려야 하고 여성은 이미 범위 안이라 거의 손대지 않는다.
# EQ도 음역이 달라 그대로 쓸 수 없다. 남성용 120Hz 보강은 여성 기본
# 주파수 아래라 울림이 아니라 잡음만 키운다.
VOICE_PROFILES = {
    "male": {
        "pitch": 0.88,                    # 142Hz → 125Hz
        "eq": ("equalizer=f=120:t=h:w=100:g=2.5,"     # 저음 두께 — 성우의 울림
               "equalizer=f=300:t=h:w=200:g=1.5,"     # 중저음 바디감
               "equalizer=f=1000:t=h:w=600:g=-1.5,"   # 답답한 중음 덜어내기
               "equalizer=f=4000:t=h:w=1500:g=2,"),   # 자음 또렷하게
    },
    "female": {
        "pitch": 0.97,                    # 201Hz → 195Hz, 살짝만 눌러 차분하게
        "eq": ("equalizer=f=250:t=h:w=150:g=2,"       # 가슴 울림 — 여성 성우의 두께
               "equalizer=f=800:t=h:w=500:g=-1,"      # 먹먹한 중음만 살짝
               "equalizer=f=3500:t=h:w=1200:g=1.5,"   # 딕션 (남성보다 약하게)
               "equalizer=f=7000:t=h:w=2000:g=1,"),   # 공기감
    },
}

# 음성 이름으로 프로필을 고른다. edge-tts 한국어는 셋뿐이다.
FEMALE_VOICES = {"ko-KR-SunHiNeural"}

# ── 프리셋 ───────────────────────────────────────────────────────────
# 음성 3개뿐이라도 피치·속도·EQ 조합을 바꾸면 성격이 달라진다.
# 이름을 붙여두면 매번 코드를 고치지 않고 골라 쓸 수 있다.
#
# 한계를 분명히 해둔다. edge-tts는 감정 연기를 하지 않는 평탄한 낭독이다.
# 다큐·앵커처럼 차분한 톤은 잘 나오지만, 만화 캐릭터처럼 연기가 필요한
# 목소리는 피치를 올려도 "빨라진 낭독"이 될 뿐 캐릭터가 되지 않는다.
# 그쪽이 필요하면 감정 표현을 지원하는 유료 엔진을 써야 한다.
PRESETS = {
    "이슈남": {   # 현재 기본값. 또렷하고 빠른 이슈 전달
        "voice": "ko-KR-HyunsuMultilingualNeural", "pitch": 0.88, "rate": "+20%",
        "eq": ("equalizer=f=120:t=h:w=100:g=2.5,equalizer=f=300:t=h:w=200:g=1.5,"
               "equalizer=f=1000:t=h:w=600:g=-1.5,equalizer=f=4000:t=h:w=1500:g=2,"),
        "desc": "또렷하고 빠른 남성 — 이슈 전달용 (기본)",
    },
    "다큐": {     # TV 다큐멘터리 내레이션. 낮고 느리게
        "voice": "ko-KR-HyunsuMultilingualNeural", "pitch": 0.80, "rate": "-5%",
        "eq": ("equalizer=f=100:t=h:w=90:g=4,equalizer=f=250:t=h:w=200:g=2,"
               "equalizer=f=1200:t=h:w=800:g=-2,equalizer=f=3500:t=h:w=1200:g=1.5,"),
        "desc": "낮고 묵직한 다큐 내레이션 — TV 자연다큐 톤",
    },
    "앵커": {     # 뉴스 앵커. 중간 음높이에 딕션 강조
        "voice": "ko-KR-InJoonNeural", "pitch": 0.90, "rate": "+10%",
        "eq": ("equalizer=f=150:t=h:w=120:g=1.5,equalizer=f=1000:t=h:w=600:g=-1,"
               "equalizer=f=4500:t=h:w=1500:g=3,"),
        "desc": "뉴스 앵커 — 또박또박한 전달",
    },
    "예고편": {   # 영화 예고편. 아주 낮고 울림 크게
        "voice": "ko-KR-HyunsuMultilingualNeural", "pitch": 0.72, "rate": "-10%",
        "eq": ("equalizer=f=85:t=h:w=80:g=5,equalizer=f=200:t=h:w=180:g=3,"
               "equalizer=f=1500:t=h:w=1000:g=-3,equalizer=f=3000:t=h:w=1000:g=1,"),
        "desc": "영화 예고편 — 아주 낮고 극적인 울림",
    },
    "차분녀": {   # 차분한 여성 내레이션
        "voice": "ko-KR-SunHiNeural", "pitch": 0.97, "rate": "+15%",
        "eq": ("equalizer=f=250:t=h:w=150:g=2,equalizer=f=800:t=h:w=500:g=-1,"
               "equalizer=f=3500:t=h:w=1200:g=1.5,equalizer=f=7000:t=h:w=2000:g=1,"),
        "desc": "차분한 여성 성우 — 정보 전달용",
    },
    "발랄녀": {   # 밝고 빠른 리포터
        "voice": "ko-KR-SunHiNeural", "pitch": 1.06, "rate": "+25%",
        "eq": ("equalizer=f=400:t=h:w=300:g=1,equalizer=f=3000:t=h:w=1500:g=2,"
               "equalizer=f=8000:t=h:w=2500:g=2,"),
        "desc": "밝고 빠른 여성 리포터 — 가벼운 이슈용",
    },
    "캐릭터": {   # 만화풍. 한계가 뚜렷하니 샘플로 판단할 것
        "voice": "ko-KR-SunHiNeural", "pitch": 1.18, "rate": "+30%",
        "eq": ("equalizer=f=500:t=h:w=400:g=2,equalizer=f=2500:t=h:w=1500:g=3,"
               "equalizer=f=9000:t=h:w=3000:g=2,"),
        "desc": "만화풍 높은 톤 — 연기가 아니라 음높이만 올린 것이라 한계가 있음",
    },
}


def voice_profile(voice, preset=None):
    """프리셋이 있으면 그 설정을, 없으면 음성 성별에 맞는 기본값을 쓴다."""
    if preset and preset in PRESETS:
        return PRESETS[preset]
    return VOICE_PROFILES["female" if voice in FEMALE_VOICES else "male"]


def parse_preset_pool(spec):
    """쉼표로 묶인 프리셋 목록을 리스트로. 빈 값이면 None."""
    if not spec:
        return None
    names = [n.strip() for n in spec.split(",") if n.strip()]
    unknown = [n for n in names if n not in PRESETS]
    if unknown:
        raise SystemExit(f"없는 프리셋: {', '.join(unknown)}\n"
                         f"가능: {', '.join(PRESETS)}")
    return names or None


def pick_preset(pool, stem):
    """목록에서 하나를 고른다.

    대본 이름으로 난수를 고정한다. 같은 대본을 다시 렌더해도 같은 목소리가
    나와야 수정본을 올릴 때 목소리가 바뀌어 당황하는 일이 없다. 대본이
    달라지면 자연히 다른 목소리가 걸린다.
    """
    if not pool:
        return None
    if len(pool) == 1:
        return pool[0]
    return random.Random(stem).choice(pool)


def scene_presets(pool, stem, count, alternate):
    """장면마다 쓸 프리셋을 정한다.

    alternate면 목록을 번갈아 돌려 한 영상 안에서 목소리가 교대한다.
    두 사람이 주고받는 느낌이 나서 이슈 전달에 리듬이 생긴다.
    아니면 영상 전체가 한 목소리다.
    """
    if not pool:
        return [None] * count
    if not alternate:
        return [pick_preset(pool, stem)] * count
    # 시작 목소리도 대본에 따라 달라지게 해서 영상마다 첫인상이 바뀌도록 한다.
    offset = random.Random(stem).randrange(len(pool))
    return [pool[(i + offset) % len(pool)] for i in range(count)]


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


def post_process_voice(src, dst, voice=DEFAULT_VOICE, preset=None):
    """성우 톤 후처리.

    성우 목소리는 세 가지가 다르다. 첫째 음높이가 제자리에 있고, 둘째
    소리 크기가 일정하며(컴프레서), 셋째 울림에 두께가 있고 말소리는
    또렷하다. 피치만 만지면 억지로 눌러 놓은 소리가 나므로 함께 잡는다.
    """
    prof = voice_profile(voice, preset)
    pitch = prof["pitch"]
    # asetrate는 "이 파일을 이 샘플레이트로 읽으라"는 뜻이라, 원본 레이트를
    # 그대로 넣어야 의도한 배수만큼만 바뀐다. 앞서 24kHz 파일에 44100을
    # 박아 넣어 피치가 1.8배로 치솟았고, 그래서 목소리가 얇게 들렸다.
    sr = audio_rate(src)
    af = (
        f"asetrate={sr}*{pitch},aresample={sr},"        # 피치 조정 (속도도 함께 변함)
        f"atempo={1 / pitch:.4f},"                       # 속도는 원래대로
        + prof["eq"] +
        "acompressor=threshold=-18dB:ratio=3:attack=8:release=180:makeup=2,"
        "loudnorm=I=-15:TP=-1.5:LRA=9"                   # 방송 수준 음량·다이내믹
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-af", af, "-c:a", "libmp3lame", "-q:a", "2", dst],
        capture_output=True, check=True
    )


def _synth_elevenlabs(text, path):
    """ElevenLabs API로 음성 생성. 성공 True / 실패 False."""
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "")
    if not api_key or not voice_id:
        return False
    try:
        from elevenlabs.client import ElevenLabs
        client = ElevenLabs(api_key=api_key)
        model = os.environ.get("ELEVENLABS_MODEL", "eleven_v3")
        audio_iter = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id=model,
            output_format="mp3_44100_128",
        )
        with open(path, "wb") as f:
            for chunk in audio_iter:
                f.write(chunk)
        return os.path.exists(path) and os.path.getsize(path) > 1000
    except Exception as e:
        print(f"  [경고] ElevenLabs TTS 실패: {e}")
        return False


_el_available = None

def _check_elevenlabs():
    """ElevenLabs 사용 가능 여부 (세션 내 캐시)."""
    global _el_available
    if _el_available is not None:
        return _el_available
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "")
    if api_key and voice_id:
        try:
            from elevenlabs.client import ElevenLabs  # noqa: F401
            _el_available = True
            print("[TTS] ElevenLabs 엔진 사용")
            return True
        except ImportError:
            print("[TTS] elevenlabs 패키지 미설치 → edge-tts 폴백")
    else:
        reason = "API_KEY" if not api_key else "VOICE_ID"
        print(f"[TTS] ELEVENLABS_{reason} 미설정 → edge-tts 폴백")
    _el_available = False
    return False


async def generate_tts(texts, voice, out_dir, style=True, rate=DEFAULT_RATE,
                       preset=None, presets=None):
    """TTS 나레이션 mp3 생성. ElevenLabs 우선, 실패 시 edge-tts 폴백.

    presets를 주면 장면마다 다른 프리셋을 쓴다. 목소리가 바뀌면 음성과
    속도도 그 프리셋 값을 따라가야 해서 매 장면 다시 집어 온다.
    """
    use_el = _check_elevenlabs()

    results = []
    for i, text in enumerate(texts):
        if not text.strip():
            results.append(None)
            continue
        # 장면별 프리셋이 있으면 음성·속도까지 그 설정으로 바꾼다.
        cur = (presets[i] if presets and i < len(presets) else None) or preset
        p = PRESETS.get(cur, {})
        cur_voice = p.get("voice", voice)
        cur_rate = p.get("rate", rate)

        raw_mp3 = os.path.join(out_dir, f"narr_raw_{i:02d}.mp3")
        mp3 = os.path.join(out_dir, f"narr_{i:02d}.mp3")

        el_ok = False
        if use_el:
            # ElevenLabs는 자체적으로 자연스러우므로 후처리 불필요
            el_ok = _synth_elevenlabs(text, mp3)
            if el_ok:
                tag = f" [EL]" if not cur else f" [EL·{cur}]"
            else:
                print(f"  [폴백] ElevenLabs 실패 → edge-tts 시도")

        if not el_ok:
            # edge-tts 폴백
            import edge_tts
            comm = edge_tts.Communicate(text, cur_voice, rate=cur_rate)
            await comm.save(raw_mp3)
            # 성우 톤 후처리 (edge-tts만 — ElevenLabs는 이미 자연스러움)
            if style:
                try:
                    post_process_voice(raw_mp3, mp3, cur_voice, cur)
                except Exception as e:
                    print(f"  후처리 실패, 원본 사용: {e}")
                    os.replace(raw_mp3, mp3)
            else:
                os.replace(raw_mp3, mp3)
            tag = f" [{cur}]" if cur else ""

        # 길이 측정
        dur = get_duration(mp3)
        results.append({"path": mp3, "duration": dur})
        print(f"  TTS [{i+1}/{len(texts)}]{tag} {dur:.1f}초  {text[:28]}...")
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
    ap.add_argument("script", nargs="?", help="대본 JSON")
    ap.add_argument("--cards", help="카드 이미지 디렉터리 (미지정 시 자동 추론)")
    ap.add_argument("--voice", default=None, help="TTS 음성 (프리셋보다 우선)")
    ap.add_argument("--rate", default=None,
                    help="발화 속도 (예: -10%%, +20%%). 프리셋보다 우선")
    ap.add_argument("--preset", default=None,
                    help="음성 프리셋. 쉼표로 여럿 주면 대본마다 하나를 "
                         "골라 쓴다 (예: 앵커,발랄녀). 가능: "
                         + ", ".join(PRESETS))
    ap.add_argument("--alternate", action="store_true",
                    help="--preset을 여럿 줬을 때 한 영상 안에서 장면마다 "
                         "번갈아 쓴다 (남녀 교대 진행 느낌)")
    ap.add_argument("--list-presets", action="store_true",
                    help="프리셋 목록만 출력하고 끝낸다")
    ap.add_argument("--no-tts", action="store_true", help="TTS 없이 무음 영상")
    ap.add_argument("--no-style", action="store_true",
                    help="양상국 스타일 후처리 없이 원본 TTS 사용")
    ap.add_argument("--require-tts", action="store_true",
                    help="TTS가 실패하면 무음으로 넘어가지 않고 중단한다")
    ap.add_argument("-o", "--out", help="출력 mp4 경로")
    a = ap.parse_args()

    if a.list_presets:
        for k, v in PRESETS.items():
            print(f"  {k:6s} {v['voice']:34s} 피치 {v['pitch']:.2f}  "
                  f"속도 {v['rate']:>5s}  {v['desc']}")
        return

    if not a.script:
        ap.error("대본 JSON 경로가 필요합니다")

    pool = parse_preset_pool(a.preset)
    stem0 = os.path.splitext(os.path.basename(a.script))[0]
    chosen = pick_preset(pool, stem0)

    # 프리셋이 음성·속도를 정하고, 따로 준 값이 있으면 그쪽을 쓴다.
    prof = PRESETS.get(chosen, {})
    a.voice = a.voice or prof.get("voice", DEFAULT_VOICE)
    a.rate = a.rate or prof.get("rate", DEFAULT_RATE)

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
    if pool and len(pool) > 1:
        mode = "장면마다 번갈아" if a.alternate else f"이 대본은 {chosen}"
        print(f"음성: 프리셋 {'/'.join(pool)} 중 {mode}")
    else:
        tag = f", 프리셋 {chosen}" if chosen else ""
        print(f"음성: {a.voice} (속도 {a.rate}{tag})")

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
            per_scene = scene_presets(pool, stem, len(texts), a.alternate)
            try:
                tts_results = asyncio.run(generate_tts(texts, a.voice, tmp,
                                                       style=not a.no_style,
                                                       rate=a.rate,
                                                       preset=chosen,
                                                       presets=per_scene))
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
