# Player integrations

[English](adapters.md) | [简体中文](adapters.zh-CN.md)

In Players (播放器), use One-click setup (一键配置) or One-click uninstall (一键卸载). If detection fails, choose a location; Change location (更改位置) supports portable installs. Choose PotPlayer's installation directory or mpv's configuration directory / directory containing `portable_config`. Restart the player afterwards.

Fresh player setup installs AheadSubs-named scripts. If an existing integration is present, one-click setup updates its installed filenames in place so player configuration and menus keep pointing to one copy.

## PotPlayer

With the background service running, press **Ctrl+Alt+J** in a playing PotPlayer window to start look-ahead, or **Ctrl+Alt+K** to stop. Each window is independent. Reloading subtitles preserves playback time; an upper-left notification confirms the operation. The adapter normally polls every 600 ms, temporarily using 150 ms after a seek.

The service needs a readable file path. The adapter first locates an open file using the title's filename, then searches directories confirmed for that window. If unresolved, it asks you to select the playing file. Hotkeys use the first embedded audio track and the helper's source, target and bilingual settings. For another track or manual binding, see `python -m aheadsubs potplayer --help` and `python -m aheadsubs potplayer-open --help`.

Mouse controls are available from the Windows tray: PotPlayer look-ahead (PotPlayer 预读) → start / stop; choose a window when several are open. The helper can also install AngelScript extensions. Under PotPlayer's subtitle → real-time subtitle translation menu, choose **AheadSubs - Start audio pre-read** or **AheadSubs - Stop audio pre-read**, then confirm the extension's login dialog. When displaying generated bilingual subtitles, leave PotPlayer's real-time translation condition disabled (不使用) so the two lines are shown unchanged. **AheadSubs (local service)** translates existing subtitle text through [`/v1/text`](server.md#text-translation).

## mpv

mpv 0.42+ can load `integrations/mpv/aheadsubs.lua` in its native right-click menu. Use One-click setup, choose the configuration directory, restart mpv, then enable AheadSubs in the menu. For portable installs choose `portable_config`. The menu includes source/target languages and look-ahead duration.

The standalone IPC adapter is also available from the CLI. Give each window a different pipe name.

```cmd
mpv.exe --input-ipc-server=relay-window-1 D:\video\clip.mkv
python -m aheadsubs mpv relay-window-1 --source ja --target zh --ahead 20
```

## Adding an adapter

The shared Python loop `run_adapter()` accepts a player object implementing:

| Method | Contract |
| --- | --- |
| `state()` | Return `path` and `position`, plus `audio`, `duration` and `speed` when available. Return `None` before readiness. Positions are seconds on the original media timeline. |
| `publish(path, revision)` | Load that SRT in the current window. Deduplicate with `(path, revision)` and wait for actual subtitle text before the initial load. |

Update the same window's session when media, track, language or position changes. Release it when the player exits or the user stops. Non-Python adapters can use [HTTP v1](server.md) directly. To test the service without a player, run `python -m aheadsubs clock D:\video\clip.mkv --position 45 --target zh`; add `--realtime` for a moving playhead.
