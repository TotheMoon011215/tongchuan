r"""分析 dump 出来的句子音频：能量包络 + 直接识别。"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Config  # noqa: E402


def read(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "seg3"
    p = ROOT / "output" / "dump" / f"{name}.wav"
    x = read(p)
    dur = x.size / 16000
    print(f"{p.name}: {dur:.2f}s")

    step = int(0.5 * 16000)
    bars = []
    for i in range(0, x.size, step):
        chunk = x[i:i + step]
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        bars.append(rms)
    print("每 0.5s RMS:")
    for i, r in enumerate(bars):
        print(f"  {i * 0.5:5.1f}s  {r:.4f}  {'#' * int(min(r * 200, 60))}")

    cfg = Config.load()
    from app.asr import ASREngine
    eng = ASREngine(cfg.model_path(), cfg.asr_device, cfg.asr_compute_type, "en", 1)
    print("模型:", eng.load())
    for label, prompt in (("无提示", None),
                          ("带上文", "Thank you all for coming today. In this session I will "
                                     "walk you through three main findings from our research.")):
        t, ms = eng.transcribe(x, prompt)
        print(f"\n[{label}] {ms:.0f}ms 词数={len(t.split())}\n  {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
