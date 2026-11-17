# Windows desktop guide

[English](desktop.md) | [简体中文](desktop.zh-CN.md)

## Everyday use

Local models (本地模型) offers Vulkan Qwen3-ASR + CPU NLLB and Whisper Small + NLLB presets. Downloads show status, hardware requirements and disk estimates. Qwen3-ASR sizes share about 0.63 GB of alignment weights/runtime; leave temporary space for archives. Translation (翻译) shows the devices used by the combination.

Under Cloud models (云端模型), select a provider and choose a key file (密钥文件) or direct entry (直接填写). Direct keys use current-user [DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata). File mode saves the path. To remove a direct key, switch to Default/environment (默认（环境变量）) and save. Alibaba recognition/translation share a key and regional endpoint; custom ASR/translation may use separate keys. Remote endpoints require HTTPS for credentials; loopback supports HTTP. Save credentials, then apply translation settings to change the service.

ChatGPT subscription · OAuth (ChatGPT 订阅 · OAuth) opens browser authorization for text translation. MiniMax accepts M Plan and pay-as-you-go keys. See [providers](providers.md).

Context enhancement (上下文增强) is saved per translator: 0–8 previous recognized cues, default 250 characters per cue (range 20–1000), at most 1000 context characters per request, prioritizing recent cues. Output covers current cues only. Context may improve pronouns/terms but increases tokens and latency. Zero cues still permits a prompt. Qwen-MT Flash and Plus support style prompts only.

Settings are single-instance. Closing hides the window; double-click the tray to reopen. Stop subtitle service (停止字幕服务) releases models but retains the helper. Stop and exit (停止并退出) closes both. Relaunch/start the service for new playback work. Disk caches remain reusable.

## Diagnostics

Logs are off by default. Under Advanced settings (高级设置), enable diagnostics (启用诊断日志), apply and reproduce. Restart look-ahead to capture a whole session. Use Open logs directory (打开日志目录), or `python -m subtitle_relay serve --diagnostics`.

Logs live under `%LOCALAPPDATA%\Subtitle Relay`. Inspect paths, hostnames and URLs before sharing. Disable diagnostics afterwards.

## Control bridge

The launcher starts `UI/AheadSubs.exe`. WPF uses `python -m subtitle_relay.desktop.bridge`, separate from the player's [HTTP API](server.md).

| Command | Behavior |
| --- | --- |
| `status` | Returns `settings`, `models`, `credentials`, `integrations`, `chatgpt_accounts` and service status. Key status includes only mode, file path and whether a direct key exists. |
| `install <model>` | Prepares a local model; identifiers are in `MODELS`. |
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
