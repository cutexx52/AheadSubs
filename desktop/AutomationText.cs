using System.Globalization;
using System.Resources;

namespace AheadSubs;

internal static class AutomationText
{
    private static readonly ResourceManager Resources = new(
        "AheadSubs.AutomationText", typeof(AutomationText).Assembly);

    public static CultureInfo ResolveCulture(string name)
    {
        return name.Replace('_', '-').ToLowerInvariant() switch
        {
            "zh" or "zh-cn" or "zh-sg" or "zh-hans" or "zh-hans-cn" => CultureInfo.GetCultureInfo("zh-CN"),
            _ => CultureInfo.GetCultureInfo("en")
        };
    }

    public static CultureInfo Culture { get; } = ResolveCulture(
        Environment.GetEnvironmentVariable("AHEADSUBS_UI_LOCALE") ?? CultureInfo.CurrentUICulture.Name);

    public static string Get(string key, CultureInfo? culture = null) =>
        Resources.GetString(key, culture ?? Culture) ?? key;
}
