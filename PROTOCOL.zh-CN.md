# AheadSubs 本地协议 v1（早期参考）

[English](PROTOCOL.md) | [简体中文](PROTOCOL.zh-CN.md)

当前客户端行为、错误码及带认证的停止接口以维护中的 [HTTP v1 合约](docs/server.zh-CN.md) 为准。保留本页以兼容旧链接。

服务默认监听 IPv4 回环地址 8769 端口。播放器和服务共享文件系统访问权限，所有时间是原媒体时间轴上的秒数。

## 播放器 → 服务

`POST /v1/playback`，`Content-Type: application/json`。

```json
{
  "session": "player-window-unique-id",
  "path": "E:/Video/clip.mkv",
  "audio": 0,
  "position": 71.2,
  "duration": 1640.4,
  "speed": 1,
  "source": "ja",
  "target": "zh",
  "ahead": 20
}
```

仅 `session`、`path`、`position` 必填。路径可为本地文件或可访问的 UNC 共享；`audio` 是从零开始的 FFmpeg 内嵌音轨序号，不是播放器轨道 ID。早期合约中省略或 null 源语言表示自动检测；当前省略行为见 HTTP v1 文档。每个窗口约每秒更新两次；新路径、轨道、语言或不连续的位置替代该窗口之前的调度偏好。10 秒无更新会话过期。

响应：

```json
{
  "revision": 5,
  "subtitle": "E:/relay/cache/example.srt",
  "ready_ahead": 16.8,
  "nearby_cues": true,
  "error": null
}
```

无覆盖时版本为零、路径为空；以路径和版本二元组识别更新。非零版本可能只有静音，等有文字才首次加载，再随版本重载。保留播放时间且不改变焦点。`ready_ahead` 是从指定位置开始连续完成的媒体覆盖，含静音；跳转/换文件可降低余量。`nearby_cues` 表示覆盖中有未结束的字幕。

`POST /v1/close` 携带 `{"session":"player-window-unique-id"}` 释放会话，`GET /v1/health` 检查就绪。

## PotPlayer 纯文本扩展

`POST /v1/text` 使用 `Content-Type: application/x-subtitle-relay`，URL 编码 `source`、`target`、`text`，返回 `translation` 字符串。它共用已配置的文本翻译器，不涉及媒体时间轴，也不需要在播放器扩展中保存 provider 密钥。
