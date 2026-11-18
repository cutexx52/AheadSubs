# 后台 HTTP v1 接口

[English](server.md) | [简体中文](server.zh-CN.md)

服务默认绑定 `127.0.0.1:8769`，用于本机客户端。服务和播放器共享文件访问权限。所有 API 时间均使用原媒体时间，单位秒。

可用 `python -m aheadsubs serve --asr local --mt local --device cpu` 独立启动服务。使用 `--port` 设置端口时，调用者也需配置相同端口。

## 文件转录 API

使用 `python -m aheadsubs serve --asr local --mt none --device cpu` 启动纯识别服务。即使服务同时配置了识别和翻译，文件转录也只调用识别后端。`--ast` 语音翻译配置没有可供这些接口使用的识别器。使用 `--mt none` 时，播放器显示原语字幕。

文件接口接受 multipart 上传并识别第一条音轨。省略 `language` 可自动识别原语音，也适用于混语。显式语言仅作为识别提示。识别质量与语言覆盖取决于所配置的模型。选用云端识别后端时，音频片段会发给对应服务商。文件任务共享推理工作池，在分块之间让位给播放和目录字幕任务。

每个缓存目录只由一个服务实例管理转录任务。若同时运行多个转录服务，请为它们分别指定 `--cache`。

请用 `127.0.0.1` 或 `localhost` 加服务端口访问。文件接口拒绝浏览器请求，也不接受服务端路径或 URL。下文的播放接口有单独的本地路径约定。转录接口信任同一台机器上的原生进程。请妥善保存任务 ID，它可用于读取状态、操作任务和获取结果。

### 持久任务

每次请求都带上 `X-AheadSubs-Transcription: 1`，并将 `{id}` 替换为返回的任务 ID。

| 请求 | 约定 |
| --- | --- |
| `GET /v1/transcription/capabilities` | 返回后端可用性、模型别名、片段时间戳、响应格式和限制。 |
| `POST /v1/transcription/jobs` | multipart `file` 和可选的 `language`（`auto` 或语言代码）。返回 `202`、`Location` 响应头和任务状态。 |
| `GET /v1/transcription/jobs/{id}` | 返回 `id`、`state`、`duration`、请求的 `language`（`null` 表示自动）、`completed_chunks`、`total_chunks` 和 `error_code`。 |
| `GET /v1/transcription/jobs/{id}/result` | 返回已完成的结果。待处理、失败或已取消的任务返回 `409`。 |
| `POST /v1/transcription/jobs/{id}/cancel` | 取消排队中或运行中的任务。已进入推理的分块可能继续运行，其结果会被丢弃。 |
| `POST /v1/transcription/jobs/{id}/resume` | 用保留的输入和已完成的分块继续失败或已取消的任务。已取消的分块仍在处理时返回 `409`，应等它处理结束。恢复时使用相同的识别设置。 |
| `DELETE /v1/transcription/jobs/{id}` | 删除任务、保留的输入和结果，返回 `204`。 |

```powershell
curl.exe -H "X-AheadSubs-Transcription: 1" -F "file=@recording.wav" http://127.0.0.1:8769/v1/transcription/jobs
```

```json
{
  "duration": 2.7,
  "text": "早上好。",
  "segments": [{"start": 0.2, "end": 1.4, "text": "早上好。"}]
}
```

片段时间以秒计，从上传音频的起点算起。片段保留识别后端给出的时间范围和重叠，加上所属分块的偏移。仅当后端提供某个片段的语言时，该片段才返回 `language`。目前没有词级时间戳、说话人标签或置信度。SRT 渲染时单独延长字幕显示时间。没有识别到语音的上传也能完成，`text` 和 `segments` 均为空。

任务状态包括 `queued`、`running`、`completed`、`failed` 和 `cancelled`。服务重启后可继续排队中和中断的任务。任务完成后删除输入音频。定期清理会移除超过 24 小时或超出 100 个终态任务配额的记录，其中包括失败或已取消任务的输入，以及已完成任务的结果。持久队列和同步请求合计最多保留八份输入、共 512 MB 规范化音频。

### 兼容 OpenAI 的文件上传

`POST /v1/audio/transcriptions` 接受 multipart `file`、`model=aheadsubs`、可选的两字母 `language`、可选的 `response_format=json`（默认）或 `text`，以及可选的 `stream=false`。`aheadsubs` 选择当前配置的识别器。请按 SDK 的要求发送非空 Bearer 值，例如 `local`。该值仅用于客户端兼容，不充当服务凭据。JSON 返回 `{"text":"…"}`，`text` 返回 UTF-8 纯文本。错误沿用 OpenAI 响应结构。接口拒绝其他模型、字段和格式。片段时间请从持久任务结果接口获取。

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8769/v1", api_key="local", max_retries=0)
with open("recording.wav", "rb") as audio:
    result = client.audio.transcriptions.create(model="aheadsubs", file=audio)
print(result.text)
```

Pipecat 的分段 HTTP `OpenAISTTService` 可使用相同的 base URL、模型和 API key。请关闭概率指标，省略 prompt、temperature 和 keywords，并选择 Pipecat 支持的输入语言。文件接口的范围不包括实时流式转录和说话人分离。

两种上传接口均支持最多 25 MB 的 WAV、MP3、FLAC、AAC、Ogg/Opus、MP4/M4A/MOV 或 Matroska/WebM 文件。解码需要支持 `fd` 协议的 FFmpeg，Windows 运行库已包含该协议。解码后的音频上限为持久任务两小时、同步请求 15 分钟。最多同时处理两个上传请求，等待同步结果也占用名额。文件传输和解码上限分别为 30 秒和 60 秒。同步等待 180 秒后超时，并清理临时任务。输入超限返回 `413`，无法解码返回 `415`，容量用尽返回 `429`。处理可能超过同步等待时间的文件适合使用持久任务。

## 更新播放状态

`POST /v1/playback`，`Content-Type: application/json`。

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

| 字段 | 合约 |
| --- | --- |
| `session` | 必填，1–100 字符，每个播放窗口独立。10 秒无更新时过期。 |
| `path` | 必填，后台可访问的媒体绝对路径。可用本地路径或共享目录。 |
| `position` | 必填，当前媒体时间，非负，最多 1000 万秒。 |
| `audio` | 可选，默认 `0`，FFmpeg 内嵌音轨序号，从零起算。 |
| `duration` | 可选，总时长，必须大于零。 |
| `speed` | 可选，默认 `1`，允许 `0.1–5`。 |
| `source` / `target` | 省略时使用服务启动配置。默认自动识别并输出 `zh`。显式设置 `source: null` 可强制自动识别。可用语言取决于 provider。 |
| `ahead` | 可选，默认 `20`，允许 `1–120` 秒。 |
| `bilingual` | 可选，默认使用服务启动配置。为 `true` 时，带语言前缀的原文在上，译文在下。 |

响应示例。

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

`revision` 和 `subtitle` 一起标识字幕版本。尚无数据时是 `0` 和 `null`。`ready_ahead` 是从指定位置开始连续处理完成的媒体秒数，包含静音。`nearby_cues` 指示附近已处理区间是否有尚未结束的字幕。`error` 是当前块的错误说明，`error_code` 是用于适配器判定的稳定分类。内容审核导致的单句拦截作为字幕检查记录保存。跳转、换轨或新文件可能使预读余量下降。

`subtitle_generation` 在有效识别、翻译、时间轴配置或双语显示切换后变化，即使新配置还没有字幕。播放器可据此撤下旧字幕，等待本次结果。回到完全相同的处理配置时可复用它自己的缓存。

## 会话与服务控制

| 请求 | 合约 |
| --- | --- |
| `GET /v1/health` | 返回 `service`、`pid`、`active_sessions` 和 `local_models`。活跃会话数统计外部播放会话，本地模型标识供桌面端保护运行中的模型。 |
| `GET /v1/status` | 返回实时状态和周汇总。请求需带 `X-AheadSubs-Status: 1`，带 `Origin` 的请求返回 `403`。响应使用 `Cache-Control: no-store`。 |
| `POST /v1/close` | 以 JSON `{"session":"window-1"}` 释放会话，成功返回 `{}`。 |
| `POST /v1/shutdown` | 以 JSON `{"token":"…"}` 停止服务。由进程管理端使用，须与启动时的控制令牌相符。 |
| `POST /v1/inspection/regenerate` | 桌面管理端发送 JSON `{"token":"…","key":"…"}`，使用控制令牌和本地缓存的版本键。接受任务后返回 `202` 和新版本的 `key`。无法开始时返回 `409` 和 `error_code`。 |

服务拒绝带 `Origin` 头的 POST，普通请求体最大 32 KiB，文字翻译为 50 KiB，以容纳 URL 编码的 Unicode。常见响应包括无效输入 `400`、未授权 `403` 和临时忙 `503`。

## 文本翻译

`POST /v1/text` 使用 `Content-Type: application/x-subtitle-relay`，请求体为 URL 编码的 `source`、`target`、`text`。文本上限为 4000 字符。成功时返回 `{"translation":"…"}`，没有配置翻译时返回 `409`，provider 失败时返回 `502` 及 `error`、`error_code`。这个入口适合翻译现成字幕，不传输媒体时间轴。

## 状态指标

`/v1/playback` 和 `/v1/text` 可通过 `X-AheadSubs-Entry` 声明入口。接受 `potplayer`、`mpv`、`cli`、`mcp` 和 `http`。旧版 PotPlayer 文本插件和 mpv 脚本可通过现有标识识别。其他未声明或未知入口计入 `http`。播放连接在关闭或 10 秒无心跳后从状态快照移除，文本请求只在处理期间计数。

| 字段 | 口径 |
| --- | --- |
| `ready`, `models` | 服务完成初始化后才提供状态。自带 Qwen3-ASR 运行时通过本机健康接口复查，不可达时返回 `ready: false`。模型按 `operation`、`model`、`device`、`state` 返回。回环兼容端点的模型状态未知，云端模型只显示已配置。 |
| `active_sessions`, `sources`, `workers` | 活跃播放会话总数、按入口的播放和文本数量，以及后台已用处理槽位和总量。 |
| `resources` | 后台及存活子进程的 CPU 占全部逻辑核百分比、工作集内存字节数、最忙 GPU 引擎占用率及独立显存字节数。初始化或计数器不可用时可能为空或缺字段。外部自建模型服务不计入。 |
| `performance.rtf`, `performance.latency` | 最近 15 分钟、各至多 1,024 个样本。返回 `count` 及最近秩百分位 `p50`、`p95`、`p99`。零样本时百分位为 `null`。 |
| `cloud` | UTC 周一日期列表 `weeks`、按周/提供商/模型/操作聚合的 `rows`，以及数据可能缺失时的 `incomplete`。每行记录调用数、失败数、已知输入和输出 Token、已知音频秒数、可估算调用数及累计估算美元金额。 |

RTF 用成功处理的片段耗时除以该片段所属窗口的实际音频时长，含提取、VAD、识别和翻译，排除排队和缓存写入。延迟以秒表示，从首次等待生成当前片段的播放更新算起，直到同一播放片段内后续请求收到可用字幕。播放器轮询间隔计入延迟。即时缓存命中、跳转或换片造成的等待取消、以及播放器收到响应后的渲染时间不计入。样本少时多个百分位可能相同。

云端用量从本版本开始记录。模型请求按调用计数，SDK 内部自动重试算入同一次调用。费用用已观测到的 Token 或音频时长，与请求时的内置公开美元费率估算。覆盖 Whisper、GPT-4.1 mini、GPT-6 Luna、MiniMax M3.1 Flash 按量 API，以及百炼北京和新加坡的内置识别与翻译模型。实际账单会受税费、优惠、免费额度、重试、取整和付费方案影响。ChatGPT 订阅、MiniMax M Plan（`minimax_plan`）和费率未知的兼容端点保留已知用量和调用数。[Whisper 价格](https://developers.openai.com/api/docs/models/whisper-1) · [GPT-4.1 mini 价格](https://developers.openai.com/api/docs/models/gpt-4.1-mini) · [GPT-6 Luna 价格](https://developers.openai.com/api/docs/models/gpt-6-luna) · [MiniMax 价格](https://www.minimax.io/blog/minimax-m31f) · [阿里云百炼价格](https://www.alibabacloud.com/help/en/model-studio/model-pricing)

## 内部接口和缓存

`Relay.update(identifier, Playback)` 接收播放状态并返回字幕元数据。`Relay.drop(identifier)` 释放会话。`Relay.close()` 关闭调度和持久化资源。工作单元读取指定音轨，保留其在媒体时间轴上的开头偏移，并在 ASR 后换算回原视频时间。输出相邻字幕若重叠，保留下一句的起始时间，并在该点结束前一句。

SQLite 保存已完成的块，缓存身份包含媒体文件及其更新时间、音轨、语言和处理配置。相同身份的窗口共享已完成的块。SRT 批量原子替换。CLI 的默认缓存目录为 `.relay`，桌面启动的服务使用 [Windows 用户数据目录](windows.zh-CN.md)下的 `cache` 子目录。
