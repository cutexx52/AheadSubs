import base64
import ctypes
import msvcrt
import time
from pathlib import Path
from tkinter import filedialog

from .assets import potplayer_directory
from .runtime import DATA, PAUSED, PORT, background_start, config, diagnostics_enabled, healthy, log_output

def pot_event(event, detail, hwnd=None):
    if not diagnostics_enabled():
        return
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / "potplayer.log").open("a", encoding="utf-8") as log:
        window = f" hwnd={hwnd:#x}" if hwnd else ""
        log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}{window} {event} {detail}\n")


def native_potplayer(encoded=None, foreground=None, disable=False):
    from subtitle_relay.adapters.potplayer import (MediaPathUnavailable, caller_potplayer, current_media,
                                          list_windows, media_from_folder)

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
        if match is None or (not disable and not match.endswith(" - PotPlayer")):
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
    from subtitle_relay.desktop.feedback import PotFeedback

    feedback = PotFeedback(hwnd)
    previous_state = None

    def report(state, message):
        nonlocal previous_state
        if state != previous_state:
            pot_event(state, message, hwnd)
            previous_state = state
        feedback.report(state, message)

    DATA.mkdir(parents=True, exist_ok=True)
    lock = DATA / f"pot-{pid}-{hwnd}.lock"
    stop = lock.with_suffix(".stop")
    folder_hint = lock.with_suffix(".folder")
    with lock.open("a+b") as handle:
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            if disable:
                stop.touch()
                report("off", "预读已关闭")
            elif foreground:
                if stop.exists():
                    report("stopping", "预读正在关闭，稍等后按 Ctrl+Alt+J 开启。")
                else:
                    report("already-active", "当前窗口的预读已开启")
            else:
                pot_event("already-active", "PotPlayer 重复调用了预读扩展", hwnd)
            feedback.close(2 if foreground else 0)
            return
        if disable:
            report("already-off", "当前窗口的预读已关闭")
            feedback.close(2)
            return
        try:
            stop.unlink(missing_ok=True)
            pot_event("launch", "快捷键" if foreground else "PotPlayer 扩展", hwnd)
            report("locating", "正在定位当前视频并启动预读…")
            folder = None
            try:
                folder = Path(folder_hint.read_text(encoding="utf-8"))
            except OSError:
                pass

            def resolve_media(name):
                nonlocal folder
                try:
                    media = current_media(pid, name)
                    pot_event("media", "自动定位成功", hwnd)
                except MediaPathUnavailable as exc:
                    media = media_from_folder(folder, name)
                    if media:
                        pot_event("media", "在当前窗口已确认的目录找到视频", hwnd)
                    else:
                        report("choose-media", f"{exc} 请选择当前视频，同一目录里的后续视频会自动接续。")
                        selected = filedialog.askopenfilename(
                            parent=feedback.root, initialdir=str(folder) if folder else "",
                            initialfile=Path(name).name, title="Subtitle Relay — 选择 PotPlayer 中正在播放的视频")
                        if not selected or stop.exists():
                            report("cancelled", "已取消选择，预读已停止。")
                            return None
                        media = Path(selected)
                        if media.name.casefold() != Path(name).name.casefold():
                            raise ValueError("所选文件名与当前 PotPlayer 窗口不一致。")
                        pot_event("media", "用户已确认当前视频和目录", hwnd)
                if media.parent != folder:
                    folder = media.parent
                    folder_hint.write_text(str(folder), encoding="utf-8")
                return media

            media = resolve_media(filename)
            if media is None:
                feedback.close()
                return
            run_native_adapter(hwnd, media, stop, report, resolve_media)
        except EOFError:
            pot_event("closed", "当前窗口的预读会话已结束", hwnd)
        except Exception as exc:
            report("failed", str(exc))
        feedback.close()


def run_native_adapter(hwnd, media, stop, report, resolve_media):
    from contextlib import redirect_stdout
    from subtitle_relay.adapters.players import run_adapter
    from subtitle_relay.adapters.potplayer import PotPlayer, find_reload_command
    from subtitle_relay.client import RelayClient

    def starting():
        report("starting", "正在启动字幕服务与识别模型…")

    def preferences():
        settings = config()
        return {"source": settings["source"] or None, "target": settings["target"],
                "bilingual": settings["bilingual"] == "1"}

    if not healthy():
        if PAUSED.exists():
            raise RuntimeError("字幕服务已停止。打开设置，点击「保存并启动」。")
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
    with log_output(DATA / "potplayer.log", text=True) as log, redirect_stdout(log):
        player = PotPlayer(hwnd, media, 0, reload, resolve_media=resolve_media)
        if stop.exists():
            return
        report("on", "预读已开启")
        run_adapter(player, RelayClient(PORT), None, None, 20, 0.6, stop,
                    report=report, seek_interval=0.15, preferences=preferences)
