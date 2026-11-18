# Original AheadSubs design and acceptance plan

[English](PLAN.md) | [简体中文](PLAN.zh-CN.md)

Historical design record, not the current delivery policy. See [architecture](docs/architecture.md), [performance](docs/performance.md) and the current [PR-to-merge workflow](docs/contributing.md).

## 1. Player protocol

- Local HTTP JSON v1; one session per window with absolute path, track, position, speed and languages. Expire disconnected sessions; refresh by subtitle path/version.
- Test services with simulated playback and adapters with simulated subtitles. Player changes stay in adapters.
- mpv uses JSON IPC or Lua; the 0.42 native menu exposes start/stop, language, look-ahead and settings.
- Validate PotPlayer Win32 messages and reload. If AngelScript translation receives current text only, expose text translation through the native list and use the helper for audio look-ahead; document actual automation steps.

## 2. Media timeline and speech boundaries

- Read the selected track with FFmpeg, retaining media time and configurable coverage ahead.
- Use bounded context for dialogue crossing chunks; configure chunk/context lengths, pauses, padding and segment limits. Detect speech with VAD, prefer natural pauses and split long speech at the limit.
- Preserve recognized start/end times, map from audio offsets, and translate by subtitle identity. Record silence coverage too.
- Handle duplicates, long silence, tracks, file updates and seeks. Stable chunk keys index source/translation; atomically replace SRT for original-time playback.

## 3. Inference and concurrency

- Interfaces cover timestamped ASR, direct speech translation and text translation. Initial local path: faster-whisper / CTranslate2 + NLLB. Initial OpenAI path: whisper-1 timestamps + small GPT translation; direct English audio translation and compatible Ollama/LM Studio text endpoints are alternatives.
- One service shares GPU models and bounds workers/in-flight jobs. Prioritize the earliest playback gaps; share cache for matching media/track/settings. Keep cloud credentials outside Git.
- Evaluate Pipecat streaming providers after local/cloud paths; unified timestamps keep that work independent.

## 4. Minimal operation

- Configure a preset and player entry in the helper; then enable from mpv's context menu with on-demand service startup.
- Validate PotPlayer existing-text translation, audio look-ahead without subtitles and reload separately. Distinguish first-install steps from daily use; document unavoidable manual steps honestly.
- Expose configuration errors, model preparation, buffering and cloud mode. Default to local providers.

## 5. Original acceptance checklist

- Unit/integration coverage: segmentation, shared cache hits, four sessions, seeking, restart reuse and SRT updates.
- Synthetic media verifies mpv state, subtitle loading and seek-time text.
- Synthetic speech verifies OpenAI ASR/GPT Chinese SRT and English direct speech translation; no keys/test caches in Git.
- RTX 4090: four independent files, empty cache, moving playheads; record buffering, minimum coverage, exhaustion, models, segmentation, duration and limitations.
- Record GUI tests, dual PotPlayer windows and known limits. The original plan ended with local Git and deferred GitHub publication; this is superseded by the current mandatory PR-to-merge workflow.
