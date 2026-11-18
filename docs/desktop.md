# Windows desktop guide

[English](desktop.md) | [简体中文](desktop.zh-CN.md)

## Everyday use

In **App settings → Interface language**, choose **Follow Windows** (default) or a display language. Changes take effect immediately. The choices are Simplified Chinese, Traditional Chinese, Japanese, English, Korean, French, German and Spanish. Regional variants use the matching language (for example, French for Canada or Traditional Chinese for Hong Kong). Other Windows display languages fall back to English. The choice is saved for the current user and is independent of the video and subtitle languages.

Open **Setup presets** on the **Subtitles** home page. The control starts collapsed. Once you select a preset, **Download now** fetches the missing models. **Manage models** opens the library with the required downloads marked. When the preset is ready, select **Apply preset**. The audio language, subtitle language, and bilingual setting carry over. Manual model combinations appear as **Custom**.

| Preset | Speech recognition | Translation |
| --- | --- | --- |
| Local · CPU | Whisper Small on CPU | NLLB on CPU |
| Local · Entry GPU | Qwen3-ASR 0.6B on Vulkan | NLLB on CPU |
| Local · High-performance GPU | Qwen3-ASR 1.7B on Vulkan | NLLB on NVIDIA CUDA |
| Recommended · Local speech + cloud translation | Qwen3-ASR 1.7B on Vulkan | Qwen-MT Flash with a Bailian API key |

The GPU presets check for a Vulkan device. The high-performance preset also checks for an NVIDIA CUDA device and its runtime libraries. The recommended preset checks whether the saved Bailian credential is readable and the service URL is supported. Save a missing key in the Bailian configuration and return to the home page to check again. The provider verifies the credential when a request is sent. If a download fails, retry to reuse any models that finished downloading.

**Local models** groups speech recognition, translation, and voice activity detection. Whisper and NLLB have separate CPU/CUDA selectors. Use the main **Save and apply** action to apply device changes. Existing configurations use their previous device setting until a per-model setting is saved. Stop the subtitle service or switch models before uninstalling a model in use. Uninstalling Whisper or NLLB removes its repository from the shared Hugging Face cache. Uninstalling one Qwen3-ASR model keeps the shared aligner, language detector, and Vulkan runtime. Silero is bundled, and FSMN is prepared when selected under **VAD and look-ahead**.

Under **VAD and look-ahead**, use **Voice activity detection (VAD)** to choose the detector and tune speech boundaries. **Look-ahead and seeking** controls the audio window used to generate subtitles during playback and after a seek.

After upgrading an existing Qwen3-ASR installation, select **Download** for your Qwen3-ASR model under **Local models**, then **Save and apply** on the **Subtitles** page. Setup adds the shared 78 MB language detector and reuses the recognition weights you already downloaded. See [Qwen3-ASR language detection](providers.md#qwen3-asr-language-detection).

**Save and apply** keeps the service and its local models running when you change subtitle languages, bilingual display, timing, translation guidance, or cloud provider settings. Playback requests pick up new defaults on the next update. Requests with explicit languages or display options keep those choices. In-flight chunks finish with their original settings and cache identity. Changing the active local model, its device, the VAD model, diagnostic output, or the service hotkey restarts the service. The status line shows when the service is waiting for existing work to finish and when it is loading local models.

Under Cloud models (云端模型), select a provider and choose a key file (密钥文件) or direct entry (直接填写). Direct keys use current-user [DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata). File mode saves the path. To remove a direct key, switch to Default/environment (默认（环境变量）) and save. Alibaba recognition/translation share a key and regional endpoint; custom ASR/translation may use separate keys. Remote endpoints require HTTPS for credentials; loopback supports HTTP. Save credentials, then apply your settings on the **Subtitles** page to change the service.

ChatGPT subscription · OAuth (ChatGPT 订阅 · OAuth) opens browser authorization for text translation. MiniMax accepts M Plan and pay-as-you-go keys. See [providers](providers.md).

Context enhancement (上下文增强) is saved per translator: 0–8 previous recognized cues, default 250 characters per cue (range 20–1000), at most 1000 context characters per request, prioritizing recent cues. Output covers current cues only. Context may improve pronouns/terms but increases tokens and latency. Zero cues still permits a prompt. Qwen-MT Flash and Plus support style prompts only.

Settings are single-instance. Closing hides the window; double-click the tray to reopen. Stop subtitle service (停止字幕服务) releases models but retains the helper. Stop and exit (停止并退出) closes both. Relaunch/start the service for new playback work. Disk caches remain reusable.

## Automatic subtitle tasks

Use **Automatic tasks** to watch multiple folders. Each rule has its own file filters and subtitle configuration. The default destination is beside the media. The filename uses the media stem, an optional suffix, and `.srt`. Existing subtitle files are preserved.

1. Open **Automatic tasks → Add rule** and choose a folder. Enable **Include subfolders** to scan its tree. Leave **Include files already present** off to start with new or modified files, or turn it on to queue the files already there.
2. Under **File filters**, enter a case-insensitive filename regex if needed, for example `^Episode.*\.mkv$`. A file must also have an allowed extension and fall within both inclusive size limits. Sizes use MiB. Leave the maximum blank for no upper limit. A regex timeout pauses scanning that folder until a later scan can match successfully.
3. Under **Subtitle configuration**, select the speech recognition and subtitle translation models independently, along with the languages, audio track (numbered from 1), and SRT content. **Use global settings** inherits the running service's model for that stage and is the default for new and existing rules. A separate output folder keeps the watched folder's relative subdirectory structure. For example, a suffix of `.en` writes `Episode 01.en.srt`. When two inputs map to the same output, the first SRT is kept.
4. Select **Save rule** and start the service with the main **Save and start** button if needed. The default idle threshold of 0 waits for AheadSubs playback sessions, text translations, and manual regenerations to finish. Set a positive number to additionally require that many minutes without Windows keyboard or mouse input.

The task worker runs while the desktop-managed subtitle service is running, including when the window is hidden in the tray. It checks folders about every 10 seconds between jobs and requires an unchanged size and file timestamp across two scans before generating. It processes one file and one chunk at a time. Once playback starts, the worker stops queuing new chunks and lets the in-flight chunk finish. The task resumes from cached chunks once idle. Pausing a rule or stopping the service retains the queue. Changes to an existing rule's output options requeue files previously accepted by that rule. Existing SRTs are always preserved.

Install selected local models under **Local models**. Cloud choices use the app's saved credentials and provider settings, including the configured ChatGPT account/model or custom API endpoint. Apply provider setting changes on **Subtitles**. For example, a Japanese series rule can choose Whisper Small with Qwen-MT Flash while a course folder inherits both models. Files processed with different model combinations have separate cached subtitle versions. To generate a new SRT beside an existing one, use a different suffix or output folder.

The selected rule shows waiting, running, completed, skipped, and failed counts. Use **Retry failed files** after fixing missing models, provider settings, or media errors. The worker stores the queue and rule settings in `folder-tasks.sqlite3` and `folder-tasks.json` in the app's local data folder. Folder scanning skips symbolic links and directory junctions. Only enable cloud recognition or translation for media you intend to process with those providers.

## Subtitle library

Open **Subtitle library** to search by file name or path and filter by primary source language. History groups records by their stored path and opens the newest version by default. You can switch to an older version. Moving a file creates a new entry. Older records with only a file name stay separate until a playback with the same cache settings records their path.

Coverage is the share of the selected version's media duration that has been processed, including silence. It is unknown when duration is unavailable. The primary source language is based on the duration of the recognized cues with a reported language. The filter uses the most recent version with a reported language for each file. The listed subtitle languages reflect the available target subtitles across versions of the file.

**Regenerate** creates a fresh version using the selected version's audio track and languages and the running service's models. The service accepts one regeneration at a time and starts the next chunk only while playback sessions are idle. If generation stops or the service exits, previously saved chunks and versions remain available. Refresh to check the status and retry. Play moved or replaced media to record it again.

**Open SRT** opens the selected version's target subtitles in Notepad. **Save SRT** exports all generated target subtitles for that version, including partial results. Recorded paths, generation state, and subtitles are kept in the local cache.

## Status

Open **Status** in the sidebar. It updates immediately and every three seconds while the page and window are visible. **Refresh now** checks on demand.

| Section | What it shows |
| --- | --- |
| Subtitle service | Readiness, active playback connections and in-flight text requests by PotPlayer, mpv, CLI, MCP and other HTTP clients. |
| Models and local resources | Active recognition, translation and voice activity detection models, their devices and load states. CPU, RAM, GPU and dedicated GPU memory cover the service and sampled child processes. Unsupported readings are blank. |
| Subtitle performance | Median RTF and subtitle-ready latency (P50, P95 and P99), with sample counts. An RTF below 1 means processing takes less time than the corresponding audio plays. Performance samples stay in memory for up to 15 minutes and reset on restart. |
| Cloud usage | Calls, failures, known usage and estimated USD cost by provider, model and operation. Select this week or one of the previous seven UTC weeks. Subscriptions and calls with missing prices or quantities are identified in the table. |

Start playback in a supported player to populate the live view. When the service is stopped or unreachable, existing weekly totals can still be read from `cloud-usage.sqlite3` in the desktop cache. Old weeks are removed when the service starts or writes new usage. Status metrics store no media paths, subtitles, accounts, credentials, session IDs or request bodies. See [status metrics](server.md#status-metrics) for the measurements and billing limits.

## Diagnostics

Logs are off by default. Open **App settings → Diagnostics**, select **Record detailed diagnostic logs**, then save and apply before reproducing the issue. Restart look-ahead to capture a whole session. Use **Open log folder**, or `python -m aheadsubs serve --diagnostics`.

Logs live in the [Windows user data directory](windows.md). Inspect paths, hostnames and URLs before sharing. Disable diagnostics afterwards.

## Control bridge

The launcher starts `UI/AheadSubs.exe`. WPF uses `python -m aheadsubs.desktop.bridge`, separate from the player's [HTTP API](server.md).

| Command | Behavior |
| --- | --- |
| `status` | Returns `settings`, `models`, `active_models`, `credentials`, `integrations`, `chatgpt_accounts` and service status. Key status includes only mode, file path and whether a direct key exists. |
| `cloud-usage` | Reads UTC weekly totals from the default cache without starting the service. |
| `preset-check [requirements]` | Checks FFmpeg and comma-separated `vulkan`, `cuda`, `dashscope` requirements; returns `missing` codes. stdin may provide a candidate `qwen_mt_url`; keys use saved settings. |
| `install <model>` / `uninstall <model>` | Downloads/removes a model; identifiers are in `MODELS`. |
| `apply` | Reads JSON settings and optional `credentials` from stdin, validates and restarts. |
| `save-credentials` | Reads `{provider_id: {mode, value}}`. `openai`, `dashscope`, `minimax`, `compatible-asr`, `compatible-mt` support `direct`, `file`, `default`. Returns status; running services keep previously loaded keys. |
| `chatgpt-status` | Lists accounts, authorization and cached models. |
| `chatgpt-login [account]` | Opens browser authorization; an ID reauthorizes that registration. |
| `chatgpt-models <account>` | Refreshes available models. |
| `chatgpt-logout <account>` | Attempts remote revocation and clears local tokens; keeps registration. |
| `stop` | Stops the helper-managed service. |
| `integrate potplayer\|mpv [--folder PATH]` | Installs integration and remembers custom locations. |
| `unintegrate potplayer\|mpv` | Removes AheadSubs extensions from the selected location. |
| `pot-windows` | Lists controllable PotPlayer windows. |
| `pot-start <window>` / `pot-stop <window>` | Starts/stops that window's look-ahead. |
| `logs` | Returns log paths. |
| `inspect-library` | Reads the local cache and returns `files` grouped by path with versions, coverage, and language summaries. |
| `inspect-rows <key>` | Returns recent originals, subtitle text, and failed rows for the selected version. |
| `inspect-regenerate <key>` | Queues regeneration on the desktop-managed service and returns the new version's `key`. |
| `inspect-srt <key>` | Reads `{"output":"…"}` from stdin and returns the `subtitle` path. A `null` output writes a copy for viewing in the cache. |
| `automation [mcp-enable\|mcp-disable\|cli-install\|cli-remove]` | Reads or updates MCP access, client configuration and CLI user-PATH registration. See [integrations](automation.md). |
| `folder-tasks [save\|retry]` | Reads rules and queue summaries. `save` replaces the saved rules with `{rules: [...]}` from stdin. Optional `speech_model` and `translation_model` fields accept model choices such as `whisper-small` and `qwen-mt-flash`. Omit either field or use `null` to inherit. `retry` reads `{id: "rule ID"}` and requeues that rule's failed files. |

Each invocation writes one JSON object with `ok` to stdout. Failure adds `error` and a nonzero exit code. Known errors can also carry a stable `error_code` and an optional ordered list of `error_args` for localized display. Technical details supplied by Windows or external tools may appear in their original language. External adapters should use HTTP v1 rather than this internal desktop interface.

The [Windows user data directory](windows.md) holds `settings.json`, models, caches and control tokens. Independent services with separate control tokens belong to their launcher. `AheadSubs.pyw` launches the app from source. `Subtitle Relay.pyw` continues to handle callbacks from existing player extensions.

ChatGPT credentials use current-user DPAPI in `chatgpt.sqlite3`. The bridge returns summaries, authorization and catalogs, never tokens. Settings retain selected account/model IDs.
