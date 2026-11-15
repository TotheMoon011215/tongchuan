"""实时记录窗口：边听边看前面的内容，同时自动存盘。

同一条长句的多个小句片段会合并成一行，读起来是完整的句子，
但内容是小句级别实时追加的。
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)

from ..config import OUTPUT_DIR

MAX_LINES = 3000


class HistoryWindow(QDialog):
    """报告/演讲场景下可以一直开着，当实时字幕稿用。"""

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.lines: list[dict] = []
        self._show_en = True
        self._follow = True

        self.setWindowTitle("同传记录（实时）")
        self.resize(840, 580)
        self._session_path = OUTPUT_DIR / f"同传_{time.strftime('%Y%m%d_%H%M%S')}.md"

        root = QVBoxLayout(self)
        self.info = QLabel("边听边记：每翻完一小句就出现在这里，同时存到 output 目录。")
        self.info.setStyleSheet("color:#9aa4b2;font-size:12px;")
        root.addWidget(self.info)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setStyleSheet(
            "QPlainTextEdit{background:#15171b;color:#e6e8ec;border:1px solid #2a2d33;"
            "border-radius:8px;padding:10px;font-family:'Microsoft YaHei UI';font-size:15px;}"
        )
        root.addWidget(self.view, 1)

        opts = QHBoxLayout()
        self.cb_zh_only = QCheckBox("只显示中文")
        self.cb_zh_only.toggled.connect(self._on_toggle_en)
        self.cb_top = QCheckBox("窗口置顶")
        self.cb_top.toggled.connect(self._on_toggle_top)
        self.cb_follow = QCheckBox("自动滚动")
        self.cb_follow.setChecked(True)
        self.cb_follow.toggled.connect(lambda v: setattr(self, "_follow", bool(v)))
        opts.addWidget(self.cb_zh_only)
        opts.addWidget(self.cb_top)
        opts.addWidget(self.cb_follow)
        opts.addStretch(1)
        root.addLayout(opts)

        row = QHBoxLayout()
        self.btn_export = QPushButton("导出…")
        self.btn_clear = QPushButton("清空")
        self.btn_close = QPushButton("关闭")
        self.btn_export.clicked.connect(self._export)
        self.btn_clear.clicked.connect(self._clear)
        self.btn_close.clicked.connect(self.hide)
        row.addStretch(1)
        row.addWidget(self.btn_export)
        row.addWidget(self.btn_clear)
        row.addWidget(self.btn_close)
        root.addLayout(row)

    # ------------------------------------------------------------------
    def append(self, en: str, zh: str, sid: int = -1) -> None:
        en = (en or "").strip()
        zh = (zh or "").strip()
        if not en and not zh:
            return

        if zh and self.lines and self.lines[-1]["sid"] == sid:
            # 同一句的后续片段：合并到同一行，读起来是完整句子
            last = self.lines[-1]
            if en:
                last["en"] = (last["en"] + " " + en).strip()
            if zh:
                last["zh"] = (last["zh"] + zh).strip()
        else:
            self.lines.append({
                "sid": sid,
                "en": en,
                "zh": zh,
                "t": time.strftime("%H:%M:%S"),
            })
            if len(self.lines) > MAX_LINES:
                del self.lines[: len(self.lines) - MAX_LINES]

        self._render()
        if self.cfg.save_transcript:
            self._append_file(en, zh)

    def _block(self, item: dict) -> str:
        if self._show_en:
            return f"[{item['t']}]\nEN  {item['en']}\n中  {item['zh']}\n"
        return f"[{item['t']}]  {item['zh'] or item['en']}\n"

    def _render(self) -> None:
        self.view.setPlainText("".join(self._block(it) for it in self.lines))
        if self._follow and self.isVisible():
            bar = self.view.verticalScrollBar()
            bar.setValue(bar.maximum())

    # ------------------------------------------------------------------
    def _on_toggle_en(self, zh_only: bool) -> None:
        self._show_en = not zh_only
        self._render()

    def _on_toggle_top(self, on: bool) -> None:
        geo = self.geometry()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(on))
        self.show()
        self.setGeometry(geo)

    def _append_file(self, en: str, zh: str) -> None:
        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            new = not self._session_path.exists()
            with self._session_path.open("a", encoding="utf-8") as fh:
                if new:
                    fh.write(f"# 同传记录 {time.strftime('%Y-%m-%d %H:%M')}\n\n")
                fh.write(f"- {time.strftime('%H:%M:%S')}  {zh or en}\n")
                if en and zh:
                    fh.write(f"  - EN: {en}\n")
        except Exception:
            pass

    def _export(self) -> None:
        default = f"同传记录_{time.strftime('%Y%m%d_%H%M%S')}.md"
        path, _ = QFileDialog.getSaveFileName(self, "导出记录", default,
                                              "Markdown (*.md);;文本 (*.txt)")
        if not path:
            return
        lines = [f"# 同传记录 {time.strftime('%Y-%m-%d %H:%M')}", ""]
        for it in self.lines:
            lines.append(f"- **{it['t']}**")
            if it["en"]:
                lines.append(f"  - EN: {it['en']}")
            lines.append(f"  - 中文: {it['zh']}")
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        self.info.setText(f"已导出：{path}")

    def _clear(self) -> None:
        self.lines.clear()
        self.view.clear()
