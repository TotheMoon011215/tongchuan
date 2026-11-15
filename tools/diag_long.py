r"""诊断：长句（>6 秒连续讲话）时识别是否丢词。

对比不同参数组合在「整段」和「切段」上的产出。
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.asr import ASREngine   # noqa: E402
from app.config import Config    # noqa: E402


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def run(eng, audio, label, **kw):
    from faster_whisper import WhisperModel  # noqa: F401

    model = eng.model
    segs, info = model.transcribe(
        np.ascontiguousarray(audio, np.float32),
        language="en", task="transcribe", beam_size=1, best_of=1,
        condition_on_previous_text=False, without_timestamps=True,
        vad_filter=False, **kw,
    )
    segs = list(segs)
    text = "".join(s.text for s in segs).strip()
    print(f"  {label:<38} 段数={len(segs):<2} 词数={len(text.split()):<3} {text[:110]}")
    return text


def main() -> int:
    cfg = Config.load()
    audio = read_wav(ROOT / "assets" / "sample_lecture.wav")
    print(f"整段音频 {audio.size / 16000:.1f}s")

    eng = ASREngine(cfg.model_path(), cfg.asr_device, cfg.asr_compute_type,
                    cfg.asr_language, cfg.asr_beam_size)
    print("模型:", eng.load())

    # 第 3 句大致在 11.0s ~ 20.3s
    clip = audio[int(10.8 * 16000):int(20.6 * 16000)]
    print(f"\n[切段] 第3句 {clip.size / 16000:.1f}s")
    run(eng, clip, "当前参数 (no_speech=0.55)")
    run(eng, clip, "no_speech=0.9", no_speech_threshold=0.9, log_prob_threshold=-1.0)
    run(eng, clip, "关闭阈值过滤", no_speech_threshold=1.0, log_prob_threshold=-2.0)

    prompt = ("Thank you all for coming today. In this session I will walk you through "
              "three main findings from our research.")
    print("\n[切段 + initial_prompt 上文]")
    run(eng, clip, "带上文提示", initial_prompt=prompt)
    run(eng, clip, "带上文提示 + 关阈值", initial_prompt=prompt,
        no_speech_threshold=1.0, log_prob_threshold=-2.0)

    print(f"\n[整段] {audio.size / 16000:.1f}s")
    run(eng, audio, "当前参数 (no_speech=0.55)")
    run(eng, audio, "关闭阈值过滤", no_speech_threshold=1.0, log_prob_threshold=-2.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
