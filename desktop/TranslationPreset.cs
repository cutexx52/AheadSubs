namespace AheadSubs;

internal sealed record TranslationPreset(string Id, string Speech, string Translation, string Device,
    string[] Models, bool UsesVulkan = false, bool NeedsDashScope = false)
{
    internal static readonly TranslationPreset[] All =
    [
        new("cpu", "whisper-small", "nllb", "cpu", ["whisper-small", "nllb"]),
        new("gpu", "qwen-0.6b", "nllb", "cpu", ["qwen-0.6b", "nllb"], UsesVulkan: true),
        new("high-gpu", "qwen-1.7b", "nllb", "cuda", ["qwen-1.7b", "nllb"], UsesVulkan: true),
        new("recommended", "qwen-1.7b", "qwen-mt-flash", "cpu", ["qwen-1.7b"],
            UsesVulkan: true, NeedsDashScope: true),
    ];

    internal string[] MissingModels(Func<string, bool> installed) => Models.Where(id => !installed(id)).ToArray();
}
