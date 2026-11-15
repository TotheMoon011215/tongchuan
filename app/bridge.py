"""LingoLens 桥接：不开 Qt 界面，运行同传管线，用 JSON 行和 Electron 通信。

stdin  一行一条命令：{"cmd":"start"} / {"cmd":"stop"} / {"cmd":"quit"} / {"cmd":"ping"}
stdout 一行一个事件：{"e":"hypothesis","text":"...","t":12.3}

环境变量：
  DEEPSEEK_API_KEY  翻译用的 key（Config.api_key 优先读它）
  LL_AUDIO_SOURCE   microphone | system
  LL_MT_MODEL       覆盖翻译模型（默认 deepseek-chat）
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

from .config import Config
from .pipeline import Pipeline

_T0 = time.monotonic()
_LOCK = threading.Lock()


def emit(**payload) -> None:
    payload.setdefault("t", round(time.monotonic() - _T0, 3))
    line = json.dumps(payload, ensure_ascii=False)
    with _LOCK:
        try:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        except Exception:
            pass


class _Sig:
    """伪 Qt 信号：有 .emit()，把参数转成 JSON。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self._last = 0.0

    def emit(self, *args) -> None:  # noqa: C901
        n = self.name
        if n == "pair" and len(args) >= 3:
            emit(e="pair", en=args[0], zh=args[1], sid=args[2])
        elif n == "zh_delta" and len(args) >= 2:
            emit(e="zh_delta", sid=args[0], delta=args[1])
        elif n == "sentence_start" and args:
            emit(e="sentence_start", sid=args[0])
        elif n == "stats" and args:
            data = args[0] if isinstance(args[0], dict) else {}
            emit(e="stats", **data)
        elif n == "listening" and args:
            emit(e="listening", on=bool(args[0]))
        elif n == "level" and args:
            now = time.monotonic()
            if now - self._last < 0.2:
                return
            self._last = now
            emit(e="level", v=round(float(args[0]), 3))
        elif n in ("status", "hypothesis", "partial", "error", "hotkey"):
            emit(e=n, text=(args[0] if args else ""))


class StdoutBus:
    """Pipeline 需要的全部信号名。"""

    def __init__(self) -> None:
        for name in ("status", "listening", "level", "hypothesis", "partial",
                     "sentence_start", "zh_delta", "pair", "error", "stats", "hotkey"):
            setattr(self, name, _Sig(name))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass

    cfg = Config.load()
    src = (os.environ.get("LL_AUDIO_SOURCE") or "").strip()
    if src in ("microphone", "system"):
        cfg.audio_source = src
    model = (os.environ.get("LL_MT_MODEL") or "").strip()
    if model:
        cfg.mt_model = model

    bus = StdoutBus()
    pipe = Pipeline(cfg, bus)

    emit(e="ready",
         model_missing=cfg.model_missing(),
         source=cfg.audio_source,
         mt_enabled=bool(cfg.mt_ready),
         version=1)

    if cfg.model_missing():
        emit(e="error", text="缺少语音识别模型（models/faster-whisper-large-v3-turbo）")

    try:
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                cmd = json.loads(line)
            except Exception:
                cmd = {"cmd": line}
            name = str(cmd.get("cmd") or "").lower()

            if name == "start":
                if pipe.running:
                    emit(e="started", already=True)
                    continue
                emit(e="status", text="启动中…")
                pipe.start()
                emit(e="started")
            elif name == "stop":
                pipe.stop()
                emit(e="stopped")
            elif name == "ping":
                emit(e="pong", running=pipe.running)
            elif name == "quit":
                break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            pipe.stop()
        except Exception:
            pass
        emit(e="bye")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
