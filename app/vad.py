"""语音活动检测（VAD）：Silero VAD v6（ONNX），并带能量法兜底。"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

SR = 16000


def _find_silero() -> Path | None:
    """优先用项目自带的模型，其次用 faster-whisper 内置的。"""
    local = Path(__file__).resolve().parent.parent / "models" / "silero_vad.onnx"
    if local.exists():
        return local
    try:
        import faster_whisper

        assets = Path(faster_whisper.__file__).parent / "assets"
        for p in sorted(assets.glob("*.onnx")):
            return p
    except Exception:
        pass
    return None


class SileroVAD:
    """逐帧输出“这是人声”的概率。"""

    def __init__(self, model_path: str | Path | None = None):
        self.available = False
        self.window = 512
        self._style = ""
        self._names: list[str] = []
        self.session = None
        self._h = self._c = self._state = None
        self.error = ""

        path = Path(model_path) if model_path else _find_silero()
        if path is None or not Path(path).exists():
            self.error = "未找到 Silero VAD 模型，改用能量检测"
            return
        try:
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
            opts.log_severity_level = 3
            self.session = ort.InferenceSession(
                str(path), sess_options=opts, providers=["CPUExecutionProvider"]
            )
            inputs = self.session.get_inputs()
            self._names = [i.name for i in inputs]
            shape = inputs[0].shape
            last = shape[-1] if shape else 512
            self.window = int(last) if isinstance(last, int) else 512
            self._style = "v4h" if "h" in self._names else "v5state"
            self.reset()
            self.available = True
        except Exception as exc:  # noqa: BLE001
            self.error = f"VAD 加载失败（{exc}），改用能量检测"
            self.session = None

    def reset(self) -> None:
        if self.session is None:
            return
        if self._style == "v4h":
            self._h = np.zeros((1, 1, 128), np.float32)
            self._c = np.zeros((1, 1, 128), np.float32)
        else:
            self._state = np.zeros((2, 1, 128), np.float32)

    def prob(self, chunk: np.ndarray) -> float:
        if self.session is None:
            return -1.0
        x = np.asarray(chunk, dtype=np.float32)[None, :]
        try:
            if self._style == "v4h":
                out = self.session.run(
                    None, {"input": x, "h": self._h, "c": self._c}
                )
                self._h, self._c = out[1], out[2]
            else:
                out = self.session.run(
                    None,
                    {
                        "input": x,
                        "state": self._state,
                        "sr": np.array(SR, dtype=np.int64),
                    },
                )
                self._state = out[1]
            return float(np.asarray(out[0]).ravel()[0])
        except Exception as exc:  # noqa: BLE001
            self.error = f"VAD 推理失败：{exc}"
            self.session = None
            return -1.0


class _EnergyVAD:
    """没有 ONNX 时的兜底：自适应噪声门限。"""

    def __init__(self) -> None:
        self.window = 512
        self.noise = 0.004
        self.available = True
        self.error = ""
        self._buf = np.zeros(0, np.float32)

    def reset(self) -> None:
        pass

    def prob(self, chunk: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(np.square(chunk)) + 1e-12))
        # 缓慢跟踪底噪
        if rms < self.noise:
            self.noise = 0.98 * self.noise + 0.02 * rms
        else:
            self.noise = 0.999 * self.noise + 0.001 * rms
        floor = max(self.noise * 3.0, 0.004)
        return float(min(1.0, max(0.0, (rms - floor) / max(floor * 3.0, 1e-6))))


def make_vad(model_path: str | Path | None = None):
    v = SileroVAD(model_path)
    if v.available:
        return v
    return _EnergyVAD()


class VADGate:
    """
    把连续音频流切成“语音段”，带起始确认与静音挂起。

    feed(block) 之后读 in_speech / just_started / just_ended。
    """

    def __init__(self, engine, threshold: float = 0.45, min_silence: float = 0.5,
                 min_speech: float = 0.09, sr: int = SR):
        self.engine = engine
        self.threshold = float(threshold)
        self.min_silence = float(min_silence)
        self.min_speech = float(min_speech)
        self.sr = sr
        self.window = int(getattr(engine, "window", 512))
        self._buf = np.zeros(0, np.float32)
        self.in_speech = False
        self.just_started = False
        self.just_ended = False
        self._speech = 0.0
        self._silence = 0.0
        self.last_prob = 1.0 if not getattr(engine, "available", False) else 0.0

    def reset(self) -> None:
        self._buf = np.zeros(0, np.float32)
        self.in_speech = False
        self.just_started = False
        self.just_ended = False
        self._speech = self._silence = 0.0
        try:
            self.engine.reset()
        except Exception:
            pass

    def feed(self, block: np.ndarray) -> None:
        self.just_started = False
        self.just_ended = False
        if block.size == 0:
            return
        self._buf = np.concatenate((self._buf, np.asarray(block, np.float32)))
        dur = self.window / self.sr
        while self._buf.size >= self.window:
            chunk = self._buf[: self.window]
            self._buf = self._buf[self.window:]
            p = self.engine.prob(chunk)
            if p < 0:
                p = 0.0
            self.last_prob = p
            if p >= self.threshold:
                self._speech += dur
                self._silence = 0.0
                if not self.in_speech and self._speech >= self.min_speech:
                    self.in_speech = True
                    self.just_started = True
            else:
                self._silence += dur
                if self._speech > 0:
                    self._speech = max(0.0, self._speech - dur * 0.5)
                if self.in_speech and self._silence >= self.min_silence:
                    self.in_speech = False
                    self.just_ended = True
