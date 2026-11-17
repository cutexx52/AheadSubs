"""Windows setup and playback controls. Run by double-clicking this file."""
import base64
import ctypes
import json
import msvcrt
import os
import shutil
import secrets
import subprocess
import sys
import time
import tkinter as tk
import winreg
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ["LOCALAPPDATA"]) / "Subtitle Relay"
QWEN = DATA / "qwen"
CONFIG = DATA / "settings.json"
PYTHON = ROOT / ".venv" / "Scripts" / "pythonw.exe"
LOG = DATA / "service.log"
PORT = 8769
CONTROL = DATA / "control-token"
DEFAULTS = {
    "route": "asr+mt",
    "pot_hotkey": "1",
    "qwen_size": "1.7b", "source": "",
    "asr_url": "http://127.0.0.1:8000/v1", "asr_model": "qwen3-asr",
    "asr": "local", "mt": "local", "device": "cuda", "whisper_model": "small",
    "llm_model": "gpt-4.1-mini", "llm_url": "http://127.0.0.1:11434/v1", "key_file": "",
    "chunk": "8", "before": "2", "after": "2", "max_speech": "12",
    "min_silence_ms": "450", "pad_ms": "160", "vad_threshold": "0.5", "backfill": "4",
}


def config():
    if not CONFIG.is_file():
        return DEFAULTS.copy()
    return {**DEFAULTS, **json.loads(CONFIG.read_text(encoding="utf-8"))}


def healthy():
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{PORT}/v1/health", timeout=0.3) as response:
            return json.load(response).get("service") == "subtitle-relay"
    except (OSError, URLError, ValueError):
        return False


def spawn(arguments, log=LOG):
    if not PYTHON.is_file():
        raise RuntimeError("Install Python dependencies in the project .venv first.")
    DATA.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as output:
        return subprocess.Popen([str(PYTHON), "-m", "subtitle_relay", *arguments],
                                cwd=ROOT, stdout=output, stderr=output,
                                stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)


def background_start(on_wait=None):
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / "starting.lock").open("a+b") as startup:
        try:
            msvcrt.locking(startup.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return
        if healthy():
            return
        settings = config()
        CONTROL.write_text(secrets.token_urlsafe(32), encoding="ascii")
        args = ["serve", "--cache", str(DATA / "cache"), "--control-token-file", str(CONTROL)]
        for name in DEFAULTS:
            if name == "source":
                continue
            if name == "pot_hotkey":
                if settings[name] == "1":
                    args.extend(["--pot-hotkey-launcher", str(Path(__file__).resolve())])
                continue
            if name == "route":
                if settings[name] == "OpenAI AST (English)":
                    args.append("--ast")
                continue
            value = settings[name]
            if value:
                args.extend(["--" + name.replace("_", "-"), value])
        if settings["asr"] == "qwen":
            args.extend(["--qwen-root", str(QWEN)])
        process = spawn(args)
        while process.poll() is None and not healthy():
            if on_wait:
                on_wait()
            time.sleep(0.4)
        if not healthy():
            raise RuntimeError(f"字幕服务启动失败，请查看 {LOG}。")


def prepare():
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / "setup.log").open("wb") as log:
        options = {"cwd": ROOT, "stdout": log, "stderr": subprocess.STDOUT,
                   "creationflags": subprocess.CREATE_NO_WINDOW, "check": True}
        if not PYTHON.is_file():
            subprocess.run([sys._base_executable, "-m", "venv", ".venv"], **options)
        subprocess.run([str(PYTHON.with_name("python.exe")), "-m", "pip", "install", "-e",
                        ".[local,cloud]", "nvidia-cublas-cu12==12.8.4.1",
                        "nvidia-cudnn-cu12==9.10.2.21"], **options)


LOCAL_MODELS = {
    "[本地] Whisper Small": "Systran/faster-whisper-small",
    "[本地] NLLB-200 600M INT8": "Adom4600/nllb-200-distilled-600M-ct2-int8",
}
QWEN_LABELS = {"[本地] Qwen3-ASR 0.6B": "0.6b", "[本地] Qwen3-ASR 1.7B": "1.7b"}


def model_ready(label):
    from subtitle_relay.qwen import installed

    if label in QWEN_LABELS:
        return installed(QWEN, QWEN_LABELS[label])
    if label in LOCAL_MODELS:
        hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
        hub = Path(os.environ.get("HF_HUB_CACHE", hf_home / "hub"))
        snapshots = hub / ("models--" + LOCAL_MODELS[label].replace("/", "--")) / "snapshots"
        return any(path.is_file() for path in snapshots.glob("*/model.bin"))
    return True


def install_model(label):
    if label in QWEN_LABELS:
        from subtitle_relay.qwen import install

        install(QWEN, QWEN_LABELS[label])
    else:
        from huggingface_hub import snapshot_download

        snapshot_download(LOCAL_MODELS[label])


def mpv_directory():
    return Path(os.environ["APPDATA"]) / "mpv"


def install_mpv(destination):
    scripts = destination / "scripts"
    opts = destination / "script-opts"
    scripts.mkdir(parents=True, exist_ok=True)
    opts.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "integrations/mpv/subtitle_relay.lua", scripts)
    (opts / "subtitle_relay.conf").write_text(
        f"pythonw={PYTHON.as_posix()}\nlauncher={Path(__file__).resolve().as_posix()}\nport={PORT}\n",
        encoding="utf-8",
    )


def potplayer_directory():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\DAUM\PotPlayer") as key:
            return Path(winreg.QueryValueEx(key, "ProgramFolder")[0])
    except OSError:
        return Path(os.environ["ProgramFiles"]) / "DAUM" / "PotPlayer"


def install_potplayer(destination):
    for path in (ROOT / "integrations/potplayer").glob("*.as"):
        script = path.read_text(encoding="utf-8").replace("@RELAY_PYTHONW@", PYTHON.as_posix())
        script = script.replace("@RELAY_LAUNCHER@", Path(__file__).resolve().as_posix())
        (destination / path.name).write_text(script, encoding="utf-8")


def native_potplayer(encoded=None, foreground=None):
    from subtitle_relay.potplayer import caller_potplayer, current_media, list_windows

    value = base64.b64decode(encoded) if encoded else b""
    encodings = ("utf-16-le", "utf-8-sig", "mbcs") if b"\0" in value else ("utf-8-sig", "mbcs")
    filename = None
    for encoding in encodings:
        try:
            candidate = value.decode(encoding).strip('\0\r\n"')
            if candidate:
                filename = candidate
                break
        except (UnicodeError, OSError, ValueError):
            continue
    if foreground:
        match = next((title for hwnd, title in list_windows() if hwnd == foreground), None)
        if not match or not match.endswith(" - PotPlayer"):
            raise RuntimeError("This PotPlayer window title does not identify the current file.")
        filename = match.removesuffix(" - PotPlayer")
    if filename is None:
        raise RuntimeError("PotPlayer did not supply a filename.")
    pid = caller_potplayer() if not foreground else None
    if pid is None and not foreground:
        raise RuntimeError("Subtitle Relay could not identify the PotPlayer process that opened it.")
    windows = [(foreground, match)] if foreground else list_windows(pid)
    matching = [window for window in windows if Path(filename).stem.casefold() in window[1].casefold()]
    if matching:
        windows = matching
    elif not windows:
        # Some builds invoke the extension from a helper process without a playback window.
        # Restrict the fallback to a unique main window whose title contains the exact filename.
        windows = [window for window in list_windows()
                   if Path(filename).name.casefold() in window[1].casefold()]
    if len(windows) != 1:
        raise RuntimeError(f"Cannot identify a unique PotPlayer playback window (PID {pid}, "
                           f"{len(windows)} candidates).")
    hwnd, _ = windows[0]
    from ctypes import wintypes

    owner = wintypes.DWORD()
    user = ctypes.WinDLL("user32")
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
    pid = owner.value
    from subtitle_relay.feedback import PotFeedback

    feedback = PotFeedback(hwnd)
    DATA.mkdir(parents=True, exist_ok=True)
    lock = DATA / f"pot-{pid}-{hwnd}.lock"
    stop = lock.with_suffix(".stop")
    with lock.open("a+b") as handle:
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            stop.touch()
            feedback.report("off", "预读已关闭")
            feedback.close(2)
            return
        try:
            feedback.report("on", "预读已开启，正在准备…")
            media = current_media(pid, filename)
            run_native_adapter(hwnd, media, stop, feedback.report)
        except EOFError:
            pass
        except Exception as exc:
            feedback.report("failed", str(exc))
            feedback.close(2.7)
            return
        feedback.close()


def run_native_adapter(hwnd, media, stop, report):
    from contextlib import redirect_stdout
    from subtitle_relay.players import run_adapter
    from subtitle_relay.potplayer import PotPlayer, find_reload_command
    from subtitle_relay.protocol import RelayClient

    def starting():
        report("starting", "正在启动字幕服务与识别模型…")

    stop.unlink(missing_ok=True)
    if not healthy():
        starting()
        background_start(starting)
    deadline = time.monotonic() + 65
    while not healthy():
        if stop.exists():
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("字幕服务启动超时，请查看 service.log。")
        starting()
        time.sleep(0.4)
    directory = potplayer_directory()
    executable = directory / "PotPlayerMini64.exe"
    if not executable.is_file():
        executable = directory / "PotPlayerMini.exe"
    reload = find_reload_command(executable)
    with (DATA / "potplayer.log").open("a", encoding="utf-8") as log, redirect_stdout(log):
        player = PotPlayer(hwnd, media, 0, reload)
        run_adapter(player, RelayClient(PORT), config()["source"] or None, "zh", 20, 0.6, stop,
                    idle_limit=4, report=report)


def gui(initial_media=None):
    from subtitle_relay.potplayer import list_windows

    root = tk.Tk()
    root.title(f"Subtitle Relay — {Path(initial_media).name}" if initial_media else "Subtitle Relay")
    root.minsize(640, 530)
    outer = ttk.Frame(root, padding=18)
    outer.pack(fill="both", expand=True)
    tabs = ttk.Notebook(outer)
    tabs.pack(fill="both", expand=True)
    setup = ttk.Frame(tabs, padding=14)
    advanced = ttk.Frame(tabs, padding=14)
    pot = ttk.Frame(tabs, padding=14)
    tabs.add(setup, text="模型")
    tabs.add(advanced, text="高级设置")
    tabs.add(pot, text="PotPlayer")
    ttk.Label(setup, text="Subtitle Relay", font=("Segoe UI", 18, "bold")).grid(row=0, columnspan=3, sticky="w")
    ttk.Label(setup, text="选择模型后启动服务。在 PotPlayer 中按 Ctrl+Alt+J。").grid(
        row=1, columnspan=3, sticky="w", pady=(0, 12))
    settings = {key: tk.StringVar(value=value) for key, value in config().items() if key in DEFAULTS}
    status = tk.StringVar(value="Checking service…")
    pot_status = tk.StringVar(value="Select a playing window and its local file.")
    starter_process = None
    setup_process = None
    model_process = None
    installing = None
    setup_status = tk.StringVar()

    def field(parent, row, key, label, choices=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)
        if choices:
            widget = ttk.Combobox(parent, textvariable=settings[key], values=choices, state="readonly")
        else:
            widget = ttk.Entry(parent, textvariable=settings[key], width=38)
        widget.grid(row=row, column=1, sticky="ew")

    asr_models = {
        "[本地] Whisper Small": "local", **dict.fromkeys(QWEN_LABELS, "qwen"),
        "[远程] OpenAI Whisper": "openai", "[自定义] 语音识别 API": "compatible",
    }
    mt_models = {"[本地] NLLB-200 600M INT8": "local",
                 f"[远程] OpenAI {settings['llm_model'].get()}": "openai",
                 "[自定义] 文本翻译 API": "compatible"}
    speech = tk.StringVar(value=next((label for label, kind in asr_models.items()
                                     if kind == settings["asr"].get() and
                                     (kind != "qwen" or QWEN_LABELS[label] == settings["qwen_size"].get())), ""))
    translation = tk.StringVar(value=next((label for label, kind in mt_models.items()
                                           if kind == settings["mt"].get()), ""))
    ttk.Label(setup, text="语音识别").grid(row=2, column=0, sticky="w", padx=(0, 12), pady=5)
    speech_box = ttk.Combobox(setup, textvariable=speech, state="readonly", width=40)
    speech_box.grid(row=2, column=1, sticky="ew")
    ttk.Label(setup, text="文本翻译").grid(row=3, column=0, sticky="w", padx=(0, 12), pady=5)
    translation_box = ttk.Combobox(setup, textvariable=translation, state="readonly", width=40)
    translation_box.grid(row=3, column=1, sticky="ew")
    ttk.Label(setup, text="视频语言").grid(row=4, column=0, sticky="w", pady=5)
    languages = {"自动识别": "", "日语": "ja", "英语": "en", "中文": "zh", "韩语": "ko"}
    language = tk.StringVar(value=next((name for name, code in languages.items()
                                        if code == settings["source"].get()), "自动识别"))
    ttk.Combobox(setup, textvariable=language, values=tuple(languages), state="readonly").grid(
        row=4, column=1, sticky="ew")
    ttk.Separator(setup).grid(row=5, columnspan=3, sticky="ew", pady=10)
    ttk.Label(setup, text="安装本地模型").grid(row=6, column=0, sticky="w", pady=5)
    missing = tk.StringVar()
    install_box = ttk.Combobox(setup, textvariable=missing, state="readonly", width=40)
    install_box.grid(row=6, column=1, sticky="ew")
    model_status = tk.StringVar()
    ttk.Label(setup, textvariable=model_status, wraplength=540).grid(row=7, columnspan=3, sticky="w")

    def refresh_models():
        speech_box["values"] = [label for label in asr_models if model_ready(label)]
        translation_box["values"] = [label for label in mt_models if model_ready(label)]
        unavailable = [label for label in (*QWEN_LABELS, *LOCAL_MODELS) if not model_ready(label)]
        install_box["values"] = unavailable
        if missing.get() not in unavailable:
            missing.set(unavailable[0] if unavailable else "")
        if speech.get() not in speech_box["values"]:
            speech.set("")
        if translation.get() not in translation_box["values"]:
            translation.set("")

    def prepare_model():
        nonlocal model_process, installing
        if not missing.get() or (model_process and model_process.poll() is None):
            return
        if not PYTHON.is_file():
            model_status.set("请先点「准备运行环境」。")
            return
        installing = missing.get()
        DATA.mkdir(parents=True, exist_ok=True)
        with (DATA / "model-install.log").open("wb") as output:
            model_process = subprocess.Popen(
                [str(PYTHON), str(Path(__file__).resolve()), "--install-model", installing],
                cwd=ROOT, stdout=output, stderr=output, creationflags=subprocess.CREATE_NO_WINDOW)
        model_status.set(f"正在下载 {installing}…")

    ttk.Button(setup, text="下载安装", command=prepare_model).grid(row=6, column=2, padx=5)
    refresh_models()
    for row, (key, label) in enumerate([
        ("chunk", "Scheduling block (seconds)"), ("before", "Context before block (seconds)"),
        ("after", "Context after block (seconds)"), ("max_speech", "Maximum ASR span (seconds)"),
        ("min_silence_ms", "Silence to split speech (ms)"), ("pad_ms", "Speech edge padding (ms)"),
        ("vad_threshold", "VAD probability threshold"),
        ("backfill", "Backfill before playhead (seconds)"),
    ]):
        field(advanced, row, key, label)
    field(advanced, 8, "asr_url", "Compatible ASR URL")
    field(advanced, 9, "asr_model", "Compatible ASR model")
    field(advanced, 10, "llm_url", "Compatible translation URL")
    field(advanced, 11, "llm_model", "Remote translation model")
    field(advanced, 12, "key_file", "OpenAI key file")
    ttk.Button(advanced, text="Browse…", command=lambda: settings["key_file"].set(
        filedialog.askopenfilename() or settings["key_file"].get())).grid(row=12, column=2, padx=5)
    field(advanced, 13, "device", "Local inference device", ["cuda", "cpu"])
    field(advanced, 14, "route", "Translation path", ["asr+mt", "OpenAI AST (English)"])

    def save():
        DATA.mkdir(parents=True, exist_ok=True)
        temporary = CONFIG.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps({key: value.get() for key, value in settings.items()}, indent=2),
                             encoding="utf-8")
        temporary.replace(CONFIG)

    def start():
        nonlocal starter_process
        if speech.get() not in asr_models or translation.get() not in mt_models:
            model_status.set("先选择已安装的本地模型或远程模型。")
            return
        settings["asr"].set(asr_models[speech.get()])
        if speech.get() in QWEN_LABELS:
            settings["qwen_size"].set(QWEN_LABELS[speech.get()])
        elif speech.get() == "[本地] Whisper Small":
            settings["whisper_model"].set("small")
        settings["mt"].set(mt_models[translation.get()])
        settings["source"].set(languages[language.get()])
        save()
        if healthy():
            messagebox.showinfo("Subtitle Relay", "The service is running. Stop and start it to apply settings.")
            return
        if not PYTHON.is_file():
            messagebox.showerror("Subtitle Relay", "The project .venv is missing. See the installation in README.md.")
            return
        with LOG.open("ab") as output:
            starter_process = subprocess.Popen([str(PYTHON), str(Path(__file__).resolve()), "--background"],
                                               stdout=output, stderr=output,
                                               creationflags=subprocess.CREATE_NO_WINDOW)
        status.set("Starting service and preparing models…")

    def stop():
        from subtitle_relay.protocol import RelayClient

        if CONTROL.is_file() and healthy():
            try:
                RelayClient(PORT).send("shutdown", {"token": CONTROL.read_text(encoding="ascii")})
            except (OSError, RuntimeError):
                messagebox.showerror("Subtitle Relay", "This running service is not owned by the settings app.")

    def mpv_install():
        selection = filedialog.askdirectory(title="Choose mpv config directory (Cancel uses AppData)")
        destination = Path(selection) if selection else mpv_directory()
        try:
            install_mpv(destination)
        except OSError as exc:
            messagebox.showerror("Subtitle Relay", str(exc))
            return
        messagebox.showinfo("Subtitle Relay",
                            f"Installed in {destination}. Restart mpv 0.42+, then right-click → Subtitle Relay.")

    def install_dependencies():
        nonlocal setup_process
        if setup_process and setup_process.poll() is None:
            return
        setup_process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--prepare"],
                                         creationflags=subprocess.CREATE_NO_WINDOW)
        setup_status.set("Preparing the Python environment…")

    def pot_install():
        try:
            destination = potplayer_directory() / "Extension" / "Subtitle" / "Translate"
            if not destination.is_dir():
                selection = filedialog.askdirectory(title="Choose PotPlayer's Extension/Subtitle/Translate directory")
                if not selection:
                    return
                destination = Path(selection)
            install_potplayer(destination)
        except OSError as exc:
            messagebox.showerror("Subtitle Relay", str(exc))
            return
        messagebox.showinfo("Subtitle Relay", "Restart PotPlayer and choose Subtitle Relay under real-time subtitle translation.")

    toolbar = ttk.Frame(setup)
    toolbar.grid(row=10, columnspan=3, sticky="w", pady=(12, 0))
    for label, handler in [("保存并启动", start), ("停止服务", stop), ("安装 mpv 菜单…", mpv_install)]:
        ttk.Button(toolbar, text=label, command=handler).pack(side="left", padx=(0, 6))
    ttk.Button(setup, text="准备运行环境", command=install_dependencies).grid(
        row=11, column=0, sticky="w", pady=8)
    ttk.Label(setup, textvariable=setup_status).grid(row=11, column=1, columnspan=2, sticky="w")

    ttk.Button(pot, text="Install PotPlayer translation menu", command=pot_install).pack(anchor="w")
    ttk.Checkbutton(pot, text="Ctrl+Alt+J toggles pre-read in the active PotPlayer window",
                    variable=settings["pot_hotkey"], onvalue="1", offvalue="0",
                    command=save).pack(anchor="w", pady=(8, 0))
    ttk.Label(pot, text="Open a local video in a new PotPlayer window with a live translated subtitle track.",
              wraplength=550).pack(anchor="w", pady=10)
    pot_log = DATA / "potplayer.log"
    pot_jobs = []

    def open_video():
        if not healthy():
            pot_status.set("Start the subtitle service first.")
            return
        selected = initial_media or filedialog.askopenfilename(title="Open local media in PotPlayer")
        if not selected:
            return
        executable = potplayer_directory() / "PotPlayerMini64.exe"
        if not executable.is_file():
            executable = filedialog.askopenfilename(title="Select PotPlayerMini.exe",
                                                    filetypes=[("Application", "*.exe")])
            if not executable:
                return
        pot_jobs.append(spawn(["potplayer-open", str(executable), selected, "--target", target.get(),
                                "--audio", audio.get(), "--ahead", ahead.get()], pot_log))
        pot_status.set("Preparing subtitles. PotPlayer will open when the initial buffer is ready.")

    ttk.Button(pot, text="Open video with translated subtitles…", command=open_video).pack(anchor="w", pady=5)
    ttk.Separator(pot).pack(fill="x", pady=8)
    ttk.Label(pot, text="Or attach to a video already playing in PotPlayer").pack(anchor="w")
    window = ttk.Combobox(pot, state="readonly", width=62)
    window.pack(fill="x")

    def refresh():
        window["values"] = [f"{hwnd:#x}  {title}" for hwnd, title in list_windows()]
        if window["values"]:
            window.current(0)

    ttk.Button(pot, text="Refresh windows", command=refresh).pack(anchor="w", pady=5)
    controls = ttk.Frame(pot)
    controls.pack(anchor="w")
    target = tk.StringVar(value="zh")
    ahead = tk.StringVar(value="20")
    audio = tk.StringVar(value="0")
    for label, variable in [("Target", target), ("Look-ahead (s)", ahead), ("Audio index", audio)]:
        ttk.Label(controls, text=label).pack(side="left", padx=(0, 3))
        ttk.Entry(controls, textvariable=variable, width=7).pack(side="left", padx=(0, 9))
    def attach():
        if not window.get():
            pot_status.set("Select a PotPlayer window first.")
            return
        if not healthy():
            pot_status.set("Start the subtitle service first.")
            return
        selected = initial_media or filedialog.askopenfilename(title="Select the file already playing in this window")
        if not selected:
            return
        hwnd = window.get().split()[0]
        from subtitle_relay.potplayer import find_reload_command

        reload_command = find_reload_command(potplayer_directory() / "PotPlayerMini64.exe")
        arguments = ["potplayer", hwnd, selected, "--target", target.get(),
                     "--audio", audio.get(), "--ahead", ahead.get()]
        if reload_command:
            arguments.extend(["--reload-command", str(reload_command)])
        pot_jobs.append(spawn(arguments, pot_log))
        instruction = "The track will refresh automatically." if reload_command else "Use Ctrl+Alt+Y to refresh."
        pot_status.set(f"Attached. Relay will load the first translated subtitles. {instruction}")

    ttk.Button(pot, text="Select media and start pre-reading…", command=attach).pack(anchor="w", pady=8)
    ttk.Label(pot, textvariable=pot_status, wraplength=550).pack(anchor="w")
    ttk.Button(pot, text="Show attachment log / SRT path", command=lambda: os.startfile(pot_log)
               if pot_log.exists() else None).pack(anchor="w", pady=6)

    footer = ttk.Frame(outer)
    footer.pack(fill="x", pady=(10, 0))
    ttk.Label(footer, textvariable=status).pack(side="left")
    ttk.Button(footer, text="View service log", command=lambda: os.startfile(LOG) if LOG.exists() else None).pack(side="right")

    def tick():
        nonlocal model_process
        if model_process and model_process.poll() is not None:
            if model_process.returncode == 0:
                refresh_models()
                (speech if installing in asr_models else translation).set(installing)
                model_status.set(f"{installing} 已安装。点击「保存并启动」使用。")
            else:
                model_status.set(f"下载失败。日志：{DATA / 'model-install.log'}")
            model_process = None
        for process in pot_jobs[:]:
            code = process.poll()
            if code is not None:
                pot_jobs.remove(process)
                if code:
                    pot_status.set(f"PotPlayer action failed ({code}). Open the attachment log for details.")
        if setup_process and setup_process.poll() is not None:
            setup_status.set("Engine dependencies ready" if setup_process.returncode == 0 else
                             f"Setup failed. See {DATA / 'setup.log'}")
        status.set("Service ready" if healthy() else
                   "启动失败，点击右侧查看服务日志。" if starter_process and starter_process.poll() else
                   "正在启动服务与模型…" if starter_process and starter_process.poll() is None
                   else "Service stopped")
        root.after(1500, tick)

    root.after(50, tick)
    if initial_media:
        tabs.select(pot)
        refresh()
        for index, entry in enumerate(window["values"]):
            if Path(initial_media).name.casefold() in entry.casefold():
                window.current(index)
                break
        pot_status.set(f"Current file: {Path(initial_media).name}")
    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--install-model":
        install_model(sys.argv[2])
    elif "--prepare" in sys.argv:
        prepare()
    elif "--background" in sys.argv:
        background_start()
    elif len(sys.argv) >= 3 and sys.argv[1] in {"--pot-toggle", "--pot-hwnd"}:
        try:
            if sys.argv[1] == "--pot-hwnd":
                native_potplayer(foreground=int(sys.argv[2]))
            else:
                native_potplayer("".join(sys.argv[2:]).strip('"'))
        except EOFError:
            pass
        except Exception as exc:
            ctypes.windll.user32.MessageBoxW(None, str(exc), "Subtitle Relay", 0x10)
    else:
        gui()
