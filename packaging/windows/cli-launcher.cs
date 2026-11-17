using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;

internal static class CliLauncher
{
    private static string Quote(string argument)
    {
        // Double backslashes before a literal quote or the closing quote.
        string escaped = Regex.Replace(argument, "(\\\\*)(\"|\\z)", "$1$1$2");
        return "\"" + escaped.Replace("\"", "\\\"") + "\"";
    }

    private static int Main(string[] args)
    {
        string root = Directory.GetParent(AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar)).FullName;
        string python = Path.Combine(root, "runtime", "python.exe");
        try
        {
            var start = new ProcessStartInfo(python, "-I -X utf8 -m subtitle_relay.cli " + string.Join(" ", args.Select(Quote)))
            {
                UseShellExecute = false
            };
            // The child also receives Ctrl+C and can close its playback session before exiting.
            Console.CancelKeyPress += (sender, e) => e.Cancel = true;
            using (var process = Process.Start(start))
            {
                process.WaitForExit();
                return process.ExitCode;
            }
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("Could not launch AheadSubs: " + error.Message);
            return 1;
        }
    }
}
