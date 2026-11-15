"""本地语音识别：faster-whisper（CTranslate2），默认跑在 CUDA 上。"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np


class ASREngine:
    def __init__(
        self,
        model_path: str | Path,
        device: str = "auto",
        compute_type: str = "auto",
        language: str = "en",
        beam_size: int = 1,
        cpu_threads: int = 0,
    ):
        self.model_path = str(model_path)
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.beam_size = int(beam_size)
        self.cpu_threads = int(cpu_threads)
        self.model = None
        self.device_used = ""
        self.compute_used = ""
        self.load_error = ""

    # ------------------------------------------------------------------
    def load(self) -> str:
        """加载模型并做一次真实推理，确认当前显卡/驱动真的能用。"""
        from .cuda_dlls import setup_cuda_dlls

        setup_cuda_dlls()
        from faster_whisper import WhisperModel

        if not Path(self.model_path).exists():
            raise FileNotFoundError(f"模型目录不存在：{self.model_path}")

        attempts: list[tuple[str, str]] = []
        if self.device == "auto":
            attempts = [("cuda", "float16"), ("cuda", "int8_float16"), ("cpu", "int8")]
        elif self.device == "cuda":
            ct = self.compute_type if self.compute_type != "auto" else "float16"
            attempts = [("cuda", ct), ("cpu", "int8")]
        else:
            ct = self.compute_type if self.compute_type != "auto" else "int8"
            attempts = [("cpu", ct)]

        errors: list[str] = []
        for dev, ct in attempts:
            try:
                kwargs = {"device": dev, "compute_type": ct, "num_workers": 1}
                if dev == "cpu" and self.cpu_threads > 0:
                    kwargs["cpu_threads"] = self.cpu_threads
                model = WhisperModel(self.model_path, **kwargs)
                self.model = model
                # 空跑一次，确保 CUDA kernel 在当前架构上真能跑
                self._transcribe(np.zeros(16000, np.float32), None)
                self.device_used, self.compute_used = dev, ct
                self.load_error = ""
                return f"{dev} / {ct}"
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{dev}/{ct} → {type(exc).__name__}: {exc}")
                self.model = None
        self.load_error = " | ".join(errors)
        raise RuntimeError("语音识别模型加载失败：" + self.load_error)

    # ------------------------------------------------------------------
    def _transcribe(self, audio: np.ndarray, initial_prompt: str | None) -> str:
        segments, _info = self.model.transcribe(
            audio,
            language=self.language,
            task="transcribe",
            beam_size=self.beam_size,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            without_timestamps=True,
            vad_filter=False,
            initial_prompt=initial_prompt or None,
            no_speech_threshold=0.55,
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
        )
        return "".join(seg.text for seg in segments).strip()

    def transcribe(self, audio: np.ndarray, initial_prompt: str | None = None) -> tuple[str, float]:
        """返回 (文本, 耗时毫秒)。"""
        if self.model is None:
            raise RuntimeError("模型未加载")
        if audio.size < 1600:  # <0.1s 不值得识别
            return "", 0.0
        t0 = time.perf_counter()
        text = self._transcribe(np.ascontiguousarray(audio, dtype=np.float32), initial_prompt)
        return text, (time.perf_counter() - t0) * 1000.0

    def close(self) -> None:
        self.model = None
