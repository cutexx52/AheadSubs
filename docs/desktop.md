# Windows desktop guide

[English](desktop.md) | [简体中文](desktop.zh-CN.md)

## Everyday use

Open **Setup presets** on the translation home page. The control starts collapsed. Once you select a preset, **Download now** fetches the missing models. **Manage models** opens the library with the required downloads marked. When the preset is ready, select **Apply preset**. The audio language, subtitle language, and bilingual setting carry over. Manual model combinations appear as **Custom**.

| Preset | Speech recognition | Translation |
| --- | --- | --- |
| Local · CPU | Whisper Small on CPU | NLLB on CPU |
| Local · Entry GPU | Qwen3-ASR 0.6B on Vulkan | NLLB on CPU |
| Local · High-performance GPU | Qwen3-ASR 1.7B on Vulkan | NLLB on NVIDIA CUDA |
| Recommended · Local speech + cloud translation | Qwen3-ASR 1.7B on Vulkan | Qwen-MT Flash with a Bailian API key |

The GPU presets check for a Vulkan device. The high-performance preset also checks for an NVIDIA CUDA device and its runtime libraries. The recommended preset checks whether the saved Bailian credential is readable and the service URL is supported. Save a missing key in the Bailian configuration and return to the home page to check again. The provider verifies the credential when a request is sent. If a download fails, retry to reuse any models that finished downloading.

**Local models** groups speech recognition, translation, and voice activity detection. Whisper and NLLB have separate CPU/CUDA selectors. Use the main **Save and apply** action to apply device changes. Existing configurations use their previous device setting until a per-model setting is saved. Stop the subtitle service or switch models before uninstalling a model in use. Uninstalling Whisper or NLLB removes its repository from the shared Hugging Face cache. Uninstalling one Qwen3-ASR model keeps the shared aligner and Vulkan runtime. Silero is bundled, and FSMN is prepared when selected in Advanced settings.

Under Cloud models (云端模型), select a provider and choose a key file (密钥文件) or direct entry (直接填写). Direct keys use current-user [DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata). File mode saves the path. To remove a direct key, switch to Default/environment (默认（环境变量）) and save. Alibaba recognition/translation share a key and regional endpoint; custom ASR/translation may use separate keys. Remote endpoints require HTTPS for credentials; loopback supports HTTP. Save credentials, then apply translation settings to change the service.

ChatGPT subscription · OAuth (ChatGPT 订阅 · OAuth) opens browser authorization for text translation. MiniMax accepts M Plan and pay-as-you-go keys. See [providers](providers.md).

Context enhancement (上下文增强) is saved per translator: 0–8 previous recognized cues, default 250 characters per cue (range 20–1000), at most 1000 context characters per request, prioritizing recent cues. Output covers current cues only. Context may improve pronouns/terms but increases tokens and latency. Zero cues still permits a prompt. Qwen-MT Flash and Plus support style prompts only.

Settings are single-instance. Closing hides the window; double-click the tray to reopen. Stop subtitle service (停止字幕服务) releases models but retains the helper. Stop and exit (停止并退出) closes both. Relaunch/start the service for new playback work. Disk caches remain reusable.

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

Logs are off by default. Under Advanced settings (高级设置), enable diagnostics (启用诊断日志), apply and reproduce. Restart look-ahead to capture a whole session. Use Open logs directory (打开日志目录), or `python -m subtitle_relay serve --diagnostics`.

Logs live under `%LOCALAPPDATA%\Subtitle Relay`. Inspect paths, hostnames and URLs before sharing. Disable diagnostics afterwards.

## Control bridge

The launcher starts `UI/AheadSubs.exe`. WPF uses `python -m subtitle_relay.desktop.bridge`, separate from the player's [HTTP API](server.md).

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
| `automation [mcp-enable\|mcp-disable\|cli-install\|cli-remove]` | Reads or updates MCP access, client configuration and CLI user-PATH registration. See [integrations](automation.md). |

Each invocation writes one JSON object with `ok` to stdout. Failure adds `error` and a nonzero exit code. External adapters should use HTTP v1 rather than this internal desktop interface.

Settings use `%LOCALAPPDATA%\Subtitle Relay\settings.json`; models, caches and control tokens remain in user data. Independent services with separate control tokens belong to their launcher. `Subtitle Relay.pyw` remains the source and compatibility entry for callbacks and feedback tools.

ChatGPT credentials use current-user DPAPI in `chatgpt.sqlite3`. The bridge returns summaries, authorization and catalogs, never tokens. Settings retain selected account/model IDs.
