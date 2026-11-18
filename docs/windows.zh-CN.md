# Windows 安装与支持

[English](windows.md) | [简体中文](windows.zh-CN.md)

## 获取和启动

使用适配 Windows x64 的安装程序或便携包。安装后从开始菜单启动；便携包先完整解压，再运行 `AheadSubs.exe`。将启动程序与其运行时目录一起移动。

文件名前缀为 `aheadsubs-v<版本>-windows-x64`。后缀 `-setup.exe` 为安装程序，`-portable.zip` 为便携包，`-SHA256.txt` 为校验清单。

- **标准版**包含 CPU 所需组件，也支持兼容硬件上的 Qwen3-ASR Vulkan 路线。
- **CUDA 版**的文件名含 `-cuda`，额外包含 faster-whisper 与 NLLB 所用的 NVIDIA CUDA 运行库。仍需可用的 NVIDIA 驱动。

发布包自带 Python 运行时及一套 LGPL FFmpeg 和 FFprobe，用于探测本地媒体并提取音轨。相应源码和构建说明随二进制发布。语音识别和翻译模型在设置时下载，云端处理使用服务凭据。GPU 推理需要另行安装兼容驱动。如提示缺少 Visual C++ 运行库，请安装微软 x64 Redistributable。构建和发布步骤见[打包文档](../packaging/README.zh-CN.md)。[微软运行库下载](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)

## 检查更新

Windows 桌面版默认在启动后从 GitHub 检查正式版本，常驻托盘期间也会检查，最多每 24 小时自动检查一次。在 **高级设置 → 软件更新** 可以关闭自动检查，或随时选择 **检查更新**。GitHub 不可用时可以稍后手动重试，字幕服务仍可使用。

发现新版本后可查看发行说明。安装版选择 **下载并安装**，确认后会下载与当前标准版或 CUDA 版匹配的安装程序。下载期间可以取消。通过下载大小和 SHA-256 校验后，AheadSubs 会停止字幕服务并退出，再启动安装程序。下载校验失败时可重试，或从发行页面手动下载安装。升级完成后，从开始菜单打开 AheadSubs，按需重新启动字幕服务。

便携版可选择 **下载便携版 ZIP**，在浏览器下载同一版本类型的压缩包。先从托盘停止并退出 AheadSubs，再将 ZIP 解压到新目录，从新目录运行 AheadSubs。设置、模型和字幕缓存仍从原有用户数据目录读取。早期没有 **软件更新** 入口的版本，可从 [GitHub Releases](https://github.com/cutexx52/AheadSubs/releases) 手动升级一次。

自动更新仅跟随稳定版；定期预览版可从 Releases 自行下载。

## 选择处理路线

- **全本地：** 本地模型页安装识别模型与 NLLB，应用方案并选择语言；下载后无需 API Key。
- **混合：** 安装本地识别模型，云端模型页保存翻译密钥，在「字幕」页选择本地识别和云端翻译。
- **全云端：** 保存凭据，选择支持的云端识别及翻译。音频和文本发送到对应供应商，本地仍运行提取和 VAD。

播放器页一键配置后重启播放器并开启预读。[README](../README.zh-CN.md) 有最短路径，[后端](providers.zh-CN.md) 介绍模型与凭据。

## 支持范围

| 系统 | 范围 |
| --- | --- |
| Windows 11 x64 | 主要发布目标。 |
| Windows 10 22H2 x64 | 仅为安装程序的最低版本，尚未独立完成安装和实播验证。优先使用仍受支持的 Windows 版本。 |
| Windows ARM64 | 暂无原生包，x64 模拟运行也尚未验证。 |
| 32 位 Windows、Windows 7/8.1、S 模式 | 未进入当前发布和验证范围。 |

CPU 可运行 faster-whisper 与本地 NLLB。Qwen3-ASR 依赖当前 Vulkan 运行时支持的硬件与驱动。CTranslate2 的 NVIDIA 模式使用 CUDA 12 相关库。系统可以打开程序和设备足以多路实时推理是两项独立的验证，详情见[性能与设备建议](performance.zh-CN.md)。

## 源码备用入口

使用开发环境启动时，先准备 Python 3.11+、FFmpeg 和 ffprobe，运行源码目录的 `AheadSubs.pyw`。详细命令见[开发与贡献](contributing.zh-CN.md)。

安装版和便携版在干净的 Windows 用户环境中使用 `%LOCALAPPDATA%\AheadSubs` 保存设置、模型和字幕缓存。如果 AheadSubs 数据目录尚未创建，已有安装继续使用 `%LOCALAPPDATA%\Subtitle Relay`。升级时从托盘退出常驻助手再更换程序文件。

两版均包含 `cli/aheadsubs.exe`，可在桌面接入页安装 CLI 或复制 MCP 配置，见[Agent 接入](automation.zh-CN.md)。
