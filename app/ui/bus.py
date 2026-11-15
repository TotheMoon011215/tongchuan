"""UI 事件总线：后台线程通过它安全地把数据送到 Qt 主线程。"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class UiBus(QObject):
    status = Signal(str)              # 状态文字
    listening = Signal(bool)          # 是否正在聆听
    level = Signal(float)             # 输入电平 0~1
    hypothesis = Signal(str)          # 当前整句英文（实时）
    partial = Signal(str)             # 已稳定的英文前缀
    sentence_start = Signal(int)      # 新的一句开始（sid）
    zh_delta = Signal(int, str)       # 中文增量（sid, 片段）
    pair = Signal(str, str, int)      # 一句完成（英文, 中文, sid）
    error = Signal(str)
    stats = Signal(dict)
    hotkey = Signal(str)              # 全局快捷键触发
