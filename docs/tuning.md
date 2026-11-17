# Tune recognition and subtitles

[English](tuning.md) | [简体中文](tuning.zh-CN.md)

Start in Subtitle inspection (字幕检查): select a video and compare timestamps, source and translation. The source is the ASR text passed to translation. Failures retain the original and show a reason. Incorrect source text calls for checking source language, speech detection and recognition first; correct source with poor translation calls for a different translator, context or prompt. Direct audio translation has no source text column.

Explicit provider moderation produces a moderation-block message. Per-sentence backends continue other sentences; batch backends identify only a blocked batch. Local NLLB makes no cloud translation requests. Apply a local configuration to generate under that configuration. [Alibaba Cloud error codes](https://help.aliyun.com/zh/model-studio/error-code/#inappropriate-content).

## Speech detection

| Setting | Default | Effect |
| --- | --- | --- |
| Detector | Silero v6 | Locates speech; FunASR FSMN-VAD is also available. |
| Threshold | Silero `0.50`, FSMN `0.80` | Lower retains quieter/distant speech but may include music/noise. Scores need not match across models. |
| Preferred pause | `450 ms` | Prefer gaps this long; otherwise choose the longest shorter pause before the limit. |
| Edge padding | `80 ms` | Preserve audio at both ends; adjacent planned segments do not overlap or each consume the entire pause. |
| Minimum segment target | `3 s` | Avoid fragmented continuous dialogue; isolated short speech and boundary leftovers still run. |
| Maximum ASR segment | `12 s` | Bound recognition input. Without a suitable pause, split at a low-energy point near the limit. |

Silero's internal minimum speech duration is `96 ms`; short-pause detection is about `64 ms`. In opt-in diagnostics, `speech_spans=0` means no speech was segmented; `asr_cues=0` means no cues were recognized. Adjust one setting at a time on the same sample.

## Look-ahead and seeking

| Setting | Default | Effect |
| --- | --- | --- |
| Scheduler chunk | `8 s` | Scheduling and cache-ownership interval. |
| Extra pause search before/after | `2 s` each | Expand VAD search beyond the longest speech segment; this entire range is not sent to ASR. |
| Minimum seek backfill | `4 s` | Include earlier tasks covering the seek target; long segments can expand this to half the maximum segment duration. |

Display extends about 0.6 seconds per side. Short cues aim for 1.4 seconds when space allows, extending at most 1 second per side. Adjacent dialogue shares free gaps only; continuous speech keeps its transitions. Inspection shows recognition timestamps. Display-only changes need no new recognition/translation.

## Translation context and bilingual display

Translation → Context enhancement (翻译 → 上下文增强) enables previous dialogue and prompts for supported models. Context counts recognized cues, 0–8, with a suggested default of 4. Zero uses only the prompt. Requests return current cues only and preserve timestamps. After a seek, fewer previous cues may be available. Cloud chat models receive those texts too. Example: “Use natural dialogue, preserve forms of address, and keep character names consistent.”

Each model saves its switch, count and prompt. Qwen-MT Flash / Plus support English style prompts; chat models support context and prompts. Qwen-MT Lite and NLLB remain segment-by-segment. Bilingual SRT reuses the cache: original above translation, prefixed with tags such as `[JP]` and `[CN]`. Detection uses the ASR language; old caches without one show `[原文]`. Display changes do not rerun inference.
