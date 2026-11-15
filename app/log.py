"""极简日志：写 output/app.log，供 pythonw 无控制台时排查。"""

from __future__ import annotations

import time
import traceback
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "output"


def log(msg: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_DIR / "app.log", "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')}  {msg}\n")
    except Exception:
        pass


def log_exc(where: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_DIR / "app.log", "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')}  !! {where}\n")
            fh.write(traceback.format_exc() + "\n")
    except Exception:
        pass
