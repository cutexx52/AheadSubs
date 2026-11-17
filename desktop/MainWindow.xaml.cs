using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using Forms = System.Windows.Forms;

namespace LocalVideoSubtitleTranslator;

public partial class MainWindow : Window
{
    private sealed record Choice(string Label, string Value);
    private static readonly Choice[] LocalModels =
    [new("Qwen3-ASR 0.6B · 轻量识别", "qwen-0.6b"), new("Qwen3-ASR 1.7B · 识别", "qwen-1.7b"),
     new("Whisper Small · 识别", "whisper-small"), new("NLLB-200 600M · 翻译", "nllb")];
    private readonly EngineBridge bridge = new();
    private readonly Forms.NotifyIcon tray;
    private readonly bool previewMode;
    private JsonObject settings = new();
    private JsonObject models = new();
    private bool busy, refreshing, initialized, exiting, trayExplained, inspecting, loadingMedia;
    private string previousVad = "silero";
    private sealed record SubtitleRow(string Time, string Original, string Translation);

    public MainWindow(bool preview = false)
    {
        previewMode = preview;
        InitializeComponent();
        SourceLanguage.ItemsSource = new Choice[] { new("自动识别", ""), new("日语", "ja"),
            new("英语", "en"), new("中文", "zh"), new("韩语", "ko") };
        TargetLanguage.ItemsSource = new Choice[] { new("简体中文", "zh"), new("繁體中文", "zh-TW"),
            new("日语", "ja"), new("英语", "en"), new("韩语", "ko"), new("法语", "fr"), new("德语", "de"), new("西班牙语", "es") };
        Device.ItemsSource = new Choice[] { new("CPU · 无需 NVIDIA 显卡", "cpu"), new("NVIDIA 显卡 · CUDA", "cuda") };
        Vad.ItemsSource = new Choice[] { new("Silero · 默认", "silero"), new("阿里 FSMN · 可选", "fsmn") };
        InstallChoice.ItemsSource = LocalModels;
        InstallChoice.SelectedIndex = 0;
        tray = new Forms.NotifyIcon
        {
            Icon = System.Drawing.SystemIcons.Application,
            Text = "视频字幕翻译 · 正在连接", Visible = !preview,
            ContextMenuStrip = new Forms.ContextMenuStrip()
        };
        if (preview)
        {
            settings = new JsonObject { ["source"] = "ja", ["target"] = "zh", ["asr"] = "qwen",
                ["qwen_size"] = "1.7b", ["mt"] = "qwen-mt", ["qwen_mt_model"] = "qwen-mt-flash", ["bilingual"] = "1" };
            models = new JsonObject { ["qwen-0.6b"] = true, ["qwen-1.7b"] = true, ["whisper-small"] = true, ["nllb"] = true };
            LoadControls(); initialized = true;
            ServiceStatus.Text = "服务已就绪"; ServiceDetail.Text = "在 PotPlayer 播放窗口按 Ctrl+Alt+J 开启，Ctrl+Alt+K 关闭。";
            SessionStatus.Text = "已连接 2 个播放窗口。"; SessionStatus.Visibility = Visibility.Visible;
            ApplyButton.Content = "保存并应用"; PlayerDetection.Text = "已检测到 PotPlayer。";
            ModelSummary.Text = "已安装：Qwen3-ASR 0.6B、Qwen3-ASR 1.7B、Whisper Small、NLLB-200";
            MediaChoice.ItemsSource = new Choice[] { new("示例视频 · 日语 → 简体中文", "preview") }; MediaChoice.SelectedIndex = 0;
            SubtitleRows.ItemsSource = new SubtitleRow[] { new("00:12.4", "今日はいい天気ですね。", "今天天气真好。"),
                new("00:16.8", "少し散歩に行きませんか。", "要不要出去散散步？"), new("00:21.2", "いいですね。駅の近くに新しいお店ができたそうです。", "好啊。听说车站附近开了一家新店。") };
            InspectStatus.Text = "预览示例 · 3 条字幕。运行时显示已生成的真实结果。";
            return;
        }
        tray.ContextMenuStrip.Items.Add("打开设置", null, (_, _) => Dispatcher.Invoke(ShowSettings));
        tray.ContextMenuStrip.Items.Add("停止字幕服务", null, (_, _) => Dispatcher.Invoke(() => Stop(this, new RoutedEventArgs())));
        tray.ContextMenuStrip.Items.Add(new Forms.ToolStripSeparator());
        tray.ContextMenuStrip.Items.Add("停止并退出", null, (_, _) => Dispatcher.Invoke(() => Exit(this, new RoutedEventArgs())));
        tray.DoubleClick += (_, _) => Dispatcher.Invoke(ShowSettings);
        Loaded += async (_, _) => await Refresh(loadSettings: true);
    }

    public void ShowSettings()
    {
        Show(); WindowState = WindowState.Normal; Activate();
        if (initialized) _ = Refresh();
    }

    private async void RefreshStatus(object sender, RoutedEventArgs e) => await Refresh();
    private void GoKeys(object sender, RoutedEventArgs e) => SettingsPanel.SelectedItem = KeysTab;
    private void GoModels(object sender, RoutedEventArgs e) => SettingsPanel.SelectedItem = ModelsTab;

    private async void PageChanged(object sender, SelectionChangedEventArgs e)
    {
        if (e.Source == SettingsPanel && SettingsPanel.SelectedItem == InspectTab && initialized && !previewMode)
            await Inspect();
    }

    private void LoadControls()
    {
        PopulateModels();
        SourceLanguage.SelectedValue = Setting("source"); TargetLanguage.SelectedValue = Setting("target", "zh");
        Bilingual.IsChecked = Setting("bilingual", "0") is "1" or "true" or "True";
        Device.SelectedValue = Setting("device", "cpu");
        previousVad = Setting("vad_model", "silero"); Vad.SelectedValue = previousVad;
        VadThreshold.Text = Setting("vad_threshold", previousVad == "fsmn" ? "0.8" : "0.5");
        Backfill.Text = Setting("backfill", "4");
        OpenAiKey.Text = Setting("key_file"); QwenKey.Text = Setting("qwen_mt_key_file"); QwenUrl.Text = Setting("qwen_mt_url");
        ChunkSeconds.Text = Setting("chunk", "8"); MaxSpeech.Text = Setting("max_speech", "12");
        BeforeSeconds.Text = Setting("before", "2"); AfterSeconds.Text = Setting("after", "2");
        MinSilence.Text = Setting("min_silence_ms", "450"); PaddingMs.Text = Setting("pad_ms", "80");
        MinSpeech.Text = Setting("min_speech", "3");
        AsrUrl.Text = Setting("asr_url"); AsrModel.Text = Setting("asr_model");
        LlmUrl.Text = Setting("llm_url"); LlmModel.Text = Setting("llm_model");
        TranslationBefore.Text = Setting("translation_before", "0"); TranslationAfter.Text = Setting("translation_after", "0");
        TranslationPrompt.Text = Setting("translation_prompt");
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
            string previousModels = models.ToJsonString();
            models = result["models"] as JsonObject ?? new();
            bool running = result["running"]?.GetValue<bool>() == true;
            ServiceStatus.Text = running ? "字幕服务已就绪" : "字幕服务已停止";
            ServiceDetail.Text = running
                ? "在 PotPlayer 播放窗口按 Ctrl+Alt+J，开始为该窗口翻译。"
                : "选择模型后启动服务。已开启的播放窗口会在应用设置后自动接续。";
            tray.Text = running ? "视频字幕翻译 · 服务就绪" : "视频字幕翻译 · 已停止";
            ApplyButton.Content = running ? "保存并应用" : "保存并启动";
            StopButton.IsEnabled = running && !busy;
            PlayerDetection.Text = result["potplayer_detected"]?.GetValue<bool>() == true
                ? "已检测到 PotPlayer。" : "尚未检测到 PotPlayer；启动播放器后可再次安装菜单。";
            if (result["active_sessions"] is JsonValue sessionCount && sessionCount.TryGetValue<int>(out int count))
            {
                SessionStatus.Text = count > 0 ? $"已连接 {count} 个播放会话。" : "尚未连接播放窗口。";
                SessionStatus.Visibility = Visibility.Visible;
            }
            else SessionStatus.Visibility = Visibility.Collapsed;
            if (loadSettings || !initialized)
            {
                settings = result["settings"] as JsonObject ?? new();
                LoadControls();
                initialized = true;
            }
            else if (previousModels != models.ToJsonString())
            {
                string speech = Selected(SpeechModel), translation = Selected(TranslationModel);
                PopulateModels();
                if (speech.Length > 0) SpeechModel.SelectedValue = speech;
                if (translation.Length > 0) TranslationModel.SelectedValue = translation;
            }
            FirstRunPanel.Visibility = !Installed("nllb") && !Installed("qwen-0.6b") && !Installed("qwen-1.7b")
                ? Visibility.Visible : Visibility.Collapsed;
            string installed = string.Join("、", LocalModels.Where(m => Installed(m.Value)).Select(m => m.Label.Split('·')[0].Trim()));
            ModelSummary.Text = "已安装：" + (installed.Length > 0 ? installed : "暂无本地模型");
        }
        catch (Exception ex)
        {
            ServiceStatus.Text = "无法连接后台";
            ServiceDetail.Text = Friendly(ex);
            if (!initialized) { LoadControls(); SourceLanguage.SelectedIndex = 0; TargetLanguage.SelectedIndex = 0; Device.SelectedIndex = 0; Vad.SelectedIndex = 0; }
        }
        finally { refreshing = false; }
    }

    private void PopulateModels()
    {
        string speech = Setting("asr", "qwen") switch
        { "qwen" => "qwen-" + Setting("qwen_size", "0.6b"), "local" => "whisper-small", var other => other };
        string translation = Setting("mt", "local") switch
        { "local" => "nllb", "qwen-mt" => Setting("qwen_mt_model", "qwen-mt-flash"), "openai" => Setting("llm_model", "gpt-4.1-mini"), var other => other };
        var speechOptions = LocalModels.Where(m => m.Value != "nllb" && Installed(m.Value))
            .Select(m => new Choice("[本地] " + m.Label, m.Value)).ToList();
        speechOptions.Add(new("[云端] OpenAI Whisper", "openai"));
        if (speech == "compatible") speechOptions.Add(new("[自定义] 已配置的语音识别 API", "compatible"));
        SpeechModel.ItemsSource = speechOptions;
        SpeechModel.SelectedValue = speech;
        var translationOptions = new List<Choice>();
        if (Installed("nllb")) translationOptions.Add(new("[本地] NLLB-200 600M INT8", "nllb"));
        translationOptions.AddRange(new Choice[] { new("[云端] Qwen-MT Flash", "qwen-mt-flash"),
            new("[云端] Qwen-MT Lite", "qwen-mt-lite"), new("[云端] Qwen-MT Plus", "qwen-mt-plus"),
            new("[云端] OpenAI GPT-4.1 mini", "gpt-4.1-mini") });
        if (Setting("mt") == "openai" && !translationOptions.Any(m => m.Value == translation))
            translationOptions.Add(new("[云端] OpenAI " + translation, translation));
        if (translation == "compatible") translationOptions.Add(new("[自定义] 已配置的翻译 API", "compatible"));
        TranslationModel.ItemsSource = translationOptions;
        TranslationModel.SelectedValue = translation;
        UpdateContext();
    }

    private void SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (OpenAiPanel is not null) UpdateContext();
    }

    private void UpdateContext()
    {
        string mt = Selected(TranslationModel);
        bool qwen = mt.StartsWith("qwen-mt-", StringComparison.Ordinal);
        bool openAi = (mt.Length > 0 && mt != "nllb" && !qwen) || Selected(SpeechModel) is "openai" or "compatible";
        CloudKeysButton.Visibility = openAi || qwen ? Visibility.Visible : Visibility.Collapsed;
        bool contextual = mt.Length > 0 && mt != "nllb" && !qwen;
        TranslationBefore.IsEnabled = contextual; TranslationAfter.IsEnabled = contextual;
        TranslationPrompt.IsEnabled = contextual || mt is "qwen-mt-flash" or "qwen-mt-plus";
        TranslationCapabilityHint.Text = contextual ? "当前模型支持邻句上下文和补充要求。最多参考前后各 15 秒；要求限 1000 字。"
            : mt is "qwen-mt-flash" or "qwen-mt-plus" ? "当前模型仅支持英文领域 / 风格描述，不支持此处的邻句上下文。"
            : "当前模型不支持邻句上下文或补充要求。可选 OpenAI / 自定义 LLM 使用这些功能。";
        TranslationHint.Text = mt == "nllb" ? "本地运行，无 API 费用；字幕翻译质量因内容而异。"
            : mt.Length == 0 ? "请选择已安装的本地模型，或使用自己的云端 API 账户。"
            : "使用你自己的云端账户，按服务商价格计费。";
    }

    private JsonObject CollectSettings()
    {
        string speech = Selected(SpeechModel), translation = Selected(TranslationModel);
        if (speech.Length == 0 || translation.Length == 0)
            throw new InvalidOperationException("请选择语音识别和字幕翻译模型；本地模型需先在模型管理中安装。");
        if (!int.TryParse(ChunkSeconds.Text, NumberStyles.Integer, CultureInfo.InvariantCulture, out int chunk) || chunk < 4 || chunk > 20)
            throw new InvalidOperationException("每次处理时长请填写 4 到 20 之间的整数秒数。");
        if (!double.TryParse(MaxSpeech.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out double maximum) || maximum < 2 || maximum > 20)
            throw new InvalidOperationException("最长语音段请填写 2 到 20 之间的秒数。");
        var value = new JsonObject
        {
            ["source"] = Selected(SourceLanguage), ["device"] = Selected(Device), ["route"] = "asr+mt", ["pot_hotkey"] = "1",
            ["target"] = Selected(TargetLanguage), ["bilingual"] = Bilingual.IsChecked == true ? "1" : "0",
            ["translation_before"] = TranslationBefore.Text.Trim(), ["translation_after"] = TranslationAfter.Text.Trim(),
            ["translation_prompt"] = TranslationPrompt.Text.Trim(), ["vad_threshold"] = VadThreshold.Text.Trim(), ["backfill"] = Backfill.Text.Trim(), ["min_speech"] = MinSpeech.Text.Trim(),
            ["asr"] = speech.StartsWith("qwen-") ? "qwen" : speech == "whisper-small" ? "local" : speech,
            ["mt"] = translation == "nllb" ? "local" : translation.StartsWith("qwen-mt-") ? "qwen-mt" : translation == "compatible" ? "compatible" : "openai",
            ["key_file"] = OpenAiKey.Text.Trim(), ["qwen_mt_key_file"] = QwenKey.Text.Trim(),
            ["qwen_mt_url"] = QwenUrl.Text.Trim(), ["diagnostics"] = Diagnostics.IsChecked == true ? "1" : "0",
            ["chunk"] = ChunkSeconds.Text.Trim(), ["max_speech"] = MaxSpeech.Text.Trim(), ["vad_model"] = Selected(Vad),
            ["before"] = BeforeSeconds.Text.Trim(), ["after"] = AfterSeconds.Text.Trim(),
            ["min_silence_ms"] = MinSilence.Text.Trim(), ["pad_ms"] = PaddingMs.Text.Trim(),
            ["asr_url"] = AsrUrl.Text.Trim(), ["asr_model"] = AsrModel.Text.Trim(), ["llm_url"] = LlmUrl.Text.Trim()
        };
        if (speech.StartsWith("qwen-")) value["qwen_size"] = speech[5..];
        if (speech == "whisper-small") value["whisper_model"] = "small";
        if (translation.StartsWith("qwen-mt-")) value["qwen_mt_model"] = translation;
        else if (translation is not "nllb" and not "compatible") value["llm_model"] = translation;
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

    private async void Apply(object sender, RoutedEventArgs e) => await Act("正在应用设置，已开启的窗口会自动接续…",
        async () => { await bridge.Run("apply", input: CollectSettings()); }, "设置已应用。到播放器按 Ctrl+Alt+J 开启翻译。", reloadSettings: true);

    private async void Stop(object sender, RoutedEventArgs e) => await Act("正在停止后台并释放资源…",
        async () => { await bridge.Run("stop"); }, "服务已停止，后台资源已释放。");

    private async void SetupLocal(object sender, RoutedEventArgs e) => await Act("正在下载并准备本地模型，首次可能需要几分钟…",
        async () =>
        {
            foreach (string id in new[] { "qwen-0.6b", "nllb" })
                if (!Installed(id)) { ActionStatus.Text = "正在安装 " + id + "，请保持网络连接…"; await bridge.Run("install", id); }
            await bridge.Run("apply", input: new JsonObject { ["asr"] = "qwen", ["qwen_size"] = "0.6b", ["mt"] = "local", ["source"] = Selected(SourceLanguage), ["target"] = Selected(TargetLanguage), ["bilingual"] = Bilingual.IsChecked == true ? "1" : "0", ["device"] = "cpu", ["route"] = "asr+mt", ["pot_hotkey"] = "1", ["diagnostics"] = "0" });
        }, "本地模型已就绪。到 PotPlayer 按 Ctrl+Alt+J 开始翻译。", reloadSettings: true);

    private async void SetupCpu(object sender, RoutedEventArgs e) => await Act("正在准备 CPU 本地方案，首次可能需要几分钟…",
        async () =>
        {
            foreach (string id in new[] { "whisper-small", "nllb" })
                if (!Installed(id)) { ActionStatus.Text = "正在安装 " + id + "，请保持网络连接…"; await bridge.Run("install", id); }
            await bridge.Run("apply", input: new JsonObject { ["asr"] = "local", ["whisper_model"] = "small", ["mt"] = "local", ["source"] = Selected(SourceLanguage), ["target"] = Selected(TargetLanguage), ["bilingual"] = Bilingual.IsChecked == true ? "1" : "0", ["device"] = "cpu", ["route"] = "asr+mt", ["pot_hotkey"] = "1", ["diagnostics"] = "0" });
        }, "CPU 本地方案已就绪。速度取决于处理器，可在高级设置中更换设备。", reloadSettings: true);

    private async void InstallModel(object sender, RoutedEventArgs e) => await Act("正在下载并安装模型，请保持网络连接…",
        async () => { string id = Selected(InstallChoice); if (id.Length == 0) throw new InvalidOperationException("先选择要安装的模型。"); await bridge.Run("install", id); },
        "模型已安装，可在上方选择后应用。");

    private async void InstallPotPlayer(object sender, RoutedEventArgs e) => await Act("正在安装 PotPlayer 菜单…",
        async () => { await bridge.Run("integrate", "potplayer"); }, "PotPlayer 菜单已安装。重新打开播放器后生效。");

    private async void InstallMpv(object sender, RoutedEventArgs e) => await Act("正在安装 mpv 菜单…",
        async () => { await bridge.Run("integrate", "mpv"); }, "mpv 菜单已安装。重新打开播放器后生效。");

    private static void Browse(System.Windows.Controls.TextBox field)
    {
        var dialog = new Microsoft.Win32.OpenFileDialog { Title = "选择 API 密钥文件", CheckFileExists = true, Filter = "所有文件|*.*" };
        if (dialog.ShowDialog() == true) field.Text = dialog.FileName;
    }
    private void BrowseOpenAi(object sender, RoutedEventArgs e) => Browse(OpenAiKey);
    private void BrowseQwen(object sender, RoutedEventArgs e) => Browse(QwenKey);

    private async void RefreshSubtitles(object sender, RoutedEventArgs e) => await Inspect(Selected(MediaChoice));
    private void SubtitleSizeChanged(object sender, SizeChangedEventArgs e)
    {
        if (SubtitleRows.Columns.Count < 3) return;
        double width = Math.Max(180, (SubtitleRows.ActualWidth - 120) / 2);
        SubtitleRows.Columns[1].Width = width; SubtitleRows.Columns[2].Width = width;
    }
    private async void InspectMediaChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!loadingMedia && !previewMode && Selected(MediaChoice).Length > 0) await Inspect(Selected(MediaChoice));
    }

    private async Task Inspect(string? key = null)
    {
        if (inspecting || previewMode) return;
        inspecting = true; InspectRefreshButton.IsEnabled = false; InspectStatus.Text = "正在读取字幕…";
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
            var data = await bridge.Run("inspect", string.IsNullOrEmpty(key) ? null : key, cancellationToken: timeout.Token);
            loadingMedia = true;
            MediaChoice.ItemsSource = (data["media"] as JsonArray ?? new()).OfType<JsonObject>()
                .Select(m => new Choice(m["display_name"]?.ToString() ?? "视频", m["key"]?.ToString() ?? "")).ToList();
            MediaChoice.SelectedValue = data["key"]?.ToString();
            loadingMedia = false;
            var rows = (data["rows"] as JsonArray ?? new()).OfType<JsonObject>().Select(r =>
            {
                double start = r["start"]?.GetValue<double>() ?? 0;
                return new SubtitleRow(TimeSpan.FromSeconds(Math.Max(0, start)).ToString(@"hh\:mm\:ss\.f"),
                    r["original"]?.ToString() ?? "", r["translation"]?.ToString() ??
                    r["status_message"]?.ToString() ?? "");
            }).ToList();
            SubtitleRows.ItemsSource = rows;
            InspectStatus.Text = rows.Count > 0 ? $"已读取 {rows.Count} 条字幕。刷新可获取最新结果。" : "还没有生成字幕。在播放器中开启翻译后，再刷新查看。";
        }
        catch (Exception ex) { InspectStatus.Text = Friendly(ex); }
        finally { loadingMedia = false; inspecting = false; InspectRefreshButton.IsEnabled = true; }
    }

    internal void RenderPreviews(string directory)
    {
        if (!previewMode) throw new InvalidOperationException("Preview requires fixture mode.");
        VerifyControls();
        Directory.CreateDirectory(directory);
        string[] pages = ["translation", "subtitles", "players", "models", "keys", "advanced", "advanced-vad", "advanced-read-ahead"];
        for (int index = 0; index < pages.Length; index++)
        {
            SettingsPanel.SelectedIndex = Math.Min(index, 5);
            if (index >= 6 && AdvancedTab.Content is ScrollViewer advanced)
                advanced.ScrollToVerticalOffset(index == 6 ? 600 : 1100);
            RootLayout.Measure(new System.Windows.Size(1040, 760));
            RootLayout.Arrange(new Rect(0, 0, 1040, 760));
            RootLayout.UpdateLayout();
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
        var values = CollectSettings();
        Require(values["target"]?.ToString() == "zh" && values["bilingual"]?.ToString() == "1", "language and bilingual settings");
        Require(values["min_speech"]?.ToString() == "3" && values["pad_ms"]?.ToString() == "80", "segmentation defaults");
        TargetLanguage.SelectedValue = "en"; Bilingual.IsChecked = false;
        values = CollectSettings();
        Require(values["target"]?.ToString() == "en" && values["bilingual"]?.ToString() == "0", "changed language and display settings");
        TargetLanguage.SelectedValue = "zh"; Bilingual.IsChecked = true;
        TranslationModel.SelectedValue = "gpt-4.1-mini";
        Require(TranslationBefore.IsEnabled && TranslationPrompt.IsEnabled, "LLM context controls");
        TranslationModel.SelectedValue = "qwen-mt-lite";
        Require(!TranslationBefore.IsEnabled && !TranslationPrompt.IsEnabled, "unsupported model controls");
        TranslationModel.SelectedValue = "qwen-mt-flash";
        Require(!TranslationBefore.IsEnabled && TranslationPrompt.IsEnabled, "Qwen-MT style capability");
        VadThreshold.Text = "0.5"; Vad.SelectedValue = "fsmn";
        Require(VadThreshold.Text == "0.8", "VAD default threshold migration");
        VadThreshold.Text = "0.61"; Vad.SelectedValue = "silero";
        Require(VadThreshold.Text == "0.61", "preserve custom VAD threshold");
        VadThreshold.Text = "0.5";
    }

    private static void SelectCustom(System.Windows.Controls.ComboBox box, string label)
    {
        var choices = ((IEnumerable<Choice>)box.ItemsSource).ToList();
        if (!choices.Any(c => c.Value == "compatible")) choices.Add(new(label, "compatible"));
        box.ItemsSource = choices; box.SelectedValue = "compatible";
    }
    private void ChooseCustomSpeech(object sender, RoutedEventArgs e) => SelectCustom(SpeechModel, "[自定义] 语音识别 API");
    private void ChooseCustomTranslation(object sender, RoutedEventArgs e) => SelectCustom(TranslationModel, "[自定义] 翻译 API");

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
            await bridge.Run("stop"); exiting = true; tray.Dispose();
            System.Windows.Application.Current.Shutdown();
        }
        catch (Exception ex)
        {
            busy = false; SetBusy(false); ShowSettings();
            ActionStatus.Text = "尚未退出：" + Friendly(ex);
            if (System.Windows.MessageBox.Show(this,
                "无法确认后台已经停止。只退出设置界面？后台进程可能仍在运行。", "退出字幕翻译",
                MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
            { exiting = true; tray.Dispose(); System.Windows.Application.Current.Shutdown(); }
        }
    }
}
