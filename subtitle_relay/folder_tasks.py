"""Persistent folder rules and a single idle subtitle worker."""
import json
import logging
import os
import re
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
from contextlib import closing, contextmanager
from pathlib import Path

import regex
from pydantic import Field, field_validator, model_validator

from .automation import Arguments, Generation, MediaPath, OperationError, generate_subtitles
from .server.protocol import playback_from_json


DEFAULT_EXTENSIONS = "mkv, mp4, mov, avi, webm, m4v, ts, mp3, m4a, wav, flac, ogg, opus"
SCAN_SECONDS = 10
STABLE_SECONDS = 10
MAX_RULES = 50


class WatchRule(Arguments):
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    name: str = Field("", max_length=80)
    folder: MediaPath
    enabled: bool = True
    recursive: bool = False
    include_existing: bool = False
    pattern: str = Field("", max_length=512)
    extensions: str = Field(DEFAULT_EXTENSIONS, min_length=1, max_length=300)
    min_bytes: int = Field(0, ge=0, le=2**53)
    max_bytes: int | None = Field(None, ge=1, le=2**53)
    source: str | None = Field(None, pattern=r"^(auto|[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*)$", max_length=32)
    target: str | None = Field(None, pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$", max_length=32)
    audio: int = Field(0, ge=0, le=255)
    bilingual: bool | None = None
    suffix: str = Field("", pattern=r"^(?:[._-][A-Za-z0-9_-][A-Za-z0-9._-]{0,62})?$", max_length=64)
    destination: MediaPath | None = None
    idle_minutes: int = Field(0, ge=0, le=120)

    @field_validator("folder", "destination")
    @classmethod
    def absolute_path(cls, value):
        if value is not None and ("\x00" in value or not Path(value).is_absolute()):
            raise ValueError("absolute path required")
        return None if value is None else str(Path(value))

    @field_validator("pattern")
    @classmethod
    def valid_regex(cls, value):
        try:
            regex.compile(value, regex.IGNORECASE)
        except regex.error as exc:
            raise ValueError("invalid regex") from exc
        return value

    @field_validator("extensions")
    @classmethod
    def valid_extensions(cls, value):
        extensions = re.split(r"[,;\s]+", value.strip())
        if not all(re.fullmatch(r"\.?[A-Za-z0-9]{1,16}", item) and item.lower().lstrip(".") != "srt"
                   for item in extensions):
            raise ValueError("invalid extensions")
        return ", ".join(dict.fromkeys(item.lower().lstrip(".") for item in extensions))

    @model_validator(mode="after")
    def valid_sizes(self):
        if self.max_bytes is not None and self.max_bytes < self.min_bytes:
            raise ValueError("invalid size range")
        return self


class RuleSet(Arguments):
    rules: list[WatchRule] = Field(default_factory=list, max_length=MAX_RULES)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({rule.id for rule in self.rules}) != len(self.rules):
            raise ValueError("duplicate rule ID")
        return self


def fingerprint(info):
    return f"{info.st_size}:{info.st_mtime_ns}:{info.st_ctime_ns}:{info.st_ino}"


def media_files(rule, check_stop):
    extensions = {f".{ext}" for ext in rule.extensions.split(", ")}
    pattern = regex.compile(rule.pattern, regex.IGNORECASE) if rule.pattern else None
    folders = [Path(rule.folder)]
    while folders:
        with os.scandir(folders.pop()) as entries:
            for entry in entries:
                check_stop()
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0) if rule.recursive else 0
                    if rule.recursive and not attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                        folders.append(Path(entry.path))
                    continue
                if Path(entry.name).suffix.lower() not in extensions:
                    continue
                try:
                    info = Path(entry.path).lstat()
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(info.st_mode) or info.st_size <= 0 or info.st_size < rule.min_bytes:
                    continue
                if rule.max_bytes is not None and info.st_size > rule.max_bytes:
                    continue
                if pattern is None or pattern.search(entry.name, timeout=0.02):
                    yield entry.path, fingerprint(info)


class TaskFiles:
    def __init__(self, directory):
        self.directory = directory
        self.settings = directory / "folder-tasks.json"
        self.database = directory / "folder-tasks.sqlite3"

    def load(self):
        try:
            return RuleSet.model_validate_json(self.settings.read_bytes())
        except FileNotFoundError:
            return RuleSet()

    def save(self, config):
        self.directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=self.directory, delete=False) as staged:
            path = Path(staged.name)
        try:
            path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
            path.replace(self.settings)
        finally:
            path.unlink(missing_ok=True)

    @contextmanager
    def connect(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS rules (id TEXT PRIMARY KEY, folder TEXT, output_key TEXT, issue TEXT);
                CREATE TABLE IF NOT EXISTS jobs (
                    rule TEXT, path TEXT, fingerprint TEXT, noticed REAL, state TEXT, issue TEXT,
                    PRIMARY KEY (rule, path)
                );
                CREATE INDEX IF NOT EXISTS jobs_state ON jobs (rule, state, noticed);
            """)
            yield db

    def status(self):
        config = self.load()
        summary = {}
        if self.database.exists():
            with self.connect() as db:
                for rule in config.rules:
                    row = db.execute("SELECT issue FROM rules WHERE id=?", (rule.id,)).fetchone()
                    counts = dict(db.execute("SELECT state, count(*) FROM jobs WHERE rule=? GROUP BY state", (rule.id,)))
                    entries = db.execute("""SELECT path, state, issue FROM jobs WHERE rule=?
                        AND state IN ('running', 'failed', 'skipped')
                        ORDER BY state='running' DESC, state='failed' DESC, noticed DESC LIMIT 10""", (rule.id,))
                    summary[rule.id] = {"issue": row[0] if row else None, "counts": counts,
                                        "items": [dict(path=p, state=s, issue=i) for p, s, i in entries]}
        return {"rules": config.model_dump()["rules"], "summary": summary}

    def retry(self, identifier):
        with self.connect() as db, db:
            db.execute("UPDATE jobs SET state='waiting', issue=NULL WHERE rule=? AND state='failed'", (identifier,))


class Deferred(Exception):
    """Leave work queued after playback, a settings change, or shutdown."""


class BackgroundPlayback:
    def __init__(self, relay, defaults):
        self.relay = relay
        self.defaults = defaults

    def send(self, route, data, *, timeout=5):
        if route == "close":
            self.relay.drop(data["session"])
            return {}
        try:
            playback = playback_from_json(data, self.defaults)
            result = self.relay.update_background(data["session"], playback)
        except FileNotFoundError as exc:
            raise Deferred from exc
        if result is None:
            raise Deferred
        return result


class FolderWorker:
    def __init__(self, files, relay, defaults, idle_seconds):
        self.files = files
        self.client = BackgroundPlayback(relay, defaults)
        self.idle_seconds = idle_seconds
        self.stopping = threading.Event()

    @contextmanager
    def running(self):
        worker = threading.Thread(target=self.run, name="FolderSubtitleTasks", daemon=True)
        worker.start()
        try:
            yield
        finally:
            self.stopping.set()
            worker.join()

    def check_stop(self):
        if self.stopping.is_set():
            raise Deferred

    def scan(self, db, rule, now):
        initialized = db.execute("SELECT folder, output_key FROM rules WHERE id=?", (rule.id,)).fetchone()
        output_key = rule.model_dump_json(include={"source", "target", "audio", "bilingual", "destination", "suffix"})
        try:
            db.execute("CREATE TEMP TABLE IF NOT EXISTS found (path TEXT PRIMARY KEY, fingerprint TEXT)")
            with db:
                db.execute("DELETE FROM found")
                db.executemany("INSERT INTO found VALUES (?, ?)", media_files(rule, self.check_stop))
                fresh = not initialized or initialized[0] != rule.folder
                if fresh:
                    db.execute("DELETE FROM jobs WHERE rule=?", (rule.id,))
                elif initialized[1] != output_key:
                    db.execute("UPDATE jobs SET state='settling', issue=NULL WHERE rule=? AND state!='ignored'", (rule.id,))
                if rule.include_existing:
                    db.execute("UPDATE jobs SET state='settling' WHERE rule=? AND state='ignored'", (rule.id,))
                initial_state = "ignored" if fresh and not rule.include_existing else "settling"
                db.execute("""UPDATE jobs SET state='waiting' WHERE rule=? AND state='settling' AND noticed<=?
                    AND fingerprint=(SELECT fingerprint FROM found WHERE found.path=jobs.path)""",
                           (rule.id, now - STABLE_SECONDS))
                db.execute("""INSERT INTO jobs SELECT ?, path, fingerprint, ?, ?, NULL FROM found WHERE true
                    ON CONFLICT(rule, path) DO UPDATE SET fingerprint=excluded.fingerprint,
                    noticed=excluded.noticed, state='settling', issue=NULL
                    WHERE jobs.fingerprint != excluded.fingerprint""", (rule.id, now, initial_state))
                db.execute("DELETE FROM jobs WHERE rule=? AND path NOT IN (SELECT path FROM found)", (rule.id,))
                db.execute("INSERT OR REPLACE INTO rules VALUES (?, ?, ?, NULL)", (rule.id, rule.folder, output_key))
        except (OSError, TimeoutError) as exc:
            issue = "regex_timeout" if isinstance(exc, TimeoutError) else "folder_unavailable"
            with db:
                # A failed initial scan must not establish the baseline.
                db.execute("""INSERT INTO rules VALUES (?, NULL, NULL, ?)
                    ON CONFLICT(id) DO UPDATE SET issue=excluded.issue""", (rule.id, issue))

    def available(self, rule):
        return (not self.stopping.is_set() and self.client.relay.background_idle()
                and (rule.idle_minutes == 0 or self.idle_seconds() >= 60 * rule.idle_minutes))

    def run_job(self, rule, path, expected):
        def checkpoint():
            if not self.available(rule) or rule not in self.files.load().rules:
                raise Deferred
            try:
                current = path.lstat()
            except FileNotFoundError as exc:
                raise Deferred from exc
            if not stat.S_ISREG(current.st_mode) or fingerprint(current) != expected:
                raise Deferred

        checkpoint()
        if not path.resolve().is_relative_to(Path(rule.folder).resolve()):
            raise OperationError("invalid_media")
        name = path.stem + rule.suffix + ".srt"
        output = path.with_name(name)
        if rule.destination:
            root = Path(rule.destination).resolve(strict=True)
            parent = (root / path.parent.relative_to(rule.folder)).resolve()
            if not parent.is_relative_to(root):
                raise OperationError("invalid_output")
            parent.mkdir(parents=True, exist_ok=True)
            output = parent / name
        options = {"audio": rule.audio}
        options.update({key: getattr(rule, key) for key in ("source", "target", "bilingual")
                        if getattr(rule, key) is not None})
        generate_subtitles(self.client, Generation(path=str(path), output=str(output), timeout=86400, **options), checkpoint)

    def next_job(self, db, rules):
        suitable = {rule.id: rule for rule in rules if rule.enabled and self.available(rule)}
        if not suitable:
            return False
        placeholders = ",".join("?" for _ in suitable)
        row = db.execute(f"""SELECT jobs.rule, path, fingerprint FROM jobs JOIN rules ON rules.id=jobs.rule
            WHERE jobs.rule IN ({placeholders}) AND state='waiting' AND rules.issue IS NULL
            ORDER BY noticed, jobs.rule, path LIMIT 1""", tuple(suitable)).fetchone()
        if row is None:
            return False
        identifier, path, signature = row
        rule = suitable[identifier]

        def set_state(state, issue=None):
            with db:
                db.execute("UPDATE jobs SET state=?, issue=? WHERE rule=? AND path=?", (state, issue, identifier, path))

        set_state("running")
        try:
            self.run_job(rule, Path(path), signature)
        except Deferred:
            set_state("waiting")
        except FileExistsError:
            set_state("skipped", "output_exists")
        except OperationError as exc:
            set_state("failed", exc.code)
        except (TimeoutError, subprocess.TimeoutExpired):
            set_state("failed", "request_timeout")
        except (OSError, ValueError, sqlite3.Error):
            set_state("failed", "operation_failed")
        else:
            set_state("done")
        return True

    def run(self):
        next_scan = 0
        previous = None
        try:
            with self.files.connect() as db:
                with db:
                    db.execute("UPDATE jobs SET state='waiting' WHERE state='running'")
                while not self.stopping.is_set():
                    try:
                        config = self.files.load()
                        if time.monotonic() >= next_scan or config != previous:
                            self.scan_rules(db, config.rules, time.time())
                            previous = config
                            next_scan = time.monotonic() + SCAN_SECONDS
                        self.next_job(db, config.rules)
                    except (OSError, ValueError, sqlite3.Error) as exc:
                        logging.getLogger(__name__).warning("Folder tasks unavailable (%s)", type(exc).__name__)
                    self.stopping.wait(1)
        except Deferred:
            pass
        except (OSError, sqlite3.Error) as exc:
            logging.getLogger(__name__).warning("Folder task store unavailable (%s)", type(exc).__name__)

    def scan_rules(self, db, rules, now):
        with db:
            known = {identifier for (identifier,) in db.execute("SELECT id FROM rules")}
            removed = known - {rule.id for rule in rules}
            db.executemany("DELETE FROM jobs WHERE rule=?", ((identifier,) for identifier in removed))
            db.executemany("DELETE FROM rules WHERE id=?", ((identifier,) for identifier in removed))
        for rule in rules:
            if rule.enabled:
                self.scan(db, rule, now)
