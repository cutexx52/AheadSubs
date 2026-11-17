# Background HTTP v1 API

[English](server.md) | [简体中文](server.zh-CN.md)

The service binds to `127.0.0.1:8769` for local clients by default. Service and player must share media access. All times are seconds on the original media timeline.

Start with `python -m subtitle_relay serve --asr local --mt local --device cpu`. Clients must match any custom `--port`.

## Update playback

`POST /v1/playback`, `Content-Type: application/json`.

```json
{
  "session": "window-1",
  "path": "E:/Video/clip.mkv",
  "audio": 0,
  "position": 71.2,
  "duration": 1640.4,
  "speed": 1,
  "source": "ja",
  "target": "zh",
  "ahead": 20,
  "bilingual": false
}
```

| Field | Contract |
| --- | --- |
| `session` | Required, 1–100 characters, unique per window. Expires after 10 seconds without updates. |
| `path` | Required absolute media path accessible to the service, local or shared. |
| `position` | Required nonnegative media time, at most 10 million seconds. |
| `audio` | Optional, default `0`: zero-based FFmpeg embedded audio-stream ordinal. |
| `duration` | Optional positive total duration. |
| `speed` | Optional, default `1`, range `0.1–5`. |
| `source` / `target` | Omitted values use service settings: by default detect source and output `zh`. Explicit `source: null` forces detection. Languages depend on the provider. |
| `ahead` | Optional, default `20`, range `1–120` seconds. |
| `bilingual` | Optional, defaults to startup settings. When true, prefixed source text appears above translation. |

Example response:

```json
{
  "revision": 5,
  "subtitle": "E:/relay/cache/example.srt",
  "subtitle_generation": "example",
  "subtitle_has_cues": true,
  "ready_ahead": 16.8,
  "nearby_cues": true,
  "error": null,
  "error_code": null
}
```

`revision` and `subtitle` jointly identify a version; initially they are `0` and `null`. `ready_ahead` is continuous completed coverage from the requested position, including silence. `nearby_cues` indicates an unended cue in nearby processed coverage. `error` describes the current chunk failure; `error_code` is a stable adapter-facing category. Sentence-level moderation blocks remain in inspection records. Seeking, track changes or new files can reduce ready-ahead coverage.

`subtitle_generation` changes when effective recognition, translation, timeline settings or bilingual display change—even before new cues exist. Players can remove old subtitles and await new results. Returning to identical processing settings can reuse their cache.

## Session and service control

| Request | Contract |
| --- | --- |
| `GET /v1/health` | Returns `service`, `pid`, `active_sessions`, `local_models`; local model IDs let the desktop protect models currently in use. |
| `POST /v1/close` | JSON `{"session":"window-1"}` releases a session; success returns `{}`. |
| `POST /v1/shutdown` | JSON `{"token":"…"}` stops the service, requiring the startup control token. |

POST requests with `Origin` are rejected. Ordinary bodies are limited to 32 KiB; text translation allows 50 KiB for URL-encoded Unicode. Common statuses: invalid input `400`, unauthorized `403`, temporarily busy `503`.

<a id="文本翻译"></a>

## Text translation

`POST /v1/text` uses `Content-Type: application/x-subtitle-relay` with URL-encoded `source`, `target`, `text`. Text is limited to 4000 characters. Success returns `{"translation":"…"}`; no translator returns `409`; provider failure returns `502` with `error` and `error_code`. This translates existing text without a media timeline.

## Internal API and cache

`Relay.update(identifier, Playback)` accepts state and returns subtitle metadata. `Relay.drop(identifier)` releases a session; `Relay.close()` closes scheduling/persistence. Tasks read the selected track and retain its offset, mapping ASR-relative times back to video time. Overlapping adjacent cues preserve the next cue's start and end the preceding cue there.

SQLite stores completed chunks. Identity includes media and modification time, track, languages and processing settings. Matching windows share completed chunks. SRT uses batched atomic replacement. CLI cache defaults to `.relay`; desktop uses `%LOCALAPPDATA%\Subtitle Relay\cache`.
