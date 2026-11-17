# Subtitle Relay local protocol v1

See the maintained [HTTP v1 contract](docs/server.md) for current client behavior, error codes and authenticated shutdown. This original reference remains available for existing links.

The service listens on IPv4 loopback, port 8769 by default. The player and service share a filesystem. All times are seconds on the original media timeline.

## Player → service

`POST /v1/playback` with `Content-Type: application/json`

```json
{
  "session": "player-window-unique-id",
  "path": "E:/Video/clip.mkv",
  "audio": 0,
  "position": 71.2,
  "duration": 1640.4,
  "speed": 1,
  "source": "ja",
  "target": "zh",
  "ahead": 20
}
```

Only `session`, `path` and `position` are required. The path may be a local disk file or an accessible Windows share (UNC). Audio is the zero-based embedded FFmpeg audio-stream ordinal, not the player's track ID. An omitted or null source enables detection. Each window sends playback updates about twice per second. A new path, track, language, or a discontinuous position supersedes that window's earlier scheduling preferences. A session expires after 10 seconds without updates.

Reply:

```json
{
  "revision": 5,
  "subtitle": "E:/relay/cache/example.srt",
  "ready_ahead": 16.8,
  "nearby_cues": true,
  "error": null
}
```

Before any coverage is available, `revision` is zero and `subtitle` is null. Treat the version as the tuple of subtitle path and revision. A nonzero revision may initially describe only silence. Load once text exists, then reload on revision changes. Preserve player time and avoid changing focus. `ready_ahead` measures continuous completed media coverage starting at the supplied position, including silence. It can shrink when the window seeks or changes file. `nearby_cues` indicates whether that coverage contains a subtitle cue that has not ended at the supplied position.

`POST /v1/close` with `{"session":"player-window-unique-id"}` releases a session. `GET /v1/health` checks service readiness.

## Text-only PotPlayer extension

`POST /v1/text` uses `Content-Type: application/x-subtitle-relay` and URL-encoded `source`, `target`, and `text` fields. The response contains a `translation` string. This route uses the same configured text translation provider and has no media timeline. It does not require provider keys in the player extension.
