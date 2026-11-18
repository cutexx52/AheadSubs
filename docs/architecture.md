# Architecture and module boundaries

[English](architecture.md) | [简体中文](architecture.zh-CN.md)

AheadSubs uses the player's current position to prepare upcoming subtitles. Audio is extracted per task; only one ASR segment is encoded to WAV at a time, then released. Neighboring transcript reuse is bounded and expires after playback becomes idle. Cues persist in SQLite; completed segments stream into SRT, while polling reads only records near playback.

```text
PotPlayer / mpv                 Windows desktop helper
        |                             | settings, start/stop
        | IPv4 loopback HTTP v1       |
        v                             v
               Service, sessions, cache
                       | scheduled chunks
                       v
             FFmpeg -> VAD -> ASR -> translation
                       | original media timestamps
                       v
                      SRT
```

| Package / directory | Responsibility | Extension point |
| --- | --- | --- |
| `aheadsubs/adapters/` | Playback state and subtitle loading; separate Win32 / mpv IPC adapters | `state()` / `publish(path, revision)`, or HTTP v1 |
| `aheadsubs/server/` | HTTP, sessions, scheduling, cache and SRT | `Playback`, `Relay.update()` / `drop()` and [HTTP v1](server.md) |
| `aheadsubs/inference/` | Segmentation, recognition and translation | [Provider interfaces](providers.md#provider-interfaces) |
| `aheadsubs/desktop/` | Control bridge, service lifecycle, PotPlayer callbacks and source fallback UI | [Desktop guide](desktop.md) |
| `desktop/` | WPF settings UI and Windows tray | Python runtime through the desktop bridge |
| `aheadsubs/automation.py` | Shared MCP/CLI operations and argument models | [Automation](automation.md) |
| `aheadsubs/client.py` | Shared desktop/player/automation loopback client | `RelayClient(port).send(route, data)` |
| `integrations/` | Player-hosted Lua / AngelScript | [Player integrations](adapters.md) |
| `aheadsubs/__main__.py` | CLI commands and runtime assembly | `python -m aheadsubs --help` |

Players supply media position and audio track. The service reads the file as needed and emits SRT on the original timeline. Adapters and service can run independently from the CLI, and tests can use a simulated playhead.

One service shares model instances and bounds in-flight chunks. Each window owns a session. Identical media, audio track and processing configuration can share cached results. Sessions expire after stopping or disconnecting; completed disk caches remain reusable. Service shutdown also stops local inference processes it owns.

Add players through the existing protocol and models through provider interfaces. Players need not know about models, VAD or credentials. Browser and other non-file sources first need a media-input and timestamp contract before reusing segmentation and translation. MCP and CLI share operation models in `automation.py`; HTTP remains available for direct integrations.
