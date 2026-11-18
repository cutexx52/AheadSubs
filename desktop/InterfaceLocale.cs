using System.Globalization;
using System.IO;
using System.Resources;
using System.Security;
using System.Windows;
using Microsoft.Win32;

namespace AheadSubs;

internal static class InterfaceLocale
{
    internal const string Automatic = "auto";
    private const string Preferences = @"Software\AheadSubs\Desktop";
    internal static readonly (string Target, string Locale, string NativeName)[] Languages =
    [
        ("zh", "zh-CN", "简体中文"), ("zh-TW", "zh-TW", "繁體中文"),
        ("ja", "ja", "日本語"), ("en", "en", "English"), ("ko", "ko", "한국어"),
        ("fr", "fr", "Français"), ("de", "de", "Deutsch"), ("es", "es", "Español")
    ];

    internal static string Preference { get; private set; } = Automatic;
    internal static CultureInfo Culture { get; private set; } = CultureInfo.GetCultureInfo("en");

    internal static CultureInfo Resolve(string? language)
    {
        try
        {
            var culture = CultureInfo.GetCultureInfo((language ?? "").Replace('_', '-'));
            for (; culture.Name.Length > 0; culture = culture.Parent)
            {
                if (culture.Name is "zh-Hant" or "zh-TW" or "zh-HK" or "zh-MO") return CultureInfo.GetCultureInfo("zh-TW");
                if (culture.Name is "zh-Hans" or "zh") return CultureInfo.GetCultureInfo("zh-CN");
                foreach (var item in Languages)
                    if (culture.Name == item.Locale) return CultureInfo.GetCultureInfo(item.Locale);
            }
        }
        catch (CultureNotFoundException) { }
        return CultureInfo.GetCultureInfo("en");
    }

    internal static void Initialize(bool preview, string? previewLanguage)
    {
        if (!preview)
        {
            try
            {
                using var key = Registry.CurrentUser.OpenSubKey(Preferences);
                if (key?.GetValue("Language") is string value && Languages.Any(item => item.Locale == value))
                    Preference = value;
            }
            catch (Exception ex) when (PreferenceError(ex)) { }
        }
        Apply(previewLanguage);
    }

    internal static bool Select(string value, bool persist)
    {
        if (persist)
        {
            try
            {
                using var key = Registry.CurrentUser.CreateSubKey(Preferences);
                key.SetValue("Language", value);
            }
            catch (Exception ex) when (PreferenceError(ex)) { return false; }
        }
        Preference = value;
        Apply(null);
        return true;
    }

    private static bool PreferenceError(Exception ex) => ex is IOException or UnauthorizedAccessException or SecurityException;

    internal static bool Apply(string? previewLanguage)
    {
        // Keep Windows' UI culture untouched so automatic mode can consult it after a manual choice.
        var culture = Resolve(previewLanguage ?? (Preference == Automatic
            ? Environment.GetEnvironmentVariable("AHEADSUBS_UI_LOCALE") ?? CultureInfo.CurrentUICulture.Name
            : Preference));
        bool changed = !Culture.Equals(culture);
        Culture = culture;
        if (changed || !System.Windows.Application.Current.Resources.Contains("Desktop.InterfaceLanguage"))
        {
            LoadResources("Desktop", UiText.Resources);
            LoadResources("Automation", AutomationText.Resources);
            LoadResources("Status", StatusText.Resources);
        }
        return changed;
    }
    private static void LoadResources(string group, ResourceManager manager)
    {
        var resources = System.Windows.Application.Current.Resources;
        foreach (System.Collections.DictionaryEntry entry in manager.GetResourceSet(CultureInfo.InvariantCulture, true, true)!)
        {
            string key = (string)entry.Key;
            resources[group + "." + key] = manager.GetString(key, Culture);
        }
    }
}

internal static class UiText
{
    internal static readonly ResourceManager Resources = new("AheadSubs.DesktopStrings", typeof(UiText).Assembly);
    internal static string Get(string key, params object[] args)
    {
        var template = Resources.GetString(key, InterfaceLocale.Culture) ?? key;
        return args.Length == 0 ? template : string.Format(InterfaceLocale.Culture, template, args);
    }
}
