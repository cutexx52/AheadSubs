import ctypes as ct
import json
import subprocess
import time
from ctypes import wintypes as win
from pathlib import Path
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


def list_windows():
    user = ct.WinDLL("user32", use_last_error=True)
    callback_type = ct.WINFUNCTYPE(win.BOOL, win.HWND, win.LPARAM)
    user.EnumWindows.argtypes = [callback_type, win.LPARAM]
    user.IsWindowVisible.argtypes = [win.HWND]
    user.GetWindowTextW.argtypes = [win.HWND, win.LPWSTR, ct.c_int]
    user.GetClassNameW.argtypes = [win.HWND, win.LPWSTR, ct.c_int]
    result = []

    @callback_type
    def add(hwnd, _):
        kind = ct.create_unicode_buffer(128)
        user.GetClassNameW(hwnd, kind, len(kind))
        if kind.value in {"PotPlayer64", "PotPlayer"} and user.IsWindowVisible(hwnd):
            title = ct.create_unicode_buffer(1024)
            user.GetWindowTextW(hwnd, title, len(title))
            result.append((hwnd, title.value))
        return True

    user.EnumWindows(add, 0)
    return result


class PotPlayer:
    """Poll one explicitly bound window and local file."""

    def __init__(self, hwnd, path, audio, reload_command):
        self.hwnd, self.path, self.audio = hwnd, Path(path).resolve(strict=True), audio
        self.reload_command = reload_command
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
        if self.path.stem.casefold() not in title.value.casefold():
            return None
        duration = self._send(0x400, 0x5002) / 1000
        position = self._send(0x400, 0x5004) / 1000
        if not 0 < duration <= 10_000_000 or not 0 <= position <= duration:
            return None
        return {"path": str(self.path), "position": position, "duration": duration, "audio": self.audio}

    def publish(self, path, revision):
        if self.subtitle != path:
            if Path(path).stat().st_size <= 1:
                return
            print(f"Load this external subtitle into the bound PotPlayer window: {path}", flush=True)
            self.subtitle, self.revision = path, revision
        elif self.revision != revision and self.reload_command is not None:
            self._send(0x111, self.reload_command)
            self.revision = revision


def open_with_subtitles(executable, path, client, audio, source, target, ahead, muted=False):
    path = Path(path).resolve(strict=True)
    duration = float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ], timeout=15))
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
                candidate = PotPlayer(hwnd, path, audio, reload_command)
                if candidate.pid == process.pid:
                    player = candidate
                    break
            if not player:
                time.sleep(0.25)
        if not player:
            raise TimeoutError("Could not identify the new PotPlayer window")
        print(json.dumps({"window": hex(player.hwnd), "subtitle": str(subtitle),
                          "reload_command": reload_command}), flush=True)
        revision = response["revision"]
        while process.poll() is None:
            state = player.state()
            if not state:
                client.send("close", {"session": session})
            else:
                response = client.send("playback", {**hints, **state})
                if response["error"]:
                    print(response["error"], flush=True)
                if response["subtitle"] and response["revision"] != revision:
                    try:
                        write_potplayer_track(subtitle, Path(response["subtitle"]))
                    except PermissionError:
                        # The player can briefly hold the external file open while reloading.
                        time.sleep(0.25)
                        continue
                    if reload_command:
                        player._send(0x111, reload_command)
                    revision = response["revision"]
            time.sleep(0.6)
    finally:
        try:
            client.send("close", {"session": session})
        except OSError:
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
