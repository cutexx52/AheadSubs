using System.Resources;
using System.Windows.Markup;

namespace AheadSubs;

internal static class StatusText
{
    private static readonly ResourceManager Resources = new(
        "AheadSubs.StatusText", typeof(StatusText).Assembly);

    public static string Get(string key) => Resources.GetString(key, AutomationText.Culture) ?? key;
    public static string Format(string key, params object[] args) => string.Format(AutomationText.Culture, Get(key), args);
}

[MarkupExtensionReturnType(typeof(string))]
public sealed class StatusTextExtension(string key) : MarkupExtension
{
    public override object ProvideValue(IServiceProvider serviceProvider) => StatusText.Get(key);
}
