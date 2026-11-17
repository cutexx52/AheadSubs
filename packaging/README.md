# Windows release engineering

[English](README.md) | [简体中文](README.zh-CN.md)

The Windows build combines a private CPython 3.11 runtime, Tcl/Tk for the fallback UI and PotPlayer status overlay, the optional self-contained WPF desktop, FFmpeg/FFprobe, and the Relay packages. The distribution stays independent of the builder's `.venv`, credentials, and model caches.

## Build locally

Use Windows x64 and a complete x64 CPython 3.11 installation that includes Tcl/Tk. Use the .NET 10 SDK for the WPF build. Install [MSYS2](https://www.msys2.org/) and run `pacman -S --needed diffutils make mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-nasm` in UCRT64. The build downloads the runtime `libwinpthread` DLL and its matching source from pinned archives. For the installer, use Inno Setup 7 or let the script download the pinned compiler into the build cache.

```bat
python packaging\windows\build.py --native --version 0.1.0
python packaging\windows\build.py --native --cuda --version 0.1.0
```

`--msys2` overrides the default `C:\msys64` installation. `--dotnet` and `--iscc` accept executable paths. Omit `--native` for the Tk fallback build or use `--portable-only` to skip Inno. Each build stages under `dist`, verifies pinned downloads and smoke-tests with a system-only `PATH`. The media check probes two audio tracks and tests resampling, timestamp preservation and the Whisper PCM interface. `--verify-install` additionally tests installation, removal of legacy PyAV files and uninstallation in a profile without an installed app.

Repeat builds reuse the private Python runtime and FFmpeg build under `.relay/packaging-tools` when their inputs match. The first FFmpeg build requires a full native compile. Player integrations, UI and Python application sources are staged anew on every build. The builder replaces release files only after verification succeeds.

The standard artifacts use names such as `aheadsubs-v0.1.0-windows-x64-setup.exe` and `aheadsubs-v0.1.0-windows-x64-portable.zip`, with a matching `-SHA256.txt`. The CUDA flavor adds `-cuda` before the artifact suffix and brings its own CUDA math libraries. The machine still needs a compatible graphics driver for GPU inference. Both variants refer to the same `-ffmpeg-source.zip`, which accompanies the binaries when redistributing them. Launch `AheadSubs.exe` from the portable archive's application directory.

## Release and support scope

The native desktop carries version/flavor metadata. The updater identifies installed copies through Inno Setup registration and selects matching latest-stable assets. Keep asset names and installer ID stable. Installer size and SHA-256 digest are validated against GitHub asset metadata over HTTPS. See [Windows updates](../docs/windows.md#check-for-updates).

- Windows bundles checks daily for eligible previews (72-hour interval, relevant changes, current-head CI). Manual `mode=verify` builds both flavors without publishing or retaining artifacts. `mode=preview` checks eligibility on the default branch. Pushing `v*` tags publishes explicit releases after verification. Publication requires four binaries, two manifests and the corresponding FFmpeg source ZIP. Tags containing `-` are prereleases. See [release policy and budget](../docs/releases.md).
- Windows 11 x64 is the primary verification target. Windows 10 22H2 x64 is the installer minimum, with separate validation needed on each supported edition. Windows 10 editions already at end of support remain outside Microsoft's support lifecycle. Windows on Arm, 32-bit Windows, Windows 7/8.1 and S Mode are outside the validated path. See the [.NET 10 platform matrix](https://learn.microsoft.com/en-us/dotnet/core/install/windows#supported-versions).
- The installer is per-user and keeps settings and model data under the existing `%LOCALAPPDATA%\Subtitle Relay` path. The standard and CUDA installers update the same application installation. Model weights and credentials are acquired independently of packaging.
- Native inference wheels can require the [Microsoft Visual C++ Redistributable x64](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist). The launcher links to Microsoft's download if the runtime is missing.
- The local build creates unsigned artifacts. `notices/ffmpeg` records the bundled LGPL build, exact source versions and replacement instructions. Keep the FFmpeg source ZIP and its checksum available from the same release as the binaries. See [licenses and redistribution](../docs/licenses.md) for other component obligations.
