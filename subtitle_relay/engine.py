import hashlib
import json
import math
import os
import sqlite3
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from .audio import Segmentation, make_wav
from .providers import Cue, NLLB_LANGUAGES


@dataclass(frozen=True)
class Playback:
    path: Path
    position: float
    audio: int = 0
    speed: float = 1
    duration: float | None = None
    source: str | None = None
    target: str = "zh"
    ahead: float = 20


def extract_audio(path, audio, start, duration):
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(start), "-i", str(path),
         "-map", f"0:a:{audio}", "-t", str(duration), "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1"],
        capture_output=True, timeout=30, check=True,
    )
    return make_wav(result.stdout)


def translate_chunk(playback, index, chunk, recognizer, translator, speech_translator=None,
                    segmenter=None):
    start = index * chunk
    settings = segmenter.settings if segmenter else Segmentation(enabled=False)
    read_start = max(0, start - settings.before)
    wav = extract_audio(playback.path, playback.audio, read_start,
                        start + chunk + settings.after - read_start)
    if len(wav) < 400:
        return []
    translated = []
    for offset, speech in segmenter.spans(wav) if segmenter else [(0, wav)]:
        base = read_start + offset
        if speech_translator:
            cues = speech_translator.speech_translate(speech, playback.source, playback.target)
            language = playback.target
        else:
            language, cues = recognizer.recognize(speech, playback.source)
        end = base + (len(speech) - 44) / 32000
        # Assign overlapping context to a single chunk by the cue midpoint.
        cues = [Cue(max(base, base + cue.start), min(end, base + cue.end), cue.text) for cue in cues
                if start <= base + (cue.start + cue.end) / 2 < start + chunk]
        cues = [cue for cue in cues if cue.end > cue.start]
        source = NLLB_LANGUAGES.get(language, language)
        target = NLLB_LANGUAGES.get(playback.target, playback.target)
        if cues and not speech_translator and source != target:
            texts = translator.translate([cue.text for cue in cues], language, playback.target)
            if len(texts) != len(cues) or any(not isinstance(s, str) or not s.strip() for s in texts):
                raise ValueError("Translation returned incomplete subtitle lines")
            cues = [Cue(cue.start, cue.end, text, cue.text)
                    for cue, text in zip(cues, texts, strict=True)]
        translated.extend(cues)
    return translated


def srt_time(seconds):
    seconds, ms = divmod(max(0, round(seconds * 1000)), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"


@dataclass
class Session:
    playback: Playback
    key: str
    updated: float


def merge_cues(cues):
    ordered = sorted(cues, key=lambda cue: (cue.start, cue.end))
    merged = []
    for cue in ordered:
        if merged:
            previous = merged[-1]
            overlap = min(previous.end, cue.end) - max(previous.start, cue.start)
            shorter = min(previous.end - previous.start, cue.end - cue.start)
            previous_text = "".join(c for c in (previous.original or previous.text).casefold() if c.isalnum())
            next_text = "".join(c for c in (cue.original or cue.text).casefold() if c.isalnum())
            if overlap > 0 and overlap >= shorter * 0.65 and previous_text and (
                previous_text in next_text or next_text in previous_text
            ):
                if len(next_text) > len(previous_text) or cue.end - cue.start > previous.end - previous.start:
                    merged[-1] = cue
                continue
        merged.append(cue)
    return merged


class Relay:
    def __init__(self, root, recognizer, translator, profile, workers=4, chunk=8,
                 speech_translator=None, segmenter=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.recognizer, self.translator = recognizer, translator
        self.speech_translator = speech_translator
        self.segmenter = segmenter
        self.profile, self.workers, self.chunk = profile, workers, chunk
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / "cache.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS chunks (key TEXT, idx INTEGER, cues TEXT, "
                        "PRIMARY KEY (key, idx))")
        self.db.commit()
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self.sessions = {}
        self.inflight = set()
        self.errors = {}
        self.rendered = {}
        self.stopping = threading.Event()
        self.scheduler = threading.Thread(target=self._run, daemon=True)
        self.scheduler.start()

    def close(self):
        self.stopping.set()
        self.scheduler.join()
        self.pool.shutdown(wait=True)
        self.db.close()

    def _identity(self, playback):
        info = playback.path.stat()
        identity = [self.profile, self.chunk, os.path.normcase(str(playback.path)),
                    info.st_size, info.st_mtime_ns, playback.audio, playback.source, playback.target]
        return hashlib.sha256(json.dumps(identity).encode()).hexdigest()

    def _rows(self, key):
        return self.db.execute("SELECT idx, cues FROM chunks WHERE key=? ORDER BY idx", (key,)).fetchall()

    def _render(self, key, rows):
        path = self.root / f"{key}.srt"
        if not rows:
            return path, 0
        revision = len(rows)
        if self.rendered.get(key) != revision or not path.exists():
            cues = merge_cues(Cue(**cue) for _, data in rows for cue in json.loads(data))
            body = "\n\n".join(f"{index}\n{srt_time(cue.start)} --> {srt_time(cue.end)}\n"
                               + " ".join(cue.text.splitlines())
                               for index, cue in enumerate(cues, 1))
            temp = path.with_suffix(f".{os.getpid()}.tmp")
            temp.write_text(body + "\n", encoding="utf-8")
            os.replace(temp, path)
            self.rendered[key] = revision
        return path, revision

    def update(self, identifier, playback):
        key = self._identity(playback)
        with self.lock:
            self.sessions[identifier] = Session(playback, key, time.monotonic())
            rows = self._rows(key)
            path, revision = self._render(key, rows)
            completed = {idx for idx, _ in rows}
            index = int(playback.position // self.chunk)
            error = self.errors.get((key, index))
            while index in completed:
                index += 1
            end = min(index * self.chunk, playback.duration or math.inf)
            return {"revision": revision, "subtitle": str(path) if revision else None,
                    "ready_ahead": max(0, end - playback.position),
                    "error": error[1] if error else None}

    def drop(self, identifier):
        with self.lock:
            self.sessions.pop(identifier, None)

    def _run(self):
        while not self.stopping.wait(0.1):
            with self.lock:
                self._schedule()

    def _schedule(self):
        now = time.monotonic()
        self.sessions = {name: s for name, s in self.sessions.items() if now - s.updated < 10}
        candidates = {}
        for session in self.sessions.values():
            playback, key = session.playback, session.key
            done = {idx for idx, _ in self._rows(key)}
            first = int(playback.position // self.chunk)
            backfill = self.segmenter.settings.backfill if self.segmenter else 0
            earliest = int(max(0, playback.position - backfill) // self.chunk)
            end = min(playback.position + playback.ahead * max(1, playback.speed),
                      playback.duration or math.inf)
            for index in range(earliest, math.ceil(end / self.chunk)):
                job = (key, index)
                if index not in done and job not in self.inflight and self.errors.get(job, (0,))[0] <= now:
                    distance = (index - first) * self.chunk / playback.speed if index >= first else 0.5
                    if job not in candidates or distance < candidates[job][0]:
                        candidates[job] = (distance, playback)
        for job in sorted(candidates, key=lambda job: candidates[job][0]):
            if len(self.inflight) >= self.workers:
                break
            self.inflight.add(job)
            future = self.pool.submit(translate_chunk, candidates[job][1], job[1], self.chunk,
                                      self.recognizer, self.translator, self.speech_translator, self.segmenter)
            future.add_done_callback(lambda result, job=job: self._finish(job, result))

    def _finish(self, job, future):
        with self.lock:
            try:
                encoded = json.dumps([asdict(cue) for cue in future.result()], ensure_ascii=False)
                self.db.execute("INSERT OR REPLACE INTO chunks VALUES (?, ?, ?)", (*job, encoded))
                self.db.commit()
                self.errors.pop(job, None)
            except Exception as exc:
                # Provider exceptions can include request material. Return only the exception type/status.
                status = getattr(exc, "status_code", None)
                self.errors[job] = (time.monotonic() + 15, f"{type(exc).__name__} ({status})" if status
                                    else type(exc).__name__)
            finally:
                self.inflight.remove(job)
