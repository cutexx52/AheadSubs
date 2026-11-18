using System.Globalization;

namespace AheadSubs;

internal static class CloudPrices
{
    private const decimal CnyPerUsd = 6.7132m;
    private const decimal Million = 1_000_000;

    internal static string Hourly(string model, string endpoint, CultureInfo language)
    {
        decimal low, high;
        switch (model)
        {
            case "openai":
                low = .006m * 30 * CnyPerUsd;
                high = low * 2;
                break;
            case "gpt-4.1-mini":
                low = (300 * (120 * .40m + 12 * 1.60m)) / Million * CnyPerUsd;
                high = (900 * (400 * .40m + 20 * 1.60m)) / Million * CnyPerUsd;
                break;
            default:
                bool singapore;
                if (string.IsNullOrWhiteSpace(endpoint))
                    singapore = false;
                else if (Uri.TryCreate(endpoint, UriKind.Absolute, out var url) &&
                         (url.Host == "dashscope-intl.aliyuncs.com" || url.Host.EndsWith(".ap-southeast-1.maas.aliyuncs.com")))
                    singapore = true;
                else if (url is not null &&
                         (url.Host == "dashscope.aliyuncs.com" || url.Host.EndsWith(".cn-beijing.maas.aliyuncs.com")))
                    singapore = false;
                else
                    return "";
                switch (model)
                {
                    case "qwen-audio-3.1-asr-flash":
                        decimal perSecond = singapore ? 13.1m * 1.094m + 2m * 3.427m : 13.1m * .8m + 2m * 2.7m;
                        low = 1800 * perSecond / Million;
                        high = low * 2;
                        break;
                    case "qwen-audio-3.0-asr-flash":
                        low = 1800 * (singapore ? .00026m : .00022m);
                        high = low * 2;
                        break;
                    default:
                        var (input, output) = model switch
                        {
                            "qwen-mt-flash" => singapore ? (1.174m, 3.596m) : (.7m, 1.95m),
                            "qwen-mt-lite" => singapore ? (.881m, 2.642m) : (.6m, 1.6m),
                            "qwen-mt-plus" => singapore ? (18.055m, 54.09m) : (1.8m, 5.4m),
                            _ => (0m, 0m)
                        };
                        if (input == 0) return "";
                        low = 300 * (47 * input + 12 * output) / Million;
                        high = low * 3;
                        break;
                }
                break;
        }
        bool chinese = language.Name == "zh-CN";
        decimal conversion = chinese ? 1 : CnyPerUsd;
        return chinese
            ? $"约 ¥{low / conversion:F2}–{high / conversion:F2}/小时"
            : $"~US${(low / conversion).ToString("F2", language)}–{(high / conversion).ToString("F2", language)}/hr";
    }
}
