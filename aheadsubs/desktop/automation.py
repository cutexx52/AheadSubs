"""Per-user Windows settings for connecting local automation clients."""
import ctypes
import os
import sys
import winreg
from ctypes import wintypes
from pathlib import Path

from . import runtime
from ..automation_text import text


def mcp_enabled():
    return (runtime.DATA / "mcp-enabled").is_file()


def cli_directory():
    return runtime.ROOT / "cli"


def path_entries(key):
    try:
        value, kind = winreg.QueryValueEx(key, "Path")
    except FileNotFoundError:
        return [], winreg.REG_EXPAND_SZ
    return value.split(";"), kind


def is_app_directory(entry):
    if not entry.strip():
        return False
    value = os.path.expandvars(entry.strip().strip('"'))
    return os.path.normcase(os.path.normpath(value)) == os.path.normcase(str(cli_directory()))


def set_cli_installed(installed):
    if installed and not (cli_directory() / "aheadsubs.exe").is_file():
        raise ValueError(text("error.cli_not_bundled"))
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
        entries, kind = path_entries(key)
        matching = any(map(is_app_directory, entries))
        if installed == matching:
            return
        if installed:
            entries.insert(0, str(cli_directory()))
        else:
            entries = [entry for entry in entries if not is_app_directory(entry)]
        winreg.SetValueEx(key, "Path", 0, kind, ";".join(entries))

    notify = ctypes.windll.user32.SendMessageTimeoutW
    notify.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR,
                       wintypes.UINT, wintypes.UINT, ctypes.c_void_p)
    notify(0xFFFF, 0x001A, 0, "Environment", 0x0002, 1000, None)


def integration_status():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            entries, _ = path_entries(key)
    except FileNotFoundError:
        entries = []
    return {"mcp_enabled": mcp_enabled(), "cli_available": (cli_directory() / "aheadsubs.exe").is_file(),
            "cli_installed": any(map(is_app_directory, entries)),
            "mcp_config": {"mcpServers": {"aheadsubs": {"command": str(Path(sys.executable)),
                           "args": ["-P", "-m", "aheadsubs.cli", "mcp", "--desktop"],
                           "env": {"PYTHONPATH": str(runtime.ROOT)}}}}}


def configure(action):
    if action in {"mcp-enable", "mcp-disable"}:
        marker = runtime.DATA / "mcp-enabled"
        if action == "mcp-enable":
            runtime.DATA.mkdir(parents=True, exist_ok=True)
            marker.touch()
        else:
            marker.unlink(missing_ok=True)
    elif action in {"cli-install", "cli-remove"}:
        set_cli_installed(action == "cli-install")
    return integration_status()
