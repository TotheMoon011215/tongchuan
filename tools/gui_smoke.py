r"""GUI 冒烟测试：离屏创建主窗口/托盘/控制器，2.5 秒后自动退出。"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer          # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import app.main as M                        # noqa: E402

_orig_exec = QApplication.exec


def _exec(*_args):  # noqa: ANN001
    app = QApplication.instance()
    QTimer.singleShot(2500, app.quit)
    return _orig_exec()


QApplication.exec = staticmethod(_exec)


def main() -> int:
    try:
        code = M.main(["--no-hotkeys"])
    except Exception:
        traceback.print_exc()
        return 1
    print(f"GUI smoke: OK (exit={code})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
