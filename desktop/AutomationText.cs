using System.Globalization;
using System.Resources;

namespace AheadSubs;

internal static class AutomationText
{
    internal static readonly ResourceManager Resources = new(
        "AheadSubs.AutomationText", typeof(AutomationText).Assembly);

    public static CultureInfo Culture => InterfaceLocale.Culture;

    public static string Get(string key, CultureInfo? culture = null) =>
        Resources.GetString(key, culture ?? Culture) ?? key;
}
