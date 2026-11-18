using System.Globalization;
using System.Resources;

namespace AheadSubs;

internal static class SetupText
{
    private static readonly ResourceManager Resources = new("AheadSubs.SetupStrings", typeof(SetupText).Assembly);

    internal static string Get(string key, params object[] args) => Format(InterfaceLocale.Culture, key, args);
    internal static string? Error(string? key) => key is null ? null : Resources.GetString(key, InterfaceLocale.Culture);
    internal static string Format(CultureInfo culture, string key, params object[] args) =>
        string.Format(culture, Resources.GetString(key, culture) ?? key, args);
}
