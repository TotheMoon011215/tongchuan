r"""总线契约测试：用真实的 UiBus + OverlayWindow 走一遍所有信号。

这类测试能抓住「信号名写错 / 参数个数不符 / 误用 signal(...) 直接调用」的问题，
之前正是因为少了它，导致启动线程抛出 TypeError 后静默死掉。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config import Config                # noqa: E402
from app.ui import OverlayWindow, UiBus      # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    cfg = Config()
    bus = UiBus()
    ov = OverlayWindow(cfg, bus)
    ov.move(-5000, -5000)
    ov.show()
    app.processEvents()

    checks: list[tuple[str, bool, str]] = []

    bus.status.emit("正在聆听（麦克风）")
    bus.listening.emit(True)
    bus.level.emit(0.5)
    bus.sentence_start.emit(1)          # 真实顺序：先开新句，再出英文
    bus.hypothesis.emit("Hello world.")
    bus.zh_delta.emit(1, "你好，")
    bus.zh_delta.emit(1, "世界。")
    bus.stats.emit({"asr_ms": 120, "mt_first_ms": 480})
    bus.error.emit("测试错误")
    bus.pair.emit("Hello world.", "你好，世界。", 1)
    app.processEvents()

    checks.append(("状态栏", ov.status.text().startswith("⚠"), ov.status.text()))
    checks.append(("聆听按钮变为停止", ov.btn_start.text() == "■", ov.btn_start.text()))
    checks.append(("英文行", "Hello world." in ov.en_label.text(), ov.en_label.text()))
    checks.append(("中文行", ov.zh_label.text() == "你好，世界。", ov.zh_label.text()))
    checks.append(("延迟统计", "识别 120ms" in ov.stats.text(), ov.stats.text()))

    # 新句子到来时旧字幕不清空，等新译文到了才清
    bus.sentence_start.emit(2)
    app.processEvents()
    checks.append(("切句不清空中文", ov.zh_label.text() == "你好，世界。", ov.zh_label.text()))
    bus.zh_delta.emit(2, "第二句。")
    app.processEvents()
    checks.append(("新译文到达后替换", ov.zh_label.text() == "第二句。", ov.zh_label.text()))

    # 旧句子的迟到增量应被忽略
    bus.zh_delta.emit(1, "过期内容")
    app.processEvents()
    checks.append(("迟到增量被丢弃", "过期" not in ov.zh_label.text(), ov.zh_label.text()))

    ok = True
    for name, passed, detail in checks:
        print(f"  {'✓' if passed else '✗'} {name}: {detail!r}")
        ok = ok and passed

    print("=" * 50)
    print("结果:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
