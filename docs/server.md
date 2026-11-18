# Background HTTP v1 API

[English](server.md) | [简体中文](server.zh-CN.md)

The service binds to `127.0.0.1:8769` for local clients by default. Service and player must share media access. All times are seconds on the original media timeline.

Start with `python -m aheadsubs serve --asr local --mt local --device cpu`. Clients must match any custom `--port`.

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
| `GET /v1/health` | Returns `service`, `pid`, `active_sessions`, `local_models`. The count covers external playback sessions. Local model IDs let the desktop protect models currently in use. |
| `GET /v1/status` | Returns live status and weekly cloud totals. Send `X-AheadSubs-Status: 1`. Requests with `Origin` return `403`. The response uses `Cache-Control: no-store`. |
| `POST /v1/close` | JSON `{"session":"window-1"}` releases a session; success returns `{}`. |
| `POST /v1/shutdown` | JSON `{"token":"…"}` stops the service, requiring the startup control token. |
| `POST /v1/inspection/regenerate` | Desktop control sends JSON `{"token":"…","key":"…"}` with the startup token and a local cache version key. Success returns `202` and the new version's `key`. A rejected job returns `409` with `error_code`. |

POST requests with `Origin` are rejected. Ordinary bodies are limited to 32 KiB; text translation allows 50 KiB for URL-encoded Unicode. Common statuses: invalid input `400`, unauthorized `403`, temporarily busy `503`.

<a id="文本翻译"></a>

## Text translation

`POST /v1/text` uses `Content-Type: application/x-subtitle-relay` with URL-encoded `source`, `target`, `text`. Text is limited to 4000 characters. Success returns `{"translation":"…"}`; no translator returns `409`; provider failure returns `502` with `error` and `error_code`. This translates existing text without a media timeline.

## Status metrics

`/v1/playback` and `/v1/text` accept an optional `X-AheadSubs-Entry` header for grouping. Values are `potplayer`, `mpv`, `cli`, `mcp` and `http`. The legacy PotPlayer text and mpv integrations are recognized by their existing identifiers. Other clients with an absent or unrecognized entry are grouped as `http`. Playback sessions drop from the snapshot on close or after 10 seconds without updates. Text requests count while being handled.

| Field | Meaning |
| --- | --- |
| `ready`, `models` | The endpoint is available after initialization. A bundled Qwen3-ASR health check can set `ready` to false. Each model shows its `operation`, `model`, `device` and `state`. External loopback services have an unknown load state, and cloud models show whether they are configured. |
| `active_sessions`, `sources`, `workers` | Active playback count, playback and text counts by entry, and worker slots currently busy and available in total. |
| `resources` | CPU as a percentage of all logical cores, working-set bytes, busiest GPU engine percentage, and dedicated GPU memory bytes for the service process tree. Fields may be null or absent during initialization or when counters are unsupported. Externally managed services are outside this scope. |
| `performance.rtf`, `performance.latency` | Up to 1,024 samples each in the last 15 minutes. Each returns `count` and nearest-rank `p50`, `p95`, `p99`, with null percentiles when no samples are available. |
| `cloud` | Monday dates in UTC (`weeks`), totals by week/provider/model/operation (`rows`), and `incomplete` when the totals may be missing data. Each row provides calls, failures, known input/output tokens and audio seconds, priced calls, and estimated USD cost. |

RTF divides successful chunk processing time by the actual audio duration in its owned media window. It includes extraction, VAD, recognition and translation, excluding scheduling and cache writes. Latency measures from the first playback update waiting for a new chunk until a subsequent response reports usable subtitles within the same playback chunk. It includes the player's polling interval. Immediate cache hits, abandoned waits after seeks or file changes, and rendering inside the player are excluded. Percentiles may match when sample counts are small.

Cloud usage starts with this version. The model request boundary counts attempts and groups automatic SDK retries into the same call. Costs use observed tokens or audio duration and built-in public USD list prices at request time. Estimates cover Whisper, GPT-4.1 mini, GPT-6 Luna, MiniMax M3.1 Flash pay-as-you-go, and the bundled Alibaba Model Studio ASR and translation models in Beijing and Singapore. Taxes, discounts, free quotas, retries, rounding and billing plans can change the actual charge. ChatGPT subscriptions, MiniMax M Plan (`minimax_plan`) and compatible endpoints with unknown rates report calls and known usage. [Whisper pricing](https://developers.openai.com/api/docs/models/whisper-1) · [GPT-4.1 mini pricing](https://developers.openai.com/api/docs/models/gpt-4.1-mini) · [GPT-6 Luna pricing](https://developers.openai.com/api/docs/models/gpt-6-luna) · [MiniMax pricing](https://www.minimax.io/blog/minimax-m31f) · [Alibaba Model Studio pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing)

## Internal API and cache

`Relay.update(identifier, Playback)` accepts state and returns subtitle metadata. `Relay.drop(identifier)` releases a session; `Relay.close()` closes scheduling/persistence. Tasks read the selected track and retain its offset, mapping ASR-relative times back to video time. Overlapping adjacent cues preserve the next cue's start and end the preceding cue there.

SQLite stores completed chunks. Identity includes media and modification time, track, languages and processing settings. Matching windows share completed chunks. SRT uses batched atomic replacement. CLI cache defaults to `.relay`. The desktop service uses the `cache` subdirectory of the [Windows user data directory](windows.md).
