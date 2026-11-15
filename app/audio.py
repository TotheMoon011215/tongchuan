"""音频采集：麦克风（sounddevice / PortAudio）与系统声音（soundcard / WASAPI 回环）。"""

from __future__ import annotations

import queue
import threading
import time
import numpy as np

TARGET_SR = 16000
BLOCK = 512          # 32ms
MAX_QUEUE = 400      # ~12.8 秒缓冲，防止界面卡死时无限堆积


def _com_init() -> None:
    """在工作线程里初始化 COM（WASAPI 回环必需，否则报 0x800401f0）。"""
    try:
        import ctypes

        ctypes.windll.ole32.CoInitializeEx(None, 0x0)  # COINIT_MULTITHREADED
    except Exception:
        pass


# --------------------------------------------------------------------------
# 设备枚举
# --------------------------------------------------------------------------
def list_microphones() -> list[str]:
    """返回可用输入设备名（优先 WASAPI，避免同一设备重复出现）。"""
    try:
        import sounddevice as sd
    except Exception:
        return []
    try:
        hostapis = sd.query_hostapis()
        devices = sd.query_devices()
    except Exception:
        return []

    names: list[str] = []
    seen: set[str] = set()
    # 先 WASAPI，再其它；同一名字只保留一次
    for want in ("Windows WASAPI", "Windows DirectSound", "MME"):
        for d in devices:
            if d.get("max_input_channels", 0) <= 0:
                continue
            api = hostapis[d["hostapi"]]["name"]
            if api != want:
                continue
            name = d["name"].strip()
            if name in seen:
                continue
            seen.add(name)
            names.append(name)
    return names


def list_loopback_devices() -> list[str]:
    """返回可采集的系统声音（回环）设备名。"""
    try:
        import soundcard as sc
        mics = sc.all_microphones(include_loopback=True)
        return [m.name for m in mics if getattr(m, "isloopback", False)]
    except Exception:
        return []


def default_input_name() -> str:
    """系统默认输入设备名（界面提示用）。"""
    try:
        import sounddevice as sd
        idx = sd.default.device[0]
        if idx is None or idx < 0:
            return ""
        return str(sd.query_devices(idx)["name"]).strip()
    except Exception:
        return ""


def default_output_name() -> str:
    """系统默认播放设备名（系统声音采集时用）。"""
    try:
        import sounddevice as sd
        idx = sd.default.device[1]
        if idx is None or idx < 0:
            return ""
        return str(sd.query_devices(idx)["name"]).strip()
    except Exception:
        return ""


# --------------------------------------------------------------------------
# 重采样（仅在设备不支持 16k 时使用）
# --------------------------------------------------------------------------
class LinearResampler:
    """带状态的分块线性重采样，保证块与块之间连续。"""

    def __init__(self, src_rate: int, dst_rate: int):
        self.step = float(src_rate) / float(dst_rate)
        self.pos = 0.0
        self.prev = np.zeros(0, np.float32)

    def process(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float32)
        if self.prev.size:
            x = np.concatenate((self.prev, x))
        n = x.shape[0]
        if n < 2:
            self.prev = x
            return np.empty(0, np.float32)

        idx = self.pos + np.arange(int(np.ceil((n - 1 - self.pos) / self.step))) * self.step
        if idx.size == 0:
            self.prev = x[-1:]
            self.pos = self.pos - (n - 1)
            return np.empty(0, np.float32)

        i0 = np.floor(idx).astype(np.int64)
        frac = (idx - i0).astype(np.float32)
        i1 = np.minimum(i0 + 1, n - 1)
        y = x[i0] * (1.0 - frac) + x[i1] * frac

        self.pos = float(idx[-1] + self.step) - (n - 1)
        self.prev = x[-1:].copy()
        return y.astype(np.float32, copy=False)


# --------------------------------------------------------------------------
# 采集器
# --------------------------------------------------------------------------
class AudioCapture:
    """
    统一采集接口：start() 后可用 read() 非阻塞/限时取 16kHz 单声道 float32 数据块。

    两种后端：
      microphone -> sounddevice（PortAudio）
      system     -> soundcard（WASAPI loopback，捕获电脑正在播放的声音）
    """

    def __init__(self, source: str = "microphone", device: str = "", samplerate: int = TARGET_SR):
        self.source = source
        self.device = device
        self.samplerate = samplerate
        self._q: queue.Queue[np.ndarray] = queue.Queue(maxsize=MAX_QUEUE)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self._level = 0.0
        self.actual_rate = 0
        self.backend = ""

    # -- 生命周期 --------------------------------------------------------
    def start(self) -> None:
        self._stop.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="audio-capture", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    @property
    def error(self) -> BaseException | None:
        return self._error

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # -- 数据读取 --------------------------------------------------------
    def read(self, timeout: float = 0.2) -> np.ndarray | None:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    @property
    def level(self) -> float:
        return self._level

    # -- 内部 ------------------------------------------------------------
    def _push(self, block: np.ndarray) -> None:
        if block.size == 0:
            return
        rms = float(np.sqrt(np.mean(np.square(block, dtype=np.float64)) + 1e-12))
        self._level = min(1.0, rms * 6.0)
        try:
            self._q.put_nowait(block)
        except queue.Full:
            try:
                self._q.get_nowait()
                self._q.put_nowait(block)
            except Exception:
                pass

    def _run(self) -> None:
        try:
            if self.source == "system":
                self._run_system()
            else:
                self._run_mic()
        except BaseException as exc:  # noqa: BLE001 - 需要把错误抛给界面
            self._error = exc
        finally:
            self._level = 0.0

    # -- 麦克风 ----------------------------------------------------------
    def _run_mic(self) -> None:
        import sounddevice as sd

        dev = self._resolve_mic(sd)
        try:
            info = sd.query_devices(dev, "input")
            native = int(info.get("default_samplerate") or 48000)
        except Exception:
            native = 48000

        candidates = [TARGET_SR]
        if native != TARGET_SR:
            candidates.append(native)

        last_err: BaseException | None = None
        for sr in candidates:
            try:
                self._stream_mic(sd, dev, sr)
                return
            except BaseException as exc:  # noqa: BLE001
                last_err = exc
                if self._stop.is_set():
                    return
        raise RuntimeError(f"无法打开麦克风（{dev}）：{last_err}")

    def _stream_mic(self, sd, dev, sr: int) -> None:
        rs = None if sr == TARGET_SR else LinearResampler(sr, TARGET_SR)

        def callback(indata, frames, time_info, status):  # noqa: ANN001
            mono = indata[:, 0] if indata.ndim > 1 else indata
            mono = np.asarray(mono, dtype=np.float32)
            if rs is not None:
                mono = rs.process(mono)
            self._push(mono.copy())

        extra = None
        try:
            if "Windows WASAPI" in (sd.query_hostapis(sd.query_devices(dev)["hostapi"])["name"]):
                extra = sd.WasapiSettings(auto_convert=True)
        except Exception:
            extra = None

        stream = sd.InputStream(
            device=dev,
            channels=1,
            samplerate=sr,
            blocksize=BLOCK,
            dtype="float32",
            latency="low",
            callback=callback,
            extra_settings=extra,
        )
        with stream:
            self.actual_rate = sr
            self.backend = "sounddevice"
            while not self._stop.is_set():
                time.sleep(0.05)

    def _resolve_mic(self, sd):
        if not self.device:
            return None  # 系统默认
        dev = self.device.strip()
        if dev.isdigit():
            return int(dev)
        devices = sd.query_devices()
        # 精确匹配优先
        for i, d in enumerate(devices):
            if d.get("max_input_channels", 0) > 0 and d["name"].strip() == dev:
                return i
        # 模糊匹配
        low = dev.lower()
        for i, d in enumerate(devices):
            if d.get("max_input_channels", 0) > 0 and low in d["name"].lower():
                return i
        return None

    # -- 系统声音 --------------------------------------------------------
    def _run_system(self) -> None:
        # 注意顺序：必须先 import soundcard —— 它在导入时就以 STA 初始化 COM。
        # 若先 CoInitializeEx(MTA) 再导入，会抛 Error 0x100000001（模式冲突）。
        import soundcard as sc

        mic = None
        if self.device:
            try:
                mic = sc.get_microphone(id=self.device, include_loopback=True)
            except Exception:
                mic = None
        if mic is None:
            speaker = sc.default_speaker()
            if speaker is None:
                raise RuntimeError("找不到默认播放设备，无法采集系统声音")
            mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
        if mic is None:
            raise RuntimeError("无法打开系统声音回环设备")

        with mic.recorder(samplerate=self.samplerate, channels=1, blocksize=BLOCK) as rec:
            self.actual_rate = self.samplerate
            self.backend = "soundcard"
            while not self._stop.is_set():
                data = rec.record(numframes=BLOCK)
                if data is None or len(data) == 0:
                    continue
                mono = data[:, 0] if getattr(data, "ndim", 1) > 1 else data
                self._push(np.asarray(mono, dtype=np.float32).copy())
