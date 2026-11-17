# Performance and hardware

[English](performance.md) | [简体中文](performance.zh-CN.md)

## Starting configurations

| Hardware | Try first | Evidence |
| --- | --- | --- |
| CPU, no usable GPU | Whisper Small + NLLB 600M INT8 on CPU | One session tested on i9-13900KF; start with one on other CPUs. |
| Vulkan GPU with limited VRAM | Qwen3-ASR 0.6B + NLLB 600M | GPU recognition + CPU translation tested on RTX 4090; entry-level GPU concurrency unmeasured. |
| RTX 4090 24 GB | Qwen3-ASR 1.7B Q4_K + NLLB 600M INT8 | Four sessions with defaults tested on a public Japanese sample. |

Model file size is not VRAM usage: alignment, runtimes and concurrent buffers add overhead. Test one session on your own media before increasing window count.

## RTX 4090 measurements

| Test | Conditions | Observation |
| --- | --- | --- |
| Lightweight local, 4 sessions | Qwen 0.6B + NLLB, 20 s | Minimum ready ahead about 18.7 s; zero sampled exhaustion |
| Starter preset, 4 sessions | Qwen 0.6B Vulkan + CPU NLLB, default 4 workers, 25 s | Target reached in 3.77 s; minimum 18.45 s; zero exhaustion |
| CPU fallback, 1 session | i9-13900KF, Whisper Small + NLLB CPU INT8, 25 s | Target reached in 2.95 s; minimum 17.69 s; zero exhaustion |
| Fully local, 4 sessions | Qwen 1.7B Q4_K + NLLB 600M INT8, default 4 workers, 45 s | Target reached in 4.81 s; minimum 18.17 s; zero exhaustion |
| Fully local, 8 sessions | Same models, 12 workers, 35 s | Minimum 16.61 s; zero exhaustion |
| Fully local, 12 sessions | Same models, 12 workers, 35 s | Minimum 16.25 s; zero exhaustion |
| PotPlayer uncached seek | Qwen 1.7B + Silero v6 + Qwen-MT Flash; two warmed rounds, 6 seeks each | Median subtitle delivery 1.17 / 1.34 s; range 0.99–1.66 s |
| Single ASR | Warm Qwen 1.7B Q4_K + Vulkan alignment; about 10 s audio, 6 runs | Median RTF 0.0244; recognition + alignment about 0.24–0.26 s |

Concurrency tests used different-path copies of one public Japanese sample, independent tasks and simulated constant-speed playheads, targeting 20 seconds ahead. Seek measurements include position, extraction, recognition, translation and SRT delivery, not final screen painting. Dialogue density, background sound, other GPU apps, network, speed and seeks affect results. Short 12-session tests are not long-run guarantees.

The starter preset, CPU fallback, 1.7B four-session setup and PotPlayer seeks were retested with current pause segmentation. The 20-second lightweight four-session and 8–12-session results predate that change.

RTF is processing time / audio duration. ASR-only RTF excludes FFmpeg, translation, scheduling, cache writes and the player.

A synthetic persistence test generated 10,000 cues into about 1.95 MiB SRT. `tracemalloc` observed about 33 KiB peak Python allocations. This measures subtitle generation only, excluding native SQLite allocation, models and the process working set.

## Reproduce

Use an empty service cache and the target models/worker count. Supply distinct paths, each at least 20 seconds longer than the test.

```cmd
python tools\benchmark.py --seconds 45 clip1.wav clip2.wav clip3.wav clip4.wav
python tools\mpv_smoke.py C:\path\mpv.exe clip1.mp4 clip2.mp4 clip3.mp4 clip4.mp4
```

Wait for the target buffer, then compare minimum ready ahead and exhaustion samples. Record GPU, OS, providers, workers, codec/track, duration and cache-hit state. Earlier tests: [VALIDATION.md](../VALIDATION.md).
