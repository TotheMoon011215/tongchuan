"""诊断：逐个尝试 WASAPI 回环设备，找出哪个能真正打开。"""
from __future__ import annotations

import ctypes
import traceback


def com_init() -> None:
    try:
        ctypes.windll.ole32.CoInitializeEx(None, 0x0)
    except Exception:
        pass


def try_open(mic, label: str) -> bool:
    try:
        with mic.recorder(samplerate=16000, channels=1, blocksize=512) as rec:
            for _ in range(3):
                data = rec.record(numframes=512)
            peak = float(abs(data).max()) if data is not None else -1.0
            print(f"  OK   {label}  peak={peak:.3f}")
            return True
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL {label}  {type(exc).__name__}: {exc}")
        return False


def main() -> None:
    import soundcard as sc  # 先导入：soundcard 自己会在导入时初始化 COM(STA)

    print("默认播放设备:", sc.default_speaker())
    try:
        spk = sc.default_speaker()
        mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
        print("默认回环 ->", mic)
        try_open(mic, "default_speaker")
    except Exception:
        traceback.print_exc()

    print("\n全部回环设备:")
    try:
        mics = sc.all_microphones(include_loopback=True)
    except Exception as exc:  # noqa: BLE001
        print("  枚举失败:", exc)
        return
    for m in mics:
        if not getattr(m, "isloopback", False):
            continue
        print(f"  - {m.name}")
        try_open(m, m.name)


if __name__ == "__main__":
    main()
