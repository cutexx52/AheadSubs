"""Local weekly aggregates for cloud model calls."""

import re
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit


USAGE_DB = "cloud-usage.sqlite3"
WEEKS = 8
_FIELDS = ("week", "provider", "model", "operation", "calls", "failed", "input_tokens",
           "output_tokens", "audio_seconds", "priced_calls", "estimated_usd")
_COUNTS = _FIELDS[4:]
_TABLE = """CREATE TABLE IF NOT EXISTS weekly (
    week TEXT, provider TEXT, model TEXT, operation TEXT, calls INTEGER, failed INTEGER,
    input_tokens INTEGER, output_tokens INTEGER, audio_seconds REAL, priced_calls INTEGER,
    estimated_usd REAL, PRIMARY KEY (week, provider, model, operation))"""


def _monday(day):
    return day - timedelta(days=day.weekday())


def _week_range(day):
    monday = _monday(day)
    return [(monday - timedelta(weeks=i)).isoformat() for i in range(WEEKS)]


def model_label(model):
    if re.fullmatch(r"[\w.-]+(?:/[\w.-]+)?", model, flags=re.ASCII) and len(model) <= 120:
        return model
    return "custom"


def usage_field(usage, field):
    value = usage.get(field) if isinstance(usage, dict) else getattr(usage, field, None)
    return value if type(value) is int and 0 <= value <= 2**32 else None


class CallUsage:
    def __init__(self):
        self.input = self.output = self.cached = self.audio = None

    def tokens(self, usage, input_field="prompt_tokens", output_field="completion_tokens"):
        if (count := usage_field(usage, input_field)) is not None:
            self.input = count
        if (count := usage_field(usage, output_field)) is not None:
            self.output = count
        details = getattr(usage, "prompt_tokens_details", None) or getattr(usage, "input_tokens_details", None)
        self.cached = usage_field(details, "cached_tokens")


def measured_call(provider, operation):
    meter = getattr(provider, "usage_meter", None)
    return meter.call(operation) if meter else _unmetered()


@contextmanager
def _unmetered():
    yield CallUsage()


def _rates(provider, model, endpoint):
    # USD list prices. Unknown models, hosts and plans have no default rate.
    if provider == "openai":
        if model == "whisper-1":
            return (0.006 / 60,)
        if model in {"gpt-4.1-mini", "gpt-4.1-mini-2025-04-14"}:
            return 0.40, 1.60, 0.10
        if model == "gpt-6-luna":
            return 0.10, 0.50, 0.01
    if provider == "minimax" and model == "MiniMax-M3.1-Flash":
        return 0.15, 0.60, 0.015
    if provider == "dashscope":
        host = urlsplit(endpoint).hostname or ""
        singapore = host == "dashscope-intl.aliyuncs.com" or host.endswith(".ap-southeast-1.maas.aliyuncs.com")
        beijing = host == "dashscope.aliyuncs.com" or host.endswith(".cn-beijing.maas.aliyuncs.com")
        if singapore or beijing:
            prices = {
                "qwen-audio-3.0-asr-flash": ((0.000035,), (0.00003,)),
                "qwen-audio-3.1-asr-flash": ((0.15, 0.47), (0.113, 0.382)),
                "qwen-mt-flash": ((0.16, 0.49), (0.101, 0.280)),
                "qwen-mt-lite": ((0.12, 0.36), (0.086, 0.229)),
                "qwen-mt-plus": ((2.46, 7.37), (0.259, 0.775)),
            }
            if model in prices:
                return prices[model][0 if singapore else 1]
    return ()


def _estimate(rates, usage):
    if len(rates) == 1 and usage.audio is not None:
        return rates[0] * usage.audio
    if len(rates) >= 2 and usage.input is not None and usage.output is not None:
        cached = min(usage.input, usage.cached or 0) if len(rates) == 3 else 0
        return ((usage.input - cached) * rates[0] + usage.output * rates[1] + cached * rates[-1]) / 1_000_000
    return None


class CloudMeter:
    def __init__(self, store, provider, model, endpoint=""):
        self.store, self.provider, self.model = store, provider, model_label(model)
        self.rates = _rates(provider, model, endpoint)

    @contextmanager
    def call(self, operation):
        day = self.store.today()
        usage = CallUsage()
        failed = True
        try:
            yield usage
            failed = False
        finally:
            cost = _estimate(self.rates, usage)
            self.store.record(day, self.provider, self.model, operation, failed, usage, cost)


def _today():
    return datetime.now(timezone.utc).date()


class CloudUsage:
    def __init__(self, root, today=_today):
        self.path = Path(root) / USAGE_DB
        self.today = today
        self.lock = Lock()
        self.db = None
        self.closed = False
        self.incomplete = False
        self.pruned_for = None
        with self.lock:
            try:
                if self.path.exists():
                    with self._connection() as db:
                        week = self._prune(db)
                    self.pruned_for = week
            except (sqlite3.Error, OSError):
                self.incomplete = True

    def _connection(self):
        if self.db is None:
            db = sqlite3.connect(self.path, timeout=0.2, check_same_thread=False)
            try:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA synchronous=NORMAL")
                db.execute(_TABLE)
            except sqlite3.Error:
                db.close()
                raise
            self.db = db
        return self.db

    def _prune(self, db):
        weeks = _week_range(self.today())
        if self.pruned_for != weeks[0]:
            db.execute("DELETE FROM weekly WHERE week < ?", (weeks[-1],))
        return weeks[0]

    def record(self, day, provider, model, operation, failed, usage, cost):
        with self.lock:
            if self.closed:
                return
            try:
                with self._connection() as db:
                    week = self._prune(db)
                    db.execute("INSERT INTO weekly VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                               "ON CONFLICT(week, provider, model, operation) DO UPDATE SET " +
                               ", ".join(f"{key} = {key} + excluded.{key}" for key in _COUNTS),
                               (_monday(day).isoformat(), provider, model, operation, 1, int(failed),
                                usage.input or 0, usage.output or 0, usage.audio or 0,
                                int(cost is not None), cost or 0))
                self.pruned_for = week
            except (sqlite3.Error, OSError):
                self.incomplete = True

    def snapshot(self):
        with self.lock:
            snapshot = read_usage(self.path, self.today())
            snapshot["incomplete"] |= self.incomplete
            return snapshot

    def close(self):
        with self.lock:
            self.closed = True
            if self.db is not None:
                self.db.close()
                self.db = None


def read_usage(path, day=None):
    weeks = _week_range(day or _today())
    result = {"weeks": weeks, "rows": [], "incomplete": False}
    try:
        if path.exists():
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.2)) as db:
                rows = db.execute("SELECT * FROM weekly WHERE week BETWEEN ? AND ? "
                                  "ORDER BY week DESC, calls DESC, provider, model, operation",
                                  (weeks[-1], weeks[0]))
                result["rows"] = [dict(zip(_FIELDS, row)) for row in rows]
    except (sqlite3.Error, OSError):
        result["incomplete"] = True
    return result
