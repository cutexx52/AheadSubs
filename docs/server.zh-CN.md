# 后台 HTTP v1 接口

[English](server.md) | [简体中文](server.zh-CN.md)

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
| `POST /v1/close` | 以 JSON `{"session":"window-1"}` 释放会话，成功返回 `{}`。 |
| `POST /v1/shutdown` | 以 JSON `{"token":"…"}` 停止服务。由进程管理端使用，须与启动时的控制令牌相符。 |

服务拒绝带 `Origin` 头的 POST，请求体最大 32 KiB。常见响应包括无效输入 `400`、未授权 `403` 和临时忙 `503`。

## 文本翻译

`POST /v1/text` 使用 `Content-Type: application/x-subtitle-relay`，请求体为 URL 编码的 `source`、`target`、`text`。文本上限为 4000 字符。成功时返回 `{"translation":"…"}`，没有配置翻译时返回 `409`，provider 失败时返回 `502` 及 `error`、`error_code`。这个入口适合翻译现成字幕，不传输媒体时间轴。

## 内部接口和缓存

`Relay.update(identifier, Playback)` 接收播放状态并返回字幕元数据。`Relay.drop(identifier)` 释放会话。`Relay.close()` 关闭调度和持久化资源。工作单元读取指定音轨，保留其在媒体时间轴上的开头偏移，并在 ASR 后换算回原视频时间。输出相邻字幕若重叠，保留下一句的起始时间，并在该点结束前一句。

SQLite 保存已完成的块，缓存身份包含媒体文件及其更新时间、音轨、语言和处理配置。相同身份的窗口共享已完成的块。SRT 批量原子替换。CLI 的默认缓存目录为 `.relay`，桌面启动的服务使用 `%LOCALAPPDATA%\Subtitle Relay\cache`。
