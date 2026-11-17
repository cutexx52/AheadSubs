import ctypes as ct
import json
import os
import struct
import subprocess
import sys
import time
from ctypes import wintypes as win
from pathlib import Path
from threading import Thread
from uuid import uuid4


def find_reload_command(executable):
    """Resolve the Reload Subtitle item in the installed build's native menu resource."""
    executable = Path(executable)
    folder = executable.parent
    suffix = "64" if "64" in executable.stem else ""
    english = folder / "Language" / "English.ini"
    try:
        label = next(line for line in english.read_text("utf-8-sig", errors="replace").splitlines()
                     if "=Reload Subtitle\t" in line)
        resource, *positions = (int(value) for value in label.split("=", 1)[0].split("_"))
    except (OSError, StopIteration, ValueError):
        return None
    if not positions:
        return None
    user, kernel = ct.WinDLL("user32"), ct.WinDLL("kernel32")
    kernel.LoadLibraryExW.argtypes = [win.LPCWSTR, win.HANDLE, win.DWORD]
    kernel.LoadLibraryExW.restype = win.HMODULE
    kernel.FreeLibrary.argtypes = [win.HMODULE]
    user.LoadMenuW.argtypes = [win.HINSTANCE, ct.c_void_p]
    user.LoadMenuW.restype = win.HMENU
    user.GetSubMenu.argtypes = [win.HMENU, ct.c_int]
    user.GetSubMenu.restype = win.HMENU
    user.GetMenuItemID.argtypes = [win.HMENU, ct.c_int]
    user.GetMenuItemID.restype = win.UINT
    user.DestroyMenu.argtypes = [win.HMENU]
    module = kernel.LoadLibraryExW(str(folder / f"PotPlayer{suffix}.dll"), None, 0x22)
    if not module:
        return None
    menu = user.LoadMenuW(module, resource)
    try:
        current = menu
        for index in positions[:-1]:
            if not current:
                return None
            current = user.GetSubMenu(current, index)
        if current:
            command = user.GetMenuItemID(current, positions[-1])
            if 1 <= command <= 65535:
                return command
        return None
    finally:
        if menu:
            user.DestroyMenu(menu)
        kernel.FreeLibrary(module)


def list_windows(pid=None):
    user = ct.WinDLL("user32", use_last_error=True)
    callback_type = ct.WINFUNCTYPE(win.BOOL, win.HWND, win.LPARAM)
    user.EnumWindows.argtypes = [callback_type, win.LPARAM]
    user.IsWindowVisible.argtypes = [win.HWND]
    user.GetWindowTextW.argtypes = [win.HWND, win.LPWSTR, ct.c_int]
    user.GetClassNameW.argtypes = [win.HWND, win.LPWSTR, ct.c_int]
    user.GetWindowThreadProcessId.argtypes = [win.HWND, ct.POINTER(win.DWORD)]
    result = []

    @callback_type
    def add(hwnd, _):
        if pid is not None:
            owner = win.DWORD()
            user.GetWindowThreadProcessId(hwnd, ct.byref(owner))
            if owner.value != pid:
                return True
        kind = ct.create_unicode_buffer(128)
        user.GetClassNameW(hwnd, kind, len(kind))
        if kind.value in {"PotPlayer64", "PotPlayer"} and (pid is not None or user.IsWindowVisible(hwnd)):
            title = ct.create_unicode_buffer(1024)
            user.GetWindowTextW(hwnd, title, len(title))
            result.append((hwnd, title.value))
        return True

    user.EnumWindows(add, 0)
    return result


def caller_potplayer():
    """Identify the launching PotPlayer through the Python launcher process chain."""
    class ProcessEntry(ct.Structure):
        _fields_ = [("size", win.DWORD), ("usage", win.DWORD), ("pid", win.DWORD),
                    ("heap", ct.c_size_t), ("module", win.DWORD), ("threads", win.DWORD),
                    ("parent", win.DWORD), ("priority", win.LONG), ("flags", win.DWORD),
                    ("name", win.WCHAR * 260)]

    kernel = ct.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [win.DWORD, win.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = win.HANDLE
    kernel.Process32FirstW.argtypes = [win.HANDLE, ct.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = kernel.Process32FirstW.argtypes
    kernel.CloseHandle.argtypes = [win.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ct.c_void_p(-1).value:
        raise ct.WinError(ct.get_last_error())
    entries = {}
    entry = ProcessEntry()
    entry.size = ct.sizeof(entry)
    try:
        found = kernel.Process32FirstW(handle, ct.byref(entry))
        while found:
            entries[entry.pid] = (entry.parent, entry.name.casefold())
            found = kernel.Process32NextW(handle, ct.byref(entry))
    finally:
        kernel.CloseHandle(handle)
    pid = os.getpid()
    for _ in range(12):
        pid, name = entries.get(pid, (0, ""))
        if not pid:
            break
        if name.startswith(("potplayermini", "potplayer")):
            return pid
    return None


class MediaPathUnavailable(RuntimeError):
    pass


def media_from_folder(folder, filename):
    relative = Path(filename)
    if not folder or not folder.is_absolute() or relative.name != filename:
        return None
    candidate = folder / relative
    return candidate if candidate.is_file() else None


def current_media(pid, filename):
    """Resolve PotPlayer's filename within the calling process's open media files."""
    import psutil

    hint = Path(filename)
    if hint.is_absolute() and hint.is_file():
        return hint
    try:
        candidates = {path for opened in psutil.Process(pid).open_files()
                      if (path := Path(opened.path)).name.casefold() == hint.name.casefold()
                      and path.is_file()}
    except psutil.AccessDenied as exc:
        raise MediaPathUnavailable("Windows 拒绝读取 PotPlayer 打开的文件列表。") from exc
    if len(candidates) == 1:
        return candidates.pop()
    raise MediaPathUnavailable(f"PotPlayer 只提供了文件名，找到 {len(candidates)} 个实际路径候选。")


def start_hotkey(launcher):
    """Register dedicated start and stop keys for the foreground PotPlayer window."""
    def listen():
        user = ct.WinDLL("user32", use_last_error=True)
        user.GetForegroundWindow.restype = win.HWND
        user.GetMessageW.argtypes = [ct.POINTER(win.MSG), win.HWND, win.UINT, win.UINT]
        commands = {}
        for identifier, key, argument in ((1, "J", "--pot-hwnd"), (2, "K", "--pot-stop-hwnd")):
            if user.RegisterHotKey(None, identifier, 0x4003, ord(key)):
                commands[identifier] = argument
                print(f"PotPlayer hotkey Ctrl+Alt+{key} registered", flush=True)
            else:
                print(f"PotPlayer hotkey Ctrl+Alt+{key} is already in use.", flush=True)
        if not commands:
            return
        message = win.MSG()
        try:
            while user.GetMessageW(ct.byref(message), None, 0, 0) > 0:
                if message.message != 0x312 or message.wParam not in commands:
                    continue
                foreground = user.GetForegroundWindow()
                if any(hwnd == foreground for hwnd, _ in list_windows()):
                    command = commands[message.wParam]
                    print(f"PotPlayer hotkey {command} hwnd={foreground:#x}", flush=True)
                    subprocess.Popen([sys.executable, str(launcher), command, str(foreground)],
                                     creationflags=subprocess.CREATE_NO_WINDOW)
        finally:
            for identifier in commands:
                user.UnregisterHotKey(None, identifier)

    Thread(target=listen, daemon=True).start()


class PotPlayer:
    """Poll one explicitly bound window and local file."""

    def __init__(self, hwnd, path, audio, reload_command, track=None, resolve_media=None):
        self.hwnd, self.path, self.audio = hwnd, Path(path).resolve(strict=True), audio
        self.reload_command = reload_command
        self.track = track
        self.resolve_media = resolve_media
        self.user = ct.WinDLL("user32", use_last_error=True)
        self.user.SendMessageTimeoutW.argtypes = [
            win.HWND, win.UINT, win.WPARAM, win.LPARAM, win.UINT, win.UINT, ct.POINTER(ct.c_size_t),
        ]
        self.user.SendMessageTimeoutW.restype = win.LPARAM
        self.user.GetWindowTextW.argtypes = [win.HWND, win.LPWSTR, ct.c_int]
        self.user.GetClassNameW.argtypes = [win.HWND, win.LPWSTR, ct.c_int]
        self.user.GetWindowThreadProcessId.argtypes = [win.HWND, ct.POINTER(win.DWORD)]
        kind = ct.create_unicode_buffer(128)
        self.user.GetClassNameW(hwnd, kind, len(kind))
        if kind.value not in {"PotPlayer64", "PotPlayer"}:
            raise ValueError("HWND is not a PotPlayer main window")
        self.pid = self._pid()
        self.subtitle = None
        self.revision = 0

    def _pid(self):
        pid = win.DWORD()
        self.user.GetWindowThreadProcessId(self.hwnd, ct.byref(pid))
        return pid.value

    def _send(self, message, code):
        value = ct.c_size_t()
        if not self.user.SendMessageTimeoutW(self.hwnd, message, code, 0, 2, 300, ct.byref(value)):
            raise OSError("PotPlayer did not respond")
        return value.value

    def state(self):
        if self._pid() != self.pid:
            raise EOFError("PotPlayer window closed")
        title = ct.create_unicode_buffer(1024)
        self.user.GetWindowTextW(self.hwnd, title, len(title))
        filename = title.value.removesuffix(" - PotPlayer")
        if self.resolve_media:
            if not title.value.endswith(" - PotPlayer") or not Path(filename).suffix:
                return None
        elif self.path.stem.casefold() not in title.value.casefold():
            return None
        duration = self._send(0x400, 0x5002) / 1000
        position = self._send(0x400, 0x5004) / 1000
        if not 0 < duration <= 10_000_000 or not 0 <= position <= duration:
            return None
        hint = Path(filename)
        current = str(self.path) if hint.is_absolute() else self.path.name
        if self.resolve_media and str(hint).casefold() != current.casefold():
            media = self.resolve_media(filename)
            if media is None:
                raise EOFError("Pre-read stopped after file selection was cancelled")
            self.path = media.resolve(strict=True)
            self.subtitle, self.revision = None, 0
            # The picker may have been open while playback advanced or changed file again.
            return None
        return {"path": str(self.path), "position": position, "duration": duration, "audio": self.audio}

    def publish(self, path, revision):
        if self.track is not None:
            if (path, revision) != (self.subtitle, self.revision):
                try:
                    write_potplayer_track(self.track, Path(path))
                except PermissionError:
                    return
                if self.reload_command:
                    self._send(0x111, self.reload_command)
                self.subtitle, self.revision = path, revision
            return
        if self.subtitle != path:
            with Path(path).open("r", encoding="utf-8-sig") as subtitle:
                if not subtitle.read(64).strip():
                    return
            self.load_subtitle(Path(path))
            print(f"Loaded subtitle into PotPlayer: {path}", flush=True)
            self.subtitle, self.revision = path, revision
        elif self.revision != revision and self.reload_command is not None:
            self._send(0x111, self.reload_command)
            self.revision = revision

    def load_subtitle(self, path):
        if self._pid() != self.pid or path.suffix.lower() != ".srt":
            raise ValueError("The target window or subtitle is no longer available")
        # Send the shell's standard single-file drop to this HWND, never the active window.
        data = struct.pack("<IiiII", 20, 0, 0, 0, 1) + (str(path) + "\0\0").encode("utf-16-le")
        kernel = ct.WinDLL("kernel32", use_last_error=True)
        kernel.GlobalAlloc.argtypes = [win.UINT, ct.c_size_t]
        kernel.GlobalAlloc.restype = win.HGLOBAL
        kernel.GlobalLock.argtypes = [win.HGLOBAL]
        kernel.GlobalLock.restype = ct.c_void_p
        kernel.GlobalUnlock.argtypes = [win.HGLOBAL]
        kernel.GlobalFree.argtypes = [win.HGLOBAL]
        kernel.GlobalFree.restype = win.HGLOBAL
        self.user.PostMessageW.argtypes = [win.HWND, win.UINT, win.WPARAM, win.LPARAM]
        drop = kernel.GlobalAlloc(0x42, len(data))
        if not drop:
            raise ct.WinError(ct.get_last_error())
        address = kernel.GlobalLock(drop)
        if address:
            ct.memmove(address, data, len(data))
            kernel.GlobalUnlock(drop)
            if self.user.PostMessageW(self.hwnd, 0x233, drop, 0):
                return
        error = ct.get_last_error()
        kernel.GlobalFree(drop)
        raise ct.WinError(error)


def open_with_subtitles(executable, path, client, audio, source, target, ahead, muted=False):
    from .players import run_adapter

    path = Path(path).resolve(strict=True)
    duration = float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ], timeout=15, creationflags=subprocess.CREATE_NO_WINDOW))
    session = uuid4().hex
    hints = {"session": session, "source": source, "target": target, "ahead": ahead,
             "path": str(path), "audio": audio, "duration": duration}
    response = None
    subtitle = None
    process = None
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            response = client.send("playback", {**hints, "position": 0})
            if response["error"]:
                raise RuntimeError(response["error"])
            if response["ready_ahead"] >= min(8, duration):
                break
            time.sleep(0.25)
        if not response or not response["subtitle"]:
            raise TimeoutError("The backend did not produce a subtitle file")
        cache_srt = Path(response["subtitle"])
        # A private external track prevents independent windows from resetting each other's subtitle.
        subtitle = cache_srt.with_name(f"{cache_srt.stem}-{session}.srt")
        write_potplayer_track(subtitle, cache_srt)
        reload_command = find_reload_command(executable)
        arguments = [str(executable), str(path), "/new", f"/sub={subtitle}"]
        if muted:
            arguments.append("/volume=0")
        process = subprocess.Popen(arguments)
        deadline = time.monotonic() + 15
        player = None
        while time.monotonic() < deadline and not player:
            for hwnd, title in list_windows():
                if path.stem.casefold() not in title.casefold():
                    continue
                candidate = PotPlayer(hwnd, path, audio, reload_command, track=subtitle)
                if candidate.pid == process.pid:
                    player = candidate
                    break
            if not player:
                time.sleep(0.25)
        if not player:
            raise TimeoutError("Could not identify the new PotPlayer window")
        print(json.dumps({"window": hex(player.hwnd), "subtitle": str(subtitle),
                          "reload_command": reload_command}), flush=True)
        player.subtitle, player.revision = str(cache_srt), response["revision"]
        run_adapter(player, client, source, target, ahead, 0.6, session=session)
    finally:
        try:
            client.send("close", {"session": session})
        except (OSError, RuntimeError):
            pass
        if subtitle and (process is None or process.poll() is not None):
            try:
                subtitle.unlink(missing_ok=True)
            except PermissionError:
                pass


def write_potplayer_track(subtitle, source):
    text = source.read_text(encoding="utf-8-sig").strip()
    if not text:
        # PotPlayer needs a valid external track even if the opening scene is silent.
        text = "1\n00:00:00,000 --> 00:00:00,100\n\u00a0"
    temporary = subtitle.with_suffix(".tmp")
    temporary.write_text(text + "\n", encoding="utf-8-sig")
    temporary.replace(subtitle)
