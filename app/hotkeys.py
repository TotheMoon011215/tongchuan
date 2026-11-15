"""全局快捷键（pynput）。失败不影响主程序。"""

from __future__ import annotations


def start_hotkeys(bus):
    """注册全局快捷键；返回 listener 或 None。"""
    try:
        from pynput import keyboard
    except Exception:
        return None

    mapping = {
        "<ctrl>+<alt>+s": "run",     # 开始 / 停止
        "<ctrl>+<alt>+p": "pin",     # 鼠标穿透
        "<ctrl>+<alt>+h": "hide",    # 显示 / 隐藏
        "<ctrl>+<alt>+q": "quit",    # 退出
    }

    def _mk(name: str):
        def _cb() -> None:
            bus.hotkey.emit(name)

        return _cb

    try:
        listener = keyboard.GlobalHotKeys({k: _mk(v) for k, v in mapping.items()})
        listener.daemon = True
        listener.start()
        return listener
    except Exception:
        return None
