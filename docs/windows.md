# Windows 安装与支持

## 获取和启动

使用适配 Windows x64 的安装程序或便携包。安装后从开始菜单启动；便携包先完整解压，再运行 `AheadSubs.exe`。将启动程序与其运行时目录一起移动。

文件名前缀为 `aheadsubs-v<版本>-windows-x64`。后缀 `-setup.exe` 为安装程序，`-portable.zip` 为便携包，`-SHA256.txt` 为校验清单。

- **标准版**包含 CPU 所需组件，也支持兼容硬件上的 Qwen3-ASR Vulkan 路线。
- **CUDA 版**的文件名含 `-cuda`，额外包含 faster-whisper 与 NLLB 所用的 NVIDIA CUDA 运行库。仍需可用的 NVIDIA 驱动。

发布包自带 Python 运行时、FFmpeg 和 FFprobe。模型需要首次下载，Windows GPU 驱动由系统或厂商安装。完全本地的配置在模型准备好后无需配置 API 密钥。如果启动时提示缺少 Visual C++ 运行库，请安装微软的 x64 Redistributable。维护者构建和发布步骤见[打包文档](../packaging/README.md)。[微软运行库下载](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)

## 检查更新

在 **高级设置** 的 **软件更新** 中检查 GitHub 上的正式版本。安装版从当前使用的标准版或 CUDA 版升级。便携版可以打开对应的 ZIP 下载链接。

## 支持范围

| 系统 | 范围 |
| --- | --- |
| Windows 11 x64 | 主要发布目标。 |
| Windows 10 22H2 x64 | 仅为安装程序的最低版本，尚未独立完成安装和实播验证。优先使用仍受支持的 Windows 版本。 |
| Windows ARM64 | 暂无原生包，x64 模拟运行也尚未验证。 |
| 32 位 Windows、Windows 7/8.1、S 模式 | 未进入当前发布和验证范围。 |

CPU 可运行 faster-whisper 与本地 NLLB。Qwen3-ASR 依赖当前 Vulkan 运行时支持的硬件与驱动。CTranslate2 的 NVIDIA 模式使用 CUDA 12 相关库。系统可以打开程序和设备足以多路实时推理是两项独立的验证，详情见[性能与设备建议](performance.md)。

## 源码备用入口

使用开发环境启动时，先准备 Python 3.11+、FFmpeg 和 ffprobe，运行源码目录的 `Subtitle Relay.pyw`。详细命令见[开发与贡献](contributing.md)。

安装版和便携版均使用当前 Windows 用户的数据目录 `%LOCALAPPDATA%\Subtitle Relay`，其中保存设置、模型和字幕缓存。升级时从托盘退出常驻助手再更换程序目录。
