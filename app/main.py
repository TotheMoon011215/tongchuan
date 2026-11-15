"""程序入口：python -m app.main"""

from __future__ import annotations

import argparse
import faulthandler
import sys
import threading
import traceback

from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication, QDialog, QMenu, QMessageBox, QSystemTrayIcon,
)

from .config import OUTPUT_DIR, Config
from .pipeline import Pipeline
from .ui import HistoryWindow, OverlayWindow, SettingsDialog, UiBus, make_tray_icon

_LOG_FH = None


def _install_crash_log() -> None:
    """pythonw 没有控制台，把崩溃写进 output/error.log，避免静默消失。"""
    global _LOG_FH
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        _LOG_FH = open(OUTPUT_DIR / "error.log", "a", buffering=1, encoding="utf-8")
    except Exception:
        _LOG_FH = None

    def _hook(exc_type, exc, tb):
        if _LOG_FH is not None:
            try:
                _LOG_FH.write("".join(traceback.format_exception(exc_type, exc, tb)) + "\n")
            except Exception:
                pass
        try:
            sys.__excepthook__(exc_type, exc, tb)
        except Exception:
            pass

    sys.excepthook = _hook

    def _thread_hook(args):  # 后台线程里没接住的异常，同样写盘
        if _LOG_FH is not None:
            try:
                _LOG_FH.write(
                    f"--- 线程 {args.thread.name if args.thread else '?'} 异常 ---\n"
                    + "".join(traceback.format_exception(args.exc_type, args.exc_value,
                                                         args.exc_traceback))
                    + "\n"
                )
            except Exception:
                pass

    threading.excepthook = _thread_hook

    if _LOG_FH is not None:
        try:
            faulthandler.enable(_LOG_FH)
        except Exception:
            pass


def _dark_palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.Window, QColor(30, 32, 36))
    p.setColor(QPalette.WindowText, QColor(228, 231, 236))
    p.setColor(QPalette.Base, QColor(21, 23, 27))
    p.setColor(QPalette.AlternateBase, QColor(34, 37, 42))
    p.setColor(QPalette.Text, QColor(228, 231, 236))
    p.setColor(QPalette.Button, QColor(40, 43, 49))
    p.setColor(QPalette.ButtonText, QColor(228, 231, 236))
    p.setColor(QPalette.Highlight, QColor(59, 130, 246))
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.ToolTipBase, QColor(40, 43, 49))
    p.setColor(QPalette.ToolTipText, QColor(228, 231, 236))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(130, 136, 145))
    return p


class AppController(QObject):
    """所有涉及界面的动作都放在这里，保证跑在 Qt 主线程。"""

    def __init__(self, app: QApplication, cfg: Config, bus: UiBus,
                 overlay: OverlayWindow, engine: Pipeline, history: HistoryWindow):
        super().__init__()
        self.app = app
        self.cfg = cfg
        self.bus = bus
        self.overlay = overlay
        self.engine = engine
        self.history = history

        overlay.on_toggle_run = self.toggle_run
        overlay.on_open_settings = self.open_settings
        overlay.on_open_history = self.open_history

        bus.pair.connect(self.on_pair)
        bus.hotkey.connect(self.on_hotkey)
        bus.error.connect(self.on_error)

    # ------------------------------------------------------------------
    @Slot()
    def toggle_run(self) -> None:
        if self.engine.running:
            self.bus.status.emit("正在停止…")
            self.engine.stop()
            self.overlay.on_listening(False)
            self.bus.status.emit("已停止")
            return

        if self.cfg.model_missing():
            QMessageBox.warning(
                self.overlay, "找不到识别模型",
                f"模型目录不存在：\n{self.cfg.model_path()}\n\n"
                "请先运行项目里的『下载模型.bat』。",
            )
            return
        if self.cfg.mt_enabled and not self.cfg.api_key:
            QMessageBox.information(
                self.overlay, "还差一步",
                "还没有填写翻译接口的 API Key。\n\n"
                "本地语音识别不需要联网，但翻译需要调用 DeepSeek。\n"
                "点『确定』打开设置填写。",
            )
            self.open_settings()
            return

        self.bus.status.emit("启动中…")
        self.engine.start()

    @Slot()
    def open_settings(self) -> None:
        dlg = SettingsDialog(self.cfg, self.bus, self.overlay)
        if dlg.exec() == QDialog.Accepted:
            self.overlay.apply_config()
            self.engine.set_config(self.cfg)
            if dlg.restart_needed and (self.engine.running or self.engine.ready):
                self.bus.status.emit("配置已更新，正在重启引擎…")
                self.engine.restart()
            else:
                self.bus.status.emit("设置已保存")

    @Slot()
    def open_history(self) -> None:
        self.history.show()
        self.history.raise_()
        self.history.activateWindow()

    # ------------------------------------------------------------------
    @Slot(str, str, int)
    def on_pair(self, en: str, zh: str, sid: int) -> None:
        self.history.append(en, zh, sid)

    @Slot(str)
    def on_error(self, msg: str) -> None:
        # pythonw 下 stdout 可能为 None，写日志更可靠
        try:
            if _LOG_FH is not None:
                _LOG_FH.write(f"[error] {msg}\n")
        except Exception:
            pass
        try:
            print(f"[error] {msg}", flush=True)
        except Exception:
            pass

    @Slot(str)
    def on_hotkey(self, name: str) -> None:
        if name == "run":
            self.toggle_run()
        elif name == "pin":
            self.overlay.toggle_click_through()
        elif name == "hide":
            self.overlay.setVisible(not self.overlay.isVisible())
        elif name == "quit":
            self.app.quit()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="同传", add_help=True)
    ap.add_argument("--no-hotkeys", action="store_true", help="不注册全局快捷键")
    ap.add_argument("--autostart", action="store_true", help="启动后立即开始聆听")
    args, _unknown = ap.parse_known_args(argv)

    _install_crash_log()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("同传字幕")
    app.setStyle("Fusion")
    app.setPalette(_dark_palette())
    font = QFont("Microsoft YaHei UI", 10)
    app.setFont(font)

    cfg = Config.load()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    bus = UiBus()
    overlay = OverlayWindow(cfg, bus)
    engine = Pipeline(cfg, bus)
    history = HistoryWindow(cfg, overlay)
    controller = AppController(app, cfg, bus, overlay, engine, history)

    # ---- 托盘 ----
    tray = QSystemTrayIcon(make_tray_icon(), app)
    tray.setToolTip("同传字幕")
    menu = QMenu()
    act_show = menu.addAction("显示 / 隐藏字幕")
    act_show.triggered.connect(lambda: overlay.setVisible(not overlay.isVisible()))
    act_run = menu.addAction("开始 / 停止")
    act_run.triggered.connect(controller.toggle_run)
    menu.addSeparator()
    act_set = menu.addAction("设置…")
    act_set.triggered.connect(controller.open_settings)
    act_hist = menu.addAction("历史记录…")
    act_hist.triggered.connect(controller.open_history)
    menu.addSeparator()
    act_quit = menu.addAction("退出")
    act_quit.triggered.connect(app.quit)
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: overlay.show() if reason == QSystemTrayIcon.Trigger else None
    )
    tray.show()

    # ---- 全局快捷键 ----
    hotkey_listener = None
    if cfg.hotkeys_enabled and not args.no_hotkeys:
        from .hotkeys import start_hotkeys

        hotkey_listener = start_hotkeys(bus)

    # ---- 退出清理 ----
    def _cleanup() -> None:
        try:
            engine.stop()
        except Exception:
            pass
        if hotkey_listener is not None:
            try:
                hotkey_listener.stop()
            except Exception:
                pass
        try:
            cfg.ui_pos_x = overlay.x()
            cfg.ui_pos_y = overlay.y()
            cfg.save()
        except Exception:
            pass

    app.aboutToQuit.connect(_cleanup)

    # ---- 启动提示 ----
    if cfg.model_missing():
        bus.error.emit("缺少语音识别模型，请运行『下载模型.bat』")
    elif not cfg.api_key and cfg.mt_enabled:
        bus.status.emit("未配置 API Key（点击 ⚙ 填写）")
    else:
        bus.status.emit("就绪，点击 ▶ 开始")

    overlay.show()
    overlay.raise_()

    if args.autostart:
        controller.toggle_run()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
