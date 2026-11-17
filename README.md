# AheadSubs

Windows 本地视频语音识别与字幕翻译工具。为 PotPlayer 和 mpv 提前生成带时间轴的字幕，多个播放窗口共享推理服务。模型在本机运行时，无需 API 密钥。

Generate translated SRT subtitles for local videos ahead of playback, using on-device speech recognition and translation on Windows.

## 我的电脑能跑几路？

| 设备 | 建议的本地配置 | 当前依据 |
| --- | --- | --- |
| 只有 CPU | Whisper Small + NLLB 600M INT8，设备选 CPU | 从单路试起。i9-13900KF 实测单路 25 秒、零缓冲耗尽。 |
| 有兼容 GPU，显存有限 | Qwen3-ASR 0.6B + 本地 NLLB | 从单路试起。4090 搭配 CPU 翻译实测四路，入门 GPU 并发待测。 |
| RTX 4090 24 GB | Qwen3-ASR 1.7B Q4_K + NLLB 600M INT8 | 默认设置实测 **4 路、45 秒、零缓冲耗尽**。最低余量 **18.17 秒**。 |

4090 的数据来自同一公开日语样本的多个独立副本，使用 20 秒目标预读和模拟播放头。更高并发、跳转延迟、测试限制和复测方法见[性能与设备建议](docs/performance.md)。

## 快速开始

1. 按[Windows 安装指南](docs/windows.md)启动助手。首次使用需要下载本地模型。
2. 在 **翻译** 首页展开 **快速预设**。选择方案并下载缺少的模型，然后点击 **应用方案**。没有可用 Vulkan GPU 时可选 **纯本地 · CPU**。[查看预设和模型管理](docs/desktop.md#日常使用)
3. 在 PotPlayer 打开本地视频，按 **Ctrl+Alt+J** 开启预读，按 **Ctrl+Alt+K** 停止当前窗口的预读。mpv 可以从助手安装右键菜单，详见[播放器适配](docs/adapters.md)。

在 **接入** 页开启 MCP 或安装 CLI，可让本机 Agent 和脚本翻译文本、生成 SRT 或控制预读。详见[Agent 与命令行接入](docs/automation.md)。

关闭设置窗口会隐藏到系统托盘。右键托盘图标选 **停止并退出** 会停止后台并释放模型资源。升级保留已有设置、模型和字幕缓存。

## 使用与扩展

也可以从 [AheadSubs Wiki](https://github.com/cutexx52/AheadSubs/wiki) 按主题查找文档。

| 文档 | 内容 |
| --- | --- |
| [Windows 安装与支持](docs/windows.md) | 安装、更新与适用系统 |
| [识别与字幕调校](docs/tuning.md) | 原文检查、停顿分段、翻译上下文与双语字幕 |
| [桌面助手](docs/desktop.md) | 配置、托盘、模型下载与诊断 |
| [播放器适配](docs/adapters.md) | PotPlayer、mpv 及新播放器接口 |
| [Agent 与命令行接入](docs/automation.md) | MCP 配置、CLI、字幕生成及自动化接口 |
| [后台协议](docs/server.md) | HTTP 请求、响应、会话、时间轴与缓存 |
| [推理与翻译后端](docs/providers.md) | 本地与云端配置、VAD、provider 接口 |
| [架构与模块边界](docs/architecture.md) | 包分层、数据流和扩展位置 |
| [开发与贡献](docs/contributing.md) | 开发环境、测试与提交前检查 |

当前支持后台可访问的本地文件与共享目录媒体。字幕按对白片段与原媒体时间对齐。
