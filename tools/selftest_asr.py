r"""命令行自检：用一段 WAV 验证语音识别链路是否正常。

用法：
    python tools\selftest_asr.py                  # 用 assets/sample_en.wav
    python tools\selftest_asr.py 路径\xxx.wav
"""

from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.asr import ASREngine          # noqa: E402
from app.audio import LinearResampler  # noqa: E402
from app.config import Config          # noqa: E402
from app.vad import make_vad, VADGate  # noqa: E402


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw == 2:
        x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    elif sw == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        x = ((b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8)
              | (b[:, 2].astype(np.int8).astype(np.int32) << 16)) / 8388608.0).astype(np.float32)
    elif sw == 4:
        x = np.frombuffer(raw, np.int32).astype(np.float32) / 2147483648.0
    else:
        x = np.frombuffer(raw, np.uint8).astype(np.float32) / 128.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        x = LinearResampler(sr, 16000).process(x)
    return np.ascontiguousarray(x, np.float32), sr


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "assets" / "sample_en.wav"
    if not path.exists():
        print(f"[x] 找不到音频：{path}")
        return 2

    audio, sr = read_wav(path)
    print(f"[i] 音频 {path.name}  {audio.size / 16000:.2f}s (原 {sr}Hz)")

    cfg = Config.load()
    print(f"[i] 模型 {cfg.model_path()}")

    # ---- VAD ----
    vad = make_vad()
    gate = VADGate(vad, cfg.vad_threshold, cfg.vad_min_silence)
    block = 512
    speech_frames = 0
    total_frames = 0
    for i in range(0, audio.size - block, block):
        gate.feed(audio[i:i + block])
        total_frames += 1
        if gate.in_speech:
            speech_frames += 1
    print(f"[i] VAD 判定语音占比 {speech_frames / max(total_frames,1) * 100:.0f}%"
          f"  (engine={'silero' if vad.available else 'energy'})")

    # ---- ASR ----
    t0 = time.perf_counter()
    eng = ASREngine(cfg.model_path(), cfg.asr_device, cfg.asr_compute_type,
                    cfg.asr_language, cfg.asr_beam_size)
    info = eng.load()
    print(f"[i] 模型加载 {info}  用时 {time.perf_counter()-t0:.1f}s")

    for label, clip in (("前5秒", audio[: 16000 * 5]), ("完整", audio)):
        text, ms = eng.transcribe(clip)
        rtf = (ms / 1000.0) / max(clip.size / 16000, 1e-6)
        print(f"\n[{label}] {ms:.0f}ms  实时率 {rtf:.2f}x")
        print(f"  EN: {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
