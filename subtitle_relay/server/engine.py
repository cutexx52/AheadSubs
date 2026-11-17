import hashlib
import json
import logging
import math
import os
import sqlite3
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from itertools import groupby
from pathlib import Path

from ..inference.audio import Segmentation, make_wav
from ..inference.errors import provider_error
from ..inference.providers import Cue, NLLB_LANGUAGES
from ..inference.recognition_cache import RecognitionCache
from .history import create_history, remember_failed_cues, remember_media


BILINGUAL_SUFFIX = "-bilingual-v2"
SUBTITLE_LABELS = {
    "ja": "JP", "jpn": "JP", "ko": "KR", "kor": "KR", "en": "EN", "eng": "EN",
    "zh": "CN", "zho": "CN", "zh-cn": "CN", "zh-hans": "CN",
    "zh-tw": "TW", "zh-hant": "TW", "zho-hant": "TW",
}


def subtitle_label(language, fallback):
    if not language or language.casefold() in {"auto", "und"}:
        return fallback
    code = language.lower().replace("_", "-")
    base = code.split("-")[0]
    if not (2 <= len(base) <= 3 and base.isascii() and base.isalpha()):
        return fallback
    return SUBTITLE_LABELS.get(code, SUBTITLE_LABELS.get(base, base.upper()))


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
    bilingual: bool = False


@dataclass(frozen=True)
class TranslationSettings:
    before: float = 0.0
    after: float = 0.0
    prompt: str = ""

    def __post_init__(self):
        if not (0 <= self.before <= 15 and 0 <= self.after <= 15):
            raise ValueError("Translation context must be between 0 and 15 seconds per side")
        if len(self.prompt) > 1000:
            raise ValueError("Translation style guidance must be at most 1000 characters")
        object.__setattr__(self, "before", float(self.before))
        object.__setattr__(self, "after", float(self.after))
        object.__setattr__(self, "prompt", self.prompt.strip())

    def for_translator(self, translator):
        return TranslationSettings(
            self.before if getattr(translator, "supports_neighbor_context", False) else 0,
            self.after if getattr(translator, "supports_neighbor_context", False) else 0,
            self.prompt if getattr(translator, "supports_style_prompt", False) else "",
        )


def extract_audio(path, audio, start, duration):
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(start), "-i", str(path),
         "-map", f"0:a:{audio}", "-t", str(duration), "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1"],
        capture_output=True, timeout=30, check=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    return make_wav(result.stdout)


class TranslationFailure(ValueError):
    """Recognized cues for a batch that could not be translated."""

    def __init__(self, cues):
        super().__init__("Translation failed after speech recognition")
        self.cues = cues


def _translate_cues(cues, translator, language, target, *, previous=(), following=(), prompt=""):
    if not cues or NLLB_LANGUAGES.get(language, language) == NLLB_LANGUAGES.get(target, target):
        return cues
    if len(cues) > 1 and getattr(translator, "per_cue_requests", False) is True:
        return [result for cue in cues
                for result in _translate_cues([cue], translator, language, target, prompt=prompt)]
    lines = [cue.text for cue in cues]
    try:
        if previous or following or prompt:
            texts = translator.translate_with_context(lines, language, target,
                                                      previous=previous, following=following, prompt=prompt)
        else:
            texts = translator.translate(lines, language, target)
        if len(texts) != len(cues) or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("Translation returned incomplete subtitle lines")
    except Exception as exc:
        if provider_error(exc).kind == "content_blocked":
            return [Cue(cue.start, cue.end, "", cue.text, "content_blocked") for cue in cues]
        raise TranslationFailure(cues) from exc
    return [Cue(cue.start, cue.end, text, cue.text, source_language=language)
            for cue, text in zip(cues, texts, strict=True)]


def _context_lines(cues, *, previous=False):
    # Keep the closest complete subtitle lines within a small per-side limit.
    selected = []
    remaining = 1000
    ordered = reversed(cues) if previous else iter(cues)
    for cue in ordered:
        if len(selected) == 8 or len(cue.text) > remaining:
            break
        selected.append(cue.text)
        remaining -= len(cue.text)
    return selected[::-1] if previous else selected


def translate_chunk(playback, index, chunk, recognizer, translator, speech_translator=None,
                    segmenter=None, translation_settings=TranslationSettings(), recognition_cache=None):
    start = index * chunk
    stop = start + chunk
    settings = segmenter.settings if segmenter else Segmentation(enabled=False)
    translation = translation_settings.for_translator(None if speech_translator else translator)
    use_neighbors = bool(translation.before or translation.after)
    margin = getattr(segmenter, "planning_margin", 0)
    read_start = max(0, start - max(settings.before + margin, translation.before))
    read_end = stop + max(settings.after + margin, translation.after)
    wav = extract_audio(playback.path, playback.audio, read_start, read_end - read_start)
    if len(wav) < 400:
        logging.getLogger(__name__).info("No audio samples start=%.1fs audio_stream=%d", start, playback.audio)
        return []
    translated = []
    owned, previous, following = [], [], []
    spans = segmenter.iter_spans(wav) if segmenter else ((0, wav),)
    raw_cues = speech_spans = 0
    for offset, speech in spans:
        speech_spans += 1
        base = read_start + offset
        end = base + (len(speech) - 44) / 32000
        owns_span = start <= (base + end) / 2 < stop
        if margin and not owns_span and not (
                use_neighbors and end > start - translation.before and base < stop + translation.after):
            continue
        if speech_translator:
            cues = speech_translator.speech_translate(speech, playback.source, playback.target)
            language = playback.target
        elif recognition_cache and use_neighbors:
            reference = (playback.path, playback.audio, round(base * 16000))
            language, cues = recognition_cache.recognize(reference, speech, playback.source)
        else:
            language, cues = recognizer.recognize(speech, playback.source)
        raw_cues += len(cues)
        current = []
        for cue in cues:
            # Assign each overlapping cue to one chunk by its original midpoint.
            midpoint = base + (cue.start + cue.end) / 2
            absolute = Cue(max(base, base + cue.start), min(end, base + cue.end), cue.text)
            if absolute.end <= absolute.start or not clear_dialogue(absolute.text):
                continue
            if (owns_span if margin else start <= midpoint < stop):
                current.append(absolute)
            elif start - translation.before <= midpoint < start:
                previous.append(absolute)
            elif stop <= midpoint < stop + translation.after:
                following.append(absolute)
        if use_neighbors:
            owned.extend((language, cue) for cue in current)
        elif speech_translator:
            translated.extend(current)
        else:
            translated.extend(_translate_cues(current, translator, language, playback.target,
                                              prompt=translation.prompt))
    if use_neighbors and owned:
        previous_lines = _context_lines(previous, previous=True)
        following_lines = _context_lines(following)
        for language, group in groupby(owned, key=lambda item: item[0]):
            translated.extend(_translate_cues([cue for _, cue in group], translator, language, playback.target,
                                              previous=previous_lines, following=following_lines,
                                              prompt=translation.prompt))
    if not translated:
        logging.getLogger(__name__).info("No subtitle start=%.1fs source=%s speech_spans=%d asr_cues=%d",
                                         start, playback.source or "auto", speech_spans, raw_cues)
    return translated


def srt_time(seconds):
    seconds, ms = divmod(max(0, round(seconds * 1000)), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"


def clear_dialogue(text):
    """Keep normal repetitions, drop pathological runs of the same text."""
    compact = "".join(char for char in text.casefold() if char.isalnum())
    if len(compact) < 14:
        return True
    for size in range(1, min(12, len(compact) // 7) + 1):
        repeat = compact[:size]
        count = len(compact) // size
        if compact[:count * size] == repeat * count:
            return False
    return True


@dataclass
class Session:
    playback: Playback
    key: str
    updated: float


def merge_cues(cues):
    return list(merge_ordered_cues(sorted(cues, key=lambda cue: (cue.start, cue.end))))


def merge_ordered_cues(cues):
    previous = None
    for cue in cues:
        if previous is not None:
            overlap = min(previous.end, cue.end) - max(previous.start, cue.start)
            shorter = min(previous.end - previous.start, cue.end - cue.start)
            previous_text = "".join(c for c in (previous.original or previous.text).casefold() if c.isalnum())
            next_text = "".join(c for c in (cue.original or cue.text).casefold() if c.isalnum())
            if overlap > 0 and overlap >= shorter * 0.65 and previous_text and (
                previous_text in next_text or next_text in previous_text
            ):
                if len(next_text) > len(previous_text) or cue.end - cue.start > previous.end - previous.start:
                    previous = cue
                continue
            yield previous
        previous = cue
    if previous is not None:
        yield previous


class Relay:
    def __init__(self, root, recognizer, translator, profile, workers=4, chunk=8,
                 speech_translator=None, segmenter=None, *, translation_settings=TranslationSettings()):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.recognizer, self.translator = recognizer, translator
        self.speech_translator = speech_translator
        self.segmenter = segmenter
        self.translation_settings = translation_settings.for_translator(None if speech_translator else translator)
        self.recognition_cache = RecognitionCache(recognizer) if recognizer and (
            self.translation_settings.before or self.translation_settings.after) else None
        self.profile, self.workers, self.chunk = profile, workers, chunk
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / "cache.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA temp_store=FILE")
        self.db.execute("CREATE TABLE IF NOT EXISTS chunks (key TEXT, idx INTEGER, cues TEXT, "
                        "PRIMARY KEY (key, idx))")
        create_history(self.db)
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
        if self.translation_settings != TranslationSettings():
            identity.append(["translation-context-v1", asdict(self.translation_settings)])
        return hashlib.sha256(json.dumps(identity).encode()).hexdigest()

    def _render(self, key, playback):
        subtitle_id = f"{key}{BILINGUAL_SUFFIX}" if playback.bilingual else key
        path = self.root / f"{subtitle_id}.srt"
        revision, = self.db.execute("SELECT COUNT(*) FROM chunks WHERE key=?", (key,)).fetchone()
        if not revision:
            return path, 0
        if self.rendered.get(subtitle_id) != revision or not path.exists():
            rows = self.db.execute(
                "SELECT entry.value FROM chunks JOIN json_each(chunks.cues) AS entry "
                "WHERE chunks.key=? AND json_extract(entry.value, '$.status') IS NULL "
                "ORDER BY json_extract(entry.value, '$.start'), json_extract(entry.value, '$.end'), chunks.idx",
                (key,))
            cues = merge_ordered_cues(Cue(**json.loads(value)) for (value,) in rows)
            def content(cue):
                translated = " ".join(cue.text.splitlines())
                original = " ".join((cue.original or "").splitlines())
                if playback.bilingual and original:
                    source = subtitle_label(cue.source_language or playback.source, "原文")
                    target = subtitle_label(playback.target, "译文")
                    return f"[{source}] {original}\n[{target}] {translated}"
                return translated

            temp = path.with_suffix(f".{os.getpid()}.tmp")
            visible = (cue for cue in cues if clear_dialogue(cue.text) and clear_dialogue(cue.original or cue.text))
            with temp.open("w", encoding="utf-8") as output:
                for index, cue in enumerate(visible, 1):
                    output.write(f"{index}\n{srt_time(cue.start)} --> {srt_time(cue.end)}\n{content(cue)}\n\n")
            os.replace(temp, path)
            self.rendered[subtitle_id] = revision
        return path, revision

    def update(self, identifier, playback):
        key = self._identity(playback)
        with self.lock:
            previous = self.sessions.get(identifier)
            if previous is None or previous.key != key:
                remember_media(self.db, key, playback, self.speech_translator is None)
            self.sessions[identifier] = Session(playback, key, time.monotonic())
            path, revision = self._render(key, playback)
            index = int(playback.position // self.chunk)
            first = index
            error = self.errors.get((key, index))
            completed = self.db.execute("SELECT idx FROM chunks WHERE key=? AND idx>=? ORDER BY idx", (key, index))
            for (idx,) in completed:
                if idx != index:
                    break
                index += 1
            completed.close()
            window = playback.ahead * max(1, playback.speed)
            last = min(index, first + math.ceil(window / self.chunk) + 1)
            margin = getattr(self.segmenter, "planning_margin", 0) / 2
            earliest = min(first - 1, int(max(0, playback.position - margin) // self.chunk))
            nearby_rows = self.db.execute(
                "SELECT cues FROM chunks WHERE key=? AND idx>=? AND idx<?", (key, earliest, last))
            end = min(index * self.chunk, playback.duration or math.inf)
            nearby = any(not cue.get("status") and cue["end"] > playback.position and cue["start"] < end
                         and clear_dialogue(cue["text"]) and clear_dialogue(cue.get("original") or cue["text"])
                         for (encoded,) in nearby_rows
                         for cue in json.loads(encoded))
            nearby_rows.close()
            return {"revision": revision, "subtitle": str(path) if revision else None,
                    "ready_ahead": max(0, end - playback.position),
                    "nearby_cues": nearby,
                    "error": error[1] if error else None, "error_code": error[2] if error else None}

    def drop(self, identifier):
        with self.lock:
            self.sessions.pop(identifier, None)

    def active_sessions(self):
        with self.lock:
            return len(self.sessions)

    def _run(self):
        while not self.stopping.wait(0.1):
            with self.lock:
                self._schedule()

    def _schedule(self):
        now = time.monotonic()
        self.sessions = {name: s for name, s in self.sessions.items() if now - s.updated < 10}
        active = {session.key for session in self.sessions.values()}
        self.rendered = {key: revision for key, revision in self.rendered.items()
                         if key.removesuffix(BILINGUAL_SUFFIX) in active}
        self.errors = {job: detail for job, detail in self.errors.items() if job[0] in active}
        if self.recognition_cache and not active:
            self.recognition_cache.clear_completed()
        candidates = {}
        for session in self.sessions.values():
            playback, key = session.playback, session.key
            first = int(playback.position // self.chunk)
            backfill = self.segmenter.settings.backfill if self.segmenter else 0
            backfill = max(backfill, getattr(self.segmenter, "planning_margin", 0) / 2)
            earliest = int(max(0, playback.position - backfill) // self.chunk)
            end = min(playback.position + playback.ahead * max(1, playback.speed),
                      playback.duration or math.inf)
            last = math.ceil(end / self.chunk)
            done = {idx for (idx,) in self.db.execute(
                "SELECT idx FROM chunks WHERE key=? AND idx>=? AND idx<?", (key, earliest, last))}
            for index in range(earliest, last):
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
                                      self.recognizer, self.translator, self.speech_translator, self.segmenter,
                                      self.translation_settings, self.recognition_cache)
            future.add_done_callback(lambda result, job=job: self._finish(job, result))

    def _finish(self, job, future):
        with self.lock:
            try:
                cues = future.result()
                encoded = json.dumps([asdict(cue) for cue in cues], ensure_ascii=False)
                self.db.execute("INSERT OR REPLACE INTO chunks VALUES (?, ?, ?)", (*job, encoded))
                self.db.execute("DELETE FROM failed_cues WHERE key=? AND idx=?", job)
                self.db.commit()
                self.errors.pop(job, None)
                logging.getLogger(__name__).info("Processed media=%s start=%.1fs cues=%d",
                                                 job[0][:10], job[1] * self.chunk, len(cues))
            except Exception as exc:
                error = provider_error(exc)
                if isinstance(exc, TranslationFailure):
                    exc = exc.__cause__ or exc
                    error = provider_error(exc, default="translation_failed")
                    remember_failed_cues(self.db, job, [replace(cue, status=error.kind) for cue in exc.cues])
                detail = f"{error}（{error.http_status}）" if error.http_status else str(error)
                retry_at = math.inf if error.kind == "content_blocked" else time.monotonic() + 15
                self.errors[job] = (retry_at, detail, error.kind)
                logging.getLogger(__name__).warning("Chunk failed media=%s start=%.1fs error=%s type=%s status=%s",
                                                    job[0][:10], job[1] * self.chunk, error.kind,
                                                    type(exc).__name__, error.http_status)
            finally:
                self.inflight.remove(job)
