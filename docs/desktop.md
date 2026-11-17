# Windows 桌面助手

[English desktop guide](en/desktop.md)

## 日常使用

在 **翻译** 首页展开 **快速预设**，检查所需的模型、运行库和密钥。缺少模型时可以 **立即下载**，也可以去 **管理模型** 查看标出的缺项。下载完成后点击 **应用方案**，字幕的源语言、目标语言和双语选项保留。预设默认折叠；手动搭配的设置显示为 **自定义**。

| 预设 | 语音识别 | 字幕翻译 |
| --- | --- | --- |
| 纯本地 · CPU | Whisper Small · CPU | NLLB · CPU |
| 纯本地 · 独显入门 | Qwen3-ASR 0.6B · Vulkan | NLLB · CPU |
| 纯本地 · 高性能 GPU | Qwen3-ASR 1.7B · Vulkan | NLLB · NVIDIA CUDA |
| 作者推荐 · 本地识别 + 云端翻译 | Qwen3-ASR 1.7B · Vulkan | Qwen-MT Flash · 百炼 API |

独显方案检查 Vulkan 设备，高性能方案另外检查 CUDA 设备和运行库。推荐方案检查已保存的百炼密钥是否可读取以及地址格式；实际凭据是否有效由服务请求验证。配置并保存密钥后返回首页会重新检查。下载失败后可再次点击 **立即下载**，已完整下载的模型会被复用。

**本地模型**分为语音识别、字幕翻译和语音检测。Whisper 和 NLLB 可独立选 CPU 或 NVIDIA CUDA，点 **保存并应用** 生效。旧配置沿用已有设备选项。运行中的模型要先切换或停止服务，再卸载。Whisper 和 NLLB 的下载放在 Hugging Face 共享缓存中，卸载会移除对应仓库的缓存。Qwen3-ASR 卸载会保留共享的约 0.63 GB 的对齐模型和运行库，其他版本可继续使用。Silero 随环境提供，FSMN 在 **高级设置** 中选用后准备。

**云端模型**可按供应商选择 **密钥文件** 或 **直接填写**。直填内容用 Windows 当前用户的 [DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata) 加密保存。文件模式保存所选文件的路径。删除直填密钥时，切回 **默认（环境变量）** 并保存。百炼的识别和翻译共用密钥及区域地址，自定义识别和翻译可以各用一把。远程自定义接口发送密钥时使用 HTTPS，本机回环地址支持 HTTP。可以先 **保存密钥**，再应用翻译设置切换当前服务。

选择 **ChatGPT 订阅 · OAuth** 可以在浏览器授权 AheadSubs 使用 ChatGPT 订阅做字幕文本翻译。MiniMax 支持 M Plan 专用 Key 和按量 API Key。参见[推理与翻译后端](providers.md)。

**上下文增强**按翻译模型保存。支持前文的模型可参考 0–8 个已识别的前文片段，每段默认最多 250 字符，可设为 20–1000 字符。请求优先保留最近的前文，总计最多 1000 字符，输出仍对应当前字幕。前文有助于改善指代和术语的翻译，也可能增加 token 用量和延迟。设为 0 时仍可使用翻译提示词。Qwen-MT Flash 和 Plus 只提供风格提示词。

设置窗口为单实例。关闭窗口后可双击 Windows 托盘图标重新打开。托盘菜单的 **停止字幕服务** 释放模型资源并保留窗口入口，**停止并退出** 同时关闭助手。退出后重新运行助手并启动服务，播放器才能继续提交新任务。已经写入磁盘的缓存可复用。

## 字幕检查

打开 **字幕检查**，按文件名或路径搜索，也可按主要源语言筛选。文件按记录的路径归并，默认打开最新版本，可切换到历史版本。移动文件会产生新的条目。升级前只记录文件名的条目保持独立，直到以相同缓存条件重放并补记路径。

覆盖率表示选定版本已处理的时间占媒体总时长的比例，静音也计入；缺少时长时显示未知。主要源语言按识别片段的时长统计，未提供语言的后端会显示未知。筛选按该文件最近一个有语言记录的版本进行。已有字幕的目标语言从该文件的各版本汇总。

选择 **重新生成** 后，运行中的服务会按所选版本的音轨及语言、当前服务的模型生成新版本，一次处理一个文件。后台只在播放会话空闲时启动下一段。任务失败或服务退出时会保留已写入的字幕和旧版本，可以刷新查看状态并再次生成。文件移动或替换后，先重新播放以记录新文件。

**打开 SRT** 在记事本中查看所选版本的目标字幕。**另存 SRT** 可保存同一内容，包括所选版本已经生成的全部字幕，适用于尚未处理完整的文件。历史路径、生成状态和字幕保存在本机缓存中。

## 诊断模式

正常模式关闭诊断日志。遇到问题时，在 **高级设置** 勾选 **启用诊断日志** 并应用，再复现问题。若需要诊断整段播放器会话，可以停一次预读再开启。用 **打开日志目录** 查看结果。命令行可用 `python -m subtitle_relay serve --diagnostics`。

源代码助手把服务和播放器日志保存在 `%LOCALAPPDATA%\Subtitle Relay`。分享诊断前，检查记录中的本地文件路径、主机名和 URL。定位结束后可以关闭诊断模式。

## 模块接口

打包启动器运行 `UI/AheadSubs.exe`。WPF 界面使用 `python -m subtitle_relay.desktop.bridge` 管理后台。该入口与播放器使用的 [HTTP 会话接口](server.md) 各自独立。

| 命令 | 输入与行为 |
| --- | --- |
| `status` | 输出 `settings`、`models`、`active_models`、`credentials`、`integrations`、`chatgpt_accounts` 和服务状态。凭据状态只包含模式、文件路径和是否已保存直填密钥。 |
| `preset-check [requirements]` | 检查 FFmpeg 和逗号分隔的 `vulkan`、`cuda`、`dashscope` 条件，返回缺项代码 `missing`。stdin 可提供 `{"qwen_mt_url": "…"}` 检查候选地址，密钥使用已保存配置。 |
| `install <model>` / `uninstall <model>` | 下载或卸载指定本地模型。标识见控制模块中的 `MODELS`。 |
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
| `inspect-library` | 读取本地缓存，返回按路径归并的 `files`，含版本、覆盖率和语言摘要。 |
| `inspect-rows <key>` | 返回指定版本最近的原文、字幕和失败行。 |
| `inspect-regenerate <key>` | 向运行中的桌面服务排队，返回新版本的 `key`。 |
| `inspect-srt <key>` | 从 stdin 读取 `{"output":"…"}` 并返回 `subtitle` 路径。目标为 `null` 时写入缓存内用于查看的 SRT。 |
| `automation [mcp-enable\|mcp-disable\|cli-install\|cli-remove]` | 返回 MCP 开关、客户端配置和 CLI 的用户 PATH 注册状态。指定操作时直接更新对应状态。详见[接入说明](automation.md)。 |

每次调用向 stdout 输出一个 JSON 对象，带 `ok` 布尔值。失败时带 `error` 并返回非零退出码。它是项目内的桌面控制接口，外部适配器应以公开的 HTTP v1 合约为准。

运行时使用 `%LOCALAPPDATA%\Subtitle Relay\settings.json` 保存设置，模型、缓存及控制令牌也留在用户数据目录。独立启动并使用不同控制令牌的服务由其启动方管理。源码入口 `Subtitle Relay.pyw` 仍可用；它也承担播放器回调和 Windows 反馈工具的兼容入口。

ChatGPT 账号凭据保存在用户数据目录的 `chatgpt.sqlite3` 中，由当前 Windows 用户的 DPAPI 加密。桌面桥接只返回账号概要、授权状态和模型目录。设置保存选中的账号及模型标识。
