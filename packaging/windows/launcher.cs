using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("AheadSubs")]
[assembly: AssemblyProduct("AheadSubs")]

internal static class Launcher
{
    [STAThread]
    private static void Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        if (args.Length == 5 && args[0] == "--finish-update")
        {
            FinishUpdate(root, args);
            return;
        }
        string desktop = Path.Combine(root, "UI", "AheadSubs.exe");
        string python = Path.Combine(root, "runtime", "pythonw.exe");
        string settings = Path.Combine(root, "AheadSubs.pyw");

        try
        {
            if (!File.Exists(Path.Combine(Environment.SystemDirectory, "msvcp140.dll")))
            {
                var answer = MessageBox.Show("Install the Microsoft Visual C++ Redistributable x64, then open the app again. Open the official download page?",
                    "AheadSubs", MessageBoxButtons.YesNo, MessageBoxIcon.Information);
                if (answer == DialogResult.Yes)
                    Process.Start("https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist");
                return;
            }
            var start = new ProcessStartInfo { WorkingDirectory = root, UseShellExecute = false };
            if (File.Exists(desktop))
            {
                start.FileName = desktop;
            }
            else
            {
                start.FileName = python;
                start.Arguments = "\"" + settings + "\"";
            }
            Process.Start(start);
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "AheadSubs", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private static void FinishUpdate(string root, string[] args)
    {
        string installer = Path.Combine(root, "setup.exe");
        try
        {
            // This copy of the launcher runs outside the installation being replaced.
            Process desktop = null;
            int pid = int.Parse(args[1], System.Globalization.CultureInfo.InvariantCulture);
            long started = long.Parse(args[2], System.Globalization.CultureInfo.InvariantCulture);
            try { desktop = Process.GetProcessById(pid); }
            catch (ArgumentException) { }
            using (desktop)
            {
                if (desktop != null && !desktop.HasExited && desktop.StartTime.ToFileTimeUtc() == started &&
                    !desktop.WaitForExit(30000))
                    throw new TimeoutException();
            }
            using (var setup = Process.Start(new ProcessStartInfo(installer)
            {
                WorkingDirectory = root,
                UseShellExecute = false
            }))
            {
                if (setup == null) throw new IOException();
                setup.WaitForExit();
                if (setup.ExitCode != 0 && setup.ExitCode != 2 && setup.ExitCode != 5)
                    throw new IOException();
            }
        }
        catch (Exception)
        {
            MessageBox.Show(args[4], args[3], MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally
        {
            try { File.Delete(installer); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }
}
