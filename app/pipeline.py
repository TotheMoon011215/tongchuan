"""实时同传主流程：采音 -> VAD 切句 -> 流式识别 -> 增量翻译 -> 事件推送。"""

from __future__ import annotations

import os
import queue
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .asr import ASREngine
from .audio import AudioCapture
from .log import log, log_exc
from .translator import Translator
from .vad import VADGate, make_vad

SR = 16000
PRE_ROLL_BLOCKS = 8          # 语音起点前保留 256ms，避免吞掉首字
MIN_ASR_AUDIO = 0.24         # 少于这个时长不识别


def _common_prefix(a: list[str], b: list[str]) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def _dump_wav(audio: np.ndarray, name: str) -> None:
    """调试用：把某一段音频存下来（TC_DUMP=1 时启用）。"""
    try:
        import wave

        d = Path(__file__).resolve().parent.parent / "output" / "dump"
        d.mkdir(parents=True, exist_ok=True)
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        with wave.open(str(d / f"{name}.wav"), "wb") as fh:
            fh.setnchannels(1)
            fh.setsampwidth(2)
            fh.setframerate(SR)
            fh.writeframes(pcm.tobytes())
    except Exception:
        pass


@dataclass
class MTJob:
    """翻译任务：一个小句一片，翻完立刻进「记录」，不等整句。"""

    sid: int
    text: str
    ctx_en: str
    ctx_zh: str
    final: bool = False


class Pipeline:
    """
    线程模型：
      采集线程（AudioCapture）
      主循环线程（本类 _run_loop）：VAD + 调度识别
      识别线程池（1 个 worker，单飞，避免堆积）
      翻译线程（串行，保证字幕顺序）
    """

    def __init__(self, cfg, bus):
        self.cfg = cfg
        self.bus = bus
        self.translator = Translator(cfg)

        self.capture: AudioCapture | None = None
        self.asr: ASREngine | None = None

        self._stop = threading.Event()
        self._running = False
        self._thread: threading.Thread | None = None
        self._mt_thread: threading.Thread | None = None
        self._pool: ThreadPoolExecutor | None = None
        self._mtq: queue.Queue = queue.Queue()
        self._asr_future = None
        self._lock = threading.Lock()

        self._zh_acc: dict[int, str] = {}
        self._last_en = ""      # 翻译上下文（含当前句已译部分）
        self._last_zh = ""
        self._prompt_en = ""    # 识别提示词：只放“上一句”，绝不能含当前句

        self._level_t = 0.0
        self._submitted_audio = False
        self._listening_flag = False

    # ------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._running

    @property
    def ready(self) -> bool:
        return self.asr is not None and self.asr.model is not None

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._running:
            log("start(): 已在运行，忽略")
            return
        self._running = True
        self._listening_flag = False
        self._stop.clear()
        log("start(): 启动管线")
        self._thread = threading.Thread(target=self._boot, name="pipeline", daemon=True)
        self._thread.start()
        threading.Thread(target=self._watchdog, name="watchdog", daemon=True).start()

    def _watchdog(self, timeout: float = 180.0) -> None:
        """启动卡住时给用户一个明确提示，而不是无限等待。"""
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            time.sleep(1.0)
            if self._listening_flag or not self._running:
                return
        if self._running and not self._listening_flag:
            log(f"watchdog: {timeout:.0f}s 仍未进入聆听")
            for emit in (
                lambda: self.bus.error.emit(f"启动超过 {int(timeout)} 秒仍未就绪，请查看 output/app.log"),
                lambda: self.bus.status.emit("启动超时"),
            ):
                try:
                    emit()
                except Exception:
                    pass

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self._running = False
        if self.capture is not None:
            try:
                self.capture.stop()
            except Exception:
                pass
            self.capture = None
        try:
            self._mtq.put_nowait(None)
        except Exception:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None
        if self._pool is not None:
            try:
                self._pool.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            self._pool = None
        self._asr_future = None

    def restart(self) -> None:
        was = self._running or self.ready
        self.stop()
        if was:
            self.start()

    # ------------------------------------------------------------------
    def _boot(self) -> None:
        log("boot: 开始")
        try:
            if not self.cfg.model_missing():
                if self.asr is None or self.asr.model is None:
                    self.bus.status.emit("正在加载语音识别模型…（首次约 20 秒）")
                    log(f"boot: 加载模型 {self.cfg.model_path()}")
                    self.asr = ASREngine(
                        self.cfg.model_path(),
                        device=self.cfg.asr_device,
                        compute_type=self.cfg.asr_compute_type,
                        language=self.cfg.asr_language,
                        beam_size=self.cfg.asr_beam_size,
                    )
                    info = self.asr.load()
                    log(f"boot: 模型就绪 {info}")
                    self.bus.status.emit(f"模型就绪 · {info}")
                else:
                    log("boot: 复用已加载模型")
            else:
                log("boot: 模型缺失")
                self.bus.error.emit("缺少语音识别模型，请先运行『下载模型.bat』")
                self._running = False
                return

            self.bus.status.emit("正在打开音频设备…")
            log(f"boot: 打开音频 source={self.cfg.audio_source} device={self.cfg.input_device!r}")
            self.capture = AudioCapture(
                source=self.cfg.audio_source, device=self.cfg.input_device
            )
            self.capture.start()
            time.sleep(0.35)
            if self.capture.error is not None:
                raise RuntimeError(f"音频设备打开失败：{self.capture.error}")
            if not self.capture.running:
                raise RuntimeError("音频设备没有启动成功")
            log(f"boot: 音频就绪 backend={self.capture.backend} rate={self.capture.actual_rate}")

            self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="asr")
            self._start_mt_worker()

            src = "系统声音" if self.cfg.audio_source == "system" else "麦克风"
            self._listening_flag = True
            self.bus.status.emit(f"正在聆听（{src}）")
            self.bus.listening.emit(True)
            log("boot: 进入主循环")
            self._run_loop()
        except Exception as exc:  # noqa: BLE001
            log_exc("boot 失败")
            # 这里的上报本身也可能出错，绝不能再让异常逃出线程
            for emit in (
                lambda: self.bus.error.emit(f"启动失败：{exc}"),
                lambda: self.bus.listening.emit(False),
                lambda: self.bus.status.emit("启动失败，详见 output/app.log"),
            ):
                try:
                    emit()
                except Exception:
                    pass
        finally:
            self._running = False
            try:
                self._mtq.put_nowait(None)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _start_mt_worker(self) -> None:
        if self._mt_thread and self._mt_thread.is_alive():
            return
        self._mt_thread = threading.Thread(target=self._mt_loop, name="translate", daemon=True)
        self._mt_thread.start()

    def _mt_loop(self) -> None:
        while True:
            job = self._mtq.get()
            if job is None:
                return
            if self._stop.is_set() and not job.final:
                continue
            pieces: list[str] = []
            if job.text.strip() and self.translator.enabled:
                t0 = time.perf_counter()
                got_first = False
                try:
                    for delta in self.translator.translate_iter(job.text, job.ctx_en, job.ctx_zh):
                        if not got_first:
                            got_first = True
                            self.bus.stats.emit({"mt_first_ms": int((time.perf_counter() - t0) * 1000)})
                        pieces.append(delta)
                        self.bus.zh_delta.emit(job.sid, delta)
                except Exception as exc:  # noqa: BLE001
                    self.bus.error.emit(f"翻译失败：{exc}")
            zh = "".join(pieces).strip()
            with self._lock:
                acc = self._zh_acc.get(job.sid, "")
                if zh:
                    acc = (acc + zh).strip()
                self._zh_acc[job.sid] = acc
                # 滚动上下文：给下一片提供上文
                if job.text.strip():
                    self._last_en = (self._last_en + " " + job.text.strip()).strip()[-500:]
                if zh:
                    self._last_zh = (self._last_zh + zh).strip()[-300:]
                if job.final:
                    self._zh_acc.pop(job.sid, None)
            # 每翻完一小句就落地到记录，报告现场可以边听边回看
            if job.text.strip() or zh:
                text = job.text.strip()
                if job.final:
                    text = text or self._last_en
                self.bus.pair.emit(text, zh, job.sid)

    # ------------------------------------------------------------------
    def _enqueue_mt(self, sid: int, text: str, ctx_en: str, ctx_zh: str,
                    final: bool = False) -> None:
        if not text.strip() and not final:
            return
        self._mtq.put(MTJob(sid=sid, text=text, ctx_en=ctx_en, ctx_zh=ctx_zh, final=final))

    # ------------------------------------------------------------------
    def _run_loop(self) -> None:
        cfg = self.cfg
        capture = self.capture
        assert capture is not None

        vad_engine = make_vad()
        if vad_engine.error:
            self.bus.status.emit(vad_engine.error)
        gate = VADGate(vad_engine, cfg.vad_threshold, cfg.vad_min_silence)

        pre_roll: deque = deque(maxlen=PRE_ROLL_BLOCKS)
        seg: list[np.ndarray] = []
        seg_dur = 0.0
        committed: list[str] = []
        prev_words: list[str] = []
        sent_words = 0
        sid = 0
        last_run = 0.0
        last_commit_t = time.monotonic()
        in_sentence = False
        audio_since_flush = 0.0
        heard_voice = False
        hint_sent = False
        t_start = time.monotonic()

        def start_sentence(tail: list[np.ndarray] | None = None) -> None:
            nonlocal seg, seg_dur, committed, prev_words, sent_words, sid, last_commit_t, in_sentence
            nonlocal audio_since_flush
            sid += 1
            seg = list(tail or [])
            seg_dur = sum(b.size for b in seg) / SR
            committed, prev_words, sent_words = [], [], 0
            last_commit_t = time.monotonic()
            audio_since_flush = 0.0
            in_sentence = True
            self.bus.sentence_start.emit(sid)
            self.bus.listening.emit(True)

        def finish_sentence(force_text: str | None = None) -> None:
            nonlocal seg, seg_dur, committed, prev_words, sent_words, in_sentence
            # 等正在跑的识别结束，避免同一个模型被并发调用
            if self._asr_future is not None:
                try:
                    self._asr_future.result(timeout=3.0)
                except Exception:
                    pass
                self._asr_future = None
            audio = np.concatenate(seg) if seg else np.zeros(0, np.float32)
            if os.environ.get("TC_DUMP"):
                _dump_wav(audio, f"seg{sid}")
            text = force_text or ""
            if not text and audio.size >= int(MIN_ASR_AUDIO * SR):
                try:
                    text, _ = self.asr.transcribe(audio, (self._prompt_en or "")[-200:] or None)
                except Exception as exc:  # noqa: BLE001
                    self.bus.error.emit(f"收尾识别失败：{exc}")
            words = text.split() or list(prev_words)
            if words:
                k = _common_prefix(committed, words)
                if k < len(committed):
                    words = list(committed) + words[len(committed):]
                en_full = " ".join(words)
                tail = " ".join(words[sent_words:])
                log(f"句 {sid} 结束: 音频 {audio.size / SR:.1f}s, 词数 {len(words)}, "
                    f"已送 {sent_words}, 尾巴 {len(words) - sent_words} 词")
                self.bus.hypothesis.emit(en_full)
                self._enqueue_mt(sid, tail, self._last_en, self._last_zh, final=True)
                # 只把这句作为下一句的识别提示，绝不能混进当前句
                self._prompt_en = en_full[-300:]
            else:
                self._enqueue_mt(sid, "", self._last_en, self._last_zh, final=True)
            seg = []
            seg_dur = 0.0
            committed, prev_words, sent_words = [], [], 0
            in_sentence = False
            self.bus.listening.emit(False)

        def maybe_flush(is_final: bool = False) -> None:
            nonlocal sent_words, last_commit_t, audio_since_flush
            if not committed:
                return
            pending = committed[sent_words:]
            if not pending:
                return
            text = " ".join(pending)
            n = len(pending)
            tail_char = text.rstrip()[-1:] if text.strip() else ""

            do = False
            if is_final:
                do = True
            elif n >= cfg.mt_max_clause_words:
                do = True
            elif n >= cfg.mt_clause_words and tail_char in ",;:，；：":
                do = True
            elif n >= cfg.mt_clause_words and (time.monotonic() - last_commit_t) > 0.7:
                do = True
            elif n >= 5 and audio_since_flush >= 3.2:
                # 讲话人不停顿、也不打标点时，按音频时长兜底，避免一直攒着
                do = True
            if not do:
                return

            ctx_en = " ".join(committed[:sent_words]) or self._last_en
            ctx_zh = self._last_zh
            with self._lock:
                if self._zh_acc.get(sid):
                    ctx_zh = self._zh_acc[sid]
            flushed_audio = audio_since_flush
            sent_words = len(committed)
            last_commit_t = time.monotonic()
            audio_since_flush = 0.0
            log(f"送翻 句{sid}: {n} 词, 累计送 {sent_words}, 音频 {flushed_audio:.1f}s")
            self._enqueue_mt(sid, text, ctx_en, ctx_zh, final=False)

        while not self._stop.is_set():
            block = capture.read(timeout=0.1)
            if block is None:
                if capture.error is not None:
                    raise RuntimeError(f"音频采集中断：{capture.error}")
                now = time.monotonic()
                if now - self._level_t > 0.1:
                    self._level_t = now
                    self.bus.level.emit(capture.level)
                continue

            gate.feed(block)
            now = time.monotonic()
            if now - self._level_t > 0.1:
                self._level_t = now
                self.bus.level.emit(capture.level)

            # ---- 段状态维护 ----
            if gate.just_started:
                heard_voice = True
                pre_roll.append(block)
                start_sentence(list(pre_roll))
                pre_roll.clear()
            elif gate.in_speech:
                if not in_sentence:
                    start_sentence()
                seg.append(block)
                seg_dur += block.size / SR
                audio_since_flush += block.size / SR
            else:
                pre_roll.append(block)

            if not hint_sent and not heard_voice and (now - t_start) > 8.0:
                hint_sent = True
                self.bus.status.emit("听不到声音：请检查麦克风是否处于静音、或换一个输入设备")

            if not in_sentence:
                continue

            # ---- 调度识别（单飞） ----
            free = self._asr_future is None or self._asr_future.done()
            if (free and gate.in_speech and seg_dur >= MIN_ASR_AUDIO
                    and (now - last_run) >= max(0.2, cfg.step_sec)):
                snapshot = np.concatenate(seg)
                last_run = now
                self._asr_future = self._pool.submit(
                    self.asr.transcribe, snapshot, (self._prompt_en or "")[-200:] or None
                )

            # ---- 取识别结果 ----
            if self._asr_future is not None and self._asr_future.done():
                fut, self._asr_future = self._asr_future, None
                try:
                    text, ms = fut.result()
                    self.bus.stats.emit({"asr_ms": int(ms)})
                except Exception as exc:  # noqa: BLE001
                    text = ""
                    self.bus.error.emit(f"识别出错：{exc}")
                if text:
                    words = text.split()
                    n = _common_prefix(prev_words, words) if prev_words else 0
                    if n > len(committed):
                        committed = words[:n]
                        self.bus.partial.emit(" ".join(committed))
                        last_commit_t = time.monotonic()
                        maybe_flush()
                    prev_words = words
                    self.bus.hypothesis.emit(text)

            # ---- 收尾 ----
            if gate.just_ended:
                finish_sentence()
            elif seg_dur >= cfg.max_sentence_sec:
                # 超过最长一句：强制切一刀，保留一点尾巴给下一句做上下文
                kept = seg[-3:] if seg else []
                finish_sentence(force_text=" ".join(prev_words) if prev_words else None)
                if gate.in_speech:
                    start_sentence(kept)

        log("主循环退出")
        self.bus.listening.emit(False)
        self.bus.status.emit("已停止")

    # ------------------------------------------------------------------
    def set_config(self, cfg) -> None:
        """设置变更后热更新翻译参数（识别模型需要 restart）。"""
        self.cfg = cfg
        self.translator.cfg = cfg
        if self.translator._client is not None:
            try:
                self.translator._client.close()
            except Exception:
                pass
            self.translator._client = None
