from collections import deque
from math import ceil


SOURCES = ("potplayer", "mpv", "cli", "mcp", "http")
SESSION_TIMEOUT = 10
WINDOW = 15 * 60
SAMPLE_LIMIT = 1024


class Samples:
    """Called while the relay holds its lock."""

    def __init__(self):
        self.values = deque(maxlen=SAMPLE_LIMIT)

    def add(self, now, value):
        self.values.append((now, value))

    def summary(self, now):
        while self.values and self.values[0][0] <= now - WINDOW:
            self.values.popleft()
        values = sorted(value for _, value in self.values)
        count = len(values)
        return {"count": count, **{f"p{p}": values[ceil(p * count / 100) - 1] if count else None
                                   for p in (50, 95, 99)}}
