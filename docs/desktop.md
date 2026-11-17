# Windows 桌面助手

## 日常使用

**本地模型**提供 Vulkan Qwen3-ASR + CPU NLLB 和 Whisper Small + NLLB 两套入门方案。下载列表显示每个模型的状态、硬件要求和大致磁盘占用。两款 Qwen3-ASR 共享约 0.63 GB 的对齐模型和运行库；首次下载时需要为压缩包额外预留临时空间。**翻译**首页显示当前组合的运行设备。

**云端模型**可按供应商选择 **密钥文件** 或 **直接填写**。直填内容用 Windows 当前用户的 [DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata) 加密保存。文件模式保存所选文件的路径。删除直填密钥时，切回 **默认（环境变量）** 并保存。百炼的识别和翻译共用密钥及区域地址，自定义识别和翻译可以各用一把。远程自定义接口发送密钥时使用 HTTPS，本机回环地址支持 HTTP。可以先 **保存密钥**，再应用翻译设置切换当前服务。

选择 **ChatGPT 订阅 · OAuth** 可以在浏览器授权 AheadSubs 使用 ChatGPT 订阅做字幕文本翻译。MiniMax 支持 M Plan 专用 Key 和按量 API Key。参见[推理与翻译后端](providers.md)。

**上下文增强**按翻译模型保存。支持前文的模型可参考 0–8 个已识别的前文片段，每段默认最多 250 字符，可设为 20–1000 字符。请求优先保留最近的前文，总计最多 1000 字符，输出仍对应当前字幕。前文有助于改善指代和术语的翻译，也可能增加 token 用量和延迟。设为 0 时仍可使用翻译提示词。Qwen-MT Flash 和 Plus 只提供风格提示词。

设置窗口为单实例。关闭窗口后可双击 Windows 托盘图标重新打开。托盘菜单的 **停止字幕服务** 释放模型资源并保留窗口入口，**停止并退出** 同时关闭助手。退出后重新运行助手并启动服务，播放器才能继续提交新任务。已经写入磁盘的缓存可复用。

## 诊断模式

正常模式关闭诊断日志。遇到问题时，在 **高级设置** 勾选 **启用诊断日志** 并应用，再复现问题。若需要诊断整段播放器会话，可以停一次预读再开启。用 **打开日志目录** 查看结果。命令行可用 `python -m subtitle_relay serve --diagnostics`。

源代码助手把服务和播放器日志保存在 `%LOCALAPPDATA%\Subtitle Relay`。分享诊断前，检查记录中的本地文件路径、主机名和 URL。定位结束后可以关闭诊断模式。

## 模块接口

打包启动器运行 `UI/AheadSubs.exe`。WPF 界面使用 `python -m subtitle_relay.desktop.bridge` 管理后台。该入口与播放器使用的 [HTTP 会话接口](server.md) 各自独立。

| 命令 | 输入与行为 |
| --- | --- |
| `status` | 输出 `settings`、`models`、`credentials`、`integrations`、`chatgpt_accounts` 和服务状态。API Key 状态只包含模式、文件路径和是否已保存直填密钥。 |
| `install <model>` | 准备指定本地模型。标识见控制模块中的 `MODELS`。 |
| `apply` | 从 stdin 读 JSON 设置，支持同时提交可选的 `credentials` 更新。验证后重启后台。 |
| `save-credentials` | 从 stdin 接收 `{供应商标识: {mode, value}}`。`openai`、`dashscope`、`minimax`、`compatible-asr` 和 `compatible-mt` 支持 `direct`、`file` 和 `default`。保存后返回凭据状态，正在运行的服务继续用启动时加载的密钥。 |
| `chatgpt-status` | 列出已保存的 ChatGPT 账号、授权状态及缓存的模型。 |
| `chatgpt-login [account]` | 在系统浏览器打开 ChatGPT 授权。带账号标识时重新授权对应注册。 |
| `chatgpt-models <account>` | 刷新账号的可用模型。 |
| `chatgpt-logout <account>` | 尝试撤销远端会话并清除本机令牌，保留账号注册。 |
| `stop` | 停止助手管理的服务。 |
| `integrate potplayer\|mpv [--folder PATH]` | 配置播放器接入。可指定并记住自定义位置。 |
| `unintegrate potplayer\|mpv` | 移除所选位置的 AheadSubs 扩展文件。 |
| `pot-windows` | 列出当前可操作的 PotPlayer 窗口。 |
| `pot-start <window>` / `pot-stop <window>` | 开启或停止对应窗口的预读。 |
| `logs` | 输出可以查看的日志路径。 |
| `automation [mcp-enable\|mcp-disable\|cli-install\|cli-remove]` | 返回 MCP 开关、客户端配置和 CLI 的用户 PATH 注册状态。指定操作时直接更新对应状态。详见[接入说明](automation.md)。 |

每次调用向 stdout 输出一个 JSON 对象，带 `ok` 布尔值。失败时带 `error` 并返回非零退出码。它是项目内的桌面控制接口，外部适配器应以公开的 HTTP v1 合约为准。

运行时使用 `%LOCALAPPDATA%\Subtitle Relay\settings.json` 保存设置，模型、缓存及控制令牌也留在用户数据目录。独立启动并使用不同控制令牌的服务由其启动方管理。源码入口 `Subtitle Relay.pyw` 仍可用；它也承担播放器回调和 Windows 反馈工具的兼容入口。

ChatGPT 账号凭据保存在用户数据目录的 `chatgpt.sqlite3` 中，由当前 Windows 用户的 DPAPI 加密。桌面桥接只返回账号概要、授权状态和模型目录。设置保存选中的账号及模型标识。

## 状态页

桌面侧栏的「状态」打开后立即刷新，可见时每 3 秒读取一次，也可手动刷新。在顶部查看服务和播放连接，在「本地模型与资源」查看当前加载的模型和服务资源占用，在「字幕性能」查看最近处理速度，在「云端用量」查看最近 8 个自然周（含本周）。[English](en/status.md)

| 区域 | 查看内容 |
| --- | --- |
| 服务与入口 | 显示服务是否就绪。活跃播放连接和正在处理的文本请求按 PotPlayer、mpv、命令行、MCP 和其他 HTTP 客户端汇总。关闭连接或心跳过期后，路数会下降。 |
| 本地模型与资源 | 显示识别、翻译和语音活动检测所用的本地模型及 CPU、CUDA 或 Vulkan 设备。可用时显示后台进程及其子进程的 CPU、RAM、GPU 及显存。 |
| 字幕性能 | 显示最近 15 分钟、每项最多 1,024 条的样本。RTF 低于 1 表示一个新片段处理得比对应音频播放更快。端到端延迟从服务收到需要生成字幕的播放更新起算，到下一次发送可用字幕响应为止。每组指标显示采样数。 |
| 云端用量 | 从周一开始按 UTC 周汇总，按提供商、模型、用途显示本机调用、失败、已知用量及美元估算。缺少用量、费率或使用订阅时显示对应状态。服务停止后也可查看已有周汇总。 |

冷启动或刚开始播放时，性能区会显示等待样本。性能统计只在内存中保留，重启后重新采样。云端周汇总存储在本机，服务启动或写入时清理过期周；指标不记录文件名、字幕、账号、密钥、会话 ID 或请求内容。更多口径和接口见 [HTTP 服务](server.md)。

WPF 直接读本机状态接口。服务未响应时，界面通过桌面桥接 `cloud-usage` 读取默认缓存目录下的 `cloud-usage.sqlite3`，不会启动后台。
