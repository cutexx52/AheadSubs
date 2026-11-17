using System.Globalization;
using System.Net;
using System.Net.Http;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using Color = System.Windows.Media.Color;

namespace LocalVideoSubtitleTranslator;

public partial class StatusPage : System.Windows.Controls.UserControl
{
    private sealed record DetailRow(string Title, string Detail);
    private sealed record Week(string Date, string Label);
    private sealed record UsageRow(string Model, string Provider, string Calls, string Failures, string Usage, string Cost);

    private static readonly HttpClient Http = new(new HttpClientHandler { UseProxy = false, AllowAutoRedirect = false });
    private static readonly SolidColorBrush ReadyBrush = new(Color.FromRgb(50, 107, 79));
    private static readonly SolidColorBrush WarningBrush = new(Color.FromRgb(138, 79, 14));
    private static CultureInfo Culture => AutomationText.Culture;
    private readonly DispatcherTimer polling = new() { Interval = TimeSpan.FromSeconds(3) };
    private EngineBridge? bridge;
    private CancellationTokenSource? visibility;
    private bool windowActive = true, loading, live;
    private DateTimeOffset offlineReadAt;
    private JsonObject? cloud;
    private string? cloudSignature;

    public StatusPage()
    {
        InitializeComponent();
        Language = System.Windows.Markup.XmlLanguage.GetLanguage(Culture.Name);
        RenderLive(null, StatusText.Get("Checking"));
        RenderCloud(null, "Checking");
        polling.Tick += async (_, _) => await Refresh();
        IsVisibleChanged += (_, _) => UpdatePolling();
    }

    internal void Enable(EngineBridge engine)
    {
        bridge = engine;
        UpdatePolling();
    }

    internal void SetWindowActive(bool active)
    {
        windowActive = active;
        UpdatePolling();
    }

    private void UpdatePolling()
    {
        if (bridge is null || !IsVisible || !windowActive)
        {
            polling.Stop();
            visibility?.Cancel();
            visibility?.Dispose();
            visibility = null;
            return;
        }
        if (visibility is not null) return;
        visibility = new CancellationTokenSource();
        polling.Start();
        _ = Refresh(manual: true);
    }

    private async void RefreshClicked(object sender, RoutedEventArgs e) => await Refresh(manual: true);

    private async Task Refresh(bool manual = false)
    {
        if (bridge is not { } engine || visibility is not { } lifetime || loading) return;
        loading = true;
        var token = lifetime.Token;
        try
        {
            JsonObject? snapshot = null;
            string offline = "Offline";
            try
            {
                using var timeout = CancellationTokenSource.CreateLinkedTokenSource(token);
                timeout.CancelAfter(TimeSpan.FromSeconds(2));
                using var request = new HttpRequestMessage(HttpMethod.Get, "http://127.0.0.1:8769/v1/status");
                request.Headers.Add("X-AheadSubs-Status", "1");
                using var response = await Http.SendAsync(request, timeout.Token);
                if (response.StatusCode == HttpStatusCode.NotFound) offline = "Unsupported";
                response.EnsureSuccessStatusCode();
                snapshot = JsonNode.Parse(await response.Content.ReadAsStringAsync(timeout.Token)) as JsonObject;
                if (Value(snapshot, "service") != "subtitle-relay") snapshot = null;
            }
            catch (Exception ex) when (ex is HttpRequestException or JsonException or OperationCanceledException)
            {
                if (token.IsCancellationRequested) return;
            }
            if (token.IsCancellationRequested) return;

            RenderLive(snapshot, StatusText.Get(offline));
            Updated.Text = StatusText.Format("Checked", DateTime.Now.ToString("T", Culture));
            if (snapshot is not null)
            {
                live = true;
                RenderCloud(snapshot["cloud"] as JsonObject);
            }
            else if (live || manual || DateTimeOffset.UtcNow - offlineReadAt >= TimeSpan.FromMinutes(1))
            {
                live = false;
                using var timeout = CancellationTokenSource.CreateLinkedTokenSource(token);
                timeout.CancelAfter(TimeSpan.FromSeconds(3));
                JsonObject? history = null;
                try { history = await engine.Run("cloud-usage", cancellationToken: timeout.Token); }
                catch (Exception ex) when (ex is InvalidOperationException or System.IO.IOException
                    or OperationCanceledException or System.ComponentModel.Win32Exception) { }
                if (token.IsCancellationRequested) return;
                offlineReadAt = DateTimeOffset.UtcNow;
                RenderCloud(history);
            }
        }
        finally
        {
            loading = false;
            if (visibility is not null && visibility != lifetime) _ = Refresh(manual: true);
        }
    }

    internal void Preview(JsonObject snapshot)
    {
        RenderLive(snapshot, "");
        Updated.Text = StatusText.Get("Preview");
        RenderCloud(snapshot["cloud"] as JsonObject);
    }

    internal void ScrollToCloud() => Scroll.ScrollToEnd();

    private void RenderLive(JsonObject? snapshot, string offline)
    {
        bool ready = Flag(snapshot, "ready");
        var sourceRows = Rows(snapshot, "sources");
        var modelRows = Rows(snapshot, "models");
        var metrics = snapshot?["performance"] as JsonObject;
        var rtf = metrics?["rtf"] as JsonObject;
        var latency = metrics?["latency"] as JsonObject;
        var workers = snapshot?["workers"] as JsonObject;
        var resources = snapshot?["resources"] as JsonObject;

        ServiceValue.Text = snapshot is null ? offline : StatusText.Get(ready ? "Ready" : "Degraded");
        ServiceValue.Foreground = ready ? ReadyBrush : WarningBrush;
        ServiceHint.Text = workers is null ? StatusText.Get("ServiceHint") :
            StatusText.Format("Workers", Integer(workers, "busy"), Integer(workers, "limit"));
        Connections.Text = snapshot is null ? StatusText.Get("Sources") :
            StatusText.Format("Connections", Integer(snapshot, "active_sessions"));
        SourceHint.Text = snapshot is null ? StatusText.Get("Unavailable") :
            sourceRows.Length == 0 ? StatusText.Get("NoConnections") : "";
        SourceHint.Visibility = sourceRows.Length == 0 ? Visibility.Visible : Visibility.Collapsed;
        Sources.ItemsSource = sourceRows.Select(row => StatusText.Format(
            Integer(row, "text") == 0 ? "SourcePlayback" : Integer(row, "playback") == 0 ? "SourceText" : "SourceBoth",
            StatusText.Get("Source_" + Value(row, "source")), Integer(row, "playback"), Integer(row, "text"))).ToArray();

        ModelHint.Text = snapshot is null ? StatusText.Get("Unavailable") :
            modelRows.Length == 0 ? StatusText.Get("NoModels") : "";
        ModelHint.Visibility = modelRows.Length == 0 ? Visibility.Visible : Visibility.Collapsed;
        Models.ItemsSource = modelRows.Select(row => new DetailRow(
            StatusText.Format("ModelTitle", StatusText.Get("Role_" + Value(row, "operation")), Model(row)),
            StatusText.Format("ModelState", StatusText.Get("Device_" + Value(row, "device")),
                StatusText.Get("State_" + Value(row, "state"))))).ToArray();
        ResourceRows.ItemsSource = new DetailRow[]
        {
            new("CPU", Measure(resources, "cpu_percent", "Percent")),
            new("RAM", Bytes(resources, "rss_bytes")),
            new("GPU", Measure(resources, "gpu_percent", "Percent")),
            new(StatusText.Get("Vram"), Bytes(resources, "vram_bytes")),
        };
        Rtf.Text = Measure(rtf, "p50", "Ratio");
        P50.Text = Measure(latency, "p50", "Seconds");
        P95.Text = Measure(latency, "p95", "Seconds");
        P99.Text = Measure(latency, "p99", "Seconds");
        PerformanceSamples.Text = snapshot is null ? StatusText.Get("Unavailable") :
            Integer(rtf, "count") + Integer(latency, "count") == 0 ? StatusText.Get("NoSamples") :
            StatusText.Format("Samples", Integer(rtf, "count"), Integer(latency, "count"));
    }

    private void RenderCloud(JsonObject? usage, string empty = "HistoryUnavailable")
    {
        string signature = usage?.ToJsonString() ?? empty;
        if (cloudSignature == signature) return;
        cloudSignature = signature;
        cloud = usage;
        var dates = (usage?["weeks"] as JsonArray)?.Select(node => node?.ToString()).OfType<string>()
            .Where(date => DateOnly.TryParseExact(date, "yyyy-MM-dd", CultureInfo.InvariantCulture,
                DateTimeStyles.None, out _)).ToArray() ?? [];
        if (!dates.SequenceEqual((Weeks.ItemsSource as Week[] ?? []).Select(week => week.Date)))
        {
            string? previous = Weeks.SelectedIndex > 0 ? Weeks.SelectedValue as string : null;
            Weeks.ItemsSource = dates.Select((date, index) =>
            {
                var monday = DateOnly.ParseExact(date, "yyyy-MM-dd", CultureInfo.InvariantCulture);
                return new Week(date, StatusText.Format(index == 0 ? "ThisWeek" : "WeekRange",
                    monday.ToString("M", Culture), monday.AddDays(6).ToString("M", Culture)));
            }).ToArray();
            Weeks.SelectedValue = previous is not null && dates.Contains(previous) ? previous : dates.FirstOrDefault();
        }
        Weeks.IsEnabled = dates.Length > 0;
        RenderWeek(empty);
    }

    private void WeekChanged(object sender, SelectionChangedEventArgs e)
    {
        if (CloudRows is not null) RenderWeek();
    }

    private void RenderWeek(string empty = "HistoryUnavailable")
    {
        bool incomplete = Flag(cloud, "incomplete");
        var rows = Rows(cloud, "rows").Where(row => Value(row, "week") == Weeks.SelectedValue as string).ToArray();
        long calls = rows.Sum(row => Integer(row, "calls"));
        long priced = rows.Sum(row => Integer(row, "priced_calls"));
        double usd = rows.Sum(row => Number(row, "estimated_usd") ?? 0);
        CloudHeader.Visibility = rows.Length > 0 ? Visibility.Visible : Visibility.Collapsed;
        CloudEmpty.Text = incomplete ? StatusText.Get("HistoryIncomplete") :
            cloud is null ? StatusText.Get(empty) :
            rows.Length == 0 ? StatusText.Get("NoUsage") : "";
        CloudEmpty.Visibility = CloudEmpty.Text.Length > 0 ? Visibility.Visible : Visibility.Collapsed;
        CloudSummary.Text = calls == 0 ? "" : priced == 0 ? StatusText.Format("CallTotal", calls) :
            StatusText.Format(priced == calls && !incomplete ? "CostTotal" : "PartialTotal", calls, Money(usd));
        CloudRows.ItemsSource = rows.Select(row =>
        {
            long count = Integer(row, "calls");
            long failures = Integer(row, "failed");
            long estimates = Integer(row, "priced_calls");
            long input = Integer(row, "input_tokens"), output = Integer(row, "output_tokens");
            double audio = Number(row, "audio_seconds") ?? 0;
            var quantities = new List<string>();
            if (input > 0 || output > 0) quantities.Add(StatusText.Format("Tokens", input, output));
            if (audio > 0) quantities.Add(StatusText.Format("Minutes", audio / 60));
            string provider = Value(row, "provider");
            double cost = Number(row, "estimated_usd") ?? 0;
            return new UsageRow(Model(row),
                StatusText.Format("ProviderRole", StatusText.Get("Provider_" + provider),
                    StatusText.Get("Role_" + Value(row, "operation"))),
                count.ToString("N0", Culture), failures > 0 ? StatusText.Format("Failures", failures) : "",
                quantities.Count > 0 ? string.Join(Environment.NewLine, quantities) : StatusText.Get("Missing"),
                provider is "chatgpt" or "minimax_plan" ? StatusText.Get("Subscription") :
                estimates == 0 ? StatusText.Get("NoEstimate") :
                estimates == count ? Money(cost) : StatusText.Format("PartialCost", Money(cost), estimates, count));
        }).ToArray();
    }

    private static JsonObject[] Rows(JsonObject? parent, string key) =>
        (parent?[key] as JsonArray)?.OfType<JsonObject>().ToArray() ?? [];
    private static string Value(JsonObject? parent, string key) => parent?[key]?.ToString() ?? "";
    private static bool Flag(JsonObject? parent, string key) =>
        parent?[key] is JsonValue json && json.TryGetValue<bool>(out bool value) && value;
    private static long Integer(JsonObject? parent, string key) =>
        parent?[key] is JsonValue json && json.TryGetValue<long>(out long value) && value >= 0 ? value : 0;
    private static double? Number(JsonObject? parent, string key) =>
        parent?[key] is JsonValue json && json.TryGetValue<double>(out double value) && double.IsFinite(value) ? value : null;
    private static string Measure(JsonObject? parent, string key, string format) =>
        Number(parent, key) is double number ? StatusText.Format(format, number) : StatusText.Get("Missing");
    private static string Bytes(JsonObject? parent, string key) => Number(parent, key) is double number ?
        StatusText.Format(number >= 1024 * 1024 * 1024 ? "GiB" : "MiB",
            number / (number >= 1024 * 1024 * 1024 ? 1024 * 1024 * 1024 : 1024 * 1024)) : StatusText.Get("Missing");
    private static string Money(double amount) => amount is > 0 and < 0.0001 ?
        StatusText.Get("SmallCost") : StatusText.Format("USD", amount);
    private static string Model(JsonObject row) =>
        Value(row, "model") is "custom" or "" ? StatusText.Get("CustomModel") : Value(row, "model");
}
