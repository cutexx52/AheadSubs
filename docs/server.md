# Background HTTP v1 API

[English](server.md) | [简体中文](server.zh-CN.md)

The service binds to `127.0.0.1:8769` for local clients by default. Service and player must share media access. All times are seconds on the original media timeline.

Start with `python -m subtitle_relay serve --asr local --mt local --device cpu`. Clients must match any custom `--port`.

## File transcription API

Use `python -m subtitle_relay serve --asr local --mt none --device cpu` for a recognition-only service. File transcription never invokes either translation backend, including when a combined profile supplies the recognizer. The `--ast` speech-translation profile has no recognizer for these routes. With `--mt none`, playback captions contain source text.

The file routes accept multipart uploads and recognize the first audio stream. Omit `language` for automatic recognition of the source speech, including mixed-language speech. An explicit language is a recognition hint. Recognition quality and language coverage depend on the configured model. Choosing a cloud recognizer sends audio segments to that provider. The file routes use the shared worker pool and yield between chunks to playback and folder subtitle work.

Only one service instance manages transcription jobs per cache directory. Use a distinct `--cache` for each simultaneous transcription service.

Use `127.0.0.1` or `localhost` with the service port. The file routes reject browser requests and never accept a server-side path or URL. The playback routes below have a separate local-path contract. Transcription trusts native processes on the same machine. Keep job IDs private because they grant access to job state, controls and results.

### Durable jobs

Send `X-AheadSubs-Transcription: 1` on each request. Replace `{id}` with the returned job ID.

| Request | Contract |
| --- | --- |
| `GET /v1/transcription/capabilities` | Reports backend availability, model alias, segment timestamps, response formats and limits. |
| `POST /v1/transcription/jobs` | Multipart `file` and optional `language` (`auto` or a language code). Returns `202`, a `Location` header and job state. |
| `GET /v1/transcription/jobs/{id}` | Returns `id`, `state`, `duration`, requested `language` (`null` for automatic), `completed_chunks`, `total_chunks` and `error_code`. |
| `GET /v1/transcription/jobs/{id}/result` | Returns the completed result. A pending, failed or cancelled job returns `409`. |
| `POST /v1/transcription/jobs/{id}/cancel` | Cancels queued or running work. A chunk already in inference may finish, and its cancelled result is discarded. |
| `POST /v1/transcription/jobs/{id}/resume` | Requeues a failed or cancelled job using its retained input and completed chunks. An outstanding cancelled chunk returns `409` until it finishes. Use the same recognition settings. |
| `DELETE /v1/transcription/jobs/{id}` | Discards the job, retained input and result. Returns `204`. |

```powershell
curl.exe -H "X-AheadSubs-Transcription: 1" -F "file=@recording.wav" http://127.0.0.1:8769/v1/transcription/jobs
```

```json
{
  "duration": 2.7,
  "text": "Good morning.",
  "segments": [{"start": 0.2, "end": 1.4, "text": "Good morning."}]
}
```

Segment times are in seconds from the start of the uploaded audio. They preserve the backend's bounds and overlaps, with the chunk offset applied. A segment carries `language` only when the backend supplies that segment's language. Word timing, speaker labels and confidence are unavailable. Subtitle display padding is applied independently when rendering SRT. An upload with no recognized speech completes with empty `text` and `segments`.

States are `queued`, `running`, `completed`, `failed` and `cancelled`. Queued and interrupted work can continue after a service restart. Completed inputs are removed. Periodic cleanup removes failed or cancelled inputs and completed results after 24 hours or when there are more than 100 terminal jobs. The durable queue and synchronous requests share up to eight retained inputs and 512 MB of normalized input storage.

### OpenAI-compatible file uploads

`POST /v1/audio/transcriptions` accepts multipart `file`, `model=aheadsubs`, optional two-letter `language`, optional `response_format=json` (default) or `text`, and optional `stream=false`. `aheadsubs` selects the configured recognizer. Send a nonempty Bearer value as required by SDKs, such as `local`. That value is for client compatibility and is not a server credential. JSON returns `{"text":"…"}` and `text` returns UTF-8 plain text. Errors use the OpenAI error envelope. Other models, fields and formats are rejected. Use the durable result endpoint for segment timing.

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8769/v1", api_key="local", max_retries=0)
with open("recording.wav", "rb") as audio:
    result = client.audio.transcriptions.create(model="aheadsubs", file=audio)
print(result.text)
```

Pipecat's segmented HTTP `OpenAISTTService` can use the same base URL, model and API key with probability metrics disabled and no prompt, temperature or keywords. Choose an input language that Pipecat supports. Realtime streaming and diarization are outside this file contract.

Both upload routes accept up to 25 MB of WAV, MP3, FLAC, AAC, Ogg/Opus, MP4/M4A/MOV or Matroska/WebM. The decoder needs FFmpeg with its `fd` protocol, included in the Windows runtime. Decoded audio is limited to two hours for durable jobs and 15 minutes for synchronous files. Up to two upload requests can be active, including synchronous waits. File transfer is limited to 30 seconds and decoding to 60 seconds. The synchronous wait ends after 180 seconds and discards its temporary job. Oversize input returns `413`, undecodable audio `415`, and exhausted capacity `429`. Use durable jobs for files whose processing might exceed the synchronous wait.

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

SQLite stores completed chunks. Identity includes media and modification time, track, languages and processing settings. Matching windows share completed chunks. SRT uses batched atomic replacement. CLI cache defaults to `.relay`; desktop uses `%LOCALAPPDATA%\Subtitle Relay\cache`.
