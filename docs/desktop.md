# Windows 桌面助手

## 日常使用

第一次使用时点 **安装本地模型并启动**，准备 Vulkan 版 Qwen3-ASR 0.6B 与在 CPU 上运行的 NLLB。没有可用 Vulkan GPU 时，选择 **无可用显卡：安装 CPU 方案**，用 Whisper Small 和 NLLB。启动后按片源选择 **视频语言**。界面分别显示可用的识别和翻译模型，**本地模型管理**负责下载其他权重。所选远程模型需要凭据时才会展开密钥配置。**高级设置**提供运行设备、语音分段和诊断选项。桌面默认用 CPU 运行 Whisper 和 NLLB，有兼容 NVIDIA GPU 的用户可在高级设置切换为 CUDA。

设置窗口为单实例。关闭窗口后可双击 Windows 托盘图标重新打开。托盘菜单的 **停止字幕服务** 释放模型资源并保留窗口入口，**停止并退出** 同时关闭助手。退出后重新运行助手并启动服务，播放器才能继续提交新任务。已经写入磁盘的缓存可复用。

## 诊断模式

正常模式关闭诊断日志。遇到问题时，在 **高级设置** 勾选 **启用诊断日志** 并应用，再复现问题。若需要诊断整段播放器会话，可以停一次预读再开启。用 **打开日志目录** 查看结果。命令行可用 `python -m subtitle_relay serve --diagnostics`。

源代码助手把服务和播放器日志保存在 `%LOCALAPPDATA%\Subtitle Relay`。分享诊断前，检查记录中的本地文件路径、主机名和 URL。定位结束后可以关闭诊断模式。

## 模块接口

打包启动器运行 `UI/LocalVideoSubtitleTranslator.exe`。WPF 界面使用 `python -m subtitle_relay.desktop.bridge` 管理后台。该入口与播放器使用的 [HTTP 会话接口](server.md) 各自独立。

| 命令 | 输入与行为 |
| --- | --- |
| `status` | 输出 `settings`、`models`、`running`、`active_sessions`、`potplayer_detected` 和 `ffmpeg_detected`。FFmpeg 探测同时检查 `ffmpeg` 和 `ffprobe`。 |
| `install <model>` | 准备指定本地模型。标识见控制模块中的 `MODELS`。 |
| `apply` | 从 stdin 读 JSON 对象，验证并应用设置。必要时重启后台。 |
| `stop` | 停止助手管理的服务。 |
| `integrate potplayer\|mpv` | 将对应播放器脚本安装到默认目录。 |
| `logs` | 输出可以查看的日志路径。 |

每次调用向 stdout 输出一个 JSON 对象，带 `ok` 布尔值。失败时带 `error` 并返回非零退出码。它是项目内的桌面控制接口，外部适配器应以公开的 HTTP v1 合约为准。

运行时使用 `%LOCALAPPDATA%\Subtitle Relay\settings.json` 保存设置，模型、缓存及控制令牌也留在用户数据目录。独立启动并使用不同控制令牌的服务由其启动方管理。源码入口 `Subtitle Relay.pyw` 仍可用；它也承担播放器回调和 Windows 反馈工具的兼容入口。
