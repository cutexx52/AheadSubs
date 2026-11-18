using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;

namespace AheadSubs;

public partial class ApiKeyEditor : System.Windows.Controls.UserControl
{
    private string savedMode = "default", savedPath = "";
    private bool hasSavedKey;
    private string SelectedMode => Mode.SelectedValue as string ?? "default";

    public ApiKeyEditor() => InitializeComponent();

    internal void Load(JsonNode? state)
    {
        savedMode = state?["mode"]?.ToString() ?? "default";
        savedPath = state?["file"]?.ToString() ?? "";
        hasSavedKey = state?["saved"]?.GetValue<bool>() == true;
        KeyPath.Text = savedPath;
        KeyInput.Clear();
        Mode.SelectedValue = savedMode;
        UpdateMode();
    }

    internal JsonObject? Edit()
    {
        string mode = SelectedMode;
        string value = mode switch { "direct" => KeyInput.Password.Trim(), "file" => KeyPath.Text.Trim(), _ => "" };
        if (mode == savedMode && (mode == "file" ? value == savedPath : value.Length == 0)) return null;
        return new JsonObject { ["mode"] = mode, ["value"] = value };
    }

    private void ChangeMode(object sender, SelectionChangedEventArgs e)
    {
        if (DirectRow is null) return;
        if (SelectedMode != "direct") KeyInput.Clear();
        UpdateMode();
    }

    internal void UpdateMode()
    {
        FileRow.Visibility = SelectedMode == "file" ? Visibility.Visible : Visibility.Collapsed;
        DirectRow.Visibility = SelectedMode == "direct" ? Visibility.Visible : Visibility.Collapsed;
        DirectHint.Text = hasSavedKey ? UiText.Get("ReplaceKey") : UiText.Get("EncryptedKey");
    }

    private void Browse(object sender, RoutedEventArgs e)
    {
        var dialog = new Microsoft.Win32.OpenFileDialog { Title = UiText.Get("ChooseKey"), CheckFileExists = true };
        if (dialog.ShowDialog(Window.GetWindow(this)) == true) KeyPath.Text = dialog.FileName;
    }
}
