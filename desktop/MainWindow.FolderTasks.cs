using System.Globalization;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Markup;
using System.Windows.Threading;

namespace AheadSubs;

public partial class MainWindow
{
    private const long MiB = 1024 * 1024;
    private const long MaxRuleBytes = 1L << 53;
    private readonly DispatcherTimer folderTimer = new() { Interval = TimeSpan.FromSeconds(5) };
    private readonly SemaphoreSlim folderOperations = new(1);
    private JsonArray folderRules = [];
    private JsonObject folderSummary = new();
    private bool folderBusy, folderLoaded, folderSwitching, folderServiceRunning;
    private string? folderRuleId;
    private sealed record FolderQueueItem(string Path, string Status);

    private static string FolderText(string key) => AutomationText.Get("Folder" + key);

    private static string FolderFormat(string key, params object[] arguments) =>
        string.Format(AutomationText.Culture, FolderText(key), arguments);

    private void InitializeFolderTasks()
    {
        LocalizeFolderChoices();
        NewFolderRuleButton.IsEnabled = false;
        FolderQueueStatus.Text = FolderText("Loading");
        if (!previewMode)
            folderTimer.Tick += async (_, _) => { if (IsVisible) await UpdateFolderTasks(); };
    }

    private void LocalizeFolderChoices()
    {
        var preferred = new Choice(FolderText("Default"), "");
        Choice[] languages = [.. InterfaceLocale.Languages.Select(item => new Choice(FolderText("Lang_" + item.Target), item.Target))];
        Choice[] sources = [preferred, new(FolderText("Auto"), "auto"), .. languages];
        Choice[] targets = [preferred, .. languages];
        FolderRuleSource.ItemsSource = sources;
        FolderRuleTarget.ItemsSource = targets;
        FolderRuleStyle.ItemsSource = new Choice[] { preferred, new(FolderText("Translated"), "translated"),
            new(FolderText("Bilingual"), "bilingual") };
    }

    private void PreviewFolderTasks()
    {
        SetFolderTasks(JsonNode.Parse("""
            {"running":true,
             "rules":[{"id":"preview","folder":"D:\\Media\\Series","name":"Series · 日本語",
                "source":"ja","target":"zh","bilingual":true,"suffix":".zh", "translation_model":"nllb"}],
             "summary":{"preview":{"counts":{"waiting":3,"running":1,"done":12},
                "items":[{"path":"D:\\Media\\Series\\第12話.mkv","state":"running"}]}}}
            """)!.AsObject(), true);
        NewFolderRuleButton.IsEnabled = true;
        FolderSubtitleOptions.IsExpanded = true;
        if (FolderRulePath.Text != @"D:\Media\Series" || Selected(FolderRuleTarget) != "zh"
            || Selected(FolderRuleStyle) != "bilingual" || FolderQueueItems.Items.Count != 1
            || Selected(FolderRuleSpeechModel) != "" || Selected(FolderRuleTranslationModel) != "nllb"
            || FolderQueueStatus.Text != FolderFormat("Counts", 3, 1, 12, 0, 0))
            throw new InvalidOperationException("Folder task desktop preview failed to load the rule and queue.");
        if (!Equals(TranslationTab.Header, AutomationText.Get("SubtitleTab"))
            || TranslationTitle.Text != AutomationText.Get("SubtitleSettings")
            || !Equals(InspectTab.Header, InspectionText.Get("Tab"))
            || InspectTitle.Text != InspectionText.Get("Title"))
            throw new InvalidOperationException("Subtitle page labels failed to load for the preview locale.");
    }

    private void UpdateFolderModelChoices(string speech, string translation)
    {
        var preferred = new Choice(FolderText("Default"), "");
        Choice LocalChoice(Choice model) => Installed(model.Value) ? model
            : model with { Label = FolderFormat("ModelNotInstalled", model.Label) };
        Choice[] speechChoices = [preferred,
            .. LocalModels.Where(model => model.Value != "nllb").Select(LocalChoice),
            new("OpenAI Whisper", "openai"), .. DashScopeSpeechModels,
            new(FolderText("CustomModel"), "compatible")];
        FolderRuleSpeechModel.ItemsSource = speechChoices;
        var translations = new List<Choice> { preferred, LocalChoice(LocalModels.First(model => model.Value == "nllb")) };
        translations.AddRange(DashScopeTranslationModels);
        translations.Add(new("OpenAI GPT-4.1 mini", "gpt-4.1-mini"));
        translations.Add(new(FolderText("ChatGptModel"), "chatgpt"));
        translations.Add(new(miniMaxModel, "minimax"));
        translations.Add(new(FolderText("CustomModel"), "compatible"));
        if (Setting("mt") == "openai" && Setting("llm_model") is { } openAiModel && openAiModel != "gpt-4.1-mini"
            && Regex.IsMatch(openAiModel, @"\A[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\z"))
            translations.Add(new("OpenAI " + openAiModel, "openai:" + openAiModel));
        if (translation.StartsWith("openai:", StringComparison.Ordinal) && !translations.Any(model => model.Value == translation))
            translations.Add(new("OpenAI " + translation[7..], translation));
        FolderRuleTranslationModel.ItemsSource = translations;
        FolderRuleSpeechModel.SelectedValue = speech;
        FolderRuleTranslationModel.SelectedValue = translation;
    }

    private async Task SelectFolderTasksPage()
    {
        folderTimer.Stop();
        if (SettingsPanel.SelectedItem != FolderTasksTab) return;
        folderTimer.Start();
        await UpdateFolderTasks();
    }

    private async Task UpdateFolderTasks(string? action = null, JsonObject? input = null, string? selection = null)
    {
        if (action is null && folderBusy) return;
        await folderOperations.WaitAsync();
        folderBusy = true;
        if (action is not null) FolderRuleEditor.IsEnabled = FolderRuleChoice.IsEnabled = false;
        NewFolderRuleButton.IsEnabled = FolderRetryButton.IsEnabled = false;
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(8));
            var result = await bridge.Run("folder-tasks", action, input, timeout.Token);
            SetFolderTasks(result, action == "save", selection);
            if (action is not null)
                FolderActionStatus.Text = FolderText(action == "retry" ? "Retried" : "Saved");
        }
        catch (InvalidOperationException ex)
        {
            if (action is null)
                FolderQueueStatus.Text = FolderText("Unavailable");
            else
                FolderActionStatus.Text = ex.Message;
        }
        catch (Exception)
        {
            if (action is null) FolderQueueStatus.Text = FolderText("Unavailable");
            else FolderActionStatus.Text = FolderText("Unavailable");
        }
        finally
        {
            folderBusy = false;
            FolderRuleEditor.IsEnabled = FolderRuleChoice.IsEnabled = FolderRetryButton.IsEnabled = true;
            NewFolderRuleButton.IsEnabled = folderLoaded && folderRules.Count < 50;
            folderOperations.Release();
        }
    }

    private void SetFolderTasks(JsonObject result, bool reloadRules, string? selection = null)
    {
        folderServiceRunning = result["running"]?.GetValue<bool>() == true;
        folderSummary = result["summary"] as JsonObject ?? new();
        if (reloadRules || !folderLoaded)
        {
            folderLoaded = true;
            folderRules = result["rules"] as JsonArray ?? [];
            folderSwitching = true;
            var choices = folderRules.OfType<JsonObject>().Select(rule => new Choice(
                string.IsNullOrWhiteSpace(rule["name"]?.ToString()) ? rule["folder"]!.ToString() : rule["name"]!.ToString(),
                rule["id"]!.ToString())).ToArray();
            FolderRuleChoice.ItemsSource = choices;
            FolderRuleChoice.SelectedValue = selection ?? choices.FirstOrDefault()?.Value;
            folderSwitching = false;
            SelectFolderRule();
        }
        ShowFolderQueue();
    }

    private void FolderRuleChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!folderLoaded || folderSwitching) return;
        FolderActionStatus.Text = "";
        SelectFolderRule();
    }

    private void SelectFolderRule()
    {
        var rule = folderRules.FirstOrDefault(item => item?["id"]?.ToString() == Selected(FolderRuleChoice));
        folderRuleId = rule?["id"]?.ToString();
        FolderRuleEditor.Visibility = rule is null ? Visibility.Collapsed : Visibility.Visible;
        if (rule is not null) LoadFolderRule(rule);
        ShowFolderQueue();
    }

    private void NewFolderRule(object sender, RoutedEventArgs e)
    {
        folderSwitching = true;
        FolderRuleChoice.SelectedIndex = -1;
        folderSwitching = false;
        folderRuleId = null;
        FolderRuleEditor.Visibility = Visibility.Visible;
        FolderActionStatus.Text = "";
        LoadFolderRule(new JsonObject());
        ShowFolderQueue();
        FolderRuleName.Focus();
    }

    private void LoadFolderRule(JsonNode rule)
    {
        string Read(string key, string fallback = "") => rule[key]?.ToString() ?? fallback;
        string Size(string key) => rule[key] is null ? "" :
            (rule[key]!.GetValue<long>() / (decimal)MiB).ToString(AutomationText.Culture);
        FolderRuleName.Text = Read("name");
        FolderRulePath.Text = Read("folder");
        FolderRuleEnabled.IsChecked = rule["enabled"]?.GetValue<bool>() ?? true;
        FolderRuleRecursive.IsChecked = rule["recursive"]?.GetValue<bool>() == true;
        FolderRuleExisting.IsChecked = rule["include_existing"]?.GetValue<bool>() == true;
        FolderRuleRegex.Text = Read("pattern");
        FolderRuleTypes.Text = Read("extensions", "mkv, mp4, mov, avi, webm, m4v, ts, mp3, m4a, wav, flac, ogg, opus");
        FolderRuleMin.Text = Size("min_bytes");
        FolderRuleMax.Text = Size("max_bytes");
        UpdateFolderModelChoices(Read("speech_model"), Read("translation_model"));
        FolderRuleSource.SelectedValue = Read("source");
        FolderRuleTarget.SelectedValue = Read("target");
        FolderRuleAudio.Text = ((rule["audio"]?.GetValue<int>() ?? 0) + 1).ToString(AutomationText.Culture);
        FolderRuleStyle.SelectedValue = (rule["bilingual"]?.GetValue<bool>()) switch
        { true => "bilingual", false => "translated", _ => "" };
        FolderRuleDestination.Text = Read("destination");
        FolderRuleSuffix.Text = Read("suffix");
        FolderRuleIdle.Text = Read("idle_minutes", "0");
        DeleteFolderRuleButton.Visibility = folderRuleId is null ? Visibility.Collapsed : Visibility.Visible;
    }

    private void ShowFolderQueue()
    {
        var rule = folderRules.FirstOrDefault(item => folderRuleId is not null && item?["id"]?.ToString() == folderRuleId);
        var summary = folderRuleId is null ? null : folderSummary[folderRuleId];
        var counts = summary?["counts"];
        int Count(string state) => counts?[state]?.GetValue<int>() ?? 0;
        var issue = summary?["issue"]?.ToString();
        FolderQueueStatus.Text = !folderServiceRunning ? FolderText("Stopped")
            : rule is null ? FolderText("Select")
            : rule["enabled"]?.GetValue<bool>() == false ? FolderText("Paused")
            : issue is not null ? FolderIssue(issue)
            : FolderFormat("Counts", Count("waiting") + Count("settling"), Count("running"), Count("done"), Count("failed"), Count("skipped"));
        FolderQueueItems.ItemsSource = (summary?["items"] as JsonArray ?? []).OfType<JsonObject>()
            .Select(row => new FolderQueueItem(row["path"]!.ToString(), row["issue"] is JsonNode error
                ? FolderIssue(error.ToString()) : FolderText("Running"))).ToArray();
        FolderRetryButton.Visibility = Count("failed") > 0 ? Visibility.Visible : Visibility.Collapsed;
    }

    private static string FolderIssue(string issue)
    {
        string key = "FolderIssue_" + issue;
        string label = AutomationText.Get(key);
        return label == key ? FolderFormat("FailureCode", issue) : label;
    }

    private static string? Optional(string value) => string.IsNullOrWhiteSpace(value) ? null : value.Trim();

    private static long? RuleBytes(string value, string label)
    {
        if (string.IsNullOrWhiteSpace(value)) return null;
        if (!decimal.TryParse(value, NumberStyles.Number, AutomationText.Culture, out var size)
            || size < 0 || size > MaxRuleBytes / MiB)
            throw new InvalidOperationException(FolderFormat("Invalid", FolderText(label)));
        return (long)decimal.Round(size * MiB);
    }

    private async void SaveFolderRule(object sender, RoutedEventArgs e)
    {
        try
        {
            var minimum = RuleBytes(FolderRuleMin.Text, "Min") ?? 0;
            var maximum = RuleBytes(FolderRuleMax.Text, "Max");
            if (maximum < Math.Max(1, minimum)) throw new InvalidOperationException(FolderText("InvalidSize"));
            if (!int.TryParse(FolderRuleAudio.Text, out int audio) || audio is < 1 or > 256)
                throw new InvalidOperationException(FolderFormat("Invalid", FolderText("Audio")));
            if (!int.TryParse(FolderRuleIdle.Text, out int idle) || idle is < 0 or > 120)
                throw new InvalidOperationException(FolderFormat("Invalid", FolderText("Idle")));
            var id = folderRuleId ?? Guid.NewGuid().ToString("N");
            var rule = new JsonObject
            {
                ["id"] = id, ["name"] = FolderRuleName.Text.Trim(), ["folder"] = FolderRulePath.Text.Trim(),
                ["enabled"] = FolderRuleEnabled.IsChecked == true, ["recursive"] = FolderRuleRecursive.IsChecked == true,
                ["include_existing"] = FolderRuleExisting.IsChecked == true, ["pattern"] = FolderRuleRegex.Text,
                ["extensions"] = FolderRuleTypes.Text, ["min_bytes"] = minimum, ["max_bytes"] = maximum,
                ["speech_model"] = Optional(Selected(FolderRuleSpeechModel)),
                ["translation_model"] = Optional(Selected(FolderRuleTranslationModel)),
                ["source"] = Optional(Selected(FolderRuleSource)), ["target"] = Optional(Selected(FolderRuleTarget)),
                ["audio"] = audio - 1, ["bilingual"] = Selected(FolderRuleStyle) switch
                { "bilingual" => JsonValue.Create(true), "translated" => JsonValue.Create(false), _ => null },
                ["destination"] = Optional(FolderRuleDestination.Text), ["suffix"] = FolderRuleSuffix.Text.Trim(),
                ["idle_minutes"] = idle
            };
            var updated = (JsonArray)folderRules.DeepClone();
            var index = updated.IndexOf(updated.FirstOrDefault(item => item?["id"]?.ToString() == id));
            if (index < 0) updated.Add(rule);
            else updated[index] = rule;
            await UpdateFolderTasks("save", new JsonObject { ["rules"] = updated }, id);
        }
        catch (InvalidOperationException ex) { FolderActionStatus.Text = ex.Message; }
    }

    private async void DeleteFolderRule(object sender, RoutedEventArgs e)
    {
        if (folderRuleId is null) return;
        var updated = new JsonArray(folderRules.Where(rule => rule?["id"]?.ToString() != folderRuleId)
            .Select(rule => rule?.DeepClone()).ToArray());
        await UpdateFolderTasks("save", new JsonObject { ["rules"] = updated });
    }

    private async void RetryFolderJobs(object sender, RoutedEventArgs e)
    {
        if (folderRuleId is not null)
            await UpdateFolderTasks("retry", new JsonObject { ["id"] = folderRuleId });
    }

    private void BrowseWatchFolder(object sender, RoutedEventArgs e) => BrowseTaskFolder(FolderRulePath);
    private void BrowseSubtitleFolder(object sender, RoutedEventArgs e) => BrowseTaskFolder(FolderRuleDestination);

    private void BrowseTaskFolder(System.Windows.Controls.TextBox field)
    {
        var dialog = new Microsoft.Win32.OpenFolderDialog { InitialDirectory = field.Text };
        if (dialog.ShowDialog(this) == true) field.Text = dialog.FolderName;
    }
}
