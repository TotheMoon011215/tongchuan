"""置顶悬浮字幕窗。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QSize, QTimer, QPoint
from PySide6.QtGui import QPainter, QPainterPath, QColor, QPen, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QSizePolicy,
)

from .bus import UiBus

ZH_FONT = "Microsoft YaHei UI"
EN_FONT = "Segoe UI"


class LevelBar(QWidget):
    """很小的输入电平条，用来确认麦克风是否真的收到声音。"""

    def __init__(self, parent=None, width: int = 84, height: int = 6):
        super().__init__(parent)
        self.setFixedSize(width, height)
        self._v = 0.0

    def set_level(self, v: float) -> None:
        self._v = max(0.0, min(1.0, float(v)))
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawRoundedRect(r, 3, 3)
        w = r.width() * self._v
        if w > 1:
            color = QColor(90, 200, 140)
            if self._v > 0.85:
                color = QColor(230, 120, 90)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(r.x(), r.y(), max(w, 3), r.height()), 3, 3)


_BTN_QSS = (
    "QToolButton{border:none;border-radius:6px;color:#c9d1d9;}"
    "QToolButton:hover{background:rgba(255,255,255,0.14);color:#fff;}"
    "QToolButton:pressed{background:rgba(255,255,255,0.22);}"
)
_BTN_ACTIVE_QSS = (
    "QToolButton{border:none;border-radius:6px;color:#0b1220;background:#4b9cf5;"
    "font-weight:600;}"
    "QToolButton:hover{background:#63a9f7;}"
)


def _mk_button(text: str, tip: str, slot, parent,
               width: int = 26, font_px: int = 14) -> QToolButton:
    b = QToolButton(parent)
    b.setText(text)
    b.setToolTip(tip)
    b.setFixedSize(width, 26)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(f"QToolButton{{font-size:{font_px}px;}}" + _BTN_QSS)
    b.clicked.connect(slot)
    return b


class OverlayWindow(QWidget):
    def __init__(self, cfg, bus: UiBus):
        super().__init__()
        self.cfg = cfg
        self.bus = bus
        self._sid = -1
        self._pending_clear = False
        self._dragging = False
        self._drag_off = QPoint()
        self._auto_pos = cfg.ui_pos_x is None and cfg.ui_pos_y is None
        self._click_through = False
        self._error_until = 0.0
        self._listening = False
        self._stats: dict = {}

        self._build()
        self._wire()
        self.apply_config()
        bus.status.emit("就绪，点击 ▶ 开始")

    # ------------------------------------------------------------------
    def _build(self) -> None:
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowTitle("同传字幕")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 12, 20, 16)
        root.setSpacing(6)

        # --- 顶部状态栏 ---
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.dot = QLabel("●")
        self.dot.setStyleSheet("color:#6b7280;font-size:12px;")
        self.status = QLabel("就绪")
        self.status.setStyleSheet("color:#9aa4b2;font-size:12px;")
        self.levelbar = LevelBar()
        self.stats = QLabel("")
        self.stats.setStyleSheet("color:#6b7280;font-size:11px;")

        self.btn_start = _mk_button("▶", "开始 / 停止（Ctrl+Alt+S）", self._toggle_run, self)
        self.btn_settings = _mk_button("⚙", "设置", self._open_settings, self)
        self.btn_history = _mk_button("☰", "历史记录", self._open_history, self)
        self.btn_pin = _mk_button("穿透", "鼠标穿透：点击直接落到下层窗口（Ctrl+Alt+P）",
                                  self.toggle_click_through, self, width=40, font_px=11)
        self.btn_close = _mk_button("✕", "隐藏窗口（可从托盘恢复）", self.hide, self)

        bar.addWidget(self.dot)
        bar.addWidget(self.status)
        bar.addSpacing(4)
        bar.addWidget(self.levelbar)
        bar.addWidget(self.stats)
        bar.addStretch(1)
        for b in (self.btn_start, self.btn_settings, self.btn_history,
                  self.btn_pin, self.btn_close):
            bar.addWidget(b)
        root.addLayout(bar)

        # --- 英文 ---
        self.en_label = QLabel("")
        self.en_label.setWordWrap(True)
        self.en_label.setTextInteractionFlags(Qt.NoTextInteraction)
        self.en_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        root.addWidget(self.en_label)

        # --- 中文 ---
        self.zh_label = QLabel("说英文，这里出现中文")
        self.zh_label.setWordWrap(True)
        self.zh_label.setTextInteractionFlags(Qt.NoTextInteraction)
        self.zh_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        root.addWidget(self.zh_label)

        self.setContextMenuPolicy(Qt.NoContextMenu)

    def _wire(self) -> None:
        self.bus.status.connect(self.on_status)
        self.bus.listening.connect(self.on_listening)
        self.bus.level.connect(self.levelbar.set_level)
        self.bus.hypothesis.connect(self.on_hypothesis)
        self.bus.sentence_start.connect(self.on_sentence_start)
        self.bus.zh_delta.connect(self.on_zh_delta)
        self.bus.error.connect(self.on_error)
        self.bus.stats.connect(self.on_stats)

    # ------------------------------------------------------------------
    def apply_config(self) -> None:
        c = self.cfg
        self.setFixedWidth(int(c.ui_width))
        self.en_label.setStyleSheet(
            f"color:#8b97a8;font-size:{int(c.ui_en_font_size)}px;"
            f"font-family:'{EN_FONT}';background:transparent;"
        )
        self.zh_label.setStyleSheet(
            f"color:#f2f5f9;font-size:{int(c.ui_font_size)}px;"
            f"font-family:'{ZH_FONT}';font-weight:600;background:transparent;"
        )
        self.en_label.setVisible(bool(c.ui_show_english))
        if c.ui_click_through and not self._click_through:
            self.toggle_click_through(True)
        elif not c.ui_click_through and self._click_through:
            self.toggle_click_through(False)
        self.update()
        self._refit()

    # ------------------------------------------------------------------
    def _refit(self) -> None:
        self.layout().activate()
        h = max(self.sizeHint().height(), 96)
        self.resize(int(self.cfg.ui_width), h)
        self._reposition()

    def _reposition(self) -> None:
        if self._auto_pos:
            scr = self.screen()
            if scr is None:
                from PySide6.QtWidgets import QApplication

                scr = QApplication.primaryScreen()
            if scr is None:
                return
            geo = scr.availableGeometry()
            x = geo.center().x() - self.width() // 2
            y = geo.bottom() - self.height() - 64
            self.move(x, y)
        else:
            x = int(self.cfg.ui_pos_x or 0)
            y = int(self.cfg.ui_pos_y or 0)
            # 换了显示器 / 分辨率后旧坐标可能在屏幕外，这时回到底部居中
            from PySide6.QtGui import QGuiApplication

            probe = QPoint(x + self.width() // 2, y + 16)
            if any(s.availableGeometry().contains(probe) for s in QGuiApplication.screens()):
                self.move(x, y)
            else:
                self._auto_pos = True
                self._reposition()

    # ------------------------------------------------------------------
    def on_status(self, text: str) -> None:
        self.status.setText(text)

    def on_listening(self, on: bool) -> None:
        self._listening = bool(on)
        self.dot.setStyleSheet(f"color:{'#4ade80' if on else '#6b7280'};font-size:12px;")
        self.btn_start.setText("■" if on else "▶")
        if not on and not self.zh_label.text():
            self.zh_label.setText("说英文，这里出现中文")

    def on_hypothesis(self, text: str) -> None:
        if self.cfg.ui_show_english:
            self.en_label.setText(text[-360:])
            self._refit()

    def on_sentence_start(self, sid: int) -> None:
        self._sid = sid
        # 不立刻清空中文：等新一句的译文到了再清，避免字幕闪空
        self._pending_clear = True
        self.en_label.setText("")

    def on_zh_delta(self, sid: int, delta: str) -> None:
        if sid != self._sid:
            return
        if self._pending_clear:
            self.zh_label.setText("")
            self._pending_clear = False
        text = self.zh_label.text() + delta
        limit = int(self.cfg.ui_max_zh_chars or 170)
        if len(text) > limit:
            # 报告场景一次能说几十秒，字幕条只保留最近一段，从标点处截断
            tail = text[-limit:]
            for i, ch in enumerate(tail[:60]):
                if ch in "，。；！？、,.!?;":
                    tail = tail[i + 1:]
                    break
            text = tail.lstrip("，。；、,. ")
        self.zh_label.setText(text)
        self._refit()

    def on_error(self, msg: str) -> None:
        self.status.setText(f"⚠ {msg}")
        self.status.setStyleSheet("color:#f87171;font-size:12px;")
        QTimer.singleShot(6000, lambda: self.status.setStyleSheet(
            "color:#9aa4b2;font-size:12px;"))

    def on_stats(self, d: dict) -> None:
        self._stats.update(d)
        parts = []
        if self._stats.get("asr_ms") is not None:
            parts.append(f"识别 {self._stats['asr_ms']}ms")
        if self._stats.get("mt_first_ms") is not None:
            parts.append(f"翻译 {self._stats['mt_first_ms']}ms")
        self.stats.setText(" · ".join(parts))

    # ------------------------------------------------------------------
    def _toggle_run(self) -> None:
        if hasattr(self, "on_toggle_run"):
            self.on_toggle_run()

    def _open_settings(self) -> None:
        if hasattr(self, "on_open_settings"):
            self.on_open_settings()

    def _open_history(self) -> None:
        if hasattr(self, "on_open_history"):
            self.on_open_history()

    def toggle_click_through(self, value: bool | None = None) -> None:
        target = (not self._click_through) if value is None else bool(value)
        if target == self._click_through:
            return
        self._click_through = target
        was_visible = self.isVisible()
        geo = self.geometry()
        self.setWindowFlag(Qt.WindowTransparentForInput, target)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        if was_visible:
            self.show()
            self.setGeometry(geo)
        for b in (self.btn_start, self.btn_settings, self.btn_history,
                  self.btn_pin, self.btn_close):
            b.setVisible(not target)
        if target:
            self.btn_pin.setStyleSheet(f"QToolButton{{font-size:11px;}}" + _BTN_ACTIVE_QSS)
        else:
            self.btn_pin.setStyleSheet(f"QToolButton{{font-size:11px;}}" + _BTN_QSS)
        self.cfg.ui_click_through = target

    # ------------------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        bg = QColor(10, 12, 16)
        bg.setAlphaF(float(self.cfg.ui_opacity))
        p.fillPath(path, bg)
        p.setPen(QPen(QColor(255, 255, 255, 24), 1))
        p.drawPath(path)

    # -- 拖动 ------------------------------------------------------------
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_off = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._dragging:
            self.move(event.globalPosition().toPoint() - self._drag_off)
            self._auto_pos = False
            event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._dragging:
            self._dragging = False
            self.cfg.ui_pos_x = self.x()
            self.cfg.ui_pos_y = self.y()
            event.accept()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.hide()


def make_tray_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(37, 99, 235))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
    p.setPen(QColor(255, 255, 255))
    f = QFont(ZH_FONT, 30)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, "译")
    p.end()
    return QIcon(pm)
