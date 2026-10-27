# -*- coding: utf-8 -*-
"""
preset_samples.py — 프리셋별 음성 샘플을 한 번에 뽑는다.

후처리까지 걸린 상태로 들어봐야 실제로 쓸지 판단할 수 있다.
edge-tts는 프록시가 막아서 작업환경에서는 돌지 않고, Actions에서 쓴다.

사용:
  python preset_samples.py                    # 전체 프리셋
  python preset_samples.py --only 다큐,앵커
  python preset_samples.py --text "읽힐 문장"
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_reels import PRESETS, post_process_voice  # noqa: E402

DEFAULT_TEXT = ("트와이스 나연이 2년 5개월 만에 솔로로 나온다카더라. "
                "첫 앨범이 빌보드 200에서 7위까지 올라갔데이. 참말로 대단한기라.")


async def build(text, out_dir, names):
    import edge_tts

    os.makedirs(out_dir, exist_ok=True)
    made = []
    for name in names:
        p = PRESETS[name]
        raw = os.path.join(out_dir, f"_{name}_raw.mp3")
        out = os.path.join(out_dir, f"{name}.mp3")
        print(f"[{name}] {p['voice']} 피치 {p['pitch']} 속도 {p['rate']}")
        try:
            await edge_tts.Communicate(text, p["voice"], rate=p["rate"]).save(raw)
            post_process_voice(raw, out, p["voice"], name)
            made.append(name)
            print(f"  ✓ {out}")
        except Exception as e:
            # 하나가 실패해도 나머지는 받아야 비교를 할 수 있다.
            print(f"  ✗ 실패: {e}")
        finally:
            if os.path.exists(raw):
                os.remove(raw)

    # 어떤 설정으로 만든 것인지 함께 남겨야 나중에 알아볼 수 있다.
    with open(os.path.join(out_dir, "_설명.txt"), "w", encoding="utf-8") as f:
        f.write(f"문장: {text}\n\n")
        for name in made:
            p = PRESETS[name]
            f.write(f"{name}\n  {p['desc']}\n"
                    f"  음성 {p['voice']} / 피치 {p['pitch']} / 속도 {p['rate']}\n\n")
    return made


def main():
    ap = argparse.ArgumentParser(description="프리셋별 음성 샘플 생성")
    ap.add_argument("--text", default=DEFAULT_TEXT)
    ap.add_argument("--out", default="samples/presets")
    ap.add_argument("--only", help="쉼표로 구분한 프리셋 이름 (기본: 전체)")
    a = ap.parse_args()

    names = [n.strip() for n in a.only.split(",")] if a.only else list(PRESETS)
    unknown = [n for n in names if n not in PRESETS]
    if unknown:
        raise SystemExit(f"없는 프리셋: {', '.join(unknown)}\n"
                         f"가능: {', '.join(PRESETS)}")

    made = asyncio.run(build(a.text, a.out, names))
    print(f"\n{len(made)}/{len(names)}개 생성: {a.out}")
    if not made:
        raise SystemExit("생성된 샘플이 없습니다")


if __name__ == "__main__":
    main()
