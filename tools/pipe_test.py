r"""端到端管线自检（不用麦克风、不用 API Key）。

把一段 WAV 当作实时麦克风输入喂给 Pipeline，验证：
    VAD 切句 -> 流式识别 -> 增量提交 -> 翻译调度 -> 整句落地
翻译用假的实现，只验证调度与字幕拼接逻辑。

用法： python tools\pipe_test.py [wav路径] [--speed 1.0]
"""

from __future__ import annotations

import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import translator as tr_mod            # noqa: E402
from app import pipeline as pipe_mod            # noqa: E402
from app.audio import LinearResampler           # noqa: E402
from app.config import Config                   # noqa: E402

BLOCK = 512


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        x = LinearResampler(sr, 16000).process(x)
    return np.ascontiguousarray(x, np.float32)


class FakeCapture:
    """把 WAV 当作实时音频流。"""

    def __init__(self, audio: np.ndarray, speed: float = 1.0):
        self.audio = audio
        self.speed = speed
        self.pos = 0
        self.error = None
        self.level = 0.0
        self.running = True
        self.actual_rate = 16000
        self.backend = "fake"
        self._t0 = time.monotonic()
        self._feeded = 0

    def start(self) -> None:
        self._t0 = time.monotonic()

    def stop(self) -> None:
        self.running = False

    def read(self, timeout: float = 0.2):
        # 按真实时间节奏吐数据
        target = (time.monotonic() - self._t0) * 16000 * self.speed
        if self.pos >= len(self.audio):
            time.sleep(0.03)
            return np.zeros(BLOCK, np.float32)   # 尾巴送静音，触发 VAD 收句
        if self.pos + BLOCK > target:
            time.sleep(0.01)
            return None
        blk = self.audio[self.pos:self.pos + BLOCK]
        if blk.size < BLOCK:
            blk = np.pad(blk, (0, BLOCK - blk.size))
        self.pos += BLOCK
        self.level = float(np.sqrt(np.mean(blk ** 2)) * 6)
        return blk


class FakeSignal:
    """模拟 PySide6 的 SignalInstance：只暴露 emit()，和真实用法保持一致。"""

    def __init__(self, fn):
        self._fn = fn

    def emit(self, *args) -> None:
        self._fn(*args)


class FakeBus:
    def __init__(self):
        self.events: list[tuple[str, object]] = []
        self.lock = threading.Lock()
        self.t0 = time.monotonic()
        # 与 app/ui/bus.py 的 UiBus 同名同参数
        self.status = FakeSignal(lambda s: self._add("status", s))
        self.listening = FakeSignal(lambda b: self._add("listening", b))
        self.level = FakeSignal(lambda v: None)
        self.hypothesis = FakeSignal(lambda s: self._add("hypothesis", s))
        self.partial = FakeSignal(lambda s: self._add("partial", s))
        self.sentence_start = FakeSignal(lambda sid: self._add("sentence_start", sid))
        self.zh_delta = FakeSignal(lambda sid, d: self._add("zh_delta", (sid, d)))
        self.pair = FakeSignal(self._pair)
        self.error = FakeSignal(lambda s: self._add("error", s))
        self.stats = FakeSignal(lambda d: None)

    def _add(self, kind, payload) -> None:
        with self.lock:
            self.events.append((kind, payload))
            t = time.monotonic() - self.t0
        if kind in ("sentence_start", "pair", "error", "status"):
            print(f"  [{t:6.2f}s] {kind:<14} {payload}", flush=True)

    def _pair(self, en, zh, sid) -> None:
        with self.lock:
            self.events.append(("pair", (en, zh, sid)))
            t = time.monotonic() - self.t0
        print(f"  [{t:6.2f}s] PAIR  EN: {en}", flush=True)
        print(f"           中文: {zh}\n", flush=True)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    speed = 1.0
    for a in sys.argv[1:]:
        if a.startswith("--speed"):
            speed = float(a.split("=")[1]) if "=" in a else 1.0
    wav = Path(args[0]) if args else ROOT / "assets" / "sample_en.wav"
    audio = load_wav(wav)
    print(f"[i] 音频 {wav.name} {audio.size/16000:.1f}s  速度 {speed}x", flush=True)

    # --- 打桩：假翻译 ---
    def fake_iter(self, text, ctx_en="", ctx_zh=""):
        out = f"〔译〕{text}"
        step = max(1, len(out) // 6)
        for i in range(0, len(out), step):
            yield out[i:i + step]
            time.sleep(0.01)

    tr_mod.Translator.translate_iter = fake_iter
    tr_mod.Translator.enabled = property(lambda self: True)

    # --- 打桩：假采集 ---
    fake = FakeCapture(audio, speed)
    pipe_mod.AudioCapture = lambda **kw: fake

    cfg = Config.load()
    cfg.mt_enabled = True
    cfg.step_sec = 0.4
    cfg.vad_min_silence = 0.5
    bus = FakeBus()

    eng = pipe_mod.Pipeline(cfg, bus)
    print("[i] 启动管线…", flush=True)
    eng.start()

    deadline = time.monotonic() + audio.size / 16000 / speed + 25
    while time.monotonic() < deadline:
        time.sleep(0.5)
        if fake.pos >= audio.size and not eng.running:
            break
    time.sleep(2.0)
    eng.stop()

    pairs = [p for k, p in bus.events if k == "pair"]
    errs = [p for k, p in bus.events if k == "error"]
    print("=" * 70)
    print(f"整句数: {len(pairs)}   错误: {len(errs)}")
    for e in errs:
        print("  ERR:", e)
    ok = len(pairs) >= 1 and not errs
    print("结果:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
