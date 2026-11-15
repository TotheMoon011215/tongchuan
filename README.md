# 同传 · 英译中实时字幕

把**听到的英文**（麦克风 / 电脑播放的声音）实时变成**中文字幕**，并且边说边把内容记成可回看的文字稿。
语音识别跑在本机显卡上（免费、离线、不出网），只有识别出来的文字会发给 DeepSeek 翻译。

> 实测：RTX 5080 上一段 15 秒英文，识别 144–400ms（约 40–100 倍实时），文字全对。

---

## 从源码运行（克隆本仓库后）

仓库里**不含** `runtime/`（3 GB 便携 Python）和 `models/`（1.5 GB 模型），两者都在 `.gitignore` 中。

```bat
:: 1. 依赖（Python 3.12）
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

:: NVIDIA 显卡想要 GPU 加速，再装这两个（不装会自动退回 CPU）
:: pip install nvidia-cublas-cu12==12.9.2.10 nvidia-cudnn-cu12==9.27.0.42

:: 2. 模型（约 1.5 GB，走魔搭）
tools\download_model.ps1

:: 3. 配置
copy config.example.json config.json

:: 4. 启动（有 .venv 时会自动用它）
启动同传.bat
```

也可以直接 `python -m app.main`。

> `runtime/`（约 3 GB 的便携 Python）和 `models/`（约 1.5 GB 的模型权重）没有放进仓库——体积超出用 git 管理的合理范围。按上面的步骤装好依赖、下好模型即可运行。

---

## 与 LingoLens 集成

`app/bridge.py` 是无界面模式：**不启动 Qt**，改用 stdin/stdout 一行一条 JSON 通信，供 [LingoLens](https://github.com/TotheMoon011215/lingolens) 这类外壳调用。

```bat
python -m app.bridge
```

| 方向 | 内容 |
|---|---|
| stdin | `{"cmd":"start"}` / `{"cmd":"stop"}` / `{"cmd":"quit"}` / `{"cmd":"ping"}` |
| stdout | `{"e":"hypothesis","text":"..."}`、`{"e":"pair","en":"...","zh":"...","sid":1}`、`{"e":"listening","on":true}`、`{"e":"stats","asr_ms":120}` 等 |

环境变量：`DEEPSEEK_API_KEY`（翻译用）、`LL_AUDIO_SOURCE=microphone` 或 `system`、`LL_MT_MODEL`。

---

## 一、三步开始用

1. **双击 `启动同传.bat`** —— 屏幕底部出现字幕条，托盘出现图标。（仓库版需先完成上一节的依赖安装；离线版直接双击即可。）
2. **点 ⚙ 填 API Key** —— 到 [platform.deepseek.com](https://platform.deepseek.com) 申请（充几块钱够用很久），
   粘贴进「API Key」，点「测试接口」看到 ✓ 后保存。
3. **点 ▶ 开始** —— 说英文，中文字幕实时出现。

快捷键 `Ctrl+Alt+S` 也能开始/停止。

---

## 二、听报告 / 演讲（最关键的场景）

报告里讲话人往往**不停顿地连讲几分钟**，所以本程序不是"等一句话说完再翻译"，而是：

- 说话过程中，每 **3~4 秒**（或攒够 6 个词、遇到逗号）就把这一小段送去翻译，中文跟着语流冒出来；
- 一小段翻完立刻落到「记录」窗口，**不用等整句结束**；
- 字幕条里的中文只保留最近一段（约 170 字，从标点处截断），不会越长越占屏幕；
- 长句也不会丢内容：每段只翻"还没翻过的那部分"，翻过的只追加不改写。

### 看前面的内容

点 **☰** 打开「同传记录（实时）」窗口：

| 功能 | 说明 |
|---|---|
| 实时追加 | 每翻完一小段就出现一行，同一句的片段会自动合并成完整句子 |
| 只显示中文 | 勾上后只看中文，屏幕更干净 |
| 窗口置顶 | 勾上后压在其他窗口上面，适合边放 PPT 边看 |
| 自动滚动 | 默认开启，始终显示最新内容 |
| 导出… | 存成 Markdown 文字稿 |

每次启动还会自动写一份 `output/同传_年月日_时分秒.md`，中途关掉也不丢。

---

## 三、界面说明

```
● 正在聆听（麦克风）  ▭▭▭▭       识别 126ms · 翻译 483ms     ▮ ⚙ ☰ 穿透 ✕
Good afternoon everyone. Today I'd like to talk about ...
各位下午好。今天我想谈谈……
```

| 元素 | 含义 |
|---|---|
| 绿点 / 灰点 | 正在聆听 / 已停止 |
| 电平条 | 麦克风输入强度，说话时会跳；不跳就是设备或静音问题 |
| 识别 xxms | 每轮重新识别的耗时 |
| 翻译 xxms | 译文第一个字出来的延迟 |
| ▶ / ■ | 开始 / 停止 |
| ⚙ | 设置 |
| ☰ | 实时记录 |
| 穿透 | 鼠标点击穿到下层窗口（再点一次或按 `Ctrl+Alt+P` 解除） |
| ✕ | 隐藏窗口（双击托盘图标恢复） |

窗口可直接拖动，位置会记住。

| 快捷键 | 作用 |
|---|---|
| `Ctrl+Alt+S` | 开始 / 停止 |
| `Ctrl+Alt+P` | 鼠标穿透开关 |
| `Ctrl+Alt+H` | 显示 / 隐藏字幕窗 |
| `Ctrl+Alt+Q` | 退出程序 |

---

## 四、做一份离线版（可选）

如果要在**没装 Python**的电脑上用，可以把运行时和模型一起打包，做成解压即用的文件夹。

前提：本机已经按上一节装好依赖、下好模型。

| 步骤 | 做什么 |
|---|---|
| 1 | 准备一个装好依赖的便携版 Python，放在项目根目录的 `runtime/` |
| 2 | 确认 `models/faster-whisper-large-v3-turbo/` 已下载完整 |
| 3 | 把 `app/`、`runtime/`、`models/` 和启动脚本一起压缩 |

目标机解压后双击 `启动同传.bat` 即可，不需要装 Python。

| 项目 | 说明 |
|---|---|
| 系统 | 64 位 Windows 10 / 11 |
| 体积 | 约 4.5 GB（模型 1.5 GB + Python 与依赖约 3 GB） |
| 显卡 | 有 NVIDIA 显卡自动用 GPU；没有则退回 CPU |
| 网络 | 只有翻译需要联网，识别完全本地 |
| API Key | `config.json` 不含 Key 时，首次启动后在设置里填写 |

在 CPU 上跑字幕会偏慢，可以把「刷新间隔」调到 0.6、「最长一句」调到 12。

---

## 五、参数怎么调

| 参数 | 默认 | 想更快 | 想更准 |
|---|---|---|---|
| 刷新间隔（识别） | 0.30 秒 | 0.25 | 0.5~0.8 |
| 断句静音 | 0.50 秒 | — | 0.8 |
| VAD 灵敏度 | 0.45 | 环境吵调 0.6 | 说话轻调 0.35 |
| 最长一句 | 18 秒 | 12 秒 | 25 秒 |
| 温度 | 0.20 | 0.1 更贴原文 | 0.3~0.4 更顺 |

**术语表**（设置 → 翻译接口）：一行一条 `英文=中文`，强制模型遵守，适合人名、公司名、专业缩写。

```
Kubernetes=Kubernetes
LLM=大语言模型
M&A=并购
```

---

## 六、目录结构

```
同传/
├─ 启动同传.bat           ← 平时用这个
├─ 调试启动.bat           ← 出问题时用，有控制台能看到报错
├─ 下载模型.bat           ← 模型丢了重下
├─ config.json            ← 所有设置（含 API Key，别外传；不入库）
├─ config.example.json    ← 配置模板
├─ requirements.txt       ← 依赖清单（取自测试过的运行时）
├─ runtime/               ← 便携 Python（不发仓库）
├─ models/                ← faster-whisper-large-v3-turbo，1.5 GB（不发仓库）
├─ assets/                ← 测试音频与界面预览图
├─ output/                ← 自动存盘的记录、app.log、error.log
├─ app/                   ← 程序源码
│   └─ bridge.py          ← 无界面模式（给她程序调用，见上一节）
└─ tools/                 ← 自检、下载、基准脚本
```

---

## 七、出问题先跑自检

```bat
runtime\python.exe tools\audio_probe.py     :: 看设备、实测电平
runtime\python.exe tools\selftest_asr.py    :: 用测试音看识别准不准
runtime\python.exe tools\pipe_test.py       :: 不用麦克风，跑完整管线
runtime\python.exe tools\ui_bus_test.py     :: 检查界面信号
```

运行时日志在 `output/app.log`（每一步都有时间戳），未捕获异常在 `output/error.log`。

### 常见问题

**字幕不出，电平条也不动**
- 耳机线上的麦克风静音键；Windows 隐私 → 麦克风 → 允许桌面应用访问；
- 设置 → 音频输入 换个设备，点「试听 20 秒」看电平跳不跳；
- 程序会在 8 秒无声时提示「听不到声音」。

**一直停在「启动中…」**
- 看 `output/app.log` 最后一行到哪一步；超过 180 秒会自己报超时。

**记录里出现断裂的句子**
- 正常：同一句会合并成一行；如果一行只有半句，多半是那句话很长且中途停顿了。

**翻译报错 401 / 402 / 429**
- 401 Key 不对；402 余额不足；429 太频繁。

**第一次启动慢**
- 首次加载模型约 20 秒（CUDA 初始化），之后每次约 2 秒。

---

## 八、隐私与费用

- **音频永远不出本机**，识别在本地显卡完成。
- 只有识别出的英文文字会发给 DeepSeek 翻译。
- 不想联网：设置里关掉翻译，就是纯英文实时字幕。
- 费用按 token 计，报告场景（每 3~4 秒一批短句）一天也就几毛到几块；以官网价格为准。
- `config.json` 存着 Key，别截图外发或上传网盘。

---

## 九、技术栈

| 组件 | 版本 | 作用 |
|---|---|---|
| Python（便携） | 3.12.14 | 运行时，随文件夹走 |
| PySide6 | 6.12 | 界面 |
| faster-whisper | 1.2.1 | 语音识别（CTranslate2 4.8.4） |
| large-v3-turbo | 809M | 识别模型，速度/精度平衡最好 |
| Silero VAD v6 | onnx | 端点检测 |
| sounddevice / soundcard | 0.5.6 / 0.4.6 | 麦克风 / 系统回环 |
| DeepSeek `deepseek-chat` | — | 流式翻译 |
| nvidia-cublas / cudnn cu12 | 12.9 / 9.27 | 便携 CUDA 运行库（免装 CUDA Toolkit） |

模型来自魔搭（ModelScope）——HuggingFace / GitHub 在多数网络下不可用，已全部绕开。
