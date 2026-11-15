"""测量翻译首字延迟：对比 模型 / 思考模式 三种组合。

用法（在 同传 目录）：
    set DEEPSEEK_API_KEY=sk-...
    runtime\\python.exe tools\\bench_mt.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.translator import Translator  # noqa: E402

TEXT = "I guess some crushes can be surface level."
CTX_EN = ""


def bench(name: str, model: str, thinking: str) -> None:
    cfg = Config.load()
    cfg.mt_api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    cfg.mt_model = model
    if not cfg.api_key:
        print("没有 API Key")
        return

    tr = Translator(cfg)
    orig = tr._payload

    def patched(text, ctx_en, ctx_zh, stream):
        p = orig(text, ctx_en, ctx_zh, stream)
        if thinking == "off":
            p["thinking"] = {"type": "disabled"}
        return p

    tr._payload = patched

    t0 = time.perf_counter()
    first = None
    out = []
    try:
        for delta in tr.translate_iter(TEXT, CTX_EN, ""):
            if first is None:
                first = time.perf_counter() - t0
            out.append(delta)
    except Exception as exc:  # noqa: BLE001
        print(f"{name:26s}  FAILED: {exc}")
        return
    total = time.perf_counter() - t0
    print(f"{name:26s}  first={first*1000:6.0f}ms  total={total*1000:6.0f}ms  out={''.join(out)[:34]}")


if __name__ == "__main__":
    print(f"model={Config.load().mt_model}  text={TEXT!r}\n")
    bench("deepseek-chat 默认思考", "deepseek-chat", "on")
    bench("deepseek-chat 关思考", "deepseek-chat", "off")
    bench("deepseek-flash 关思考", "deepseek-flash", "off")
