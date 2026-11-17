# Windows setup and support

[English](windows.md) | [简体中文](windows.zh-CN.md)

## Download and launch

Download an installer or portable archive from [Releases](https://github.com/cutexx52/AheadSubs/releases). Stable versions are intended for regular use; automatic previews let you try recent changes. After installation, launch from Start. For a portable build, extract the entire archive and run `AheadSubs.exe`. Keep the launcher and its runtime directories together.

Files start with `aheadsubs-v<version>-windows-x64`. `-setup.exe` is the installer, `-portable.zip` is the archive, and `-SHA256.txt` lists checksums.

- **Standard:** includes CPU dependencies and supports Qwen3-ASR on compatible Vulkan hardware.
- **CUDA:** includes `-cuda` in its filename and adds NVIDIA runtime libraries for faster-whisper and NLLB. A compatible NVIDIA driver is still required.

Packages include Python, FFmpeg and FFprobe. Local models download on first setup; cloud processing instead needs provider credentials. Neither package includes GPU drivers. If prompted for Visual C++ components, install the [Microsoft x64 Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist). See [build instructions](../packaging/README.md).

## Choose your processing route

- **Fully local:** install a local speech model and NLLB from Local models (本地模型); apply the preset and select your languages. No API key is needed after model downloads.
- **Hybrid:** install a local speech model, save a cloud translation key under Cloud models (云端模型), then select that recognizer and cloud translator on Translation (翻译).
- **Cloud recognition and translation:** save provider credentials, choose supported cloud ASR and translation models, and apply. Audio segments and text are sent to the selected providers; local extraction and speech detection still run.

Use Players (播放器) → One-click setup (一键配置), restart the player, then enable look-ahead. The [README](../README.md) gives the shortest setup paths; [providers](providers.md) explains credentials and model combinations.

## Supported systems

| System | Scope |
| --- | --- |
| Windows 11 x64 | Primary release validation target. |
| Windows 10 22H2 x64 | Installer minimum only; installation and real playback have not been independently validated. Prefer a Windows version still receiving support. |
| Windows ARM64 | No native package; x64 emulation is unverified. |
| 32-bit Windows, Windows 7/8.1, S Mode | Outside the current release and validation scope. |

CPU can run faster-whisper and NLLB. Qwen3-ASR depends on hardware and drivers supported by its Vulkan runtime; CTranslate2 NVIDIA mode uses CUDA 12 libraries. Launching successfully and sustaining multiple real-time sessions are different tests. See [performance](performance.md).

## Source fallback and upgrades

For source use, install Python 3.11+, FFmpeg and ffprobe, then run `Subtitle Relay.pyw`. See [contributing](contributing.md) for commands.

Both installer and portable editions store settings, models and subtitle caches under `%LOCALAPPDATA%\Subtitle Relay`. Exit the resident helper from the tray before replacing application files. Existing settings and caches survive upgrades.

Both variants include `cli/aheadsubs.exe`. Use the desktop Integrations page to install CLI access or copy MCP configuration. See [Agent integrations](automation.md).
