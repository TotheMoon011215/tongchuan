r"""离屏渲染界面截图，用于检查布局（窗口会移到屏幕外，不打扰使用）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QRectF          # noqa: E402
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication    # noqa: E402

from app.config import Config                  # noqa: E402
from app.ui import HistoryWindow, OverlayWindow, SettingsDialog, UiBus  # noqa: E402

OUT = ROOT / ".tmp"
PARK = (-5000, -5000)   # 把窗口停到屏幕外


def compose(widget, path: Path, w: int = 1240, h: int = 420) -> None:
    """把带透明背景的窗口贴到模拟桌面上。"""
    shot = widget.grab()
    canvas = QPixmap(w, h)
    p = QPainter(canvas)
    g = QLinearGradient(0, 0, 0, h)
    g.setColorAt(0.0, QColor(38, 44, 56))
    g.setColorAt(1.0, QColor(22, 26, 33))
    p.fillRect(0, 0, w, h, g)
    p.setPen(QColor(70, 78, 92))
    p.setFont(QFont("Segoe UI", 11))
    p.drawText(40, 46, "（模拟桌面背景）")
    x = (w - shot.width()) // 2
    y = h - shot.height() - 40
    p.drawPixmap(x, y, shot)
    p.end()
    canvas.save(str(path))
    print(f"  saved {path}  ({shot.width()}x{shot.height()})")


def main() -> int:
    app = QApplication(sys.argv)
    from app.main import _dark_palette

    app.setStyle("Fusion")
    app.setPalette(_dark_palette())
    app.setFont(QFont("Microsoft YaHei UI", 10))
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = Config()
    bus = UiBus()

    # ---------- 悬浮字幕 ----------
    ov = OverlayWindow(cfg, bus)
    ov._auto_pos = False
    cfg.ui_pos_x, cfg.ui_pos_y = PARK
    ov.move(*PARK)
    ov.show()
    app.processEvents()
    bus.listening.emit(True)
    bus.status.emit("正在聆听（麦克风）")
    bus.level.emit(0.62)
    bus.sentence_start.emit(1)
    bus.hypothesis.emit(
        "Good afternoon everyone. Today I'd like to talk about how AI is changing the way we work.")
    bus.zh_delta.emit(1, "各位下午好。今天我想谈谈")
    bus.zh_delta.emit(1, "人工智能正在如何改变我们的工作方式。")
    bus.stats.emit({"asr_ms": 126, "mt_first_ms": 483})
    app.processEvents()
    compose(ov, OUT / "preview_overlay.png", 1240, 380)

    # 只有英文时（未配置 Key）
    ov2 = OverlayWindow(cfg, bus)
    ov2._auto_pos = False
    ov2.move(*PARK)
    ov2.show()
    ov2._pending_clear = False
    ov2.zh_label.setText("说英文，这里出现中文")
    ov2.en_label.setText("")
    app.processEvents()
    compose(ov2, OUT / "preview_idle.png", 1240, 300)

    # ---------- 设置 ----------
    dlg = SettingsDialog(cfg, bus)
    dlg.move(*PARK)
    for i in range(4):
        dlg.tabs.setCurrentIndex(i)
        dlg.resize(640, 520)
        dlg.show()
        app.processEvents()
        dlg.grab().save(str(OUT / f"preview_settings_{i}.png"))
        print(f"  saved preview_settings_{i}.png (tab {dlg.tabs.tabText(i)})")

    # ---------- 历史 ----------
    hist = HistoryWindow(cfg)
    hist.append("Good afternoon everyone.", "各位下午好。")
    hist.append("Thank you for joining today's session on AI.",
                "感谢参加今天关于人工智能的会议。")
    hist.move(*PARK)
    hist.show()
    app.processEvents()
    hist.grab().save(str(OUT / "preview_history.png"))
    print("  saved preview_history.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
