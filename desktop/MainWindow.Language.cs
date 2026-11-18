using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Markup;
using ComboBox = System.Windows.Controls.ComboBox;

namespace AheadSubs;

public partial class MainWindow
{
    private bool localizing;

    private void ApplyWindowLanguage() => Language = XmlLanguage.GetLanguage(InterfaceLocale.Culture.Name);

    private void PopulateLanguagePicker()
    {
        var automatic = new ComboBoxItem { Tag = InterfaceLocale.Automatic };
        automatic.SetResourceReference(ContentProperty, "Desktop.FollowSystem");
        InterfaceLanguage.Items.Add(automatic);
        foreach (var item in InterfaceLocale.Languages)
            InterfaceLanguage.Items.Add(new ComboBoxItem { Content = item.NativeName, Tag = item.Locale });
        InterfaceLanguage.SelectedValue = InterfaceLocale.Preference;
    }

    private void InterfaceLanguageChanged(object sender, SelectionChangedEventArgs e)
    {
        if (localizing || InterfaceLanguage.SelectedValue is not string value || value == InterfaceLocale.Preference) return;
        var previous = InterfaceLocale.Culture;
        if (!InterfaceLocale.Select(value, persist: !previewMode))
        {
            InterfaceLanguage.SelectedValue = InterfaceLocale.Preference;
            ActionStatus.Text = UiText.Get("PreferenceFailed");
            ActionStatus.Visibility = Visibility.Visible;
            return;
        }
        if (!previous.Equals(InterfaceLocale.Culture)) RefreshLanguage(previous);
    }

    private void LocalizeChoices()
    {
        Choice LanguageChoice(string code) => new(FolderText("Lang_" + code), code);
        SourceLanguage.ItemsSource = new Choice[] { new(FolderText("Auto"), ""), LanguageChoice("ja"),
            LanguageChoice("en"), new(UiText.Get("Chinese"), "zh"), LanguageChoice("ko") };
        TargetLanguage.ItemsSource = InterfaceLocale.Languages.Select(item => LanguageChoice(item.Target)).ToArray();
        Vad.ItemsSource = new Choice[] { new(UiText.Get("Silero"), "silero"), new(UiText.Get("Fsmn"), "fsmn") };
        CloudProvider.ItemsSource = new Choice[] { new(UiText.Get("BailianProvider"), "dashscope"),
            new(UiText.Get("OpenAiKey"), "openai"), new(UiText.Get("ChatGptProvider"), "chatgpt"),
            new(UiText.Get("MinimaxKey"), "minimax"), new(UiText.Get("CompatibleProvider"), "compatible") };
        DashScopeSpeech.ItemsSource = DashScopeSpeechModels.Select(CloudChoice).ToArray();
        DashScopeTranslation.ItemsSource = DashScopeTranslationModels.Select(CloudChoice).ToArray();
    }

    private void RefreshLanguage(CultureInfo previous)
    {
        localizing = true;
        try
        {
            ApplyWindowLanguage();
            // Keep the editor in place, including unsubmitted model choices, prompts and credentials.
            ComboBox[] choices = [SourceLanguage, TargetLanguage, Vad, CloudProvider, DashScopeSpeech,
                DashScopeTranslation, WhisperDevice, NllbDevice, PresetChoice, FolderRuleSource,
                FolderRuleTarget, FolderRuleStyle];
            var selected = choices.Select(box => box.SelectedValue).ToArray();
            string speech = Selected(SpeechModel), translation = Selected(TranslationModel);
            LocalizeChoices();
            InitializeSetup();
            LocalizeFolderChoices();
            for (int i = 0; i < choices.Length; i++) choices[i].SelectedValue = selected[i];
            foreach (var field in new[] { FolderRuleMin, FolderRuleMax })
                if (decimal.TryParse(field.Text, NumberStyles.Number, previous, out var size))
                    field.Text = size.ToString(InterfaceLocale.Culture);
            PopulateModels(speech, translation);
            UpdatePresetHeading();
            UpdatePresetGuide();
            if (folderLoaded) ShowFolderQueue();
            else FolderQueueStatus.Text = FolderText("Loading");
            FolderActionStatus.Text = AutomationStatus.Text = "";
            if (!busy) ActionStatus.Visibility = Visibility.Collapsed;
            LocalizeInspection();
            SetInspectionFiles(subtitleFiles, (MediaList.SelectedItem as SubtitleFile)?.Id);
            if (SubtitleRows.Items.Count > 0) InspectPreviewNote.Text = InspectionText.Get("PreviewRows");
            UpdateChatGptControls();
            foreach (var (_, editor) in KeyEditors()) editor.UpdateMode();
            LoadAutomationText();
            if (lastAutomation is not null) UpdateAutomation(lastAutomation);
            LocalizeUpdates();
            StatusDashboard.Localize();
            LoadTrayMenu();
            UpdatePlayers();
            RenderServiceStatus();
        }
        finally { localizing = false; }
    }

    private void VerifyLanguageSwitch()
    {
        string[] tabs = ["字幕", "字幕", "字幕", "Subtitles", "자막", "Sous-titres", "Untertitel", "Subtítulos"];
        var initial = InterfaceLocale.Culture;
        var initialTranslation = Selected(TranslationModel);
        LoadChatGptAccounts(System.Text.Json.Nodes.JsonNode.Parse("""
            [{"id":"example","connected":true,"models":[{"id":"first","name":"First"},{"id":"second","name":"Second"}]}]
            """)!.AsArray(), "example", "second");
        TranslationModel.SelectedValue = "chatgpt";
        TranslationPrompt.Text = "Keep this draft for the second model.";
        var settingsBefore = CollectSettings();
        var ruleName = FolderRuleName.Text;
        FolderRuleName.Text = "日本語 · café";
        for (int i = 0; i < InterfaceLocale.Languages.Length; i++)
        {
            var item = InterfaceLocale.Languages[i];
            InterfaceLanguage.SelectedValue = item.Locale;
            if (Selected(InterfaceLanguage) != item.Locale || InterfaceLocale.Culture.Name != item.Locale || !Equals(TranslationTab.Header, tabs[i])
                || !TranslationHint.Text.Contains("Second") || TranslationPrompt.Text != "Keep this draft for the second model."
                || !System.Text.Json.Nodes.JsonNode.DeepEquals(settingsBefore, CollectSettings())
                || FolderRuleName.Text != "日本語 · café" || Selected(FolderRuleTarget) != "zh")
                throw new InvalidOperationException("Language switch or draft preservation failed for " + item.Locale);
        }
        InterfaceLanguage.SelectedValue = InterfaceLocale.Automatic;
        if (Selected(InterfaceLanguage) != InterfaceLocale.Automatic || !initial.Equals(InterfaceLocale.Culture) || InterfaceLocale.Resolve("zh-HK").Name != "zh-TW"
            || InterfaceLocale.Resolve("zh_Hans_SG").Name != "zh-CN" || InterfaceLocale.Resolve("fr-CA").Name != "fr"
            || InterfaceLocale.Resolve("it-IT").Name != "en" || InterfaceLocale.Resolve("??").Name != "en")
            throw new InvalidOperationException("System language or English fallback failed.");
        FolderRuleName.Text = ruleName;
        TranslationModel.SelectedValue = initialTranslation;
        LoadChatGptAccounts([], "", "");
        enhancementDrafts.Remove("chatgpt:second");
    }
}
