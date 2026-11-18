using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using Forms = System.Windows.Forms;

namespace AheadSubs;

public partial class MainWindow : Window
{
    private sealed record Choice(string Label, string Value);
    private static readonly Choice[] LocalModels =
    [new("Qwen3-ASR 0.6B", "qwen-0.6b"), new("Qwen3-ASR 1.7B", "qwen-1.7b"),
     new("Whisper Small", "whisper-small"), new("NLLB-200 600M INT8", "nllb")];
    private static readonly double[] ModelSizes = [0.63, 1.33, 0.49, 0.65];
    private sealed record ModelDownload(string Id, string Label, string Details, string Status, string Action,
        bool Installed, bool CanAct, string? DisabledReason);
    private static readonly Choice[] DashScopeSpeechModels =
    [new("Qwen-Audio 3.1 ASR Flash", "qwen-audio-3.1-asr-flash"),
     new("Qwen-Audio 3.0 ASR Flash", "qwen-audio-3.0-asr-flash")];
    private static readonly Choice[] DashScopeTranslationModels =
    [new("Qwen-MT Flash", "qwen-mt-flash"), new("Qwen-MT Lite", "qwen-mt-lite"),
     new("Qwen-MT Plus", "qwen-mt-plus")];
    private sealed record EnhancementDraft(bool Enabled, string PreviousCues, string ContextChars, string Prompt);
    private readonly Dictionary<string, EnhancementDraft> enhancementDrafts = new();
    private string? enhancementModel;
    private readonly EngineBridge bridge = new();
    private readonly Forms.NotifyIcon tray;
    private readonly bool previewMode;
    private JsonObject settings = new();
    private JsonObject models = new();
    private JsonObject integrations = new();
    private JsonArray chatGptAccounts = new();
    private string miniMaxModel = "MiniMax-M3.1-Flash";
    private bool mcpEnabled, cliInstalled;
    private bool busy, refreshing, initialized, exiting, trayExplained;
    private string previousVad = "silero";

    public MainWindow(bool preview = false)
    {
        previewMode = preview;
        InitializeComponent();
        LoadAutomationText();
        InitializeFolderTasks();
        InitializeInspection();
        SourceLanguage.ItemsSource = new Choice[] { new("自动识别", ""), new("日语", "ja"),
            new("英语", "en"), new("中文", "zh"), new("韩语", "ko") };
        TargetLanguage.ItemsSource = new Choice[] { new("简体中文", "zh"), new("繁體中文", "zh-TW"),
            new("日语", "ja"), new("英语", "en"), new("韩语", "ko"), new("法语", "fr"), new("德语", "de"), new("西班牙语", "es") };
        InitializeSetup();
        Vad.ItemsSource = new Choice[] { new("Silero · 默认", "silero"), new("阿里 FSMN · 可选", "fsmn") };
        CloudProvider.ItemsSource = new Choice[] { new("阿里云百炼 · API Key", "dashscope"),
            new("OpenAI · API Key", "openai"), new("ChatGPT 订阅 · OAuth", "chatgpt"),
            new("MiniMax · API Key", "minimax"), new("自定义兼容接口 · API Key", "compatible") };
        CloudProvider.SelectedIndex = 0;
        DashScopeSpeech.ItemsSource = DashScopeSpeechModels.Select(CloudChoice).ToArray();
        DashScopeTranslation.ItemsSource = DashScopeTranslationModels.Select(CloudChoice).ToArray();
        using var iconStream = System.Windows.Application.GetResourceStream(
            new Uri("Assets/AheadSubs.ico", UriKind.Relative)).Stream;
        var appIcon = new System.Drawing.Icon(iconStream);
        tray = new Forms.NotifyIcon
        {
            Icon = appIcon,
            Text = "AheadSubs · 正在连接", Visible = !preview,
            ContextMenuStrip = new Forms.ContextMenuStrip()
        };
        tray.Disposed += (_, _) => appIcon.Dispose();
        if (preview)
        {
            settings = new JsonObject { ["source"] = "ja", ["target"] = "zh", ["asr"] = "qwen",
                ["qwen_size"] = "1.7b", ["mt"] = "qwen-mt", ["qwen_mt_model"] = "qwen-mt-flash", ["bilingual"] = "1" };
            models = new JsonObject { ["qwen-0.6b"] = false, ["qwen-1.7b"] = true, ["whisper-small"] = false, ["nllb"] = true };
            activeModels = ["qwen-1.7b"];
            integrations = new JsonObject { ["potplayer"] = new JsonObject { ["installed"] = true, ["configured"] = true, ["detected"] = true },
                ["mpv"] = new JsonObject { ["detected"] = true } };
            UpdatePlayers();
            UpdateModelDownloads();
            LoadControls(); initialized = true;
            ServiceStatus.Text = "服务已就绪"; ServiceDetail.Text = "在 PotPlayer 播放窗口按 Ctrl+Alt+J 开启，Ctrl+Alt+K 关闭。";
            SessionStatus.Text = "已连接 2 个播放窗口。"; SessionStatus.Visibility = Visibility.Visible;
            ApplyButton.Content = "保存并应用";
            LoadInspectionPreview();
            UpdateAutomation(JsonNode.Parse("""
                {"mcp_enabled":true,"cli_available":true,"cli_installed":false,
                 "mcp_config":{"mcpServers":{"aheadsubs":{"command":"C:\\AheadSubs\\runtime\\python.exe",
                 "args":["-m","aheadsubs.cli","mcp","--desktop"]}}}}
                """)!.AsObject());
            PreviewFolderTasks();
            StatusDashboard.Preview(JsonNode.Parse("""
                {"ready":true,"active_sessions":2,"workers":{"busy":1,"limit":4},
                 "sources":[{"source":"potplayer","playback":1,"text":0},{"source":"mpv","playback":1,"text":0}],
                 "models":[{"operation":"asr","model":"Qwen3-ASR-1.7b","device":"vulkan","state":"loaded"},
                           {"operation":"mt","model":"qwen-mt-flash","device":"cloud","state":"configured"},
                           {"operation":"vad","model":"silero","device":"cpu","state":"loaded"}],
                 "resources":{"cpu_percent":12.6,"rss_bytes":1174405120,"gpu_percent":22.4,"vram_bytes":805306368},
                 "performance":{"rtf":{"count":87,"p50":0.44},"latency":{"count":32,"p50":1.36,"p95":2.14,"p99":3.07}},
                 "cloud":{"weeks":["2026-11-16","2026-11-09"],"rows":[
                   {"week":"2026-11-16","provider":"dashscope","model":"qwen-mt-flash","operation":"mt",
                    "calls":248,"failed":2,"input_tokens":10830,"output_tokens":3041,"priced_calls":246,"estimated_usd":0.0019},
                   {"week":"2026-11-16","provider":"chatgpt","model":"gpt-5.4-mini","operation":"mt",
                    "calls":13,"failed":0,"input_tokens":4120,"output_tokens":902,"priced_calls":0,"estimated_usd":0}]}}
                """)!.AsObject());
            return;
        }
        StatusDashboard.Enable(bridge);
        StateChanged += (_, _) => StatusDashboard.SetWindowActive(WindowState != WindowState.Minimized);
        tray.ContextMenuStrip.Items.Add("打开设置", null, (_, _) => Dispatcher.Invoke(ShowSettings));
        var potMenu = new Forms.ToolStripMenuItem("PotPlayer 预读");
        potMenu.DropDownItems.Add("读取播放窗口…");
        potMenu.DropDownOpening += async (_, _) => await LoadPotPlayerMenu(potMenu);
        tray.ContextMenuStrip.Items.Add(potMenu);
        tray.ContextMenuStrip.Items.Add("停止字幕服务", null, (_, _) => Dispatcher.Invoke(() => Stop(this, new RoutedEventArgs())));
        tray.ContextMenuStrip.Items.Add(new Forms.ToolStripSeparator());
        tray.ContextMenuStrip.Items.Add("停止并退出", null, (_, _) => Dispatcher.Invoke(() => Exit(this, new RoutedEventArgs())));
        tray.DoubleClick += (_, _) => Dispatcher.Invoke(ShowSettings);
        InitializeUpdates();
        Loaded += async (_, _) => await Refresh(loadSettings: true);
    }

    public void ShowSettings()
    {
        Show(); WindowState = WindowState.Normal; Activate();
        if (initialized) _ = Refresh();
    }

    private async void RefreshStatus(object sender, RoutedEventArgs e) => await Refresh();
    private void GoKeys(object sender, RoutedEventArgs e)
    {
        string speech = Selected(SpeechModel), mt = Selected(TranslationModel);
        CloudProvider.SelectedValue = mt is "chatgpt" or "minimax" ? mt : IsDashScopeSpeech(speech) || mt.StartsWith("qwen-mt-", StringComparison.Ordinal)
            ? "dashscope" : speech == "compatible" || mt == "compatible" ? "compatible" : "openai";
        SettingsPanel.SelectedItem = KeysTab;
    }

    private async Task LoadPotPlayerMenu(Forms.ToolStripMenuItem menu)
    {
        menu.DropDownItems.Clear();
        menu.DropDownItems.Add(new Forms.ToolStripMenuItem("读取播放窗口…") { Enabled = false });
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            var result = await bridge.Run("pot-windows", cancellationToken: timeout.Token);
            var windows = (result["windows"] as JsonArray ?? new()).OfType<JsonObject>().ToList();
            menu.DropDownItems.Clear();
            if (windows.Count == 0)
                menu.DropDownItems.Add(new Forms.ToolStripMenuItem("没有打开的 PotPlayer 窗口") { Enabled = false });
            foreach (var window in windows)
            {
                string id = window["id"]?.ToString() ?? "";
                var items = menu.DropDownItems;
                if (windows.Count > 1)
                {
                    var entry = new Forms.ToolStripMenuItem(window["title"]?.ToString() ?? "PotPlayer");
                    menu.DropDownItems.Add(entry);
                    items = entry.DropDownItems;
                }
                items.Add("开启预读", null, async (_, _) => await ControlPotPlayer("pot-start", id));
                items.Add("关闭预读", null, async (_, _) => await ControlPotPlayer("pot-stop", id));
            }
        }
        catch (Exception)
        {
            menu.DropDownItems.Clear();
            menu.DropDownItems.Add(new Forms.ToolStripMenuItem("无法读取窗口，请重新打开此菜单") { Enabled = false });
        }
    }

    private async Task ControlPotPlayer(string command, string id)
    {
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            await bridge.Run(command, id, cancellationToken: timeout.Token);
        }
        catch (Exception ex)
        {
            ShowSettings();
            ActionStatus.Text = Friendly(ex);
            ActionStatus.Visibility = Visibility.Visible;
        }
    }

    private async void PageChanged(object sender, SelectionChangedEventArgs e)
    {
        if (e.Source != SettingsPanel) return;
        if (ServiceStrip is not null)
            ServiceStrip.Visibility = SettingsPanel.SelectedItem == StatusTab ? Visibility.Collapsed : Visibility.Visible;
        if (previewMode) return;
        await SelectFolderTasksPage();
        if (SettingsPanel.SelectedItem == InspectTab && initialized) await Inspect();
        if (SettingsPanel.SelectedItem == AutomationTab) await ChangeAutomation();
        if (initialized && SettingsPanel.SelectedItem == TranslationTab && PresetDisclosure.IsExpanded) await CheckPreset();
    }

    private void LoadAutomationText()
    {
        AutomationTab.Language = System.Windows.Markup.XmlLanguage.GetLanguage(AutomationText.Culture.Name);
        AutomationTab.Header = AutomationTitle.Text = AutomationText.Get("Title");
        AutomationIntro.Text = AutomationText.Get("Intro");
        McpHint.Text = AutomationText.Get("McpHint");
        McpStatus.Text = CliStatus.Text = AutomationText.Get("Loading");
        McpToggle.Content = AutomationText.Get("Enable");
        CopyMcpButton.Content = AutomationText.Get("Copy");
        System.Windows.Automation.AutomationProperties.SetName(McpConfiguration, AutomationText.Get("Configuration"));
        CliTitle.Text = AutomationText.Get("CliTitle");
        CliHint.Text = AutomationText.Get("CliHint");
        CliToggle.Content = AutomationText.Get("Install");
    }

    private void UpdateAutomation(JsonObject result)
    {
        mcpEnabled = result["mcp_enabled"]?.GetValue<bool>() == true;
        cliInstalled = result["cli_installed"]?.GetValue<bool>() == true;
        bool cliAvailable = result["cli_available"]?.GetValue<bool>() == true;
        McpStatus.Text = AutomationText.Get(mcpEnabled ? "Enabled" : "Disabled");
        McpToggle.Content = AutomationText.Get(mcpEnabled ? "Disable" : "Enable");
        McpToggle.IsEnabled = true;
        CopyMcpButton.IsEnabled = mcpEnabled;
        McpConfiguration.Visibility = mcpEnabled ? Visibility.Visible : Visibility.Collapsed;
        McpConfiguration.Text = mcpEnabled ? result["mcp_config"]?.ToJsonString(
            new System.Text.Json.JsonSerializerOptions { WriteIndented = true }) ?? "" : "";
        CliStatus.Text = AutomationText.Get(cliInstalled ? "Installed" : "NotInstalled");
        CliToggle.Content = AutomationText.Get(cliInstalled ? "Remove" : "Install");
        CliToggle.IsEnabled = cliAvailable;
        CliHint.Text = AutomationText.Get(cliAvailable ? "CliHint" : "SourceHint");
    }

    private async Task ChangeAutomation(string? action = null, string success = "")
    {
        McpToggle.IsEnabled = CopyMcpButton.IsEnabled = CliToggle.IsEnabled = false;
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
            UpdateAutomation(await bridge.Run("automation", action, cancellationToken: timeout.Token));
            AutomationStatus.Text = success;
        }
        catch (Exception)
        {
            AutomationStatus.Text = AutomationText.Get("Failed");
            if (action is not null) await ChangeAutomation(success: AutomationStatus.Text);
        }
    }

    private async void ToggleMcp(object sender, RoutedEventArgs e) => await ChangeAutomation(
        mcpEnabled ? "mcp-disable" : "mcp-enable", AutomationText.Get(mcpEnabled ? "DisabledNotice" : "EnabledNotice"));

    private async void ToggleCli(object sender, RoutedEventArgs e) => await ChangeAutomation(
        cliInstalled ? "cli-remove" : "cli-install", AutomationText.Get(cliInstalled ? "RemovedNotice" : "InstalledNotice"));

    private void CopyMcpConfig(object sender, RoutedEventArgs e)
    {
        try
        {
            System.Windows.Clipboard.SetText(McpConfiguration.Text);
            AutomationStatus.Text = AutomationText.Get("Copied");
        }
        catch (System.Runtime.InteropServices.ExternalException)
        {
            AutomationStatus.Text = AutomationText.Get("ClipboardUnavailable");
        }
    }

    private void LoadControls()
    {
        enhancementModel = null;
        enhancementDrafts.Clear();
        if (settings["translation_enhancements"] is JsonObject enhancements)
            foreach (var pair in enhancements)
                if (pair.Value is JsonObject entry)
                    enhancementDrafts[pair.Key] = new(entry["enabled"]?.GetValue<bool>() == true,
                        entry["previous_cues"]?.ToString() ?? "4", entry["context_chars"]?.ToString() ?? "250",
                        entry["prompt"]?.ToString() ?? "");
        LlmModel.Text = Setting("llm_model");
        WhisperDevice.SelectedValue = Setting("asr_device") is { Length: > 0 } asrDevice ? asrDevice : Setting("device", "cpu");
        NllbDevice.SelectedValue = Setting("mt_device") is { Length: > 0 } mtDevice ? mtDevice : Setting("device", "cpu");
        LoadChatGptAccounts(chatGptAccounts, Setting("chatgpt_account"), Setting("chatgpt_model"));
        PopulateModels();
        SourceLanguage.SelectedValue = Setting("source"); TargetLanguage.SelectedValue = Setting("target", "zh");
        Bilingual.IsChecked = Setting("bilingual", "0") is "1" or "true" or "True";
        previousVad = Setting("vad_model", "silero"); Vad.SelectedValue = previousVad;
        VadThreshold.Text = Setting("vad_threshold", previousVad == "fsmn" ? "0.8" : "0.5");
        Backfill.Text = Setting("backfill", "4");
        QwenUrl.Text = Setting("qwen_mt_url");
        DashScopeSpeech.SelectedValue = Setting("dashscope_asr_model", DashScopeSpeechModels[0].Value);
        DashScopeTranslation.SelectedValue = Setting("qwen_mt_model", DashScopeTranslationModels[0].Value);
        ChunkSeconds.Text = Setting("chunk", "8"); MaxSpeech.Text = Setting("max_speech", "12");
        BeforeSeconds.Text = Setting("before", "2"); AfterSeconds.Text = Setting("after", "2");
        MinSilence.Text = Setting("min_silence_ms", "450"); PaddingMs.Text = Setting("pad_ms", "80");
        MinSpeech.Text = Setting("min_speech", "3");
        AsrUrl.Text = Setting("asr_url"); AsrModel.Text = Setting("asr_model");
        LlmUrl.Text = Setting("llm_url");
        Diagnostics.IsChecked = Setting("diagnostics") is "1" or "true" or "True";
    }

    private void VadChanged(object sender, SelectionChangedEventArgs e)
    {
        if (VadThreshold is null) return;
        double oldDefault = previousVad == "fsmn" ? 0.8 : 0.5;
        if (string.IsNullOrWhiteSpace(VadThreshold.Text) ||
            (double.TryParse(VadThreshold.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out double current) && Math.Abs(current - oldDefault) < 0.0001))
            VadThreshold.Text = Selected(Vad) == "fsmn" ? "0.8" : "0.5";
        previousVad = Selected(Vad);
    }

    private string Setting(string key, string fallback = "") => settings[key]?.ToString() ?? fallback;
    private static string Selected(System.Windows.Controls.ComboBox box) => box.SelectedValue?.ToString() ?? "";
    private bool Installed(string id) => models[id]?.GetValue<bool>() == true;

    private async Task Refresh(bool loadSettings = false, bool force = false)
    {
        if (refreshing || (busy && !force) || exiting) return;
        refreshing = true;
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
            var result = await bridge.Run("status", cancellationToken: timeout.Token);
            bool wasInitialized = initialized;
            string previousModels = models.ToJsonString();
            activeModels = (result["active_models"] as JsonArray ?? new()).Select(item => item!.GetValue<string>()).ToHashSet();
            models = result["models"] as JsonObject ?? new();
            bool running = result["running"]?.GetValue<bool>() == true;
            ServiceStatus.Text = running ? "字幕服务已就绪" : "字幕服务已停止";
            ServiceDetail.Text = running
                ? "在 PotPlayer 播放窗口按 Ctrl+Alt+J，开始为该窗口翻译。"
                : "选择模型后启动服务。已开启的播放窗口会在应用设置后自动接续。";
            tray.Text = running ? "AheadSubs · 服务就绪" : "AheadSubs · 已停止";
            ApplyButton.Content = running ? "保存并应用" : "保存并启动";
            StopButton.IsEnabled = running && !busy;
            integrations = result["integrations"] as JsonObject ?? new();
            UpdatePlayers();
            if (result["active_sessions"] is JsonValue sessionCount && sessionCount.TryGetValue<int>(out int count))
            {
                SessionStatus.Text = count > 0 ? $"已连接 {count} 个播放会话。" : "尚未连接播放窗口。";
                SessionStatus.Visibility = Visibility.Visible;
            }
            else SessionStatus.Visibility = Visibility.Collapsed;
            if (loadSettings || !initialized)
            {
                settings = result["settings"] as JsonObject ?? new();
                chatGptAccounts = result["chatgpt_accounts"] as JsonArray ?? new();
                miniMaxModel = result["minimax_model"]?.ToString() ?? miniMaxModel;
                LoadControls();
                LoadKeys(result["credentials"]);
                initialized = true;
            }
            else
            {
                if (result["chatgpt_accounts"] is JsonArray accounts && !JsonNode.DeepEquals(chatGptAccounts, accounts))
                    LoadChatGptAccounts(accounts, Selected(ChatGptAccount), Selected(ChatGptModel));
                if (previousModels != models.ToJsonString())
                {
                    string speech = Selected(SpeechModel), translation = Selected(TranslationModel);
                    PopulateModels();
                    if (speech.Length > 0) SpeechModel.SelectedValue = speech;
                    if (translation.Length > 0) TranslationModel.SelectedValue = translation;
                }
            }
            UpdateModelDownloads();
            if (PresetDisclosure.IsExpanded)
            {
                if (wasInitialized) UpdatePresetGuide();
                else await CheckPreset();
            }
        }
        catch (Exception ex)
        {
            ServiceStatus.Text = "无法连接后台";
            ServiceDetail.Text = Friendly(ex);
            if (!initialized) { LoadControls(); SourceLanguage.SelectedIndex = 0; TargetLanguage.SelectedIndex = 0; Vad.SelectedIndex = 0; }
        }
        finally { refreshing = false; }
    }

    private void PopulateModels()
    {
        string speech = Setting("asr", "qwen") switch
        { "qwen" => "qwen-" + Setting("qwen_size", "0.6b"), "local" => "whisper-small",
          "dashscope" => Setting("dashscope_asr_model", DashScopeSpeechModels[0].Value), var other => other };
        string translation = Setting("mt", "local") switch
        { "local" => "nllb", "qwen-mt" => Setting("qwen_mt_model", "qwen-mt-flash"), "openai" => Setting("llm_model", "gpt-4.1-mini"), var other => other };
        var speechOptions = LocalModels.Where(m => m.Value != "nllb" && Installed(m.Value))
            .Select(m => new Choice("[本地] " + m.Label, m.Value)).ToList();
        speechOptions.Add(new("[云端] OpenAI Whisper", "openai"));
        speechOptions.AddRange(DashScopeSpeechModels.Select(CloudChoice));
        if (speech == "compatible") speechOptions.Add(new("[自定义] 已配置的语音识别 API", "compatible"));
        SpeechModel.ItemsSource = speechOptions;
        SpeechModel.SelectedValue = speech;
        var translationOptions = new List<Choice>();
        if (Installed("nllb")) translationOptions.Add(new("[本地] NLLB-200 600M INT8 · CPU / CUDA", "nllb"));
        translationOptions.AddRange(DashScopeTranslationModels.Select(CloudChoice));
        translationOptions.Add(new("[云端] OpenAI GPT-4.1 mini", "gpt-4.1-mini"));
        translationOptions.Add(new("[云端] ChatGPT 订阅", "chatgpt"));
        translationOptions.Add(new("[云端] " + miniMaxModel, "minimax"));
        if (Setting("mt") == "openai" && !translationOptions.Any(m => m.Value == translation))
            translationOptions.Add(new("[云端] OpenAI " + translation, translation));
        if (translation == "compatible") translationOptions.Add(new("[自定义] 已配置的翻译 API", "compatible"));
        TranslationModel.ItemsSource = translationOptions;
        TranslationModel.SelectedValue = translation;
        UpdateFolderModelChoices(Selected(FolderRuleSpeechModel), Selected(FolderRuleTranslationModel));
        UpdateContext();
    }

    private static Choice CloudChoice(Choice model) => model with { Label = "[云端] " + model.Label };

    private void SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (TranslationEnhancement is not null && TranslationHint is not null) UpdateContext();
    }

    private void UpdateContext()
    {
        string mt = Selected(TranslationModel);
        bool qwen = mt.StartsWith("qwen-mt-", StringComparison.Ordinal);
        bool openAi = (mt.Length > 0 && mt != "nllb" && !qwen) || Selected(SpeechModel) is "openai" or "compatible";
        CloudKeysButton.Visibility = openAi || qwen || IsDashScopeSpeech(Selected(SpeechModel)) ? Visibility.Visible : Visibility.Collapsed;
        bool contextual = mt.Length > 0 && mt != "nllb" && !qwen;
        bool styleOnly = mt is "qwen-mt-flash" or "qwen-mt-plus";
        string? key = mt == "compatible" ? "compatible:" + LlmModel.Text.Trim()
            : mt == "chatgpt" ? (Selected(ChatGptModel) is { Length: > 0 } model ? "chatgpt:" + model : null)
            : mt == "minimax" ? "minimax:" + miniMaxModel
            : contextual ? "openai:" + mt : styleOnly ? "qwen-mt:" + mt : null;
        if (enhancementModel != key)
        {
            SaveEnhancementDraft();
            enhancementModel = key;
            var draft = key is not null && enhancementDrafts.TryGetValue(key, out var saved)
                ? saved : new EnhancementDraft(false, "4", "250", "");
            EnhancementEnabled.IsChecked = draft.Enabled;
            PreviousCues.Text = draft.PreviousCues;
            ContextChars.Text = draft.ContextChars;
            TranslationPrompt.Text = draft.Prompt;
            TranslationEnhancement.IsExpanded = draft.Enabled;
        }
        TranslationEnhancement.Visibility = key is null ? Visibility.Collapsed : Visibility.Visible;
        PreviousCuesPanel.Visibility = contextual ? Visibility.Visible : Visibility.Collapsed;
        TranslationCapabilityHint.Text = contextual
            ? "参考前文有助于译准指代和术语，也可能增加 token 用量和延迟。片段数填 0 时只用提示词。"
            : "用英文提示词指定领域或字幕风格。";
        TranslationHint.Text = mt == "chatgpt" ? "使用 ChatGPT 订阅额度 · " + (ChatGptModel.SelectedItem is Choice modelChoice ? modelChoice.Label : "请先登录并选择模型")
            : mt == "minimax" ? "用量由 MiniMax Key 类型决定。"
            : mt == "nllb" ? "本地运行"
            : mt.Length == 0 ? "请选择已安装的本地模型，或使用自己的云端 API 账户。"
            : "";
        UpdateCompute();
        UpdatePrices();
    }

    private void PriceChanged(object sender, RoutedEventArgs e) => UpdatePrices();

    private void UpdatePrices()
    {
        if (CloudNmtCost is null) return;
        var language = Language.GetSpecificCulture();
        string endpoint = QwenUrl.Text;
        ShowPrice(SpeechCost, Selected(SpeechModel), endpoint, language);
        ShowPrice(TranslationCost, Selected(TranslationModel), endpoint, language);
        ShowPrice(CloudAsrCost, Selected(DashScopeSpeech), endpoint, language);
        ShowPrice(CloudNmtCost, Selected(DashScopeTranslation), endpoint, language);
        ShowPrice(OpenAiAsrCost, "openai", endpoint, language);
        ShowPrice(OpenAiMtCost, "gpt-4.1-mini", endpoint, language);
    }

    private static void ShowPrice(TextBlock label, string model, string endpoint, CultureInfo language)
    {
        label.Text = CloudPrices.Hourly(model, endpoint, language);
        label.Visibility = label.Text.Length == 0 ? Visibility.Collapsed : Visibility.Visible;
    }

    private void SaveEnhancementDraft()
    {
        if (enhancementModel is null) return;
        var draft = new EnhancementDraft(EnhancementEnabled.IsChecked == true, PreviousCues.Text.Trim(),
            ContextChars.Text.Trim(), TranslationPrompt.Text.Trim());
        if (draft.Enabled || draft.PreviousCues != "4" || draft.ContextChars != "250" || draft.Prompt.Length > 0
            || enhancementDrafts.ContainsKey(enhancementModel))
            enhancementDrafts[enhancementModel] = draft;
    }

    private JsonObject CollectEnhancements()
    {
        UpdateContext();
        SaveEnhancementDraft();
        var result = new JsonObject();
        foreach (var (model, draft) in enhancementDrafts)
        {
            int count = 0;
            int chars = 250;
            if (!model.StartsWith("qwen-mt:", StringComparison.Ordinal))
            {
                if (!int.TryParse(draft.PreviousCues, NumberStyles.None, CultureInfo.InvariantCulture, out count) || count is < 0 or > 8)
                    throw new InvalidOperationException("前文片段数请填写 0 到 8 的整数。");
                if (!int.TryParse(draft.ContextChars, NumberStyles.None, CultureInfo.InvariantCulture, out chars) || chars is < 20 or > 1000)
                    throw new InvalidOperationException("前文每段最多字符请填写 20 到 1000 的整数。");
            }
            result[model] = new JsonObject { ["enabled"] = draft.Enabled, ["previous_cues"] = count,
                ["context_chars"] = chars, ["prompt"] = draft.Prompt };
        }
        return result;
    }

    private void DeviceChanged(object sender, SelectionChangedEventArgs e) => UpdateCompute();

    private void UpdateCompute()
    {
        if (ComputeSummary is null || WhisperDevice is null || NllbDevice is null) return;
        string speech = Selected(SpeechModel), mt = Selected(TranslationModel);
        var routes = new List<string>();
        if (speech.StartsWith("qwen-", StringComparison.Ordinal) && !IsDashScopeSpeech(speech))
            routes.Add(SetupText.Get("asr-device", "Vulkan GPU"));
        else if (speech == "whisper-small") routes.Add(SetupText.Get("asr-device", DeviceName(WhisperDevice)));
        if (mt == "nllb") routes.Add(SetupText.Get("mt-device", DeviceName(NllbDevice)));
        ComputeSummary.Text = string.Join("  ·  ", routes);
        ComputeSummary.Visibility = Visible(routes.Count > 0);
        UpdatePresetHeading();
    }

    private static string DeviceName(System.Windows.Controls.ComboBox selector) =>
        SetupText.Get(Selected(selector) == "cuda" ? "cuda-device" : "cpu-device");

    private static string ModelName(string id) => LocalModels.First(model => model.Value == id).Label;

    private void UpdateModelDownloads()
    {
        var rows = LocalModels.Select((model, index) =>
        {
            string id = model.Value;
            bool downloaded = Installed(id), inUse = activeModels.Contains(id);
            string hardware = id.StartsWith("qwen-", StringComparison.Ordinal) ? "Vulkan GPU" : "CPU / NVIDIA CUDA";
            string status = downloaded ? SetupText.Get(inUse ? "active-model" : "installed-model")
                : guidedModels.Contains(id) ? SetupText.Get("needed") : "";
            return new ModelDownload(id, model.Label, SetupText.Get("model-info", hardware, ModelSizes[index]), status,
                SetupText.Get(downloaded ? "remove-model" : "download-model"), downloaded, !downloaded || !inUse,
                inUse ? SetupText.Get("uninstall-active") : null);
        }).ToArray();
        SpeechDownloads.ItemsSource = rows.Where(row => row.Id != "nllb").ToArray();
        TranslationDownloads.ItemsSource = rows.Where(row => row.Id == "nllb").ToArray();
    }

    private JsonObject CollectSettings(TranslationPreset? preset = null)
    {
        string speech = preset?.Speech ?? Selected(SpeechModel), translation = preset?.Translation ?? Selected(TranslationModel);
        if (speech.Length == 0 || translation.Length == 0)
            throw new InvalidOperationException("请选择语音识别和字幕翻译模型；本地模型需先在模型管理中安装。");
        if (!int.TryParse(ChunkSeconds.Text, NumberStyles.Integer, CultureInfo.InvariantCulture, out int chunk) || chunk < 4 || chunk > 20)
            throw new InvalidOperationException("每次处理时长请填写 4 到 20 之间的整数秒数。");
        if (!double.TryParse(MaxSpeech.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out double maximum) || maximum < 2 || maximum > 20)
            throw new InvalidOperationException("最长语音段请填写 2 到 20 之间的秒数。");
        var value = new JsonObject
        {
            ["source"] = Selected(SourceLanguage), ["route"] = "asr+mt", ["pot_hotkey"] = "1",
            ["asr_device"] = preset is { Speech: "whisper-small" } ? preset.Device : Selected(WhisperDevice),
            ["mt_device"] = preset is { Translation: "nllb" } ? preset.Device : Selected(NllbDevice),
            ["target"] = Selected(TargetLanguage), ["bilingual"] = Bilingual.IsChecked == true ? "1" : "0",
            ["translation_enhancements"] = CollectEnhancements(),
            ["vad_threshold"] = VadThreshold.Text.Trim(), ["backfill"] = Backfill.Text.Trim(), ["min_speech"] = MinSpeech.Text.Trim(),
            ["asr"] = IsDashScopeSpeech(speech) ? "dashscope"
                : speech.StartsWith("qwen-") ? "qwen" : speech == "whisper-small" ? "local" : speech,
            ["mt"] = translation == "nllb" ? "local" : translation.StartsWith("qwen-mt-") ? "qwen-mt"
                : translation is "compatible" or "chatgpt" or "minimax" ? translation : "openai",
            ["chatgpt_account"] = Selected(ChatGptAccount), ["chatgpt_model"] = Selected(ChatGptModel),
            ["credentials"] = CollectKeyEdits(),
            ["qwen_mt_url"] = QwenUrl.Text.Trim(), ["diagnostics"] = Diagnostics.IsChecked == true ? "1" : "0",
            ["chunk"] = ChunkSeconds.Text.Trim(), ["max_speech"] = MaxSpeech.Text.Trim(), ["vad_model"] = Selected(Vad),
            ["before"] = BeforeSeconds.Text.Trim(), ["after"] = AfterSeconds.Text.Trim(),
            ["min_silence_ms"] = MinSilence.Text.Trim(), ["pad_ms"] = PaddingMs.Text.Trim(),
            ["asr_url"] = AsrUrl.Text.Trim(), ["asr_model"] = AsrModel.Text.Trim(), ["llm_url"] = LlmUrl.Text.Trim()
        };
        if (IsDashScopeSpeech(speech)) value["dashscope_asr_model"] = speech;
        else if (speech.StartsWith("qwen-")) value["qwen_size"] = speech[5..];
        if (speech == "whisper-small") value["whisper_model"] = "small";
        if (translation.StartsWith("qwen-mt-")) value["qwen_mt_model"] = translation;
        else if (translation is not "nllb" and not "compatible" and not "chatgpt" and not "minimax") value["llm_model"] = translation;
        else if (translation == "compatible") value["llm_model"] = LlmModel.Text.Trim();
        return value;
    }

    private async Task Act(string message, Func<Task> action, string success, bool reloadSettings = false)
    {
        if (busy) return;
        busy = true; SetBusy(true); ActionStatus.Text = message; ActionStatus.Visibility = Visibility.Visible;
        ActionStatus.Foreground = System.Windows.Media.Brushes.DimGray;
        try
        {
            await action(); ActionStatus.Text = success;
            await Refresh(loadSettings: reloadSettings, force: true);
        }
        catch (Exception ex)
        {
            ActionStatus.Text = Friendly(ex);
            ActionStatus.Foreground = System.Windows.Media.Brushes.Firebrick;
            await Refresh(force: true);
            ShowSettings();
        }
        finally { busy = false; SetBusy(false); }
    }

    private void SetBusy(bool value)
    {
        SettingsPanel.IsEnabled = !value; ApplyButton.IsEnabled = !value;
        StopButton.IsEnabled = !value; ExitButton.IsEnabled = !value;
        Progress.Visibility = value ? Visibility.Visible : Visibility.Collapsed;
    }

    private static string Friendly(Exception error) => error is OperationCanceledException
        ? "后台响应超时。请稍后重试；若持续发生，可开启诊断日志排查。" : error.Message;

    private Task<JsonObject> ApplySettings(JsonObject values) =>
        bridge.Run("apply", "refresh-in-ui", input: values, progress: stage => ActionStatus.Text = SetupText.Get(stage));

    private async void Apply(object sender, RoutedEventArgs e) => await Act("正在应用设置，已开启的窗口会自动接续…",
        async () => { await ApplySettings(CollectSettings()); }, "设置已应用。到播放器按 Ctrl+Alt+J 开启翻译。", reloadSettings: true);

    private async void Stop(object sender, RoutedEventArgs e) => await Act("正在停止后台并释放资源…",
        async () => { await bridge.Run("stop"); }, "服务已停止，后台资源已释放。");

    private async void ManageModel(object sender, RoutedEventArgs e)
    {
        if (((FrameworkElement)sender).Tag is not ModelDownload row || !row.CanAct) return;
        if (row.Installed && System.Windows.MessageBox.Show(this,
            SetupText.Get(row.Id.StartsWith("qwen-", StringComparison.Ordinal) ? "uninstall-ask-local" : "uninstall-ask", row.Label),
            "AheadSubs", MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No) != MessageBoxResult.Yes)
            return;
        await Act(SetupText.Get(row.Installed ? "uninstalling" : "downloading", row.Label), async () =>
        {
            await bridge.Run(row.Installed ? "uninstall" : "install", row.Id);
        }, SetupText.Get(row.Installed ? "uninstalled" : "downloaded"));
    }

    private void UpdatePlayers()
    {
        UpdateIntegration("potplayer", PlayerDetection, PotPlayerFolder, ConfigurePotPlayer, RemovePotPlayer, PickPotPlayer);
        UpdateIntegration("mpv", MpvIntegration, MpvFolder, ConfigureMpv, RemoveMpv, PickMpv);
    }

    private void UpdateIntegration(string player, TextBlock status, TextBlock folder,
        FrameworkElement configure, FrameworkElement remove, FrameworkElement pick)
    {
        var value = integrations[player];
        bool installed = value?["installed"]?.GetValue<bool>() == true;
        bool detected = value?["detected"]?.GetValue<bool>() == true;
        configure.Visibility = installed ? Visibility.Collapsed : Visibility.Visible;
        remove.Visibility = installed ? Visibility.Visible : Visibility.Collapsed;
        pick.Visibility = !installed && detected ? Visibility.Visible : Visibility.Collapsed;
        folder.Text = detected || installed ? value?["folder"]?.ToString() ?? "" : "";
        folder.Visibility = folder.Text.Length > 0 ? Visibility.Visible : Visibility.Collapsed;
        status.Text = value?["configured"]?.GetValue<bool>() == true ? "已配置"
            : installed ? "部分配置" : detected ? "未配置" : "未找到位置";
    }

    private async void ConfigurePlayer(object sender, RoutedEventArgs e) =>
        await ConfigurePlayer(((FrameworkElement)sender).Tag.ToString()!, false);

    private async void PickPlayerFolder(object sender, RoutedEventArgs e) =>
        await ConfigurePlayer(((FrameworkElement)sender).Tag.ToString()!, true);

    private async Task ConfigurePlayer(string player, bool pickFolder)
    {
        string? folder = null;
        if (pickFolder || integrations[player]?["detected"]?.GetValue<bool>() != true)
        {
            var dialog = new Microsoft.Win32.OpenFolderDialog
            { Title = player == "potplayer" ? "选择 PotPlayer 安装文件夹" : "选择 mpv 配置文件夹" };
            var current = integrations[player]?["folder"]?.ToString();
            if (Directory.Exists(current)) dialog.InitialDirectory = current;
            if (dialog.ShowDialog(this) != true) return;
            folder = dialog.FolderName;
        }
        await Act("正在配置…", async () => { await bridge.Run("integrate", player, folder: folder); },
                  "已配置。重开播放器后生效。");
    }

    private async void RemovePlayer(object sender, RoutedEventArgs e) => await Act("正在卸载…",
        async () => { await bridge.Run("unintegrate", ((FrameworkElement)sender).Tag.ToString()); },
        "已卸载。重开播放器后生效。");

    private IEnumerable<(string Provider, ApiKeyEditor Editor)> KeyEditors()
    {
        yield return ("openai", OpenAiKey);
        yield return ("dashscope", QwenKey);
        yield return ("minimax", MiniMaxKey);
        yield return ("compatible-asr", CustomAsrKey);
        yield return ("compatible-mt", CustomMtKey);
    }

    private void LoadKeys(JsonNode? state, string? group = null)
    {
        foreach (var (provider, editor) in KeyEditors())
            if (group is null || provider.StartsWith(group, StringComparison.Ordinal)) editor.Load(state?[provider]);
    }

    private JsonObject CollectKeyEdits(string? group = null)
    {
        var edits = new JsonObject();
        foreach (var (provider, editor) in KeyEditors())
            if ((group is null || provider.StartsWith(group, StringComparison.Ordinal)) && editor.Edit() is JsonObject edit)
                edits[provider] = edit;
        return edits;
    }

    private async void SaveKeys(object sender, RoutedEventArgs e)
    {
        string group = Selected(CloudProvider);
        var edits = CollectKeyEdits(group);
        if (edits.Count == 0) return;
        await Act("正在保存密钥…", async () =>
        {
            var result = await bridge.Run("save-credentials", input: edits);
            LoadKeys(result["credentials"], group);
        }, AutomationText.Get("CredentialsSaved"));
    }

    internal void RenderPreviews(string directory)
    {
        if (!previewMode) throw new InvalidOperationException("Preview requires fixture mode.");
        VerifyControls();
        VerifyInspection();
        Directory.CreateDirectory(directory);
        string[] pages = ["translation", "subtitles", "players", "models", "keys", "advanced", "advanced-vad",
                          "advanced-read-ahead", "translation-context", "chatgpt-oauth", "automation", "presets",
                          "status", "status-cloud", "folder-tasks"];
        for (int index = 0; index < pages.Length; index++)
        {
            if (index == 14) SettingsPanel.SelectedItem = FolderTasksTab;
            else if (index is 12 or 13) SettingsPanel.SelectedItem = StatusTab;
            else SettingsPanel.SelectedIndex = index switch { 8 or 11 => 0, 9 => 4, 10 => 6, _ => Math.Min(index, 5) };
            if (index is 6 or 7 && AdvancedTab.Content is ScrollViewer advanced)
                advanced.ScrollToVerticalOffset(index == 6 ? 600 : 1100);
            if (index == 8)
            {
                TranslationModel.SelectedValue = "gpt-4.1-mini";
                TranslationEnhancement.IsExpanded = true;
                TranslationScroll.ScrollToVerticalOffset(320);
            }
            if (index == 9) CloudProvider.SelectedValue = "chatgpt";
            if (index == 11)
            {
                TranslationModel.SelectedValue = "qwen-mt-flash";
                TranslationEnhancement.IsExpanded = false;
                PresetChoice.SelectedValue = "cpu";
                missingRequirements = [];
                UpdatePresetGuide();
                PresetDisclosure.IsExpanded = true;
                TranslationScroll.ScrollToTop();
            }
            RootLayout.Measure(new System.Windows.Size(1040, 760));
            RootLayout.Arrange(new Rect(0, 0, 1040, 760));
            RootLayout.UpdateLayout();
            if (index == 13) StatusDashboard.ScrollToCloud();
            if (index == 14 && FolderTasksTab.Content is ScrollViewer folderTasks)
                folderTasks.ScrollToVerticalOffset(525);
            Dispatcher.Invoke(() => { }, System.Windows.Threading.DispatcherPriority.Render);
            RootLayout.UpdateLayout();
            var bitmap = new System.Windows.Media.Imaging.RenderTargetBitmap(1040, 760, 96, 96, System.Windows.Media.PixelFormats.Pbgra32);
            bitmap.Render(RootLayout);
            var encoder = new System.Windows.Media.Imaging.PngBitmapEncoder();
            encoder.Frames.Add(System.Windows.Media.Imaging.BitmapFrame.Create(bitmap));
            using var output = File.Create(Path.Combine(directory, pages[index] + ".png"));
            encoder.Save(output);
        }
        tray.Dispose();
    }

    private void VerifyControls()
    {
        static void Require(bool condition, string message)
        { if (!condition) throw new InvalidOperationException("Desktop preview check failed: " + message); }
        Require(ConfigurePotPlayer.Visibility == Visibility.Collapsed && RemovePotPlayer.Visibility == Visibility.Visible
                && ConfigureMpv.Visibility == Visibility.Visible && RemoveMpv.Visibility == Visibility.Collapsed,
                "each player has one setup action");
        var catalog = ((IEnumerable<ModelDownload>)SpeechDownloads.ItemsSource).Concat((IEnumerable<ModelDownload>)TranslationDownloads.ItemsSource).ToDictionary(model => model.Id);
        Require(catalog["qwen-1.7b"] is { Installed: true, CanAct: false }
                && catalog["whisper-small"].Details.Contains(0.49.ToString("0.00", CultureInfo.CurrentUICulture)) && catalog["whisper-small"].CanAct,
                "model size and download state");
        LoadKeys(new JsonObject { ["openai"] = new JsonObject { ["mode"] = "direct", ["saved"] = true } });
        Require(CollectKeyEdits().Count == 0, "loading a stored key leaves it untouched");
        var values = CollectSettings();
        Require(values["target"]?.ToString() == "zh" && values["bilingual"]?.ToString() == "1", "language and bilingual settings");
        Require(!PresetDisclosure.IsExpanded && TranslationPreset.All.Length == 4, "four presets stay collapsed on launch");
        PresetChoice.SelectedValue = "cpu";
        missingRequirements = [];
        UpdatePresetGuide();
        Require(PresetDownload.Visibility == Visibility.Visible && PresetModels.Visibility == Visibility.Visible
            && PresetApply.Visibility == Visibility.Collapsed, "offer either download path for missing models");
        GoPresetModels(PresetModels, new RoutedEventArgs());
        Require(SettingsPanel.SelectedItem == ModelsTab && guidedModels.SetEquals(["whisper-small"]), "model management highlights the missing model");
        SettingsPanel.SelectedItem = TranslationTab;
        PresetChoice.SelectedValue = "recommended";
        missingRequirements = ["dashscope"];
        UpdatePresetGuide();
        Require(PresetKeys.Visibility == Visibility.Visible && PresetApply.Visibility == Visibility.Collapsed,
            "missing credentials route to Bailian");
        missingRequirements = [];
        UpdatePresetGuide();
        Require(PresetApply.Visibility == Visibility.Visible && PresetDownload.Visibility == Visibility.Collapsed, "ready preset can be applied");
        values = CollectSettings(TranslationPreset.All.Single(p => p.Id == "high-gpu"));
        Require(values["qwen_size"]?.ToString() == "1.7b" && values["mt_device"]?.ToString() == "cuda"
            && values["source"]?.ToString() == "ja" && values["bilingual"]?.ToString() == "1", "preset keeps the language and display preferences");
        Require(Selected(TranslationModel) == "qwen-mt-flash", "preset selection alone leaves the current route intact");
        Require(SetupText.Format(CultureInfo.GetCultureInfo("ja-JP"), "download") == "Download now", "unknown locale falls back to English");
        Require(values["min_speech"]?.ToString() == "3" && values["pad_ms"]?.ToString() == "80", "segmentation defaults");
        TargetLanguage.SelectedValue = "en"; Bilingual.IsChecked = false;
        values = CollectSettings();
        Require(values["target"]?.ToString() == "en" && values["bilingual"]?.ToString() == "0", "changed language and display settings");
        TargetLanguage.SelectedValue = "zh"; Bilingual.IsChecked = true;
        TranslationModel.SelectedValue = "gpt-4.1-mini";
        Require(TranslationEnhancement.Visibility == Visibility.Visible && PreviousCuesPanel.Visibility == Visibility.Visible, "LLM context controls");
        EnhancementEnabled.IsChecked = true; PreviousCues.Text = "3"; ContextChars.Text = "120";
        TranslationPrompt.Text = "Use natural dialogue.";
        TranslationModel.SelectedValue = "qwen-mt-lite";
        Require(TranslationEnhancement.Visibility == Visibility.Collapsed, "unsupported model controls");
        TranslationModel.SelectedValue = "qwen-mt-flash";
        Require(TranslationEnhancement.Visibility == Visibility.Visible && PreviousCuesPanel.Visibility == Visibility.Collapsed, "Qwen-MT style capability");
        EnhancementEnabled.IsChecked = true; TranslationPrompt.Text = "Use conversational subtitles.";
        TranslationModel.SelectedValue = "gpt-4.1-mini";
        Require(EnhancementEnabled.IsChecked == true && PreviousCues.Text == "3" && ContextChars.Text == "120"
                && TranslationPrompt.Text == "Use natural dialogue.", "per-model enhancement draft");
        Require(CollectSettings()["translation_enhancements"]?["openai:gpt-4.1-mini"]?["context_chars"]?.GetValue<int>() == 120,
                "context length reaches bridge");
        Require(CollectSettings()["translation_enhancements"]?["qwen-mt:qwen-mt-flash"]?["previous_cues"]?.GetValue<int>() == 0,
                "NMT provider receives prompt only");
        SpeechModel.SelectedValue = "qwen-audio-3.1-asr-flash";
        Require(CollectSettings()["asr"]?.ToString() == "dashscope" && !ComputeSummary.Text.Contains("Vulkan"), "cloud ASR route");
        Require(SpeechCost.Text.Contains("0.03–0.06"), "Chinese hourly estimate");
        QwenUrl.Text = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1";
        Require(SpeechCost.Text.Contains("0.04–0.08"), "regional hourly estimate");
        QwenUrl.Text = "";
        SpeechModel.SelectedValue = "qwen-1.7b";
        TranslationModel.SelectedValue = "nllb"; NllbDevice.SelectedValue = "cuda";
        Require(ComputeSummary.Text.Contains("Vulkan") && ComputeSummary.Text.Contains("CUDA"), "separate GPU routes");
        NllbDevice.SelectedValue = "cpu";
        TranslationModel.SelectedValue = "qwen-mt-flash";
        VadThreshold.Text = "0.5"; Vad.SelectedValue = "fsmn";
        Require(VadThreshold.Text == "0.8", "VAD default threshold migration");
        VadThreshold.Text = "0.61"; Vad.SelectedValue = "silero";
        Require(VadThreshold.Text == "0.61", "preserve custom VAD threshold");
        VadThreshold.Text = "0.5";
        LoadChatGptAccounts(JsonNode.Parse("""
            [{"id":"oaiapp_test","email":"demo@example.com","connected":true,
              "models":[{"id":"test-model","name":"Test Model"}]}]
            """)!.AsArray(), "oaiapp_test", "test-model");
        CloudProvider.SelectedValue = "chatgpt";
        TranslationModel.SelectedValue = "chatgpt";
        values = CollectSettings();
        Require(ChatGptUse.IsEnabled && TranslationHint.Text.Contains("Test Model")
            && values["mt"]?.ToString() == "chatgpt" && values["chatgpt_account"]?.ToString() == "oaiapp_test"
            && values["chatgpt_model"]?.ToString() == "test-model", "ChatGPT account and model selection");
        TranslationModel.SelectedValue = "minimax";
        Require(CollectSettings()["mt"]?.ToString() == "minimax", "MiniMax text route");
        CloudProvider.SelectedValue = "dashscope";
        TranslationModel.SelectedValue = "qwen-mt-flash";
    }

    private static void SelectCustom(System.Windows.Controls.ComboBox box, string label)
    {
        var choices = ((IEnumerable<Choice>)box.ItemsSource).ToList();
        if (!choices.Any(c => c.Value == "compatible")) choices.Add(new(label, "compatible"));
        box.ItemsSource = choices; box.SelectedValue = "compatible";
    }
    private void ChooseCustomSpeech(object sender, RoutedEventArgs e) => SelectCustom(SpeechModel, "[自定义] 语音识别 API");
    private void ChooseCustomTranslation(object sender, RoutedEventArgs e) => SelectCustom(TranslationModel, "[自定义] 翻译 API");

    private static bool IsDashScopeSpeech(string speech) => speech.StartsWith("qwen-audio-", StringComparison.Ordinal);

    private void CloudProviderChanged(object sender, SelectionChangedEventArgs e)
    {
        if (CustomCloudPanel is null) return;
        string provider = Selected(CloudProvider);
        QwenMtPanel.Visibility = provider == "dashscope" ? Visibility.Visible : Visibility.Collapsed;
        OpenAiPanel.Visibility = provider == "openai" ? Visibility.Visible : Visibility.Collapsed;
        ChatGptPanel.Visibility = provider == "chatgpt" ? Visibility.Visible : Visibility.Collapsed;
        MiniMaxPanel.Visibility = provider == "minimax" ? Visibility.Visible : Visibility.Collapsed;
        CustomCloudPanel.Visibility = provider == "compatible" ? Visibility.Visible : Visibility.Collapsed;
    }

    private void LoadChatGptAccounts(JsonArray accounts, string account, string model)
    {
        chatGptAccounts = accounts;
        var choices = accounts.OfType<JsonObject>().Select(profile =>
        {
            string id = profile["id"]?.ToString() ?? "";
            string email = profile["email"]?.ToString() ?? "ChatGPT";
            return new Choice($"{email} · {id[^Math.Min(6, id.Length)..]}", id);
        }).ToList();
        ChatGptAccount.ItemsSource = choices;
        ChatGptAccount.SelectedValue = account;
        if (account.Length == 0 && choices.Count > 0) ChatGptAccount.SelectedIndex = 0;
        UpdateChatGptAccount();
        if (model.Length > 0 && ChatGptModel.ItemsSource is IEnumerable<Choice> models
            && models.Any(choice => choice.Value == model))
            ChatGptModel.SelectedValue = model;
    }

    private void ChatGptAccountChanged(object sender, SelectionChangedEventArgs e) => UpdateChatGptAccount();

    private void UpdateChatGptAccount()
    {
        if (ChatGptModel is null || ChatGptUse is null) return;
        string id = Selected(ChatGptAccount);
        var profile = chatGptAccounts.OfType<JsonObject>().FirstOrDefault(item => item["id"]?.ToString() == id);
        bool connected = profile?["connected"]?.GetValue<bool>() == true;
        var choices = (profile?["models"] as JsonArray ?? new()).OfType<JsonObject>()
            .Select(item => new Choice(item["name"]?.ToString() ?? "", item["id"]?.ToString() ?? "")).ToList();
        ChatGptModel.ItemsSource = choices;
        ChatGptModel.SelectedIndex = choices.Count > 0 ? 0 : -1;
        ChatGptStatus.Text = connected
            ? choices.Count > 0 ? "ChatGPT 订阅已授权。" : "ChatGPT 订阅已授权，请刷新模型。"
            : id.Length > 0 ? "请重新授权使用 ChatGPT 订阅。" : "请在浏览器中登录并授权使用订阅。";
        ChatGptReauthorize.IsEnabled = id.Length > 0;
        ChatGptSignOut.IsEnabled = connected;
        ChatGptReloadModels.IsEnabled = connected;
        ChatGptUse.IsEnabled = connected && choices.Count > 0;
        UpdateContext();
    }

    private async Task ChatGptAction(string command, string? account, string progress)
    {
        if (busy || previewMode) return;
        busy = true; SetBusy(true); ActionStatus.Text = progress; ActionStatus.Visibility = Visibility.Visible;
        ActionStatus.Foreground = System.Windows.Media.Brushes.DimGray;
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(command == "chatgpt-login" ? 245 : 90));
            var result = await bridge.Run(command, account, cancellationToken: timeout.Token);
            string model = Selected(ChatGptModel);
            LoadChatGptAccounts(result["accounts"] as JsonArray ?? new(),
                result["selected"]?.ToString() ?? account ?? "", model);
            ActionStatus.Text = result["notice"]?.ToString() ?? (command == "chatgpt-logout"
                ? result["revoked"]?.GetValue<bool>() == true ? "已退出 ChatGPT。" : "已在本机退出。请在 ChatGPT 设置中确认已撤销授权。"
                : ChatGptStatus.Text);
        }
        catch (Exception ex)
        {
            ActionStatus.Text = Friendly(ex);
            ActionStatus.Foreground = System.Windows.Media.Brushes.Firebrick;
            try
            {
                using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
                var result = await bridge.Run("chatgpt-status", cancellationToken: timeout.Token);
                LoadChatGptAccounts(result["accounts"] as JsonArray ?? new(),
                    Selected(ChatGptAccount), Selected(ChatGptModel));
            }
            catch (Exception) { }
        }
        finally { busy = false; SetBusy(false); }
    }

    private async void ChatGptLogin(object sender, RoutedEventArgs e) => await ChatGptAction(
        "chatgpt-login", sender == ChatGptReauthorize ? Selected(ChatGptAccount) : null, "请在浏览器中完成 ChatGPT 登录和授权…");
    private async void ChatGptLogout(object sender, RoutedEventArgs e) => await ChatGptAction(
        "chatgpt-logout", Selected(ChatGptAccount), "正在退出 ChatGPT…");
    private async void ChatGptRefreshModels(object sender, RoutedEventArgs e) => await ChatGptAction(
        "chatgpt-models", Selected(ChatGptAccount), "正在读取 ChatGPT 模型…");
    private void ChatGptUsage(object sender, RoutedEventArgs e) => Process.Start(
        new ProcessStartInfo("https://chatgpt.com/settings/usage") { UseShellExecute = true });
    private void ChooseChatGptTranslation(object sender, RoutedEventArgs e)
    { TranslationModel.SelectedValue = "chatgpt"; SettingsPanel.SelectedItem = TranslationTab; }

    private void ChooseMiniMaxTranslation(object sender, RoutedEventArgs e)
    { TranslationModel.SelectedValue = "minimax"; SettingsPanel.SelectedItem = TranslationTab; }

    private void ChooseDashScopeSpeech(object sender, RoutedEventArgs e)
    { SpeechModel.SelectedValue = Selected(DashScopeSpeech); SettingsPanel.SelectedItem = TranslationTab; }

    private void ChooseDashScopeTranslation(object sender, RoutedEventArgs e)
    { TranslationModel.SelectedValue = Selected(DashScopeTranslation); SettingsPanel.SelectedItem = TranslationTab; }

    private void ChooseOpenAiSpeech(object sender, RoutedEventArgs e)
    { SpeechModel.SelectedValue = "openai"; SettingsPanel.SelectedItem = TranslationTab; }

    private void ChooseOpenAiTranslation(object sender, RoutedEventArgs e)
    { TranslationModel.SelectedValue = "gpt-4.1-mini"; SettingsPanel.SelectedItem = TranslationTab; }

    private async void OpenLogs(object sender, RoutedEventArgs e) => await Act("正在打开日志目录…", async () =>
    {
        var result = await bridge.Run("logs");
        string? file = result["logs"]?["server"]?.ToString();
        string? directory = file is null ? null : Path.GetDirectoryName(file);
        if (directory is null || !Directory.Exists(directory)) throw new InvalidOperationException("尚未创建日志目录。");
        Process.Start(new ProcessStartInfo(directory) { UseShellExecute = true });
    }, "日志目录已打开。");

    private void OnClosing(object? sender, CancelEventArgs e)
    {
        if (exiting) return;
        e.Cancel = true; Hide();
        if (!trayExplained)
        {
            trayExplained = true;
            tray.ShowBalloonTip(3000, "字幕翻译仍在后台", "双击托盘图标打开设置；右键选择“停止并退出”释放资源。", Forms.ToolTipIcon.Info);
        }
    }

    private async void Exit(object sender, RoutedEventArgs e)
    {
        ActionStatus.Visibility = Visibility.Visible;
        if (busy) { ShowSettings(); ActionStatus.Text = "请等待当前操作结束后退出。"; return; }
        busy = true; SetBusy(true); ActionStatus.Text = "正在停止服务并退出…";
        try
        {
            await bridge.Run("stop");
            ExitDesktop();
        }
        catch (Exception ex)
        {
            busy = false; SetBusy(false); ShowSettings();
            ActionStatus.Text = "尚未退出：" + Friendly(ex);
            if (System.Windows.MessageBox.Show(this,
                "无法确认后台已经停止。只退出设置界面？后台进程可能仍在运行。", "退出字幕翻译",
                MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                ExitDesktop();
        }
    }

    private void ExitDesktop()
    {
        StopUpdateChecks();
        exiting = true;
        tray.Dispose();
        System.Windows.Application.Current.Shutdown();
    }
}
