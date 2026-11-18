using System.Resources;

namespace AheadSubs;

internal static class StatusText
{
    internal static readonly ResourceManager Resources = new(
        "AheadSubs.StatusText", typeof(StatusText).Assembly);

    public static string Get(string key) => Resources.GetString(key, AutomationText.Culture) ?? key;
    public static string Format(string key, params object[] args) => string.Format(AutomationText.Culture, Get(key), args);
}
