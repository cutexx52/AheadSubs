"""Windows idle detection and the desktop bridge for folder tasks."""
import ctypes
import json
from ctypes import wintypes

from pydantic import ValidationError

from ..automation import OperationError
from ..folder_tasks import FolderWorker, RuleSet, TaskFiles
from . import runtime


class LastInput(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def windows_idle_seconds():
    state = LastInput(ctypes.sizeof(LastInput), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(state)):
        return 0
    uptime = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    return ((uptime - state.dwTime) & 0xFFFFFFFF) / 1000


def background_worker(relay, defaults):
    return FolderWorker(TaskFiles(runtime.DATA), relay, defaults, windows_idle_seconds).running()


def configure(action, stream):
    files = TaskFiles(runtime.DATA)
    if action == "save":
        try:
            config = RuleSet.model_validate(json.load(stream))
        except ValidationError as exc:
            field = ".".join(map(str, exc.errors(include_input=False)[0]["loc"])) or "rules"
            raise OperationError("folder_task_invalid", field=field) from exc
        files.save(config)
    elif action == "retry":
        request = json.load(stream)
        identifier = request.get("id") if isinstance(request, dict) else None
        if not any(rule.id == identifier for rule in files.load().rules):
            raise OperationError("folder_task_invalid", field="id")
        files.retry(identifier)
    elif action is not None:
        raise OperationError("folder_task_invalid", field="action")
    return {**files.status(), "running": runtime.healthy()}
