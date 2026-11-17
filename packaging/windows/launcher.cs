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
    private static void Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string desktop = Path.Combine(root, "UI", "AheadSubs.exe");
        string python = Path.Combine(root, "runtime", "pythonw.exe");
        string settings = Path.Combine(root, "Subtitle Relay.pyw");

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
}
