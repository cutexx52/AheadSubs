using System.Diagnostics;
using System.IO;
using System.Text.Json.Nodes;

namespace LocalVideoSubtitleTranslator;

/// <summary>The desktop never imports engine code or reads secrets. Commands use one JSON response.</summary>
internal sealed class EngineBridge
{
    public string Root { get; } = FindRoot();

    private static string FindRoot()
    {
        foreach (var start in new[] { AppContext.BaseDirectory, Environment.CurrentDirectory })
            for (DirectoryInfo? dir = new(start); dir is not null; dir = dir.Parent)
                if (Directory.Exists(Path.Combine(dir.FullName, "subtitle_relay"))) return dir.FullName;
        return AppContext.BaseDirectory;
    }

    public async Task<JsonObject> Run(string command, string? argument = null,
        JsonObject? input = null, CancellationToken cancellationToken = default, string? folder = null)
    {
        string python = new[] { Path.Combine(Root, "runtime", "python.exe"),
            Path.Combine(Root, ".venv", "Scripts", "python.exe") }.FirstOrDefault(File.Exists)
            ?? throw new InvalidOperationException("找不到随软件提供的运行环境。请重新解压完整安装包，不要单独移动 UI 文件夹。");
        var info = new ProcessStartInfo(python)
        {
            WorkingDirectory = Root, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = System.Text.Encoding.UTF8,
            StandardErrorEncoding = System.Text.Encoding.UTF8
        };
        info.Environment["PYTHONUTF8"] = "1";
        info.ArgumentList.Add("-m");
        info.ArgumentList.Add("subtitle_relay.desktop.bridge");
        info.ArgumentList.Add(command);
        if (argument is not null) info.ArgumentList.Add(argument);
        if (folder is not null)
        {
            info.ArgumentList.Add("--folder");
            info.ArgumentList.Add(folder);
        }
        using var process = Process.Start(info) ?? throw new IOException("无法启动字幕服务。");
        using var registration = cancellationToken.Register(() =>
        {
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
            catch (InvalidOperationException) { }
        });
        var output = process.StandardOutput.ReadToEndAsync(cancellationToken);
        var error = process.StandardError.ReadToEndAsync(cancellationToken);
        if (input is not null) await process.StandardInput.WriteAsync(input.ToJsonString());
        process.StandardInput.Close();
        await process.WaitForExitAsync(cancellationToken);
        string response = await output;
        _ = await error; // Never display raw subprocess stderr: it may contain private configuration.
        JsonObject? data;
        try { data = JsonNode.Parse(response) as JsonObject; }
        catch (System.Text.Json.JsonException)
        { throw new InvalidOperationException("后台没有返回有效结果。请在高级设置中打开诊断日志后重试。"); }
        if (data is null || data["ok"]?.GetValue<bool>() != true)
            throw new InvalidOperationException(SetupText.Error(data?["error_code"]?.ToString())
                ?? data?["error"]?.ToString() ?? "后台操作失败，请查看诊断日志。");
        return data;
    }
}
