# 架构与模块边界

[English](architecture.md) | [简体中文](architecture.zh-CN.md)

音频预读按任务提取，每次只为一个 ASR 片段编码 WAV；任务完成后释放音频。邻近对白的识别复用只保留有界文本，在播放会话空闲后清理。字幕保存在 SQLite；新片段完成后流式生成 SRT，日常轮询只读取当前进度附近的字幕记录。

```text
PotPlayer / mpv                    Windows 桌面助手
        │                              │ 配置、启停
        │ IPv4 loopback HTTP v1         │
        ▼                              ▼
               后台服务、会话、缓存
                      │ 分块任务
                      ▼
            FFmpeg → VAD → ASR → 文本翻译
                      │ 媒体时间轴
                      ▼
                    SRT
```

| 包或目录 | 职责 | 扩展入口 |
| --- | --- | --- |
| `subtitle_relay/adapters/` | 播放状态和字幕加载。Win32 消息和 mpv IPC 在各自适配层 | `state()` / `publish(path, revision)`，或直接使用 HTTP v1 |
| `subtitle_relay/server/` | HTTP、会话调度、缓存和 SRT 输出 | `Playback`、`Relay.update()` / `drop()` 与 [HTTP v1](server.zh-CN.md) |
| `subtitle_relay/inference/` | 音频分段、识别与翻译 | [Recognizer、Translator、SpeechTranslator](providers.zh-CN.md#后端接口) |
| `subtitle_relay/desktop/` | 控制桥、服务生命周期、PotPlayer 回调和源码备用界面 | [桌面助手](desktop.zh-CN.md) |
| `desktop/` | WPF 设置界面和 Windows 托盘 | 通过桌面控制桥调用 Python 运行时 |
| `subtitle_relay/client.py` | 桌面和播放器共用的 loopback HTTP 客户端 | `RelayClient(port).send(route, data)` |
| `integrations/` | 由播放器宿主装载的 Lua / AngelScript 脚本 | [播放器适配](adapters.zh-CN.md) |
| `subtitle_relay/__main__.py` | CLI 命令和运行时组装 | `python -m subtitle_relay --help` |

播放器提供媒体位置和音轨。服务按需读文件，以原媒体时间输出 SRT。适配器与服务可由命令行独立启动，测试可以用模拟播放头代替真实播放器。

一个服务共享模型实例，并限制在途分块任务。每个播放窗口持有一个会话。相同媒体、音轨和处理配置可共用缓存。窗口停止或失联后会话释放，已完成的磁盘缓存可供下次使用。后台退出后会关闭其管理的本地推理进程。

新播放器优先实现已有协议，新增模型优先实现 provider 接口。播放器无需了解模型、VAD 或云端凭据。新增浏览器或其他非文件媒体来源时，需要先定义媒体输入与时间坐标契约，再复用现有的分段和翻译流程。

目前提供 CLI 和 HTTP 接入，尚未内置 MCP server。
