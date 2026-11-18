using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;

namespace AheadSubs;

public partial class MainWindow
{
    private string[]? missingRequirements;
    private bool checkingPreset;
    private int presetRequest;
    private HashSet<string> activeModels = [];
    private HashSet<string> guidedModels = [];

    private TranslationPreset? ChosenPreset => TranslationPreset.All.FirstOrDefault(p => p.Id == Selected(PresetChoice));

    private void InitializeSetup()
    {
        var devices = new Choice[] { new(SetupText.Get("cpu-device"), "cpu"), new(SetupText.Get("cuda-device"), "cuda") };
        WhisperDevice.ItemsSource = devices;
        NllbDevice.ItemsSource = devices;
        PresetChoice.ItemsSource = TranslationPreset.All.Select(p => new Choice(SetupText.Get(p.Id), p.Id)).ToArray();
        PresetChoice.SelectedValue = "cpu";
        PresetDownload.Content = SetupText.Get("download");
        PresetModels.Content = SetupText.Get("models");
        PresetKeys.Content = SetupText.Get("keys");
        PresetRetry.Content = SetupText.Get("retry");
        PresetApply.Content = SetupText.Get("apply");
        ModelsHeading.Text = SetupText.Get("model-page");
        ModelsTab.Header = ModelsHeading.Text;
        AsrModelHeading.Text = SetupText.Get("model-asr");
        MtModelHeading.Text = SetupText.Get("model-mt");
        VadModelHeading.Text = SetupText.Get("model-vad");
        VadModelHint.Text = SetupText.Get("managed-vad");
        SharedModelsHint.Text = SetupText.Get("shared-info");
        WhisperDeviceLabel.Text = SetupText.Get("whisper-device");
        NllbDeviceLabel.Text = SetupText.Get("nllb-device");
        AutomationProperties.SetName(WhisperDevice, WhisperDeviceLabel.Text);
        AutomationProperties.SetName(NllbDevice, NllbDeviceLabel.Text);
        AutomationProperties.SetName(PresetChoice, SetupText.Get("heading"));
        UpdatePresetHeading();
        UpdateModelDownloads();
    }

    private void UpdatePresetHeading()
    {
        string speech = Selected(SpeechModel), translation = Selected(TranslationModel);
        var active = TranslationPreset.All.FirstOrDefault(p => p.Speech == speech && p.Translation == translation
            && (speech != "whisper-small" || Selected(WhisperDevice) == p.Device)
            && (translation != "nllb" || Selected(NllbDevice) == p.Device));
        PresetDisclosure.Header = speech.Length == 0 || translation.Length == 0 ? SetupText.Get("heading")
            : SetupText.Get("active", SetupText.Get(active?.Id ?? "custom"));
        if (!initialized && active is not null) PresetChoice.SelectedValue = active.Id;
    }

    private async void PresetOpened(object sender, RoutedEventArgs e)
    {
        if (e.Source == sender && initialized) await CheckPreset();
    }

    private async void PresetChanged(object sender, SelectionChangedEventArgs e)
    {
        missingRequirements = null;
        if (PresetStatus is null) return;
        if (PresetDisclosure.IsExpanded && initialized) await CheckPreset();
    }

    private async Task<string[]> ProbePreset(TranslationPreset preset)
    {
        var requirements = new List<string>();
        if (preset.UsesVulkan) requirements.Add("vulkan");
        if (preset.Device == "cuda") requirements.Add("cuda");
        if (preset.NeedsDashScope) requirements.Add("dashscope");
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var input = preset.NeedsDashScope ? new JsonObject { ["qwen_mt_url"] = QwenUrl.Text } : null;
        var result = await bridge.Run("preset-check", string.Join(",", requirements), input, timeout.Token);
        return (result["missing"] as JsonArray ?? throw new InvalidOperationException(SetupText.Get("check-failed")))
            .Select(value => value!.GetValue<string>()).ToArray();
    }

    private async Task CheckPreset()
    {
        if (previewMode || ChosenPreset is not { } preset) return;
        int request = ++presetRequest;
        checkingPreset = true;
        UpdatePresetGuide();
        string[]? missing;
        try { missing = await ProbePreset(preset); }
        catch (Exception) { missing = null; }
        if (request != presetRequest) return;
        checkingPreset = false;
        missingRequirements = missing;
        UpdatePresetGuide();
    }

    private void UpdatePresetGuide()
    {
        if (ChosenPreset is not { } preset) return;
        string[] missingModels = preset.MissingModels(Installed);
        string[] missing = missingRequirements ?? [];
        bool needsModels = missingModels.Length > 0;
        bool checkedPreset = missingRequirements is not null && !checkingPreset;
        bool deviceReady = checkedPreset && missing.All(code => code == "dashscope");
        var notes = missing.Select(code => SetupText.Get(code)).ToList();
        if (needsModels) notes.Add(SetupText.Get("missing", string.Join(", ", missingModels.Select(ModelName))));
        PresetDetail.Text = SetupText.Get("detail-" + preset.Id);
        PresetStatus.Text = checkingPreset ? SetupText.Get("checking") : !checkedPreset ? SetupText.Get("check-failed")
            : notes.Count == 0 ? SetupText.Get("ready") : string.Join("\n", notes);
        PresetDownload.Visibility = Visible(deviceReady && needsModels);
        PresetModels.Visibility = Visible(needsModels && !checkingPreset);
        PresetKeys.Visibility = Visible(checkedPreset && missing.Contains("dashscope"));
        PresetRetry.Visibility = Visible(!checkingPreset && (!checkedPreset || !deviceReady));
        PresetApply.Visibility = Visible(checkedPreset && !needsModels && missing.Length == 0);
    }

    private static Visibility Visible(bool condition) => condition ? Visibility.Visible : Visibility.Collapsed;

    private void GoPresetModels(object sender, RoutedEventArgs e)
    {
        guidedModels = [.. (ChosenPreset?.MissingModels(Installed) ?? [])];
        UpdateModelDownloads();
        SettingsPanel.SelectedItem = ModelsTab;
        var target = guidedModels.SetEquals(["nllb"]) ? TranslationDownloads : SpeechDownloads;
        Dispatcher.BeginInvoke(() => target.BringIntoView(), System.Windows.Threading.DispatcherPriority.Loaded);
    }

    private void GoPresetKeys(object sender, RoutedEventArgs e)
    {
        CloudProvider.SelectedValue = "dashscope";
        SettingsPanel.SelectedItem = KeysTab;
    }

    private async void DownloadPreset(object sender, RoutedEventArgs e)
    {
        if (ChosenPreset is not { } preset) return;
        await Act(SetupText.Get("downloading", SetupText.Get(preset.Id)), async () =>
        {
            foreach (string model in preset.MissingModels(Installed))
            {
                ActionStatus.Text = SetupText.Get("downloading", ModelName(model));
                await bridge.Run("install", model);
            }
        }, SetupText.Get("downloaded"));
        await CheckPreset();
    }

    private async void ApplyPreset(object sender, RoutedEventArgs e)
    {
        if (ChosenPreset is not { } preset) return;
        bool applied = false;
        await Act(SetupText.Get("applying"), async () =>
        {
            missingRequirements = await ProbePreset(preset);
            if (missingRequirements.Length > 0) throw new InvalidOperationException(SetupText.Get(missingRequirements[0]));
            if (preset.MissingModels(Installed).Length > 0)
                throw new InvalidOperationException(SetupText.Get("missing", string.Join(", ", preset.MissingModels(Installed).Select(ModelName))));
            await ApplySettings(CollectSettings(preset));
            applied = true;
        }, SetupText.Get("applied"), reloadSettings: true);
        UpdatePresetGuide();
        if (applied) PresetDisclosure.IsExpanded = false;
    }
}
