"""On-demand process resource samples for the desktop status page."""

import ctypes
import os
import sys
from collections import Counter
from time import monotonic

try:
    import psutil
except ImportError:
    psutil = None


class CounterValue(ctypes.Structure):
    _fields_ = [("status", ctypes.c_uint32), ("value", ctypes.c_double)]


class CounterItem(ctypes.Structure):
    _fields_ = [("name", ctypes.c_wchar_p), ("sample", CounterValue)]


def gpu_totals(engines, memory, pids):
    busy = Counter()
    for name, value in engines or ():
        pid, _, engine = name.removeprefix("pid_").partition("_")
        if pid in pids:
            busy[engine] += value
    return {"gpu_percent": min(100, max(busy.values(), default=0)) if engines is not None else None,
            "vram_bytes": round(sum(value for name, value in memory
                                   if name.removeprefix("pid_").partition("_")[0] in pids))
            if memory is not None else None}


class WindowsGpu:
    """A single PDH query keeps the two samples required by the utilization counter."""

    def __init__(self):
        self.pdh = ctypes.WinDLL("pdh")
        self.query = ctypes.c_void_p()
        if self.pdh.PdhOpenQueryW(None, ctypes.c_size_t(), ctypes.byref(self.query)):
            return
        self.engines = self._add(r"\GPU Engine(*)\Utilization Percentage")
        self.memory = self._add(r"\GPU Process Memory(*)\Dedicated Usage")

    def _add(self, path):
        handle = ctypes.c_void_p()
        self.pdh.PdhAddEnglishCounterW(self.query, ctypes.c_wchar_p(path), ctypes.c_size_t(), ctypes.byref(handle))
        return handle

    def _values(self, handle):
        if not handle:
            return None
        size, count = ctypes.c_uint32(), ctypes.c_uint32()
        read = self.pdh.PdhGetFormattedCounterArrayW
        # PDH_FMT_DOUBLE, then allocate exactly the size reported by PDH.
        status = read(handle, 0x200, ctypes.byref(size), ctypes.byref(count), None)
        if status & 0xFFFFFFFF != 0x800007D2 or not 0 < size.value <= 4 * 1024 * 1024:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if read(handle, 0x200, ctypes.byref(size), ctypes.byref(count), buffer):
            return None
        items = ctypes.cast(buffer, ctypes.POINTER(CounterItem))
        return [(item.name, max(0, item.sample.value)) for item in items[:count.value]
                if item.name and item.sample.status in (0, 1)] or None

    def read(self, pids):
        if not self.query or self.pdh.PdhCollectQueryData(self.query):
            return {}
        return gpu_totals(self._values(self.engines), self._values(self.memory), pids)

    def close(self):
        if self.query:
            self.pdh.PdhCloseQuery(self.query)


class Resources:
    def __init__(self):
        try:
            self.process = psutil.Process() if psutil else None
        except (OSError, psutil.Error):
            self.process = None
        self.gpu = None
        self.last = None
        self.last_times = {}
        self.sample = {}

    def read(self):
        now = monotonic()
        if self.last is not None and now - self.last < 1:
            return self.sample
        if self.last is not None and now - self.last > 12:
            self.last_times = {}
            self.close()
        cpu_times = {}
        memory = 0
        if self.process:
            try:
                processes = [self.process, *self.process.children(recursive=True)]
            except psutil.Error:
                processes = [self.process]
            for process in processes:
                try:
                    with process.oneshot():
                        times = process.cpu_times()
                        rss = process.memory_info().rss
                        key = (process.pid, process.create_time())
                except psutil.Error:
                    continue
                cpu_times[key] = times.user + times.system
                memory += rss
        elapsed_cpu = sum(max(0, seconds - self.last_times[key]) for key, seconds in cpu_times.items()
                          if key in self.last_times)
        self.sample = {"cpu_percent": min(100, elapsed_cpu * 100 / ((now - self.last) * (os.cpu_count() or 1)))
                       if self.last_times and cpu_times else None,
                       "rss_bytes": memory if cpu_times else None}
        self.last, self.last_times = now, cpu_times
        if sys.platform == "win32":
            try:
                if self.gpu is None:
                    self.gpu = WindowsGpu()
                self.sample.update(self.gpu.read({str(os.getpid()), *(str(pid) for pid, _ in cpu_times)}))
            except OSError:
                pass
        return self.sample

    def close(self):
        if self.gpu is not None:
            self.gpu.close()
            self.gpu = None
