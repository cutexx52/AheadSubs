# Agent 与命令行接入

[English](automation.md) | [简体中文](automation.zh-CN.md)

AheadSubs 的 CLI 和 MCP 共用同一套操作、参数和错误码。两者调用本机字幕服务，沿用当前识别、翻译、音轨和字幕缓存。先在桌面的 **翻译** 页保存配置并启动服务，或者用 [HTTP 服务入口](server.zh-CN.md) 独立启动。默认端口是 `8769`。独立服务用了其他端口时，在 CLI 命令或 MCP 启动参数末尾加 `--port <端口>`。

## Windows 桌面接入

- 打开 **接入 → 开启 MCP 接入 → 复制 MCP 配置**，把配置加入客户端的本地 MCP 设置，再连接。支持 `mcpServers` 格式的客户端可以直接使用该 JSON，其他客户端可以填写其中的 `command`、`args` 和 `env`。客户端通过 stdio 启动 MCP 进程。
- 点击 **安装 CLI** 将 `cli` 目录加入当前用户的 PATH。重新打开终端，运行 `aheadsubs status` 或 `aheadsubs --help`。也可以直接运行发布包内的 `cli/aheadsubs.exe`。便携包移动后可重新安装 CLI，并重新复制 MCP 配置。
- **关闭 MCP 接入** 会阻止通过桌面配置发起的新调用。**从 PATH 移除** 会撤销当前安装目录的 PATH 注册。

MCP 客户端可以提交本机可读的媒体或文本，并把 SRT 写入指定路径。启用云端模型时，任务使用已配置的云端服务。只把配置交给你信任、能访问同一台机器的客户端。

接入页、CLI 的 AheadSubs 文案和 MCP 工具说明随系统界面语言显示，也可通过进程环境变量 `AHEADSUBS_UI_LOCALE` 选择 `zh-CN` 或 `en`。其他语言回退到英文。识别和字幕语言独立配置，参数名与错误码保持一致。自动化接口保留来自字幕服务的原始错误说明。

## CLI 示例

```powershell
aheadsubs status
aheadsubs translate-text "おはようございます" ja zh
Get-Content -Raw ./line.txt | aheadsubs translate-text - ja zh
aheadsubs generate-subtitles "D:/Videos/clip.mp4" "D:/Videos/clip.zh.srt" --source ja --target zh --bilingual
aheadsubs update-playback my-player "D:/Videos/clip.mp4" 12.5 --ahead 30
aheadsubs close-playback my-player
```

每次操作向 stdout 输出一个 JSON 对象。成功时含 `ok: true`，操作失败时含 `ok: false`、`error` 和 `error_code`，进程退出码为 `1`。命令行语法错误由参数解析器写入 stderr，退出码为 `2`。

## MCP 工具

| MCP 工具 | 对应 CLI 命令 | 行为 |
| --- | --- | --- |
| `aheadsubs_status` | `status` | 返回字幕服务是否在运行及活跃会话数。 |
| `aheadsubs_translate_text` | `translate-text` | 翻译最多 4000 字符的文本，需要指定来源和目标语言。 |
| `aheadsubs_generate_subtitles` | `generate-subtitles` | 处理整个媒体文件，并将完整 SRT 写到指定位置。 |
| `aheadsubs_update_playback` | `update-playback` | 提交位置并返回预读进度、字幕路径和版本。用同一 `session` 重复提交，10 秒无更新则自动释放。 |
| `aheadsubs_close_playback` | `close-playback` | 释放指定播放会话，保留磁盘缓存。 |

MCP 客户端通过工具列表获得参数 schema。调用结果包含与 CLI 一致的结构化 JSON。生成 SRT 的参数示例。

```json
{
  "path": "D:/Videos/clip.mp4",
  "output": "D:/Videos/clip.zh.srt",
  "source": "ja",
  "target": "zh",
  "audio": 0,
  "bilingual": true,
  "timeout": 1800
}
```

`audio` 是从零开始的音轨序号。省略 `source`、`target` 和 `bilingual` 会沿用服务默认值。用 `source: "auto"` 或 `--source auto` 显式启用源语言自动识别。媒体与输出路径以调用进程的工作目录为基准，MCP 配置中建议传绝对路径。

生成操作会用 FFprobe 确认时长和音轨，逐段推进有界预读，只在处理完整个文件后发布 SRT。输出目录需已存在。用 `overwrite: true` 或 `--overwrite` 替换现有输出。没有对白时会生成空 SRT，返回 `has_cues: false`。超时或失败后可以用相同参数复用已完成的分块。默认超时 1800 秒，可通过 `timeout` 或 `--timeout` 调整。长视频还要为 MCP 客户端的单次调用设置足够的等待时间。

## 源码安装和扩展

在项目目录运行 `python -m pip install .` 安装 `aheadsubs`。也可运行 `python -m aheadsubs.cli --help`。独立启动 MCP 的客户端配置使用 `aheadsubs` 作为 `command`，`["mcp"]` 作为 `args`。如果客户端找不到 CLI，请填写已安装命令的绝对路径。部署使用桌面控制开关时，可给 MCP 加 `--desktop`。

新增操作时，在 `aheadsubs/automation.py` 定义参数模型和处理函数，注册到 `OPERATIONS`，并在 `automation_text.py` 中补齐两种语言。CLI 帮助、命令参数和 MCP 工具 schema 从同一个参数模型生成。需要直接接入播放器或自定义客户端时，可使用 [HTTP v1](server.zh-CN.md)。
