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
        InterfaceLanguage.ItemsSource = new Choice[] { new(UiText.Get("FollowSystem"), InterfaceLocale.Automatic) }
            .Concat(InterfaceLocale.Languages.Select(item => new Choice(item.NativeName, item.Locale))).ToArray();
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
            LanguageChoice("en"), LanguageChoice("zh"), LanguageChoice("ko") };
        TargetLanguage.ItemsSource = InterfaceLocale.Languages.Select(item => LanguageChoice(item.Target)).ToArray();
        Vad.ItemsSource = new Choice[] { new(UiText.Get("Silero"), "silero"), new(UiText.Get("Fsmn"), "fsmn") };
        CloudProvider.ItemsSource = new Choice[] { new(UiText.Get("BailianProvider"), "dashscope"),
            new("OpenAI · API Key", "openai"), new(UiText.Get("ChatGptProvider"), "chatgpt"),
            new("MiniMax · API Key", "minimax"), new(UiText.Get("CompatibleProvider"), "compatible") };
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
            PopulateLanguagePicker();
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
            ShowFolderQueue();
            LocalizeInspection();
            SetInspectionFiles(subtitleFiles, (MediaList.SelectedItem as SubtitleFile)?.Id);
            if (SubtitleRows.Items.Count > 0) InspectPreviewNote.Text = InspectionText.Get("PreviewRows");
            LoadChatGptAccounts(chatGptAccounts, Selected(ChatGptAccount), Selected(ChatGptModel));
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
}
