# 后台 HTTP v1 接口

服务默认绑定 `127.0.0.1:8769`，用于本机客户端。服务和播放器共享文件访问权限。所有 API 时间均使用原媒体时间，单位秒。

可用 `python -m subtitle_relay serve --asr local --mt local --device cpu` 独立启动服务。使用 `--port` 设置端口时，调用者也需配置相同端口。

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
| `GET /v1/health` | 返回 `service`、`pid` 和 `active_sessions`，用于本地就绪与状态检查。 |
| `GET /v1/status` | 返回实时状态和周汇总。请求需带 `X-AheadSubs-Status: 1`，带 `Origin` 的请求返回 `403`。响应禁止缓存。 |
| `POST /v1/close` | 以 JSON `{"session":"window-1"}` 释放会话，成功返回 `{}`。 |
| `POST /v1/shutdown` | 以 JSON `{"token":"…"}` 停止服务。由进程管理端使用，须与启动时的控制令牌相符。 |

服务拒绝带 `Origin` 头的 POST。普通请求体最大 32 KiB，文本翻译请求体最大 50 KiB，以容纳 URL 编码后的 Unicode 文本。常见响应包括无效输入 `400`、未授权 `403` 和临时忙 `503`。

## 文本翻译

`POST /v1/text` 使用 `Content-Type: application/x-subtitle-relay`，请求体为 URL 编码的 `source`、`target`、`text`。文本上限为 4000 字符。成功时返回 `{"translation":"…"}`，没有配置翻译时返回 `409`，provider 失败时返回 `502` 及 `error`、`error_code`。这个入口适合翻译现成字幕，不传输媒体时间轴。

## 状态指标

`/v1/playback` 和 `/v1/text` 可通过 `X-AheadSubs-Entry` 声明入口。接受 `potplayer`、`mpv`、`cli`、`mcp` 和 `http`。未声明或未知入口计入 `http`，现有的 PotPlayer 文本插件自动识别。入口分类仅用于汇总。播放连接在关闭或 10 秒无心跳后从状态快照移除，文本请求只在处理期间计数。

| 字段 | 口径 |
| --- | --- |
| `ready`, `models` | 服务完成初始化后才提供状态。自带 Qwen3-ASR 运行时通过本机健康接口复查；不可达时返回 `ready: false`。模型按 `operation`、`model`、`device`、`state` 返回。回环兼容端点的模型状态未知，云端模型只显示已配置。 |
| `active_sessions`, `sources`, `workers` | 活跃播放会话总数、按入口的 `playback` 和 `text` 数量，以及后台已用处理槽位 `busy` 和总量 `limit`。 |
| `resources` | 后台及存活子进程的 CPU 占全部逻辑核百分比、工作集内存字节数，以及 Windows 提供的最忙 GPU 引擎占用率和独立显存字节数。初始化或计数器不可用时可能为空或缺字段。外部自建模型服务不计入。 |
| `performance.rtf`, `performance.latency` | 最近 15 分钟、各至多 1,024 个内存样本。返回 `count` 及最近秩百分位 `p50`、`p95`、`p99`；零样本时百分位为 `null`。 |
| `cloud` | UTC 周一日期列表 `weeks`、按周/提供商/模型/操作聚合的 `rows`，以及数据可能缺失时的 `incomplete`。每行记录调用数、失败数、已知输入和输出 Token、已知音频秒数、可估算调用数及累计估算美元金额。 |

RTF 用新片段的实际处理耗时除以该片段所属的音频时长，含提取、VAD、识别、翻译，排除排队和缓存写入；尾段按读取到的时长计算。端到端延迟以秒表示，从首次因当前片段尚未生成而需要等待的播放更新，到同一片段内回复中提供可用字幕。播放器轮询间隔计入延迟；已缓存命中、跳转或换片导致放弃的等待、播放器拿到响应后的渲染时间不计入。样本少时多个百分位可能相同。

云端用量从开启该版本起，在模型请求边界计数。SDK 内部自动重试归在同一次调用，缓存命中不会触发新的模型调用。费用用已观测到的音频时长或 Token 与请求时的内置公开费率估算，覆盖 Whisper、GPT-4.1 mini、GPT-6 Luna、MiniMax M3.1 Flash 按量 API，以及百炼北京和新加坡的内置识别与翻译模型。实际账单可能因免费额度、税费、重试、计费取整和付费方案不同而有差异。ChatGPT 订阅、MiniMax M Plan（`minimax_plan`）和费率未知的兼容端点保留已知用量和调用数。费率参考 [OpenAI Whisper](https://developers.openai.com/api/docs/models/whisper-1)、[GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini)、[GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)、[MiniMax M3.1 Flash](https://www.minimax.io/blog/minimax-m31f) 和 [阿里云百炼价格表](https://www.alibabacloud.com/help/en/model-studio/model-pricing)。

## 内部接口和缓存

`Relay.update(identifier, Playback)` 接收播放状态并返回字幕元数据。`Relay.drop(identifier)` 释放会话。`Relay.close()` 关闭调度和持久化资源。工作单元读取指定音轨，保留其在媒体时间轴上的开头偏移，并在 ASR 后换算回原视频时间。输出相邻字幕若重叠，保留下一句的起始时间，并在该点结束前一句。

SQLite 保存已完成的块，缓存身份包含媒体文件及其更新时间、音轨、语言和处理配置。相同身份的窗口共享已完成的块。SRT 批量原子替换。CLI 的默认缓存目录为 `.relay`，桌面启动的服务使用 `%LOCALAPPDATA%\Subtitle Relay\cache`。
