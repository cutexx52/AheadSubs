"""Localized text for the automation interfaces. Protocol identifiers stay invariant."""
import locale
import os


MESSAGES = {
    "operation.status": (
        "Check whether the local subtitle service is running.",
        "查询本机字幕服务是否在运行。",
    ),
    "operation.translate_text": (
        "Translate text using the active AheadSubs translation provider.",
        "使用当前 AheadSubs 翻译服务处理文本。",
    ),
    "operation.generate_subtitles": (
        "Generate a complete SRT for a local media file using the active profile.",
        "使用当前配置为本机媒体生成完整 SRT。",
    ),
    "operation.update_playback": (
        "Start or refresh a look-ahead session. Poll with the same ID. Sessions expire after 10 seconds of inactivity.",
        "开启或刷新预读会话。轮询时使用同一 ID，会话在 10 秒无更新后过期。",
    ),
    "operation.close_playback": (
        "Release a look-ahead session and retain its cached subtitles.",
        "释放预读会话并保留缓存字幕。",
    ),
    "field.path": (
        "Path to a local media file",
        "本机媒体文件路径",
    ),
    "field.text": (
        "Text to translate (up to 4000 characters)",
        "待翻译文本（最多 4000 字符）",
    ),
    "field.text_stdin": (
        "{description} (use - to read from stdin)",
        "{description}。用 - 从标准输入读取。",
    ),
    "field.source": (
        "Source language code, for example ja",
        "来源语言代码，例如 ja",
    ),
    "field.target": (
        "Target language code, for example zh",
        "目标语言代码，例如 zh",
    ),
    "field.media_source": (
        "Source language code. Use auto for detection. Omit for the service default.",
        "来源语言代码。用 auto 自动识别，省略时沿用服务默认值。",
    ),
    "field.media_target": (
        "Target language code. Omit for the service default.",
        "目标语言代码。省略时沿用服务默认值。",
    ),
    "field.audio": (
        "Zero-based audio stream ordinal",
        "从零开始的音轨序号",
    ),
    "field.bilingual": (
        "Include original text. Omit for the service default.",
        "包含字幕原文。省略时沿用服务默认值。",
    ),
    "field.session": (
        "Unique playback session ID",
        "唯一的播放会话 ID",
    ),
    "field.position": (
        "Position in media seconds",
        "媒体时间位置，单位为秒",
    ),
    "field.duration": (
        "Total media duration in seconds",
        "媒体总时长，单位为秒",
    ),
    "field.speed": (
        "Playback speed",
        "播放速度",
    ),
    "field.ahead": (
        "Look-ahead in seconds",
        "预读时长，单位为秒",
    ),
    "field.output": (
        "Destination .srt file in an existing directory",
        "已存在目录中的 .srt 输出文件",
    ),
    "field.overwrite": (
        "Replace an existing destination file",
        "替换已有的输出文件",
    ),
    "field.timeout": (
        "Maximum processing time in seconds",
        "最长处理时间，单位为秒",
    ),
    "cli.intro": (
        "Automate the local AheadSubs subtitle service.",
        "自动化调用本机 AheadSubs 字幕服务。",
    ),
    "cli.port": (
        "Local subtitle service port",
        "本机字幕服务端口",
    ),
    "cli.port_error": (
        "Port must be between 1 and 65535.",
        "端口必须在 1 到 65535 之间。",
    ),
    "cli.mcp": (
        "Run the MCP stdio server for a local agent",
        "为本机 Agent 运行 MCP stdio 服务",
    ),
    "cli.desktop": (
        "Honor the desktop app's MCP access switch",
        "遵循桌面应用的 MCP 接入开关",
    ),
    "error.media_not_found": (
        "Choose a media file accessible to the local AheadSubs service.",
        "请选择本机 AheadSubs 字幕服务可以访问的媒体文件。",
    ),
    "error.ffprobe_not_found": (
        "FFprobe was not found. Use the Windows bundle or put FFprobe on PATH.",
        "找不到 FFprobe。请使用 Windows 发布包，或将 FFprobe 添加到 PATH。",
    ),
    "error.invalid_media": (
        "FFprobe could not determine a supported media duration.",
        "FFprobe 无法确定有效的媒体时长。",
    ),
    "error.invalid_audio": (
        "The selected audio stream does not exist.",
        "所选音轨不存在。",
    ),
    "error.unexpected_service": (
        "The configured port is not serving AheadSubs.",
        "指定的端口没有运行 AheadSubs。",
    ),
    "error.invalid_output": (
        "Choose a separate .srt destination in an existing directory.",
        "请在已存在的目录中选择单独的 .srt 输出文件。",
    ),
    "error.generation_timeout": (
        "Subtitle generation timed out. Completed chunks can be reused on retry.",
        "字幕生成超时。重试时可复用已完成的分块。",
    ),
    "error.generation_changed": (
        "The media or service profile changed during processing. Retry the export.",
        "处理期间媒体或服务配置发生变化，请重试导出。",
    ),
    "error.unknown_operation": (
        "Unknown AheadSubs operation.",
        "未知的 AheadSubs 操作。",
    ),
    "error.invalid_arguments": (
        "Check the value of {field} against the command help or tool schema.",
        "请参照命令帮助或工具参数定义检查 {field} 的值。",
    ),
    "error.request_timeout": (
        "The local AheadSubs request or media probe timed out.",
        "本机 AheadSubs 请求或媒体探测超时。",
    ),
    "error.service_unavailable": (
        "Start AheadSubs or check the local service port ({port}).",
        "请启动 AheadSubs 或检查本机服务端口（{port}）。",
    ),
    "error.output_exists": (
        "The destination already exists. Set overwrite to replace it.",
        "输出文件已存在。设置 overwrite 可替换该文件。",
    ),
    "error.operation_failed": (
        "AheadSubs could not complete the operation. Check the files and local service.",
        "AheadSubs 无法完成该操作。请检查文件和本机服务。",
    ),
    "error.mcp_disabled": (
        "MCP access is off. Enable it in the AheadSubs desktop app.",
        "MCP 接入已关闭。请在 AheadSubs 桌面应用内打开。",
    ),
    "error.cli_not_bundled": (
        "From a source checkout, run python -m pip install . to install the CLI.",
        "源码运行时请执行 python -m pip install . 安装 CLI。",
    ),
    "error.integration_action": (
        "Unknown AheadSubs integration action.",
        "不支持的 AheadSubs 接入操作。",
    ),
}


def text(key, **values):
    name = os.getenv("AHEADSUBS_UI_LOCALE")
    if name is None:
        name = locale.getlocale()[0] or ""
    name = name.replace("_", "-").lower()
    chinese = name in {"zh", "zh-cn", "zh-sg", "zh-hans", "zh-hans-cn"} or name.startswith("chinese (simplified)")
    variants = MESSAGES[key]
    return (variants[1] or variants[0] if chinese else variants[0]).format(**values)
