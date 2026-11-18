"""Durable file transcription on the relay's scheduler and chunk store."""

import errno
import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import stat
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ..inference.audio import SAMPLE_RATE, make_wav
from ..inference.errors import provider_error
from ..inference.segmentation import quiet_boundary


MAX_INPUTS = 8
MAX_INPUT_BYTES = 512_000_000
MAX_TERMINAL_JOBS = 100
RETENTION_SECONDS = 24 * 60 * 60
STORAGE_RETRY_SECONDS = 5
MODEL = "aheadsubs"
READY_STATES = {"queued", "running"}
RESUMABLE_STATES = {"failed", "cancelled"}
ERRORS = {
    "transcription_unavailable": (409, "This service profile has no transcription backend"),
    "transcription_cache_in_use": (503, "Another service owns transcription for this cache"),
    "transcription_stopping": (503, "The transcription service is stopping"),
    "job_not_found": (404, "Transcription job not found"),
    "job_not_ready": (409, "Transcription has not completed"),
    "job_not_active": (409, "Transcription job is no longer active"),
    "job_not_resumable": (409, "Transcription job cannot be resumed"),
    "job_busy": (409, "Wait for the cancelled chunk to finish before resuming"),
    "input_unavailable": (409, "Transcription input is unavailable"),
    "profile_changed": (409, "Restore the job's recognition profile before resuming"),
    "queue_full": (429, "The transcription queue or its input storage is full"),
    "invalid_language": (400, "Invalid language hint"),
    "processing_failed": (502, "The recognition backend did not return valid segments"),
}


class TranscriptionError(ValueError):
    def __init__(self, code, status=None, message=None):
        self.code = code
        default_status, default_message = ERRORS.get(code, (400, "Invalid transcription request"))
        self.status = default_status if status is None else status
        super().__init__(default_message if message is None else message)


def acquire_queue_lock(path):
    # Keep the lock file in place. Closing the handle releases the lock even after a crash.
    handle = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
            raise
        return None
    return handle


def transcribe_chunk(path, index, chunk, recognizer, segmenter):
    """Return source text and recognizer times on the normalized input timeline."""
    size = round(chunk * SAMPLE_RATE)
    start = index * size
    radius = min(SAMPLE_RATE * 3 // 4, size // 4) if segmenter and segmenter.settings.enabled else 0
    context = radius + SAMPLE_RATE // 100 if radius else 0
    with wave.open(str(path), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, SAMPLE_RATE):
            raise TranscriptionError("input_unavailable")
        total = audio.getnframes()
        if start >= total:
            return []
        stop = min(start + size, total)
        read_start = max(0, start - context)
        audio.setpos(read_start)
        pcm = audio.readframes(min(total, stop + context) - read_start)
    first, last = start - read_start, stop - read_start
    if radius:
        # Adjacent work windows share a quiet cut computed around the same sample.
        # Plan VAD spans only inside the owned window, so retries cannot shift ownership.
        def cut(nominal):
            return quiet_boundary(pcm, max(0, nominal - radius), min(len(pcm) // 2, nominal + radius),
                                  preferred=nominal)

        first = cut(first) if start else first
        last = cut(last) if stop < total else last
    pcm = pcm[first * 2:last * 2]
    if not pcm or not pcm.strip(b"\x00"):
        return []
    base_start = (read_start + first) / SAMPLE_RATE
    wav = make_wav(pcm)
    segments = []
    spans = segmenter.iter_spans(wav) if segmenter else ((0, wav),)
    for offset, speech in spans:
        base = base_start + offset
        for cue in recognizer(speech):
            if not cue.text.strip():
                continue
            if not math.isfinite(cue.start) or not math.isfinite(cue.end) or not 0 <= cue.start < cue.end:
                raise TranscriptionError("processing_failed")
            segment = {"start": base + cue.start, "end": base + cue.end, "text": cue.text}
            if cue.source_language and cue.source_language.lower() not in {"auto", "und", "unknown"}:
                segment["language"] = cue.source_language
            segments.append(segment)
    return segments


@dataclass(frozen=True)
class TranscriptionChunk:
    id: str
    index: int
    language: str | None

    @property
    def key(self):
        return f"transcription:{self.id}"


class Transcriptions:
    def __init__(self, relay, profile):
        self.relay = relay
        self.db = relay.db
        self.profile = hashlib.sha256(json.dumps(["transcription-v2", profile, relay.chunk],
                                                 sort_keys=True).encode()).hexdigest()
        self.upload_directory = relay.root / "transcription-staging"
        self.inputs = relay.root / "transcription-inputs"
        self.inflight = None
        self.pending_finish = None
        self.storage_retry_at = 0
        self.next_maintenance = 0
        self.purge_inputs = set()
        self.lease = acquire_queue_lock(relay.root / "transcription.lock")
        if self.lease is not None:
            try:
                self._initialize()
            except BaseException:
                self.lease.close()
                raise

    def _initialize(self):
        for directory in (self.upload_directory, self.inputs):
            directory.mkdir(mode=0o700, exist_ok=True)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS transcription_jobs (
                id TEXT PRIMARY KEY, cache_key TEXT NOT NULL, profile TEXT NOT NULL,
                state TEXT NOT NULL, language TEXT, duration REAL NOT NULL,
                next_index INTEGER NOT NULL, total_chunks INTEGER NOT NULL,
                input_bytes INTEGER NOT NULL, ephemeral INTEGER NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL, error_code TEXT
            );
            CREATE INDEX IF NOT EXISTS transcription_state ON transcription_jobs(state, created);
        """)
        for (identifier,) in list(self.db.execute("SELECT id FROM transcription_jobs WHERE ephemeral OR state='discarded'")):
            self._delete(identifier)
        with self.db:
            self.db.execute("UPDATE transcription_jobs SET state='queued' WHERE state='running'")
        retained = {identifier for (identifier,) in self.db.execute(
            "SELECT id FROM transcription_jobs WHERE input_bytes > 0")}
        for path in self.inputs.glob("*.wav"):
            if re.fullmatch(r"[0-9a-f]{32}", path.stem) and path.stem not in retained:
                self.purge_inputs.add(path.stem)
        for path in self.upload_directory.iterdir():
            if path.suffix in {".upload", ".wav"}:
                try:
                    path.unlink()
                except OSError:
                    logging.getLogger(__name__).warning("Could not remove a staged transcription upload")
        self.maintain()

    def capabilities(self):
        available = (self.lease is not None and not self.lease.closed
                     and self.relay.recognizer is not None and not self.relay.stopping.is_set())
        return {"available": available, "model": MODEL if available else None,
                "task": "transcribe", "segment_timestamps": available,
                "response_formats": ["json", "text"] if available else [],
                "queue": {"max_inputs": MAX_INPUTS, "max_input_bytes": MAX_INPUT_BYTES,
                          "retention_seconds": RETENTION_SECONDS, "max_terminal_jobs": MAX_TERMINAL_JOBS}}

    def _input(self, identifier):
        return self.inputs / f"{identifier}.wav"

    def _row(self, identifier):
        self._require_queue()
        cursor = self.db.execute("SELECT * FROM transcription_jobs WHERE id=? AND state!='discarded'", (identifier,))
        cursor.row_factory = sqlite3.Row
        row = cursor.fetchone()
        if row is None:
            raise TranscriptionError("job_not_found")
        return row

    def _status(self, row):
        return {"id": row["id"], "state": row["state"], "duration": row["duration"],
                "language": row["language"], "completed_chunks": row["next_index"],
                "total_chunks": row["total_chunks"], "error_code": row["error_code"]}

    def _require_queue(self):
        if self.relay.stopping.is_set():
            raise TranscriptionError("transcription_stopping")
        if self.lease is None:
            raise TranscriptionError("transcription_cache_in_use")

    def require_backend(self):
        self._require_queue()
        if self.relay.recognizer is None:
            raise TranscriptionError("transcription_unavailable")

    def submit(self, path: Path, duration: float, language: str | None, *, ephemeral=False):
        if language and language.lower() != "auto":
            if not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*", language) or len(language) > 32:
                raise TranscriptionError("invalid_language")
            language = language.lower()
        else:
            language = None
        if not math.isfinite(duration) or duration <= 0:
            raise TranscriptionError("input_unavailable")
        if path.parent != self.upload_directory or path.suffix != ".wav":
            raise TranscriptionError("input_unavailable")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise TranscriptionError("input_unavailable")
        size = info.st_size
        with self.relay.lock:
            self.require_backend()
            # A completed or discarded input still occupies space if deletion was blocked.
            retained = [entry.lstat().st_size for entry in self.inputs.glob("*.wav")
                        if re.fullmatch(r"[0-9a-f]{32}", entry.stem)]
            if len(retained) >= MAX_INPUTS or sum(retained) + size > MAX_INPUT_BYTES:
                raise TranscriptionError("queue_full")
            identifier = uuid4().hex
            destination = self._input(identifier)
            now = time.time()
            path.replace(destination)
            try:
                with self.db:
                    self.db.execute("INSERT INTO transcription_jobs VALUES (?, ?, ?, 'queued', ?, ?, 0, ?, ?, ?, ?, ?, NULL)",
                                    (identifier, TranscriptionChunk(identifier, 0, language).key, self.profile,
                                     language, duration, math.ceil(duration / self.relay.chunk), size,
                                     ephemeral, now, now))
            except Exception:
                self._purge_input(identifier)
                raise
            return self._status(self._row(identifier))

    def status(self, identifier):
        with self.relay.lock:
            return self._status(self._row(identifier))

    def result(self, identifier):
        with self.relay.lock:
            row = self._row(identifier)
            if row["state"] != "completed":
                raise TranscriptionError("job_not_ready")
            chunks = list(self.db.execute("SELECT cues FROM chunks WHERE key=? ORDER BY idx", (row["cache_key"],)))
        segments = sorted((segment for (encoded,) in chunks for segment in json.loads(encoded)),
                          key=lambda segment: (segment["start"], segment["end"]))
        return {"duration": row["duration"], "segments": segments,
                "text": " ".join(segment["text"].strip() for segment in segments)}

    def _set_state(self, identifier, state, error_code=None):
        self.db.execute("UPDATE transcription_jobs SET state=?, error_code=?, updated=? WHERE id=?",
                        (state, error_code, time.time(), identifier))

    def cancel(self, identifier):
        with self.relay.lock, self.db:
            row = self._row(identifier)
            if row["state"] == "cancelled":
                return self._status(row)
            if row["state"] not in READY_STATES:
                raise TranscriptionError("job_not_active")
            self._set_state(identifier, "cancelled")
            return self._status(self._row(identifier))

    def resume(self, identifier):
        with self.relay.lock, self.db:
            self.require_backend()
            row = self._row(identifier)
            if row["state"] not in RESUMABLE_STATES:
                raise TranscriptionError("job_not_resumable")
            if self.inflight == identifier:
                raise TranscriptionError("job_busy")
            if row["profile"] != self.profile:
                raise TranscriptionError("profile_changed")
            if not self._input(identifier).is_file():
                raise TranscriptionError("input_unavailable")
            self._set_state(identifier, "queued")
            return self._status(self._row(identifier))

    def discard(self, identifier):
        with self.relay.lock:
            self._row(identifier)
            if self.inflight == identifier:
                with self.db:
                    self._set_state(identifier, "discarded")
            else:
                self._delete(identifier)

    def _delete(self, identifier):
        with self.db:
            self.db.execute("DELETE FROM chunks WHERE key=(SELECT cache_key FROM transcription_jobs WHERE id=?)",
                            (identifier,))
            self.db.execute("DELETE FROM transcription_jobs WHERE id=?", (identifier,))
        self._purge_input(identifier)

    def _purge_input(self, identifier):
        try:
            self._input(identifier).unlink(missing_ok=True)
        except OSError:
            self.purge_inputs.add(identifier)
            logging.getLogger(__name__).warning("Could not remove a retained transcription input")
        else:
            self.purge_inputs.discard(identifier)

    def maintain(self):
        if self.lease is None or time.monotonic() < self.storage_retry_at:
            return
        if self.pending_finish is not None:
            self.finish(*self.pending_finish)
            if self.pending_finish is not None:
                return
        try:
            self._prune_expired()
        except sqlite3.Error as exc:
            self._delay_storage(exc)

    def _delay_storage(self, exc):
        self.storage_retry_at = time.monotonic() + STORAGE_RETRY_SECONDS
        logging.getLogger(__name__).warning("Transcription storage retry scheduled (%s)", type(exc).__name__)

    def _prune_expired(self):
        now = time.time()
        if now < self.next_maintenance:
            return
        for identifier in tuple(self.purge_inputs):
            self._purge_input(identifier)
        expired = list(self.db.execute("""
            SELECT id FROM transcription_jobs WHERE state IN ('completed', 'failed', 'cancelled')
                AND (updated <= ? OR id IN (
                    SELECT id FROM transcription_jobs WHERE state IN ('completed', 'failed', 'cancelled')
                    ORDER BY updated DESC LIMIT -1 OFFSET ?))
            """, (now - RETENTION_SECONDS, MAX_TERMINAL_JOBS)))
        for (identifier,) in expired:
            if identifier != self.inflight:
                self._delete(identifier)
        self.next_maintenance = now + 60

    def next_chunk(self):
        if (self.lease is None or self.relay.recognizer is None or self.inflight is not None
                or time.monotonic() < self.storage_retry_at):
            return None
        try:
            return self._claim_chunk()
        except sqlite3.Error as exc:
            self._delay_storage(exc)
            return None

    def _claim_chunk(self):
        job = self.db.execute("""
            SELECT id, next_index, language, profile FROM transcription_jobs
            WHERE state IN ('running', 'queued') ORDER BY state='running' DESC, updated, id LIMIT 1
            """).fetchone()
        if job is None:
            return None
        identifier, index, language, profile = job
        with self.db:
            if profile != self.profile:
                self._set_state(identifier, "failed", "profile_changed")
                return None
            if not self._input(identifier).is_file():
                self._set_state(identifier, "failed", "input_unavailable")
                return None
            self._set_state(identifier, "running")
        self.inflight = identifier
        return TranscriptionChunk(identifier, index, language)

    def process(self, task):
        def recognize(wav):
            _, cues = self.relay.recognizer.recognize(wav, task.language)
            return cues

        return transcribe_chunk(self._input(task.id), task.index, self.relay.chunk, recognize, self.relay.segmenter)

    def finish(self, task, future):
        try:
            self._persist_result(task, future)
        except sqlite3.Error as exc:
            # Retry the same completed chunk when SQLite is writable again.
            self.pending_finish = task, future
            self._delay_storage(exc)
        else:
            self.pending_finish = None
            self.inflight = None

    def _persist_result(self, task, future):
        identifier = task.id
        state, total_chunks = self.db.execute(
            "SELECT state, total_chunks FROM transcription_jobs WHERE id=?", (identifier,)).fetchone()
        if state == "discarded":
            self._delete(identifier)
            return
        if state != "running":
            return
        try:
            segments = future.result()
        except Exception as exc:
            code = exc.code if isinstance(exc, TranscriptionError) else provider_error(exc).kind
            with self.db:
                self._set_state(identifier, "failed", code)
            logging.getLogger(__name__).warning("Transcription chunk failed chunk=%d error=%s type=%s",
                                                task.index, code, type(exc).__name__)
            return
        next_index = task.index + 1
        complete = next_index == total_chunks
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO chunks VALUES (?, ?, ?)",
                            (task.key, task.index, json.dumps(segments, ensure_ascii=False)))
            self.db.execute("UPDATE transcription_jobs SET next_index=? WHERE id=?", (next_index, identifier))
            if complete:
                self._set_state(identifier, "completed")
                self.db.execute("UPDATE transcription_jobs SET input_bytes=0 WHERE id=?", (identifier,))
        if complete:
            self._purge_input(identifier)

    def close(self):
        if self.lease is not None:
            try:
                if self.pending_finish is not None:
                    self.finish(*self.pending_finish)
                for (identifier,) in list(self.db.execute(
                        "SELECT id FROM transcription_jobs WHERE ephemeral OR state='discarded'")):
                    self._delete(identifier)
            except sqlite3.Error as exc:
                self._delay_storage(exc)
            finally:
                self.lease.close()
