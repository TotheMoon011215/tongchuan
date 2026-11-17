# Tongchuan · Real-time English → Chinese subtitles

<p align="center"><a href="README.md">中文</a> · <b>English</b></p>

Turns the English you **hear** — from your microphone or from whatever your PC is playing — into **Chinese subtitles** in real time, while keeping a transcript you can scroll back through.

Speech recognition runs on your own GPU (free, offline, nothing leaves the machine). Only the recognized text is sent to DeepSeek for translation.

> Measured: on an RTX 5080, a 15-second English clip recognized in 144–400 ms (~40–100× real time), fully accurate.

---

## Running from source (after cloning)

The repository does **not** contain `runtime/` (a 3 GB portable Python) or `models/` (1.5 GB of weights); both are in `.gitignore`.

```bat
:: 1. dependencies (Python 3.12)
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

:: 2. for NVIDIA GPU acceleration, add these two as well (omit them and it falls back to CPU)
:: pip install nvidia-cublas-cu12==12.9.2.10 nvidia-cudnn-cu12==9.27.0.42

:: 3. model weights (~1.5 GB, from ModelScope)
tools\download_model.ps1

:: 4. configuration
copy config.example.json config.json

:: 5. launch (picks up .venv automatically when present)
启动同传.bat
```

You can also run `python -m app.main` directly.

> `runtime/` (~3 GB portable Python) and `models/` (~1.5 GB weights) are left out because they are far beyond what git is meant to hold. Install the dependencies and download the model as shown above and it runs.

---

## LingoLens integration

`app/bridge.py` is a headless mode: **it does not start Qt**, and instead speaks one JSON object per line over stdin/stdout, so a shell such as [LingoLens](https://github.com/TotheMoon011215/lingolens) can drive it.

```bat
python -m app.bridge
```

| Direction | Payload |
|---|---|
| stdin | `{"cmd":"start"}` / `{"cmd":"stop"}` / `{"cmd":"quit"}` / `{"cmd":"ping"}` |
| stdout | `{"e":"hypothesis","text":"..."}`, `{"e":"pair","en":"...","zh":"...","sid":1}`, `{"e":"listening","on":true}`, `{"e":"stats","asr_ms":120}` and so on |

Environment variables: `DEEPSEEK_API_KEY` (for translation), `LL_AUDIO_SOURCE=microphone` or `system`, `LL_MT_MODEL`.

---

## 1. Three steps to get started

1. **Double-click `启动同传.bat`** — a subtitle bar appears at the bottom of the screen and an icon shows up in the tray. (From a clone, finish the dependency install above first; an offline bundle needs no setup.)
2. **Click ⚙ and enter your API key** — get one at [platform.deepseek.com](https://platform.deepseek.com) (a few dollars lasts a long time). Paste it into "API Key", click "测试接口" ("test endpoint") until you see ✓, then save.
3. **Click ▶ to start** — speak English and Chinese subtitles appear as you go.

`Ctrl+Alt+S` also starts and stops.

---

## 2. For talks and lectures

Speakers rarely pause, so the program does not wait for a full sentence:

- while someone is talking, every **3–4 seconds** (or every 6 words, or at a comma) the pending fragment is sent for translation, so Chinese follows the speech;
- each fragment lands in the transcript window as soon as it is translated — **no waiting for the end of a sentence**;
- the subtitle bar keeps only the most recent chunk (~170 characters, cut at punctuation), so it never grows to fill the screen;
- long sentences lose nothing: each fragment translates only the part that has not been translated yet, and earlier text is appended to, never rewritten.

### Looking back

Click **☰** to open the live transcript window:

| Feature | What it does |
|---|---|
| Live append | One line per translated fragment; fragments of the same sentence are merged automatically |
| Chinese only | Hides the English column for a cleaner screen |
| Always on top | Keeps the window above others — handy while presenting slides |
| Auto-scroll | On by default, always showing the newest content |
| Export… | Saves the transcript as Markdown |

Every run also writes `output/同传_YYYYMMDD_HHMMSS.md` automatically, so closing the app mid-session loses nothing.

---

## 3. UI reference

```
● Listening (microphone)  ▭▭▭▭       ASR 126ms · MT 483ms     ▮ ⚙ ☰ Click-through ✕
Good afternoon everyone. Today I'd like to talk about ...
各位下午好。今天我想谈谈……
```

| Element | Meaning |
|---|---|
| Green / grey dot | Listening / stopped |
| Level meter | Input loudness; it should move when you speak. If it never moves, it's the device or a mute |
| ASR xx ms | Time spent on each recognition pass |
| MT xx ms | Time until the first Chinese character appears |
| ▶ / ■ | Start / stop |
| ⚙ | Settings |
| ☰ | Live transcript |
| Click-through | Mouse clicks pass to the window below (click again or press `Ctrl+Alt+P` to undo) |
| ✕ | Hide the window (double-click the tray icon to restore) |

The window is draggable and remembers its position.

| Hotkey | Action |
|---|---|
| `Ctrl+Alt+S` | Start / stop |
| `Ctrl+Alt+P` | Toggle click-through |
| `Ctrl+Alt+H` | Show / hide the subtitle window |
| `Ctrl+Alt+Q` | Quit |

---

## 4. Building an offline bundle (optional)

To run on a machine **without Python**, bundle the runtime together with the model into a folder that works as soon as it is unzipped.

Prerequisite: dependencies installed and the model downloaded, per the section above.

| Step | Do this |
|---|---|
| 1 | Prepare a portable Python with the dependencies installed and place it in `runtime/` at the project root |
| 2 | Make sure `models/faster-whisper-large-v3-turbo/` is fully downloaded |
| 3 | Zip `app/`, `runtime/`, `models/` and the launcher scripts together |

On the target machine, unzip and double-click `启动同传.bat`; no Python installation needed.

| Item | Notes |
|---|---|
| OS | 64-bit Windows 10 / 11 |
| Size | ~4.5 GB (1.5 GB model + ~3 GB Python and dependencies) |
| GPU | Uses an NVIDIA GPU automatically; otherwise falls back to CPU |
| Network | Only translation needs the network; recognition is fully local |
| API key | If `config.json` has no key, fill it in from the settings after the first launch |

On CPU, subtitles lag noticeably. Try bumping 「刷新间隔」 (refresh interval) to 0.6 and 「最长一句」 (max sentence length) to 12.

---

## 5. Tuning

| Parameter | Default | Faster | More accurate |
|---|---|---|---|
| Refresh interval (ASR) | 0.30 s | 0.25 | 0.5–0.8 |
| Silence to end a sentence | 0.50 s | — | 0.8 |
| VAD threshold | 0.45 | 0.6 in noisy rooms | 0.35 for quiet speakers |
| Max sentence length | 18 s | 12 s | 25 s |
| Temperature | 0.20 | 0.1 hugs the source | 0.3–0.4 reads more smoothly |

**Glossary** (Settings → Translation): one `english=中文` per line, enforced on the model. Useful for names, company names and acronyms.

```
Kubernetes=Kubernetes
LLM=大语言模型
M&A=并购
```

---

## 6. Project layout

```
同传/
├─ 启动同传.bat           ← normal launcher
├─ 调试启动.bat           ← launcher with a console, for when something goes wrong
├─ 下载模型.bat           ← re-download the model
├─ config.json            ← all settings (contains the API key; never commit)
├─ config.example.json    ← configuration template
├─ requirements.txt       ← dependency list (taken from the tested runtime)
├─ runtime/               ← portable Python (not in the repo)
├─ models/                ← faster-whisper-large-v3-turbo, 1.5 GB (not in the repo)
├─ assets/                ← sample audio and UI preview
├─ output/                ← saved transcripts, app.log, error.log
├─ app/                   ← application source
│   └─ bridge.py          ← headless JSON-lines mode (for external programs)
└─ tools/                 ← diagnostics, download and benchmark scripts
```

---

## 7. Self-checks first

```bat
runtime\python.exe tools\audio_probe.py     :: list devices, measure input level
runtime\python.exe tools\selftest_asr.py    :: check recognition accuracy on sample audio
runtime\python.exe tools\pipe_test.py       :: run the whole pipeline without a microphone
runtime\python.exe tools\ui_bus_test.py     :: check UI signals
```

Runtime logs are in `output/app.log` (timestamped at every step); uncaught exceptions go to `output/error.log`.

### FAQ

**No subtitles and the level meter is flat**
- Check the hardware mute on your headset cable; Windows Settings → Privacy → Microphone → allow desktop apps;
- Settings → Audio input: try another device and use 「试听 20 秒」 ("preview 20 s") to see whether the meter moves;
- After 8 seconds of silence the app shows a "can't hear anything" hint.

**Stuck on "启动中…" ("starting…")**
- Check the last line of `output/app.log` to see which step it reached; it times out on its own after 180 seconds.

**Broken sentences in the transcript**
- Expected: fragments of the same sentence are merged into one line. A line with half a sentence usually means the sentence was very long and the speaker paused mid-way.

**Translation errors 401 / 402 / 429**
- 401 wrong key; 402 out of balance; 429 rate limited.

**First launch is slow**
- Loading the model takes ~20 s (CUDA initialization) the first time, ~2 s afterwards.

---

## 8. Privacy and cost

- **Audio never leaves the machine**; recognition happens on the local GPU.
- Only the recognized English text is sent to DeepSeek for translation.
- Don't want any network at all? Turn translation off in the settings and you get plain English live captions.
- Cost is per token. A lecture session (one short batch every 3–4 seconds) costs cents a day; check the official pricing page.
- `config.json` holds your key — don't screenshot it or upload it anywhere.

---

## 9. Tech stack

| Component | Version | Role |
|---|---|---|
| Python (portable) | 3.12.14 | Runtime, ships with the folder |
| PySide6 | 6.12 | UI |
| faster-whisper | 1.2.1 | Speech recognition (CTranslate2 4.8.4) |
| large-v3-turbo | 809M | Recognition model, best speed/accuracy balance |
| Silero VAD v6 | onnx | Endpoint detection |
| sounddevice / soundcard | 0.5.6 / 0.4.6 | Microphone / system loopback |
| DeepSeek `deepseek-chat` | — | Streaming translation |
| nvidia-cublas / cudnn cu12 | 12.9 / 9.27 | Portable CUDA libraries (no CUDA Toolkit install) |

Model weights come from ModelScope — HuggingFace and GitHub are unreachable on many networks, so they are avoided entirely.
