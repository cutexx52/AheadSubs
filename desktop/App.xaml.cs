using System.Threading;

namespace LocalVideoSubtitleTranslator;

public partial class App : System.Windows.Application
{
    private Mutex? singleton;
    private EventWaitHandle? activate;
    private RegisteredWaitHandle? activationWait;

    protected override void OnStartup(System.Windows.StartupEventArgs e)
    {
        base.OnStartup(e);
        if (e.Args.Length == 2 && e.Args[0] == "--render-preview")
        {
            new MainWindow(preview: true).RenderPreviews(e.Args[1]);
            Shutdown(); return;
        }
        singleton = new Mutex(true, @"Local\LocalVideoSubtitleTranslator.Settings", out bool first);
        activate = new EventWaitHandle(false, EventResetMode.AutoReset,
            @"Local\LocalVideoSubtitleTranslator.Activate");
        if (!first) { activate.Set(); Shutdown(); return; }
        var window = new MainWindow();
        MainWindow = window;
        window.Show();
        activationWait = ThreadPool.RegisterWaitForSingleObject(activate,
            (_, _) => Dispatcher.BeginInvoke(new Action(window.ShowSettings)), null, Timeout.Infinite, false);
    }

    protected override void OnExit(System.Windows.ExitEventArgs e)
    {
        activationWait?.Unregister(null);
        activate?.Dispose();
        singleton?.Dispose();
        base.OnExit(e);
    }
}
