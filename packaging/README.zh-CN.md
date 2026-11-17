# Windows 构建与发布

[English](README.md) | [简体中文](README.zh-CN.md)

发布包组合独立 CPython 3.11、备用界面和 PotPlayer 提示使用的 Tcl/Tk、可选自包含 WPF、FFmpeg/FFprobe 及程序包。不依赖构建者的 `.venv`、凭据或模型缓存。

## 本地构建

使用 Windows x64 和包含 Tcl/Tk 的完整 x64 CPython 3.11。WPF 构建需要 .NET 10 SDK。安装 [MSYS2](https://www.msys2.org/)，在 UCRT64 中运行 `pacman -S --needed diffutils make mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-nasm`。构建从固定归档下载 `libwinpthread` DLL 和对应源码。安装包需要 Inno Setup 7，也可让脚本下载固定编译器到构建缓存。

```bat
python packaging\windows\build.py --native --version 0.1.0
python packaging\windows\build.py --native --cuda --version 0.1.0
```

`--msys2` 可覆盖默认路径 `C:\msys64`，`--dotnet`、`--iscc` 可指定程序路径。不带 `--native` 构建 Tk 备用版，`--portable-only` 跳过 Inno。每次在 `dist` 临时目录构建，校验固定下载，在只有系统路径的 `PATH` 下测试私有运行时。媒体检查探测双音轨并测试重采样、时间戳保留和 Whisper 的 PCM 输入。`--verify-install` 在未安装程序的用户环境中测试安装、清除旧 PyAV 文件和卸载。

输入匹配时复用 `.relay/packaging-tools` 中的私有 Python 运行时和 FFmpeg。首次构建 FFmpeg 需要完整原生编译。播放器集成、UI 和 Python 源码每次重新放入，全部验证成功才替换输出文件。

标准文件如 `aheadsubs-v0.1.0-windows-x64-setup.exe`、`aheadsubs-v0.1.0-windows-x64-portable.zip`，配套 `-SHA256.txt`。CUDA 文件加 `-cuda` 并附带 CUDA 数学库，仍需兼容驱动。两个变体使用同一个 `-ffmpeg-source.zip`，再分发二进制时一并提供。便携 ZIP 内是一个程序目录，运行其中 `AheadSubs.exe`。

## 发布与支持边界

原生桌面包带版本/类型元数据。更新器通过 Inno Setup 注册识别安装版，选择匹配的最新稳定版附件；保留附件命名及安装器 ID。下载器通过 HTTPS 对照 GitHub 附件元数据核对大小与 SHA-256。见 [Windows 更新](../docs/windows.zh-CN.md#检查更新)。

- Windows bundles 每日检查预览版资格，包括 72 小时间隔、有效程序改动及当前 head CI。手工 `mode=verify` 仅验证两版，不发布或保留产物。`mode=preview` 检查默认分支资格。推送 `v*` 标签显式发布。四个二进制、两个校验清单与对应的 FFmpeg 源码 ZIP 齐全才公开。含 `-` 的标签标记预发布。详见[发布与预算](../docs/releases.zh-CN.md)。
- Windows 11 x64 是主要验证目标。Windows 10 22H2 x64 是安装最低版本，各受支持版本仍需独立验证。已结束支持的 Windows 10 版本不在微软支持周期。ARM、32 位、Windows 7/8.1、S 模式不在已验证路径。[.NET 10 支持矩阵](https://learn.microsoft.com/en-us/dotnet/core/install/windows#supported-versions)。
- 按用户安装；设置/模型仍在 `%LOCALAPPDATA%\Subtitle Relay`。标准和 CUDA 更新同一应用安装。模型与凭据独立获取。
- 原生推理依赖可能需要 [Visual C++ Redistributable x64](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)，缺失时启动器提供链接。
- 当前包未签名。`notices/ffmpeg` 记录随包分发的 LGPL 构建、准确源码版本及替换说明。请在同一 Release 提供二进制、FFmpeg 源码 ZIP 和校验清单。其他组件义务见[许可证与再分发](../docs/licenses.zh-CN.md)。
