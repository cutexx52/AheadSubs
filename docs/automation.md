# Agent and command-line integrations

[English](automation.md) | [简体中文](automation.zh-CN.md)

AheadSubs exposes the same operations, argument validation, and error codes over CLI and MCP. Both use the subtitle service's active model profile and cache. Start that service from the desktop Subtitles page or [run it independently](server.md). The default port is `8769`. For a different local port, append `--port <port>` to the CLI command or MCP launch arguments.

## Windows desktop setup

- Open **Integrations → Enable MCP access → Copy MCP configuration**. Add the JSON to your local MCP client's settings, or enter the `command`, `args`, and `env` fields separately. The client launches MCP over stdio when it connects.
- Select **Install CLI** to add the bundle's `cli` directory to your Windows user PATH. Reopen your terminal and run `aheadsubs status` or `aheadsubs --help`. You can also run `cli/aheadsubs.exe` directly. If you move a portable bundle, register the new directory and copy the updated MCP configuration.
- **Disable MCP access** blocks new calls through the desktop MCP configuration. **Remove from PATH** removes the registration for the current installation.

The MCP client can submit local media or text and write SRT files to a destination it specifies. With cloud models, requests use the configured provider. Share the configuration with clients you trust on the same machine.

The Integrations page, AheadSubs CLI messages, and MCP tool descriptions use the system UI locale. Set the process environment variable `AHEADSUBS_UI_LOCALE` to `en` or `zh-CN` to override it. Unsupported locales fall back to English. Speech and subtitle languages are configured separately. Automation preserves error details returned by the subtitle service.

## CLI examples

```powershell
aheadsubs status
aheadsubs translate-text "Good morning" en zh
Get-Content -Raw ./line.txt | aheadsubs translate-text - en zh
aheadsubs generate-subtitles "D:/Videos/clip.mp4" "D:/Videos/clip.zh.srt" --source en --target zh --bilingual
aheadsubs update-playback my-player "D:/Videos/clip.mp4" 12.5 --ahead 30
aheadsubs close-playback my-player
```

Each operation writes a single JSON object to stdout. Success includes `ok: true`. An operation failure returns `ok: false`, `error`, and `error_code` with exit code `1`. CLI syntax errors go to stderr with exit code `2`.

## MCP tools

| MCP tool | CLI command | Behavior |
| --- | --- | --- |
| `aheadsubs_status` | `status` | Report whether the service is running and how many sessions are active. |
| `aheadsubs_translate_text` | `translate-text` | Translate up to 4000 characters between two language codes. |
| `aheadsubs_generate_subtitles` | `generate-subtitles` | Process a whole local media file and write the completed SRT. |
| `aheadsubs_update_playback` | `update-playback` | Submit a position and return progress, subtitle path, and revision. Reuse the session ID when polling. A session expires after 10 seconds without updates. |
| `aheadsubs_close_playback` | `close-playback` | Release a playback session and retain its cached subtitles. |

The MCP tool list provides the argument schemas. Tool calls return the same structured JSON as their CLI counterparts. Example arguments for SRT generation follow.

```json
{
  "path": "D:/Videos/clip.mp4",
  "output": "D:/Videos/clip.zh.srt",
  "source": "en",
  "target": "zh",
  "audio": 0,
  "bilingual": true,
  "timeout": 1800
}
```

`audio` is the zero-based stream ordinal. Omit `source`, `target`, or `bilingual` to use the service defaults. Pass `source: "auto"` or `--source auto` to request detection. Relative paths use the process's working directory. For MCP calls, prefer absolute paths.

Generation uses FFprobe to check media duration and available audio, advances through bounded look-ahead windows, and publishes the output after processing completes. The destination directory must already exist. Set `overwrite: true` or use `--overwrite` to replace an existing file. With no dialogue, the operation writes an empty SRT and returns `has_cues: false`. Completed chunks can be reused when retrying a failed or timed-out run. The default timeout is 1800 seconds, configurable with `timeout` or `--timeout`. Set the MCP client's per-call timeout to leave enough time for long media.

## Source installation and extension

Run `python -m pip install .` from the source checkout to install `aheadsubs`. You can also run `python -m aheadsubs.cli --help`. For a standalone MCP connection, set the client command to `aheadsubs` with `["mcp"]` as its arguments. Use the installed command's absolute path if your client cannot find it. Use `--desktop` on Windows to honor the desktop access switch.

To add an operation, define its argument model and handler in `aheadsubs/automation.py`, register it in `OPERATIONS`, and add localized strings in `automation_text.py`. Both transports derive their arguments from the shared models. See [HTTP v1](server.md) for direct integrations.
