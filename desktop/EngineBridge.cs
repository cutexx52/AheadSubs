using System.Diagnostics;
using System.IO;
using System.Text.Json.Nodes;

namespace AheadSubs;

internal sealed class InspectionBridgeException(string message) : InvalidOperationException(message);

internal sealed class DesktopBridgeException(string key) : InvalidOperationException
{
    public override string Message => UiText.Get(key);
}

/// <summary>The desktop never imports engine code or reads secrets. Commands use one JSON response.</summary>
internal sealed class EngineBridge
{
    public string Root { get; } = FindRoot();

    private static string FindRoot()
    {
        foreach (var start in new[] { AppContext.BaseDirectory, Environment.CurrentDirectory })
            for (DirectoryInfo? dir = new(start); dir is not null; dir = dir.Parent)
                if (Directory.Exists(Path.Combine(dir.FullName, "aheadsubs"))) return dir.FullName;
        return AppContext.BaseDirectory;
    }

    public async Task<JsonObject> Run(string command, string? argument = null,
        JsonObject? input = null, CancellationToken cancellationToken = default, string? folder = null,
        Action<string>? progress = null)
    {
        string python = new[] { Path.Combine(Root, "runtime", "python.exe"),
            Path.Combine(Root, ".venv", "Scripts", "python.exe") }.FirstOrDefault(File.Exists)
            ?? throw new DesktopBridgeException("MissingRuntime");
        var info = new ProcessStartInfo(python)
        {
            WorkingDirectory = Root, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = System.Text.Encoding.UTF8,
            StandardErrorEncoding = System.Text.Encoding.UTF8
        };
        info.Environment["AHEADSUBS_UI_LOCALE"] = InterfaceLocale.Culture.Name;
        info.Environment["PYTHONUTF8"] = "1";
        info.ArgumentList.Add("-m");
        info.ArgumentList.Add("aheadsubs.desktop.bridge");
        info.ArgumentList.Add(command);
        if (argument is not null) info.ArgumentList.Add(argument);
        if (folder is not null)
        {
            info.ArgumentList.Add("--folder");
            info.ArgumentList.Add(folder);
        }
        using var process = Process.Start(info) ?? throw new DesktopBridgeException("LaunchFailed");
        using var registration = cancellationToken.Register(() =>
        {
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
            catch (InvalidOperationException) { }
        });
        var output = process.StandardOutput.ReadToEndAsync(cancellationToken);
        async Task ReadProgress()
        {
            while (await process.StandardError.ReadLineAsync(cancellationToken) is { } line)
                if (line is "apply:restart" or "apply:restart-models" or "apply:load-models" or "apply:start")
                    progress?.Invoke(line[6..]);
        }
        Task error = progress is null ? process.StandardError.ReadToEndAsync(cancellationToken) : ReadProgress();
        if (input is not null) await process.StandardInput.WriteAsync(input.ToJsonString());
        process.StandardInput.Close();
        await process.WaitForExitAsync(cancellationToken);
        string response = await output;
        await error; // Never display raw subprocess stderr: it may contain private configuration.
        JsonObject? data;
        try { data = JsonNode.Parse(response) as JsonObject; }
        catch (System.Text.Json.JsonException)
        { throw new DesktopBridgeException("InvalidResponse"); }
        if (data is null || data["ok"]?.GetValue<bool>() != true)
        {
            string? code = data?["error_code"]?.ToString();
            if (command.StartsWith("inspect-", StringComparison.Ordinal) && InspectionText.Error(code) is { } message)
                throw new InspectionBridgeException(message);
            throw new InvalidOperationException(LocalizedError(code, data?["error_args"] as JsonArray)
                ?? data?["error"]?.ToString() ?? UiText.Get("BackendFailed"));
        }
        return data;
    }

    internal static string? LocalizedError(string? code, JsonArray? arguments = null)
    {
        if (code is null) return null;
        if (code == "backend-failed") return UiText.Get("BackendFailed");
        var format = UiText.Resources.GetString("Error_" + code, InterfaceLocale.Culture);
        if (format is null)
            return InspectionText.Error(code) ?? SetupText.Error(code);
        var values = (arguments ?? []).Select(value => (object)(value?.ToString() ?? "")).ToArray();
        try { return string.Format(InterfaceLocale.Culture, format, values); }
        catch (FormatException) { return null; }
    }
}
