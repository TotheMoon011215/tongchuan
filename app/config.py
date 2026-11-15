"""配置管理：所有可调参数集中在这里，保存到项目根目录的 config.json。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
MODELS_DIR = ROOT / "models"
OUTPUT_DIR = ROOT / "output"

DEFAULTS: dict[str, Any] = {
    # ---------- 音频 ----------
    "audio_source": "microphone",          # microphone | system
    "input_device": "",                    # 设备名（空 = 系统默认）
    # ---------- 语音识别 ----------
    "asr_model": "models/faster-whisper-large-v3-turbo",
    "asr_device": "auto",                  # auto | cuda | cpu
    "asr_compute_type": "auto",            # auto | float16 | int8_float16 | int8 | float32
    "asr_beam_size": 1,
    "asr_language": "en",
    "step_sec": 0.3,                       # 每隔多久重新识别一次当前句
    "max_sentence_sec": 18.0,              # 一句话最多累积多久，超了强制切
    "vad_threshold": 0.45,
    "vad_min_silence": 0.5,                # 停顿多久视为一句结束
    # ---------- 翻译 ----------
    "mt_enabled": True,
    "mt_base_url": "https://api.deepseek.com",
    "mt_api_key": "",
    "mt_model": "deepseek-chat",
    "mt_temperature": 0.2,
    "mt_timeout": 45.0,
    "mt_clause_words": 6,                  # 攒够多少词就先翻一段（同传感）
    "mt_max_clause_words": 14,             # 再长也必须切
    "glossary": "",                        # 术语表，每行 "term=译名"
    # ---------- 界面 ----------
    "ui_font_size": 26,
    "ui_en_font_size": 15,
    "ui_opacity": 0.88,
    "ui_width": 1080,
    "ui_show_english": True,
    "ui_click_through": False,
    "ui_max_zh_chars": 170,                # 字幕条里中文最多留多少字，超了从头滚动
    "ui_pos_x": None,
    "ui_pos_y": None,
    # ---------- 其他 ----------
    "save_transcript": True,
    "hotkeys_enabled": True,
}


class Config:
    """轻量配置对象，支持 cfg.xxx 读写。"""

    def __init__(self, data: dict | None = None):
        object.__setattr__(self, "_d", {**DEFAULTS, **(data or {})})

    # -- 属性式访问 ------------------------------------------------------
    def __getattr__(self, name: str) -> Any:
        try:
            return object.__getattribute__(self, "_d")[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name: str, value: Any) -> None:
        object.__getattribute__(self, "_d")[name] = value

    def update(self, **kwargs: Any) -> None:
        self._d.update(kwargs)

    def as_dict(self) -> dict:
        return dict(self._d)

    # -- 持久化 ----------------------------------------------------------
    @classmethod
    def load(cls) -> "Config":
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                return cls(data)
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        CONFIG_PATH.write_text(
            json.dumps(self._d, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # -- 派生属性 --------------------------------------------------------
    @property
    def api_key(self) -> str:
        """优先读环境变量，方便不想把 Key 写进文件的人。"""
        return (
            os.environ.get("DEEPSEEK_API_KEY", "").strip()
            or (self.mt_api_key or "").strip()
            or os.environ.get("OPENAI_API_KEY", "").strip()
        )

    @property
    def mt_ready(self) -> bool:
        return bool(self.mt_enabled and self.api_key)

    def model_path(self) -> Path:
        p = Path(self.asr_model).expanduser()
        if not p.is_absolute():
            p = ROOT / p
        return p

    def model_missing(self) -> bool:
        p = self.model_path()
        return not (p.exists() and (p / "model.bin").exists())

    def glossary_pairs(self) -> list[tuple[str, str]]:
        out = []
        for line in (self.glossary or "").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            for sep in ("=", "：", ":"):
                if sep in line:
                    a, b = line.split(sep, 1)
                    if a.strip() and b.strip():
                        out.append((a.strip(), b.strip()))
                    break
        return out
