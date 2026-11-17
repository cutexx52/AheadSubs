# Early validation record

[English](VALIDATION.md) | [简体中文](VALIDATION.zh-CN.md)

Current presets, RTX 4090 concurrency and reproduction commands are in [performance](docs/performance.md). This historical record covers synthetic media and player integration.

Machine: Windows, RTX 4090 24 GB. Inputs were Windows SAPI speech and FFmpeg-generated black video only.

| Check | Observed result |
| --- | --- |
| Shared GPU service | faster-whisper Small + NLLB 600M INT8 in one process, four independent paths, empty cache, 45 s moving playheads. Prebuffer 4.28 s; minimum ready-ahead values 18.66, 18.99, 18.78, 18.66 s; no exhaustion samples. Inputs were independent copies of one synthetic WAV, with no shared tasks/cache. |
| mpv 0.42.0 | Native context menu loaded; controls started background work and Chinese SRT. Seeking to unprocessed time loaded updates and returned the corresponding Chinese cue. |
| Four real mpv windows | Independent synthetic MP4s, prebuffered and played to about 20.1 s. All read the current Chinese cue; minima 10.7, 11.4, 12.1, 10.5 s, no exhaustion. Includes playback, IPC and SRT reload. |
| PotPlayer 261021 | Two real windows returned independent positions. Native DLL menu resources identified reload; replacing SRT and sending the command showed new text in screenshots. Adapter-prebuffered playback showed generated Chinese subtitles. Both native translation entries appeared; audio look-ahead opened settings. |
| OpenAI ASR/translation | Synthetic speech through whisper-1 and gpt-4.1-mini produced timestamped Chinese SRT. Direct English speech translation returned valid start/end times. |
| Disk cache | Two windows requesting one interval processed it once; restarting reused the subtitle version. |
| GUI helper | Started the local service through Windows GUI and showed readiness. |
| Existing PotPlayer window | Translation extension triggered look-ahead; when the player supplied only a filename, the adapter found the open video and delivered SRT. Single-file drag/drop messages also displayed subtitles. |

Four-session figures measure synthetic-speech pipeline throughput. Real films with music, mixed languages, translation quality and long runs require separate evaluation. Look-ahead is a scheduling target; actual coverage depends on recognition, requests, pauses, speed and seeks. Subtitle timing is segment-level; translated word order may differ from speech.
