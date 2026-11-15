"""设置对话框。"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QRadioButton, QSlider, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
    QButtonGroup,
)

from ..audio import (
    AudioCapture, default_input_name, default_output_name, list_loopback_devices,
    list_microphones,
)
from ..config import ROOT, Config
from ..translator import Translator
from .overlay import LevelBar

ASR_KEYS = {
    "asr_model", "asr_device", "asr_compute_type", "audio_source", "input_device",
    "vad_threshold", "vad_min_silence", "step_sec", "max_sentence_sec", "asr_beam_size",
}


class _LevelMonitor(QObject):
    """打开一次采集，把电平画到字幕条上，让用户确认设备对不对。"""

    def __init__(self, bar: LevelBar):
        super().__init__()
        self.bar = bar
        self.cap: AudioCapture | None = None
        self.deadline = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    def start(self, source: str, device: str, seconds: float = 25.0) -> None:
        self.stop()
        try:
            self.cap = AudioCapture(source, device)
            self.cap.start()
        except Exception:
            self.cap = None
            return
        self.deadline = time.monotonic() + seconds
        self.timer.start(80)

    def _tick(self) -> None:
        cap = self.cap
        if cap is None:
            self.timer.stop()
            return
        if cap.error is not None:
            self.bar.set_level(0.0)
            self.bar.setToolTip(f"设备打开失败：{cap.error}")
            self.stop()
            return
        self.bar.set_level(cap.level)
        if time.monotonic() > self.deadline:
            self.stop()

    def stop(self) -> None:
        self.timer.stop()
        if self.cap is not None:
            try:
                self.cap.stop()
            except Exception:
                pass
            self.cap = None
        self.bar.set_level(0.0)


class _TestWorker(QThread):
    done = Signal(bool, str)

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg

    def run(self) -> None:  # noqa: D401
        try:
            t = Translator(self.cfg)
            out = t.test()
            t.close()
            self.done.emit(True, out)
        except Exception as exc:  # noqa: BLE001
            self.done.emit(False, str(exc))


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, bus=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.bus = bus
        self.restart_needed = False
        self._worker: _TestWorker | None = None

        self.setWindowTitle("同传设置")
        self.setMinimumWidth(600)
        self._build()
        self._load()
        self.tabs.currentChanged.connect(self._on_tab_changed)

    # ------------------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_api(), "翻译接口")
        self.tabs.addTab(self._tab_asr(), "语音识别")
        self.tabs.addTab(self._tab_audio(), "音频输入")
        self.tabs.addTab(self._tab_ui(), "外观")
        root.addWidget(self.tabs)

        box = QDialogButtonBox()
        self.btn_save = box.addButton("保存", QDialogButtonBox.AcceptRole)
        box.addButton("取消", QDialogButtonBox.RejectRole)
        self.btn_save.setDefault(True)
        box.accepted.connect(self._on_accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)

    # ------------------------------------------------------------------
    def _tab_api(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.ed_base = QLineEdit()
        self.ed_base.setPlaceholderText("https://api.deepseek.com")
        self.ed_key = QLineEdit()
        self.ed_key.setEchoMode(QLineEdit.Password)
        self.ed_key.setPlaceholderText("sk-...")
        self.cb_model = QComboBox()
        self.cb_model.setEditable(True)
        self.cb_model.addItems(["deepseek-chat", "deepseek-reasoner"])
        self.sp_temp = QDoubleSpinBox()
        self.sp_temp.setRange(0.0, 1.5)
        self.sp_temp.setSingleStep(0.1)
        self.sp_temp.setToolTip("越低越忠实原文，越高越灵活。字幕建议 0.1~0.3")

        self.ed_glossary = QPlainTextEdit()
        self.ed_glossary.setPlaceholderText(
            "每行一条，例如：\nKubernetes=Kubernetes\nLLM=大语言模型\nM&A=并购")
        self.ed_glossary.setFixedHeight(96)

        row = QHBoxLayout()
        btn_test = QPushButton("测试接口")
        btn_test.clicked.connect(self._test_api)
        self.lb_test = QLabel("")
        self.lb_test.setWordWrap(True)
        row.addWidget(btn_test)
        row.addWidget(self.lb_test, 1)

        f.addRow("Base URL", self.ed_base)
        f.addRow("API Key", self.ed_key)
        f.addRow("模型", self.cb_model)
        f.addRow("温度", self.sp_temp)
        f.addRow("术语表", self.ed_glossary)
        f.addRow("", self._wrap(row))
        tip = QLabel("提示：Key 也可用环境变量 DEEPSEEK_API_KEY，则不必写进配置文件。")
        tip.setStyleSheet("color:#9aa4b2;font-size:11px;")
        f.addRow("", tip)
        return w

    def _tab_asr(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.ed_model_path = QLineEdit()
        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._browse_model)
        row = QHBoxLayout()
        row.addWidget(self.ed_model_path, 1)
        row.addWidget(btn_browse)

        self.cb_device = QComboBox()
        for label, val in (("自动（优先 GPU）", "auto"), ("GPU (CUDA)", "cuda"), ("CPU", "cpu")):
            self.cb_device.addItem(label, val)
        self.cb_compute = QComboBox()
        for label, val in (("自动", "auto"), ("float16（GPU 最快）", "float16"),
                           ("int8_float16", "int8_float16"), ("int8", "int8"),
                           ("float32", "float32")):
            self.cb_compute.addItem(label, val)

        self.sp_step = QDoubleSpinBox()
        self.sp_step.setRange(0.2, 2.0)
        self.sp_step.setSingleStep(0.1)
        self.sp_step.setSuffix(" 秒")
        self.sp_step.setToolTip("每隔多久重新识别当前句。越小越快，也越吃显卡")
        self.sp_silence = QDoubleSpinBox()
        self.sp_silence.setRange(0.15, 2.5)
        self.sp_silence.setSingleStep(0.05)
        self.sp_silence.setSuffix(" 秒")
        self.sp_silence.setToolTip("停顿多久算一句话结束")
        self.sp_vad = QDoubleSpinBox()
        self.sp_vad.setRange(0.1, 0.9)
        self.sp_vad.setSingleStep(0.05)
        self.sp_vad.setToolTip("越高越不容易被噪声触发")
        self.sp_maxsent = QDoubleSpinBox()
        self.sp_maxsent.setRange(4.0, 40.0)
        self.sp_maxsent.setSingleStep(1.0)
        self.sp_maxsent.setSuffix(" 秒")

        f.addRow("模型目录", self._wrap(row))
        f.addRow("推理设备", self.cb_device)
        f.addRow("计算精度", self.cb_compute)
        f.addRow("刷新间隔", self.sp_step)
        f.addRow("断句静音", self.sp_silence)
        f.addRow("VAD 灵敏度", self.sp_vad)
        f.addRow("最长一句", self.sp_maxsent)
        return w

    def _tab_audio(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("声音来源")
        gv = QVBoxLayout(g)
        self.rb_mic = QRadioButton("麦克风（现场说话 / 会议外放）")
        self.rb_sys = QRadioButton("系统声音（电脑正在播放的声音，如 Zoom、视频）")
        grp = QButtonGroup(w)
        grp.addButton(self.rb_mic)
        grp.addButton(self.rb_sys)
        gv.addWidget(self.rb_mic)
        gv.addWidget(self.rb_sys)
        v.addWidget(g)

        f = QFormLayout()
        row = QHBoxLayout()
        self.cb_input = QComboBox()
        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self._refresh_devices)
        row.addWidget(self.cb_input, 1)
        row.addWidget(btn_refresh)
        f.addRow("设备", self._wrap(row))
        v.addLayout(f)

        self.level = LevelBar(width=130, height=8)
        self._monitor = _LevelMonitor(self.level)
        btn_probe = QPushButton("试听 20 秒")
        btn_probe.clicked.connect(self._probe)
        lrow = QHBoxLayout()
        lrow.addWidget(QLabel("输入电平"))
        lrow.addSpacing(6)
        lrow.addWidget(self.level)
        lrow.addSpacing(14)
        lrow.addWidget(btn_probe)
        lrow.addStretch(1)
        v.addLayout(lrow)
        hint = QLabel("对着麦克风说话，绿色条应该跳动；不跳说明设备选错了。\n"
                      "选「系统默认」即使用 Windows 当前的默认录音设备。")
        hint.setStyleSheet("color:#9aa4b2;font-size:11px;")
        v.addWidget(hint)
        v.addStretch(1)

        self.rb_mic.toggled.connect(self._refresh_devices)
        self.rb_sys.toggled.connect(self._refresh_devices)
        self.cb_input.currentIndexChanged.connect(self._probe_if_visible)
        return w

    def _probe_if_visible(self, *_args) -> None:
        if self.isVisible() and self.tabs.currentIndex() == 2:
            self._probe()

    def _on_tab_changed(self, index: int) -> None:
        if index == 2 and self.isVisible():
            self._probe()
        else:
            self._monitor.stop()

    def _probe(self) -> None:
        src = "system" if self.rb_sys.isChecked() else "microphone"
        self._monitor.start(src, self.cb_input.currentData() or "", 20.0)

    def _tab_ui(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.sp_zh_font = QSpinBox()
        self.sp_zh_font.setRange(12, 64)
        self.sp_zh_font.setSuffix(" px")
        self.sp_en_font = QSpinBox()
        self.sp_en_font.setRange(8, 40)
        self.sp_en_font.setSuffix(" px")
        self.sp_width = QSpinBox()
        self.sp_width.setRange(420, 2400)
        self.sp_width.setSingleStep(20)
        self.sp_width.setSuffix(" px")
        self.sl_opacity = QSlider(Qt.Horizontal)
        self.sl_opacity.setRange(40, 100)
        self.cb_show_en = QCheckBox("显示英文原文")
        self.cb_click = QCheckBox("鼠标穿透（点不到字幕窗，可用 Ctrl+Alt+P 切换）")

        f.addRow("中文字号", self.sp_zh_font)
        f.addRow("英文字号", self.sp_en_font)
        f.addRow("字幕宽度", self.sp_width)
        f.addRow("不透明度", self.sl_opacity)
        f.addRow("", self.cb_show_en)
        f.addRow("", self.cb_click)
        return w

    # ------------------------------------------------------------------
    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        return w

    def _browse_model(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择 faster-whisper 模型目录",
                                             str(self.ed_model_path.text() or ""))
        if d:
            self.ed_model_path.setText(d)

    def _refresh_devices(self, *_args) -> None:
        src = "system" if self.rb_sys.isChecked() else "microphone"
        items = list_loopback_devices() if src == "system" else list_microphones()
        default_name = default_output_name() if src == "system" else default_input_name()
        cur = self.cb_input.currentData() or ""

        self.cb_input.blockSignals(True)
        self.cb_input.clear()
        label = f"（系统默认：{default_name}）" if default_name else "（系统默认）"
        self.cb_input.addItem(label, "")
        for name in items:
            self.cb_input.addItem(name, name)
        if cur and cur not in items:
            self.cb_input.addItem(cur, cur)
        idx = self.cb_input.findData(cur) if cur else 0
        self.cb_input.setCurrentIndex(idx if idx >= 0 else 0)
        self.cb_input.blockSignals(False)

    def _test_api(self) -> None:
        tmp = Config(self.cfg.as_dict())
        tmp.mt_base_url = self.ed_base.text().strip()
        tmp.mt_api_key = self.ed_key.text().strip()
        tmp.mt_model = self.cb_model.currentText().strip()
        self.lb_test.setText("测试中…")
        self.lb_test.setStyleSheet("color:#9aa4b2;")
        self._worker = _TestWorker(tmp)
        self._worker.done.connect(self._on_test_done)
        self._worker.start()

    @staticmethod
    def _portable_path(path_txt: str) -> str:
        """项目内的路径存成相对路径，整个文件夹换位置也能用。"""
        try:
            p = Path(path_txt)
            rel = p.relative_to(ROOT)
            return str(rel).replace("\\", "/")
        except Exception:
            return path_txt

    def _on_test_done(self, ok: bool, msg: str) -> None:
        if ok:
            self.lb_test.setText(f"✓ {msg}")
            self.lb_test.setStyleSheet("color:#4ade80;")
        else:
            self.lb_test.setText(f"✗ {msg[:160]}")
            self.lb_test.setStyleSheet("color:#f87171;")

    # ------------------------------------------------------------------
    def _load(self) -> None:
        c = self.cfg
        self.ed_base.setText(c.mt_base_url)
        self.ed_key.setText(c.mt_api_key)
        self.cb_model.setCurrentText(c.mt_model)
        self.sp_temp.setValue(float(c.mt_temperature))
        self.ed_glossary.setPlainText(c.glossary or "")

        self.ed_model_path.setText(str(c.model_path()))
        self.cb_device.setCurrentIndex(max(0, self.cb_device.findData(c.asr_device)))
        self.cb_compute.setCurrentIndex(max(0, self.cb_compute.findData(c.asr_compute_type)))
        self.sp_step.setValue(float(c.step_sec))
        self.sp_silence.setValue(float(c.vad_min_silence))
        self.sp_vad.setValue(float(c.vad_threshold))
        self.sp_maxsent.setValue(float(c.max_sentence_sec))

        if c.audio_source == "system":
            self.rb_sys.setChecked(True)
        else:
            self.rb_mic.setChecked(True)
        self._refresh_devices()
        idx = self.cb_input.findData(c.input_device or "")
        self.cb_input.setCurrentIndex(idx if idx >= 0 else 0)

        self.sp_zh_font.setValue(int(c.ui_font_size))
        self.sp_en_font.setValue(int(c.ui_en_font_size))
        self.sp_width.setValue(int(c.ui_width))
        self.sl_opacity.setValue(int(round(float(c.ui_opacity) * 100)))
        self.cb_show_en.setChecked(bool(c.ui_show_english))
        self.cb_click.setChecked(bool(c.ui_click_through))

    def _on_accept(self) -> None:
        c = self.cfg
        before = c.as_dict()

        c.mt_base_url = self.ed_base.text().strip() or "https://api.deepseek.com"
        c.mt_api_key = self.ed_key.text().strip()
        c.mt_model = self.cb_model.currentText().strip() or "deepseek-chat"
        c.mt_temperature = float(self.sp_temp.value())
        c.glossary = self.ed_glossary.toPlainText()

        path_txt = self.ed_model_path.text().strip()
        c.asr_model = self._portable_path(path_txt)
        c.asr_device = self.cb_device.currentData() or "auto"
        c.asr_compute_type = self.cb_compute.currentData() or "auto"
        c.step_sec = float(self.sp_step.value())
        c.vad_min_silence = float(self.sp_silence.value())
        c.vad_threshold = float(self.sp_vad.value())
        c.max_sentence_sec = float(self.sp_maxsent.value())

        c.audio_source = "system" if self.rb_sys.isChecked() else "microphone"
        c.input_device = self.cb_input.currentData() or ""

        c.ui_font_size = int(self.sp_zh_font.value())
        c.ui_en_font_size = int(self.sp_en_font.value())
        c.ui_width = int(self.sp_width.value())
        c.ui_opacity = self.sl_opacity.value() / 100.0
        c.ui_show_english = bool(self.cb_show_en.isChecked())
        c.ui_click_through = bool(self.cb_click.isChecked())

        after = c.as_dict()
        self.restart_needed = any(before.get(k) != after.get(k) for k in ASR_KEYS)
        c.save()
        self._monitor.stop()
        self.accept()

    def reject(self) -> None:
        self._monitor.stop()
        super().reject()

    def closeEvent(self, event):  # noqa: N802
        self._monitor.stop()
        super().closeEvent(event)
