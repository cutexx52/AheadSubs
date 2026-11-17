# Windows release engineering

[English](README.md) | [简体中文](README.zh-CN.md)

The Windows build combines a private CPython 3.11 runtime, Tcl/Tk for the fallback UI and PotPlayer status overlay, the optional self-contained WPF desktop, FFmpeg/FFprobe, and the Relay packages. The distribution stays independent of the builder's `.venv`, credentials, and model caches.

## Build locally

Use Windows x64 and a complete x64 CPython 3.11 installation that includes Tcl/Tk. Use the .NET 10 SDK for the WPF build. For the installer, either use Inno Setup 7 or let the script download and install the pinned compiler under `.relay/packaging-tools` for the current user.

```bat
python packaging\windows\build.py --native --version 0.1.0
python packaging\windows\build.py --native --cuda --version 0.1.0
```

`--dotnet` and `--iscc` accept explicit executable paths. Omit `--native` for the Tk fallback build. Use `--portable-only` to skip the Inno toolchain. Each build stages in a temporary directory inside `dist`, checks the pinned FFmpeg and Inno hashes and tests the private runtime with a system-only `PATH`. Smoke checks cover native Python dependencies, Tcl/Tk, the `aheadsubs.exe` launcher, MCP initialization and a tool call, desktop bridge JSON, and FFmpeg/FFprobe. `--verify-install` additionally installs, verifies and uninstalls a test copy in a profile without an installed app.

Repeat builds reuse the private Python runtime under `.relay/packaging-tools` only when the Python binary and pinned dependency inputs match. Player integrations, UI and Python application sources are staged anew on every build. The builder replaces release files only after its verification steps pass.

The standard artifacts use names such as `aheadsubs-v0.1.0-windows-x64-setup.exe` and `aheadsubs-v0.1.0-windows-x64-portable.zip`, with a matching `-SHA256.txt`. The CUDA flavor adds `-cuda` before the artifact suffix and brings its own CUDA math libraries. The machine still needs a compatible graphics driver for GPU inference. The `.zip` contains one application directory. Launch `AheadSubs.exe` from that directory.

## Release and support scope

The native desktop carries version/flavor metadata. The updater identifies installed copies through Inno Setup registration and selects matching latest-stable assets. Keep asset names and installer ID stable. Installer size and SHA-256 digest are validated against GitHub asset metadata over HTTPS. See [Windows updates](../docs/windows.md#check-for-updates).

- Windows bundles checks daily for eligible previews (72-hour interval, relevant changes, current-head CI). Manual `mode=verify` builds both flavors without publishing or retaining artifacts; `mode=preview` checks eligibility on the default branch. Pushing `v*` tags publishes explicit releases after both builds pass. Files upload directly to a draft Release; all four binaries and two manifests must be complete before publication. Tags containing `-` are prereleases. See [release policy and budget](../docs/releases.md).
- Windows 11 x64 is the primary verification target. Windows 10 22H2 x64 is the installer minimum, with separate validation needed on each supported edition. Windows 10 editions already at end of support remain outside Microsoft's support lifecycle. Windows on Arm, 32-bit Windows, Windows 7/8.1 and S Mode are outside the validated path. See the [.NET 10 platform matrix](https://learn.microsoft.com/en-us/dotnet/core/install/windows#supported-versions) and [FFmpeg distribution support notes](https://github.com/FFmpeg-Builds/FFmpeg-Builds).
- The installer is per-user and keeps settings and model data under the existing `%LOCALAPPDATA%\Subtitle Relay` path. The standard and CUDA installers update the same application installation. Model weights and credentials are acquired independently of packaging.
- Native inference wheels can require the [Microsoft Visual C++ Redistributable x64](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist). The launcher links to Microsoft's download if the runtime is missing.
- The local build creates unsigned artifacts. Before public redistribution, review all third-party terms and corresponding-source obligations for the bundled LGPL shared FFmpeg build and optional NVIDIA runtime. The archive carries the upstream FFmpeg notice, binary hash, source/build links, Python license and wheel metadata. Keep applicable notices and corresponding source available alongside published binaries. Review the [FFmpeg license guide](https://ffmpeg.org/legal.html) for upstream expectations.
