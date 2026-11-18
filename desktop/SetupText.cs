using System.Globalization;

namespace AheadSubs;

internal static class SetupText
{
    private static readonly Dictionary<string, (string English, string Chinese)> Resources = new()
    {
        ["heading"] = ("Setup presets", "快速预设"),
        ["active"] = ("Setup presets · {0}", "快速预设 · {0}"),
        ["custom"] = ("Custom", "自定义"),
        ["cpu"] = ("Local · CPU", "纯本地 · CPU"),
        ["gpu"] = ("Local · Entry GPU", "纯本地 · 独显入门"),
        ["high-gpu"] = ("Local · High-performance GPU", "纯本地 · 高性能 GPU"),
        ["recommended"] = ("Recommended · Local speech + cloud translation", "作者推荐 · 本地识别 + 云端翻译"),
        ["detail-cpu"] = ("Whisper Small + NLLB · CPU", "Whisper Small + NLLB · CPU"),
        ["detail-gpu"] = ("Qwen3-ASR 0.6B · Vulkan / NLLB · CPU", "Qwen3-ASR 0.6B · Vulkan / NLLB · CPU"),
        ["detail-high-gpu"] = ("Qwen3-ASR 1.7B · Vulkan / NLLB · NVIDIA CUDA", "Qwen3-ASR 1.7B · Vulkan / NLLB · NVIDIA CUDA"),
        ["detail-recommended"] = ("Qwen3-ASR 1.7B · Vulkan / Qwen-MT Flash · Bailian API key required", "Qwen3-ASR 1.7B · Vulkan / Qwen-MT Flash · 需百炼 API Key"),
        ["missing"] = ("Download required: {0}", "待下载：{0}"),
        ["checking"] = ("Checking requirements…", "正在检查运行条件…"),
        ["ready"] = ("Ready to apply.", "已就绪，可以应用。"),
        ["retry"] = ("Check again", "重新检查"),
        ["check-failed"] = ("Could not check this preset. Try again.", "暂时无法检查这套方案，请重试。"),
        ["ffmpeg"] = ("FFmpeg and FFprobe are required. Use a complete Windows package.", "需要 FFmpeg 和 FFprobe，请使用完整的 Windows 安装包。"),
        ["vulkan"] = ("No Vulkan device detected. Check the graphics driver or choose Local · CPU.", "未检测到 Vulkan 设备。请检查显卡驱动，或选择纯本地 CPU 方案。"),
        ["cuda"] = ("NVIDIA CUDA is unavailable. Check the driver and CUDA package, or choose Local · Entry GPU.", "CUDA 不可用。请检查 NVIDIA 驱动和 CUDA 安装包，或选择纯本地独显入门方案。"),
        ["dashscope"] = ("Save your Bailian API key and check the service URL.", "请保存百炼 API Key，并检查服务地址。"),
        ["models"] = ("Manage models", "管理模型"),
        ["download"] = ("Download now", "立即下载"),
        ["keys"] = ("Configure Bailian", "配置百炼"),
        ["apply"] = ("Apply preset", "应用方案"),
        ["applying"] = ("Applying preset…", "正在应用方案…"),
        ["restart-models"] = ("Waiting for current work to finish, then reloading local models…", "正在等待当前任务结束，随后会重新加载本地模型…"),
        ["restart"] = ("Restarting the subtitle service. Waiting for current work to finish…", "正在重启字幕服务，等待当前任务结束…"),
        ["load-models"] = ("Loading local models. This may take a moment…", "正在加载本地模型，可能需要一些时间…"),
        ["start"] = ("Starting the subtitle service…", "正在启动字幕服务…"),
        ["applied"] = ("Preset applied.", "已应用方案。"),
        ["downloading"] = ("Downloading {0}…", "正在下载 {0}…"),
        ["downloaded"] = ("Download complete.", "下载完成。"),
        ["download-failed"] = ("Download failed. Check your connection and available disk space, then retry.", "下载失败。请检查网络连接和剩余磁盘空间，再重试。"),
        ["needed"] = ("Required by the selected preset", "所选方案需要"),
        ["model-page"] = ("Local models", "本地模型"),
        ["model-asr"] = ("Speech recognition", "语音识别"),
        ["model-mt"] = ("Translation", "字幕翻译"),
        ["model-vad"] = ("Voice activity detection", "语音检测"),
        ["managed-vad"] = ("Silero is bundled. FSMN is prepared when selected in Advanced settings.", "Silero 随运行环境提供，FSMN 在高级设置中选用后准备。"),
        ["installed-model"] = ("Installed", "已下载"),
        ["active-model"] = ("Installed · In use", "已下载 · 使用中"),
        ["download-model"] = ("Download", "下载"),
        ["remove-model"] = ("Uninstall", "卸载"),
        ["uninstall-ask"] = ("Uninstall {0}? Models in the shared Hugging Face cache may also be used by other apps.", "卸载 {0}？其他应用也可能在使用 Hugging Face 共享缓存里的模型。"),
        ["uninstall-ask-local"] = ("Uninstall {0}?", "卸载 {0}？"),
        ["uninstall-active"] = ("Switch to another model or stop the subtitle service before uninstalling this model.", "请先切换模型或停止字幕服务，再卸载这个模型。"),
        ["uninstall-incomplete"] = ("This model's cache is incomplete and could not be removed.", "缓存不完整，无法卸载这个模型。"),
        ["uninstall-location"] = ("The cache path is outside this model's repository.", "缓存位置不属于这个模型，无法卸载。"),
        ["uninstall-failed"] = ("Could not remove the model cache. Close other apps using it and try again.", "模型缓存未能完全删除，请关闭其他正在使用它的应用后重试。"),
        ["uninstalling"] = ("Uninstalling {0}…", "正在卸载 {0}…"),
        ["uninstalled"] = ("Model uninstalled.", "已卸载模型。"),
        ["model-info"] = ("{0} · about {1:0.00} GB", "{0} · 约 {1:0.00} GB"),
        ["shared-info"] = ("Both Qwen3-ASR models share about 0.71 GB for alignment, automatic language detection, and the runtime.", "两款 Qwen3-ASR 共用约 0.71 GB 的对齐模型、自动语言检测模型和运行库。"),
        ["whisper-device"] = ("Whisper Small device", "Whisper Small 运算设备"),
        ["nllb-device"] = ("NLLB device", "NLLB 运算设备"),
        ["cpu-device"] = ("CPU", "CPU"),
        ["cuda-device"] = ("NVIDIA CUDA", "NVIDIA CUDA"),
        ["asr-device"] = ("Speech: {0}", "识别：{0}"),
        ["mt-device"] = ("Translation: {0}", "翻译：{0}"),
    };

    internal static string Get(string key, params object[] args) => Format(CultureInfo.CurrentUICulture, key, args);

    internal static string? Error(string? key) => key is not null && Resources.ContainsKey(key) ? Get(key) : null;

    internal static string Format(CultureInfo culture, string key, params object[] args)
    {
        var text = Resources[key];
        return string.Format(culture, culture.Name is "zh-CN" or "zh-Hans" or "zh-SG" or "zh" ? text.Chinese : text.English, args);
    }
}
