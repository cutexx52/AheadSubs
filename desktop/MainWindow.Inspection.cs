using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Threading;
using static LocalVideoSubtitleTranslator.InspectionText;

namespace LocalVideoSubtitleTranslator;

public partial class MainWindow
{
    private sealed record SubtitleVersion(string Key, double Created, string? Source, string Target,
        int? Audio, double? Coverage, bool HasSubtitles, bool CanRegenerate, string? State, string? ErrorCode)
    {
        public bool IsPending => State is "queued" or "running";

        public string Label => Get("VersionChoice",
            DateTimeOffset.UnixEpoch.AddSeconds(Created).ToLocalTime().ToString("G", Culture), InspectionText.Language(Target),
            Audio is int index ? (index + 1).ToString(Culture) : Get("Unknown"));
    }

    private sealed record SubtitleFile(string Id, string Name, string? Path, string? Source,
        string[] Targets, SubtitleVersion[] Versions)
    {
        public string Location => Path is null ? Get("PathUnknown") : System.IO.Path.GetDirectoryName(Path) ?? Path;
    }

    private sealed record SubtitleRow(string Time, string Original, string Translation);

    private SubtitleFile[] subtitleFiles = [];
    private readonly DispatcherTimer inspectionTimer = new() { Interval = TimeSpan.FromSeconds(4) };
    private CancellationTokenSource? rowRequest;
    private string? requestedRows;
    private bool refreshingLibrary, settingInspectionChoices, inspectionAction;
    private string? pinnedVersion;

    private void InitializeInspection()
    {
        InspectTab.Language = System.Windows.Markup.XmlLanguage.GetLanguage(Culture.Name);
        InspectTab.Header = Get("Tab");
        InspectTitle.Text = Get("Title");
        InspectSearchLabel.Content = Get("Search");
        InspectVersionLabel.Content = Get("Version");
        InspectRefreshButton.Content = Get("Refresh");
        InspectRegenerate.Content = Get("Regenerate");
        InspectOpen.Content = Get("Open");
        InspectSave.Content = Get("Save");
        InspectTimeColumn.Header = Get("Time");
        InspectOriginalColumn.Header = Get("Original");
        InspectTranslationColumn.Header = Get("Translation");
        AutomationProperties.SetName(SourceFilter, Get("Filter"));
        AutomationProperties.SetName(MediaList, Get("Files"));
        InspectStatus.Text = Get("EmptyLibrary");
        inspectionTimer.Tick += async (_, _) =>
        {
            if (IsVisible && SettingsPanel.SelectedItem == InspectTab && !inspectionAction)
                await Inspect(quiet: true);
        };
        SetInspectionFiles([], null);
    }

    private SubtitleVersion? SelectedVersion()
    {
        string? key = VersionChoice.SelectedValue as string;
        return (MediaList.SelectedItem as SubtitleFile)?.Versions.FirstOrDefault(version => version.Key == key);
    }

    private async void RefreshSubtitles(object sender, RoutedEventArgs e) => await Inspect();

    private async Task Inspect(bool quiet = false)
    {
        if (refreshingLibrary || previewMode) return;
        refreshingLibrary = true;
        InspectRefreshButton.IsEnabled = false;
        if (!quiet) InspectStatus.Text = Get("Loading");
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
            var result = await bridge.Run("inspect-library", cancellationToken: timeout.Token);
            var files = (result["files"]?.AsArray() ?? []).OfType<JsonObject>().Select(ParseSubtitleFile).ToArray();
            SetInspectionFiles(files, (MediaList.SelectedItem as SubtitleFile)?.Id);
            await LoadInspectionRows(refresh: true);
        }
        catch (Exception) { InspectStatus.Text = Get("ReadFailed"); }
        finally
        {
            refreshingLibrary = false;
            InspectRefreshButton.IsEnabled = true;
        }
    }

    private static SubtitleFile ParseSubtitleFile(JsonObject file)
    {
        var versions = file["versions"]!.AsArray().OfType<JsonObject>()
            .Select(version => new SubtitleVersion(
                version["key"]!.GetValue<string>(), (version["created"] ?? version["updated"])!.GetValue<double>(),
                version["primary_source"]?.GetValue<string>(), version["target"]!.GetValue<string>(),
                version["audio"]?.GetValue<int>(), version["coverage"]?.GetValue<double>(),
                version["has_subtitles"]!.GetValue<bool>(), version["can_regenerate"]!.GetValue<bool>(),
                version["state"]?.GetValue<string>(), version["error_code"]?.GetValue<string>())).ToArray();
        return new(file["id"]!.GetValue<string>(), file["display_name"]!.GetValue<string>(),
            file["path"]?.GetValue<string>(), file["primary_source"]?.GetValue<string>(),
            file["target_languages"]!.AsArray().Select(language => language!.GetValue<string>()).ToArray(), versions);
    }

    private void SetInspectionFiles(SubtitleFile[] files, string? selectedId)
    {
        subtitleFiles = files;
        string? filter = SourceFilter.SelectedValue as string;
        var options = files.Select(file => file.Source ?? "und").Distinct()
            .Select(code => new Choice(InspectionText.Language(code == "und" ? null : code), code))
            .OrderBy(option => option.Label, StringComparer.Create(Culture, ignoreCase: true)).ToArray();
        settingInspectionChoices = true;
        try
        {
            SourceFilter.ItemsSource = new[] { new Choice(Get("AllSources"), "") }.Concat(options);
            SourceFilter.SelectedValue = options.Any(option => option.Value == filter) ? filter : "";
            FilterInspectionFiles(selectedId);
        }
        finally { settingInspectionChoices = false; }
        inspectionTimer.IsEnabled = !previewMode && files.Any(file => file.Versions.Any(version => version.IsPending));
    }

    private void FilterInspectionFiles(string? selectedId)
    {
        string query = MediaSearch.Text.Trim();
        string? source = SourceFilter.SelectedValue as string;
        var matches = subtitleFiles.Where(file =>
            (string.IsNullOrEmpty(source) || source == (file.Source ?? "und")) &&
            (file.Name.Contains(query, StringComparison.OrdinalIgnoreCase)
                || file.Path?.Contains(query, StringComparison.OrdinalIgnoreCase) == true)).ToArray();
        var selected = matches.FirstOrDefault(file => file.Id == selectedId) ?? matches.FirstOrDefault();
        if (selected?.Id != selectedId) pinnedVersion = null;
        MediaList.ItemsSource = matches;
        MediaList.SelectedItem = selected;
        SetInspectionVersions(selected);
        InspectStatus.Text = matches.Length > 0 ? "" : Get(subtitleFiles.Length == 0 ? "EmptyLibrary" : "NoMatches");
    }

    private async void InspectFilterChanged(object sender, RoutedEventArgs e)
    {
        if (settingInspectionChoices || MediaList is null) return;
        settingInspectionChoices = true;
        try { FilterInspectionFiles((MediaList.SelectedItem as SubtitleFile)?.Id); }
        finally { settingInspectionChoices = false; }
        await LoadInspectionRows();
    }

    private async void InspectMediaChanged(object sender, SelectionChangedEventArgs e)
    {
        if (settingInspectionChoices) return;
        pinnedVersion = null;
        settingInspectionChoices = true;
        try { SetInspectionVersions(MediaList.SelectedItem as SubtitleFile); }
        finally { settingInspectionChoices = false; }
        await LoadInspectionRows();
    }

    private void SetInspectionVersions(SubtitleFile? file)
    {
        InspectDetails.Visibility = file is null ? Visibility.Collapsed : Visibility.Visible;
        InspectFileName.Text = file?.Name ?? "";
        InspectPath.Text = file?.Path ?? Get("PathUnknown");
        InspectPath.ToolTip = file?.Path;
        VersionChoice.ItemsSource = file?.Versions.Select(version => new Choice(version.Label, version.Key)).ToArray();
        VersionChoice.SelectedValue = file?.Versions.FirstOrDefault(version => version.Key == pinnedVersion)?.Key
            ?? file?.Versions.FirstOrDefault()?.Key;
        ShowVersionSummary();
    }

    private async void InspectVersionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (settingInspectionChoices) return;
        var selected = SelectedVersion();
        pinnedVersion = VersionChoice.SelectedIndex > 0 ? selected?.Key : null;
        ShowVersionSummary();
        await LoadInspectionRows();
    }

    private void ShowVersionSummary()
    {
        var version = SelectedVersion();
        var file = MediaList.SelectedItem as SubtitleFile;
        InspectSource.Text = Get("PrimarySource", InspectionText.Language(version?.Source));
        InspectCoverage.Text = Get("Coverage", version?.Coverage is double coverage
            ? Math.Min(coverage, coverage < 1 ? .99 : 1).ToString("P0", Culture) : Get("Unknown"));
        InspectTargets.Text = Get("Targets", file?.Targets.Length > 0
            ? string.Join(Culture.TextInfo.ListSeparator + " ", file.Targets.Select(InspectionText.Language)) : Get("NoTargets"));
        InspectGenerationState.Text = version?.State switch
        {
            "queued" => Get("Queued"),
            "running" => Get("Running"),
            "complete" => Get("Complete"),
            "failed" => Get("Failed", Error(version.ErrorCode) ?? Get("ActionFailed")),
            "interrupted" => Get("Interrupted"),
            _ => "",
        };
        InspectGenerationState.Visibility = string.IsNullOrEmpty(InspectGenerationState.Text)
            ? Visibility.Collapsed : Visibility.Visible;
        bool pending = subtitleFiles.Any(item => item.Versions.Any(itemVersion => itemVersion.IsPending));
        InspectRegenerate.IsEnabled = !inspectionAction && !pending && version?.CanRegenerate == true;
        InspectRegenerate.ToolTip = Get("RegenerateHint");
        InspectOpen.IsEnabled = InspectSave.IsEnabled = !inspectionAction && version?.HasSubtitles == true;
    }

    private void SubtitleTableResized(object sender, SizeChangedEventArgs e)
    {
        // Fixed widths keep text wrapping consistent during preview and in the live DataGrid.
        const double scrollbarMargin = 20;
        var width = new DataGridLength(Math.Max(112, (e.NewSize.Width - InspectTimeColumn.Width.Value - scrollbarMargin) / 2));
        InspectOriginalColumn.Width = InspectTranslationColumn.Width = width;
    }

    private async Task LoadInspectionRows(bool refresh = false)
    {
        if (previewMode) return;
        var version = SelectedVersion();
        if (!refresh && version is not null && (requestedRows == version.Key || SubtitleRows.Tag as string == version.Key))
            return;
        rowRequest?.Cancel();
        if (version is null)
        {
            SubtitleRows.ItemsSource = null;
            SubtitleRows.Tag = null;
            return;
        }
        if (SubtitleRows.Tag as string != version.Key)
        {
            SubtitleRows.ItemsSource = null;
            SubtitleRows.Tag = null;
            InspectPreviewNote.Text = Get("Loading");
        }
        using var request = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        rowRequest = request;
        requestedRows = version.Key;
        try
        {
            var result = await bridge.Run("inspect-rows", version.Key, cancellationToken: request.Token);
            if (rowRequest != request || SelectedVersion()?.Key != version.Key) return;
            var rows = (result["rows"]?.AsArray() ?? []).OfType<JsonObject>().Select(row =>
            {
                var start = TimeSpan.FromSeconds(row["start"]!.GetValue<double>());
                var time = string.Format(CultureInfo.InvariantCulture, "{0:00}:{1:00}:{2:00}.{3:0}",
                    (int)start.TotalHours, start.Minutes, start.Seconds, start.Milliseconds / 100);
                return new SubtitleRow(time, row["original"]?.GetValue<string>() ?? "",
                    row["translation"]?.GetValue<string>() ?? Error(row["status"]?.GetValue<string>()) ?? Get("ActionFailed"));
            }).ToArray();
            SubtitleRows.ItemsSource = rows;
            SubtitleRows.Tag = version.Key;
            InspectPreviewNote.Text = rows.Length == 0 ? Get("EmptyVersion") : Get("PreviewRows");
        }
        catch (Exception)
        {
            if (rowRequest == request && SelectedVersion()?.Key == version.Key)
                InspectPreviewNote.Text = Get("ReadFailed");
        }
        finally
        {
            if (rowRequest == request)
            {
                rowRequest = null;
                requestedRows = null;
            }
        }
    }

    private async void RegenerateSubtitle(object sender, RoutedEventArgs e)
    {
        if (previewMode || SelectedVersion() is not { } version) return;
        await RunInspectionAction(async () =>
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(22));
            await bridge.Run("inspect-regenerate", version.Key, cancellationToken: timeout.Token);
            if (SelectedVersion()?.Key == version.Key) pinnedVersion = null;
            await Inspect();
        });
    }

    private async void OpenSubtitle(object sender, RoutedEventArgs e)
    {
        if (previewMode || SelectedVersion() is not { } version) return;
        await RunInspectionAction(async () =>
        {
            string path = await ExportInspectionSubtitle(version.Key, null);
            var info = new ProcessStartInfo("notepad.exe") { UseShellExecute = false };
            info.ArgumentList.Add(path);
            using var process = Process.Start(info);
        });
    }

    private async void SaveSubtitle(object sender, RoutedEventArgs e)
    {
        if (previewMode || SelectedVersion() is not { } version || MediaList.SelectedItem is not SubtitleFile file)
            return;
        string target = string.Concat(version.Target.Select(character =>
            char.IsAsciiLetterOrDigit(character) || character is '-' or '_' ? character : '_'));
        var dialog = new Microsoft.Win32.SaveFileDialog
        {
            Title = Get("Save"), Filter = Get("SrtFilter"), DefaultExt = ".srt", AddExtension = true,
            FileName = Path.GetFileNameWithoutExtension(file.Name) + "." + target + ".srt",
            OverwritePrompt = true,
        };
        if (dialog.ShowDialog(this) != true) return;
        await RunInspectionAction(async () =>
        {
            await ExportInspectionSubtitle(version.Key, dialog.FileName);
            InspectStatus.Text = Get("Saved", dialog.FileName);
        });
    }

    private async Task<string> ExportInspectionSubtitle(string key, string? output)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var result = await bridge.Run("inspect-srt", key, new JsonObject { ["output"] = output }, timeout.Token);
        return result["subtitle"]!.GetValue<string>();
    }

    private async Task RunInspectionAction(Func<Task> action)
    {
        if (inspectionAction) return;
        inspectionAction = true;
        ShowVersionSummary();
        InspectStatus.Text = "";
        try { await action(); }
        catch (InspectionBridgeException error) { InspectStatus.Text = error.Message; }
        catch (Exception) { InspectStatus.Text = Get("ActionFailed"); }
        finally
        {
            inspectionAction = false;
            ShowVersionSummary();
        }
    }

    private void LoadInspectionPreview()
    {
        SetInspectionFiles([
            new("walk", "雨后的散步.mkv", @"D:\Movies\雨后的散步.mkv", "ja", ["zh", "en"], [
                new("walk-1", 1794915000, "ja", "zh", 0, .68, true, true, null, null),
                new("walk-2", 1794828600, "ja", "en", 0, 1, true, true, null, null),
            ]),
            new("city", "City Lights.mp4", @"E:\Library\City Lights.mp4", "en", ["zh"], [
                new("city-1", 1794700000, "en", "zh", 0, .32, true, true, null, null),
            ]),
            new("coast", "Coastal Journey.mkv", @"D:\Documentaries\Coastal Journey.mkv", null, [], [
                new("coast-1", 1794600000, null, "zh", 0, null, false, true, null, null),
            ])
        ], null);
        SubtitleRows.ItemsSource = new SubtitleRow[] {
            new("00:00:12.4", "今日はいい天気ですね。", "今天天气真好。"),
            new("00:00:16.8", "少し散歩に行きませんか。", "要不要出去散散步？"),
            new("00:00:21.2", "いいですね。駅の近くに新しいお店ができたそうです。", "好啊。听说车站附近开了一家新店。"),
        };
        InspectPreviewNote.Text = Get("PreviewRows");
    }

    private void VerifyInspection()
    {
        void Require(bool condition, string message)
        {
            if (!condition) throw new InvalidOperationException("Subtitle inspection preview check failed: " + message);
        }
        Require(SelectedVersion()?.Key == "walk-1", "newest version opens first");
        VersionChoice.SelectedIndex = 1;
        Require(SelectedVersion()?.Key == "walk-2", "older version is selectable");
        SourceFilter.SelectedValue = "en";
        Require(SelectedVersion()?.Key == "city-1", "source language filter selects the matching file");
        MediaSearch.Text = "documentaries";
        Require(MediaList.Items.Count == 0 && InspectDetails.Visibility == Visibility.Collapsed, "empty filter clears details");
        SourceFilter.SelectedIndex = 0;
        Require(SelectedVersion()?.Key == "coast-1" && !InspectSave.IsEnabled, "path search and export availability");
        MediaSearch.Text = "雨后";
        Require(SelectedVersion()?.Key == "walk-1" && InspectSave.IsEnabled, "Unicode search and newest version");
        MediaSearch.Clear();
        Require(InspectCoverage.Text.Contains(.68.ToString("P0", Culture)), "localized coverage");
    }
}
