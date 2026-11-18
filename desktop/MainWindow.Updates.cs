using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Net.Http;
using System.Resources;
using System.Security;
using System.Text.Json;
using System.Windows;
using System.Windows.Threading;
using Microsoft.Win32;
using Forms = System.Windows.Forms;

namespace AheadSubs;

public partial class MainWindow
{
    private const string UpdatePreferences = @"Software\AheadSubs\Updates";
    private const string UninstallRegistration =
        @"Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalVideoSubtitleTranslator_is1";
    private static readonly ResourceManager UpdateResources = new(
        "AheadSubs.UpdateStrings", typeof(MainWindow).Assembly);
    private static readonly HttpClient UpdateHttp = new()
    {
        Timeout = Timeout.InfiniteTimeSpan,
        MaxResponseContentBufferSize = 2 * 1024 * 1024
    };
    private readonly ReleaseUpdates updateClient = new(UpdateHttp);
    private readonly CancellationTokenSource updateLifetime = new();
    private ReleasePackage? updatePackage;
    private ReleaseAsset? availableUpdate;
    private string? installedUpdateRoot;
    private DispatcherTimer? updateTimer;
    private DateTime lastUpdateCheck;
    private bool checkingForUpdate;
    private CancellationTokenSource? updateDownload;
    private Version? announcedUpdate;

    private static string UpdateText(string key, params object[] args)
    {
        string text = UpdateResources.GetString(key, AutomationText.Culture)!;
        return args.Length == 0 ? text : string.Format(AutomationText.Culture, text, args);
    }

    private void InitializeUpdates()
    {
        try
        {
            string metadata = File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "aheadsubs-release.json"));
            updatePackage = JsonSerializer.Deserialize<ReleasePackage>(metadata);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException) { return; }
        if (updatePackage?.IsSupported != true) return;

        installedUpdateRoot = FindInstalledUpdateRoot();
        UpdateCard.Language = System.Windows.Markup.XmlLanguage.GetLanguage(AutomationText.Culture.Name);
        UpdateTitle.Text = UpdateText("Title");
        InstalledVersion.Text = UpdateText("CurrentVersion", updatePackage.Version);
        AutomaticUpdates.Content = UpdateText("Automatic");
        CheckUpdateButton.Content = UpdateText("Check");
        ReleaseNotesButton.Content = UpdateText("Notes");
        GetUpdateButton.Content = UpdateText(installedUpdateRoot is null ? "Portable" : "Install");
        CancelUpdateButton.Content = UpdateText("Cancel");
        AutomaticUpdates.IsChecked = true;
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(UpdatePreferences);
            AutomaticUpdates.IsChecked = key?.GetValue("Automatic") is not 0;
            if (key?.GetValue("LastCheck") is long ticks && ticks >= 0 && ticks <= DateTime.MaxValue.Ticks)
                lastUpdateCheck = new DateTime(ticks, DateTimeKind.Utc);
        }
        catch (Exception error) when (error is IOException or SecurityException or UnauthorizedAccessException)
        {
            AutomaticUpdates.IsChecked = false;
        }
        UpdateCard.Visibility = Visibility.Visible;
        updateTimer = new DispatcherTimer { Interval = TimeSpan.FromHours(1) };
        updateTimer.Tick += async (_, _) => await CheckForReleaseAsync(manual: false);
        Loaded += async (_, _) =>
        {
            updateTimer.Start();
            await CheckForReleaseAsync(manual: false);
        };
    }

    private static string? FindInstalledUpdateRoot()
    {
        try
        {
            using var user = RegistryKey.OpenBaseKey(RegistryHive.CurrentUser, RegistryView.Registry64);
            using var key = user.OpenSubKey(UninstallRegistration);
            var root = Directory.GetParent(Path.TrimEndingDirectorySeparator(AppContext.BaseDirectory));
            if (root is not null && key?.GetValue("InstallLocation") is string location &&
                Path.IsPathFullyQualified(location) &&
                string.Equals(root.FullName, Path.TrimEndingDirectorySeparator(Path.GetFullPath(location)),
                    StringComparison.OrdinalIgnoreCase) &&
                File.Exists(Path.Combine(root.FullName, "AheadSubs.exe")))
                return root.FullName;
        }
        catch (Exception error) when (error is IOException or SecurityException or UnauthorizedAccessException or ArgumentException) { }
        return null;
    }

    private void SetAutomaticUpdates(object sender, RoutedEventArgs e)
    {
        bool enabled = AutomaticUpdates.IsChecked == true;
        try
        {
            using var key = Registry.CurrentUser.CreateSubKey(UpdatePreferences);
            key.SetValue("Automatic", enabled ? 1 : 0, RegistryValueKind.DWord);
        }
        catch (Exception error) when (error is IOException or SecurityException or UnauthorizedAccessException)
        {
            AutomaticUpdates.IsChecked = !enabled;
            UpdateStatus.Text = UpdateText("PreferenceFailed");
            return;
        }
        if (enabled) _ = CheckForReleaseAsync(manual: false);
    }

    private async void CheckForUpdate(object sender, RoutedEventArgs e) => await CheckForReleaseAsync(manual: true);

    private async Task CheckForReleaseAsync(bool manual)
    {
        if (updatePackage is null || checkingForUpdate || updateDownload is not null || exiting) return;
        DateTime now = DateTime.UtcNow;
        if (!manual && (AutomaticUpdates.IsChecked != true ||
            (now >= lastUpdateCheck && now - lastUpdateCheck < TimeSpan.FromDays(1)))) return;

        checkingForUpdate = true;
        lastUpdateCheck = now;
        CheckUpdateButton.IsEnabled = GetUpdateButton.IsEnabled = false;
        if (manual) UpdateStatus.Text = UpdateText("Checking");
        try
        {
            using (var key = Registry.CurrentUser.CreateSubKey(UpdatePreferences))
                key.SetValue("LastCheck", now.Ticks, RegistryValueKind.QWord);
        }
        catch (Exception error) when (error is IOException or SecurityException or UnauthorizedAccessException) { }

        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(updateLifetime.Token);
        timeout.CancelAfter(TimeSpan.FromSeconds(15));
        try
        {
            availableUpdate = await updateClient.CheckAsync(updatePackage, installedUpdateRoot is not null, timeout.Token);
            GetUpdateButton.Visibility = ReleaseNotesButton.Visibility =
                availableUpdate is null ? Visibility.Collapsed : Visibility.Visible;
            if (availableUpdate is { } release)
            {
                UpdateStatus.Text = UpdateText("Available", release.Version);
                if (!manual && AutomaticUpdates.IsChecked == true && announcedUpdate != release.Version)
                {
                    announcedUpdate = release.Version;
                    tray.ShowBalloonTip(4000, UpdateStatus.Text, UpdateText("Notification"), Forms.ToolTipIcon.Info);
                }
            }
            else if (manual || !string.IsNullOrEmpty(UpdateStatus.Text))
                UpdateStatus.Text = UpdateText("UpToDate");
        }
        catch (Exception)
        {
            if (updateLifetime.IsCancellationRequested) return;
            // Abandon a previous offer if it could no longer be confirmed.
            availableUpdate = null;
            GetUpdateButton.Visibility = ReleaseNotesButton.Visibility = Visibility.Collapsed;
            if (manual || !string.IsNullOrEmpty(UpdateStatus.Text))
                UpdateStatus.Text = UpdateText("CheckFailed");
        }
        finally
        {
            checkingForUpdate = false;
            CheckUpdateButton.IsEnabled = GetUpdateButton.IsEnabled = true;
        }
    }

    private void OpenUpdateNotes(object sender, RoutedEventArgs e)
    {
        if (availableUpdate is { } release) OpenUpdateLink(release.Notes);
    }

    private void OpenUpdateLink(Uri uri)
    {
        try { using var browser = Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true }); }
        catch (Exception error) when (error is Win32Exception or InvalidOperationException)
        {
            UpdateStatus.Text = UpdateText("BrowserFailed");
        }
    }

    private async void GetUpdate(object sender, RoutedEventArgs e)
    {
        if (availableUpdate is not { } release || updateDownload is not null || busy || checkingForUpdate) return;
        if (installedUpdateRoot is null)
        {
            OpenUpdateLink(release.Download);
            return;
        }
        string confirm = UpdateText("Confirm", release.Version, release.Size / 1048576.0);
        if (System.Windows.MessageBox.Show(this, confirm, UpdateText("Title"), MessageBoxButton.YesNo,
            MessageBoxImage.Question, MessageBoxResult.No) != MessageBoxResult.Yes) return;

        using var download = CancellationTokenSource.CreateLinkedTokenSource(updateLifetime.Token);
        updateDownload = download;
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(download.Token);
        timeout.CancelAfter(TimeSpan.FromMinutes(30));
        GetUpdateButton.IsEnabled = CheckUpdateButton.IsEnabled = false;
        CancelUpdateButton.Visibility = Visibility.Visible;
        UpdateStatus.Text = UpdateText("Downloading");
        DirectoryInfo? stage = null;
        bool handoff = false;
        bool applying = false;
        try
        {
            RemoveOldUpdateStages();
            stage = Directory.CreateTempSubdirectory("AheadSubs-update-");
            await updateClient.DownloadAsync(release, Path.Combine(stage.FullName, "setup.exe"), timeout.Token);
            download.Token.ThrowIfCancellationRequested();
            if (busy)
            {
                UpdateStatus.Text = UpdateText("Busy");
                return;
            }
            if (FindInstalledUpdateRoot() != installedUpdateRoot)
                throw new IOException();

            applying = busy = true;
            SetBusy(true);
            CancelUpdateButton.Visibility = Visibility.Collapsed;
            UpdateStatus.Text = UpdateText("Stopping");
            using var stopTimeout = new CancellationTokenSource(TimeSpan.FromSeconds(45));
            await bridge.Run("stop", cancellationToken: stopTimeout.Token);
            StartUpdateLauncher(stage.FullName, installedUpdateRoot);
            handoff = true;
            ExitDesktop();
        }
        catch (OperationCanceledException) when (download.IsCancellationRequested)
        {
            if (!exiting) UpdateStatus.Text = UpdateText("Canceled");
        }
        catch (Exception)
        {
            UpdateStatus.Text = UpdateText(applying ? "InstallFailed" : "DownloadFailed");
        }
        finally
        {
            if (!handoff && stage is not null) RemoveUpdateStage(stage);
            if (!exiting)
            {
                if (applying)
                {
                    busy = false;
                    SetBusy(false);
                    _ = Refresh();
                }
                CancelUpdateButton.Visibility = Visibility.Collapsed;
                CheckUpdateButton.IsEnabled = GetUpdateButton.IsEnabled = true;
            }
            updateDownload = null;
        }
    }

    private static void StartUpdateLauncher(string stage, string root)
    {
        string helper = Path.Combine(stage, "AheadSubs.exe");
        File.Copy(Path.Combine(root, "AheadSubs.exe"), helper);
        using var current = Process.GetCurrentProcess();
        var start = new ProcessStartInfo(helper) { UseShellExecute = false, WorkingDirectory = stage };
        start.ArgumentList.Add("--finish-update");
        start.ArgumentList.Add(current.Id.ToString(CultureInfo.InvariantCulture));
        start.ArgumentList.Add(current.StartTime.ToFileTimeUtc().ToString(CultureInfo.InvariantCulture));
        start.ArgumentList.Add(UpdateText("Title"));
        start.ArgumentList.Add(UpdateText("SetupFailed"));
        using var launcher = Process.Start(start) ?? throw new IOException();
    }

    private static void RemoveUpdateStage(DirectoryInfo stage)
    {
        try
        {
            File.Delete(Path.Combine(stage.FullName, "setup.exe"));
            File.Delete(Path.Combine(stage.FullName, "AheadSubs.exe"));
            stage.Delete();
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
    }

    private static void RemoveOldUpdateStages()
    {
        try
        {
            var temp = new DirectoryInfo(Path.GetTempPath());
            var cutoff = DateTime.UtcNow.AddDays(-2);
            foreach (var stage in temp.EnumerateDirectories("AheadSubs-update-*"))
                if ((stage.Attributes & FileAttributes.ReparsePoint) == 0 && stage.CreationTimeUtc < cutoff)
                    RemoveUpdateStage(stage);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
    }

    private void CancelUpdate(object sender, RoutedEventArgs e) => updateDownload?.Cancel();

    private void StopUpdateChecks()
    {
        updateTimer?.Stop();
        updateLifetime.Cancel();
    }
}
