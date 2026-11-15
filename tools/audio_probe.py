r"""音频设备检测：列出设备，并实采 2.5 秒看电平。

用法：
    python tools\audio_probe.py             # 只测默认麦克风 + 系统声音
    python tools\audio_probe.py --list      # 只列出设备
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.audio import (  # noqa: E402
    AudioCapture, default_input_name, default_output_name, list_loopback_devices,
    list_microphones,
)


def probe(source: str, device: str = "", seconds: float = 2.5) -> tuple[int, float, str]:
    cap = AudioCapture(source, device)
    cap.start()
    time.sleep(0.8)
    blocks = 0
    peak = 0.0
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        b = cap.read(timeout=0.2)
        if b is not None:
            blocks += 1
            peak = max(peak, float(np.abs(b).max()), cap.level)
    cap.stop()
    err = cap.error
    err_s = f"{type(err).__name__}: {str(err)[:110]}" if err else "-"
    print(f"  backend={cap.backend or '-':<12} rate={cap.actual_rate:<6} "
          f"blocks={blocks:<3} level={peak:.3f}  err={err_s}")
    return blocks, peak, err_s


def main() -> int:
    only_list = "--list" in sys.argv

    mics = list_microphones()
    loops = list_loopback_devices()
    print(f"默认麦克风: {default_input_name() or '(无)'}")
    print(f"默认播放设备: {default_output_name() or '(无)'}")
    print(f"\n输入设备 {len(mics)} 个:")
    for m in mics:
        print(f"  - {m}")
    print(f"\n系统声音(回环) {len(loops)} 个:")
    for m in loops:
        print(f"  - {m}")
    if only_list:
        return 0

    print("\n[实测 · 麦克风（默认）]  请说几句话…")
    mb, ml, _ = probe("microphone")
    if mb == 0:
        print("  !! 一个音频块都没收到，麦克风打不开或被占用")

    print("\n[实测 · 系统声音（默认）]  请播放一点声音…")
    sb, sl, _ = probe("system")
    if sb == 0:
        print("  !! 系统声音采集失败（可忽略，如果你只用麦克风）")

    print("\n结论:")
    print(f"  麦克风 {'OK' if mb and ml > 0.01 else '电平太低 / 不可用'}")
    print(f"  系统声音 {'OK' if sb and sl > 0.01 else '不可用（可能没有回环设备）'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
