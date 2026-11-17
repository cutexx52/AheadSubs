# Subtitle Relay

为 Windows 本地视频提前生成带时间戳的翻译字幕。播放器适配器上报播放头，独立后台读取音轨、识别语音、翻译，再输出持续更新的 SRT。一个后台服务可供多个窗口使用。

## Windows 图形入口

1. 准备 Python 3.11+、`ffmpeg` 和 `ffprobe`，并把它们放到 PATH。NVIDIA 模式需要支持 CUDA 12 的驱动。
2. 双击 `Subtitle Relay.pyw`。选择本地或 OpenAI provider，可以从窗口准备项目环境。首次运行本地 provider 会下载模型。
3. 在 **Setup** 点击 **Install mpv menu…**，选择现有配置目录。使用默认目录时可以按取消。用便携 mpv 时选择其 `portable_config`。重开 mpv 0.42+，在视频窗口右键打开 **Subtitle Relay**，启用字幕即可。可以在同一菜单切换源语言、目标语言和预读时长。服务未启动时会按保存的配置启动。

**PotPlayer** 标签提供两个入口：

- **Open video with translated subtitles…** 选择本地视频，服务先准备起始字幕，再用新 PotPlayer 窗口加载 SRT。已知版本会由适配器定位并调用原生 Reload Subtitle 命令。找不到该命令时，可以启用 PotPlayer 的 **F5 → 字幕 → 字幕文件变化时自动重载**。已打开的视频也可用 **Select media and start pre-reading…** 手动绑定，并在该窗口加载输出的 SRT。切换视频或音轨后重新绑定。
- **Install PotPlayer translation menu** 安装原生 **Subtitle Relay (local service)** 翻译引擎。重开 PotPlayer 后，在实时字幕翻译的引擎列表选择它，并指定来源和目标语言。该回调处理 PotPlayer 传入的现成字幕文本。观看已经由后台生成译文的 SRT 时，可关闭 PotPlayer 自己的字幕翻译以免重复处理。
- 安装还会加上 **Subtitle Relay (audio pre-read setup)**。打开视频后，在该项的设置中点击**确定**打开图形助手，无需输入账号。要直接进入自动加载、刷新的流程，选 **Open video with translated subtitles…**。如果绑定已打开窗口，需在原窗口加载一次生成的 SRT。

## 单独运行后台

```cmd
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[local,cloud]" nvidia-cublas-cu12==12.8.4.1 nvidia-cudnn-cu12==9.10.2.21
.venv\Scripts\python -m subtitle_relay serve
```

本地默认使用 faster-whisper `small` 和 NLLB 600M INT8，经 CTranslate2 在 CUDA 上运行。CPU 可用 `--device cpu`。NLLB 支持 ISO 简写和模型语言代码，例如 `en`、`ja`、`zh`、`zh-TW`。默认 checkpoint 的基础权重使用 CC BY-NC 4.0，可通过 `--nllb-model` 指向其他兼容权重或指定 `--mt compatible`。

```cmd
.venv\Scripts\python -m subtitle_relay serve --asr openai --mt openai --key-file D:\path\outside-repo\openai
.venv\Scripts\python -m subtitle_relay serve --mt compatible --llm-url http://127.0.0.1:11434/v1 --llm-model qwen2.5:3b
.venv\Scripts\python -m subtitle_relay serve --ast --key-file D:\path\outside-repo\openai
```

云端 ASR 默认用能返回起止时间的 `whisper-1`。默认小型文本模型为 `gpt-4.1-mini`。OpenAI 音频直译模式的目标选 `en`。使用 OpenAI ASR / AST 时会发送处理过的语音段，使用云端文本翻译时会发送该段的字幕文本。凭据从环境变量 `OPENAI_API_KEY` 或本地密钥文件读取。兼容文本接口的可选密钥读取 `RELAY_LLM_API_KEY`。

## 单独运行适配器

```cmd
mpv.exe --input-ipc-server=relay-window-1 D:\video\clip.mkv
.venv\Scripts\python -m subtitle_relay mpv relay-window-1 --source ja --target zh --ahead 25
.venv\Scripts\python -m subtitle_relay clock D:\video\clip.mkv --position 45 --target zh --ahead 20
```

第二个 mpv 实例使用另一个管道名。使用原生菜单时，由每个 mpv 窗口自动建立不同的会话。模拟播放头模式无需播放器即可调试后台，`--realtime` 会让模拟播放头按真实时间推进。

## 音频与时间轴配置

| 参数 | 默认 | 作用 |
|---|---:|---|
| `--ahead` | 20 秒 | 适配器的目标已译余量。倍速会按比例扩大要处理的媒体区间。 |
| `--chunk` | 8 秒 | 固定调度和缓存块。 |
| `--before` / `--after` | 各 2 秒 | 每个块解码时额外读取的前后文。 |
| `--backfill` | 4 秒 | 跳转后补算播放头前可能含有正在说的对白的块。 |
| `--min-silence-ms` | 450 ms | Silero VAD 判定语音结束所需的静音。 |
| `--pad-ms` | 160 ms | VAD 切出的语音边缘保留。 |
| `--max-speech` | 12 秒 | 送入识别的单段上限。长段优先在 VAD 找到的边界切分。 |
| `--vad-threshold` | 0.5 | Silero VAD 的语音阈值。 |

同一个服务内的所有会话共享模型。任务先补离播放头近的缺口；播放位置跳变会改变下一轮任务优先级，已在运行的请求可以完成并写入缓存。SQLite 将媒体和音轨、模型及语言参数作为缓存键的一部分，原文与译文保留在同一条记录。SRT 用原视频时间保存，每批原子替换。首次打开或跳到未处理的位置时，可以暂停到菜单中显示已有缓冲再继续。

## 测试与扩展

```cmd
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python tools\benchmark.py --seconds 45 clip1.wav clip2.wav clip3.wav clip4.wav
.venv\Scripts\python tools\mpv_smoke.py C:\path\mpv.exe clip1.mp4 clip2.mp4 clip3.mp4 clip4.mp4
```

用一个空缓存的服务跑 benchmark。需要至少四个不同文件路径，各文件至少为测试时长加 20 秒。工具会先在所有会话达到 20 秒已译覆盖时启动模拟播放，再输出最低余量和断字幕采样数。

播放器协议见 [PROTOCOL.md](PROTOCOL.md)，详细分工和验收见 [PLAN.md](PLAN.md)。适配新推理后端实现 `subtitle_relay/providers.py` 中的相应接口，返回相对所传音频的 start/end。
