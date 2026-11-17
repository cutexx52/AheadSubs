using System.Globalization;
using System.Resources;

namespace LocalVideoSubtitleTranslator;

internal static class InspectionText
{
    private static readonly ResourceManager Resources = new(
        "LocalVideoSubtitleTranslator.InspectionText", typeof(InspectionText).Assembly);

    public static CultureInfo Culture => AutomationText.Culture;

    public static string Get(string key, params object[] values)
    {
        string format = Resources.GetString(key, Culture) ?? key;
        return values.Length == 0 ? format : string.Format(Culture, format, values);
    }

    public static string? Error(string? code) =>
        code is null ? null : Resources.GetString("Error_" + code, Culture);

    public static string Language(string? code) =>
        code is null ? Get("Unknown") : Resources.GetString("Language_" + code.ToLowerInvariant(), Culture) ?? code;
}
