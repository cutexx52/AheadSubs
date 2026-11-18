import hashlib
import json
import logging
import math
import os
import sqlite3
import subprocess
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import asdict, dataclass, replace
from itertools import chain, groupby
from pathlib import Path
from uuid import uuid4

from ..inference.audio import Segmentation, make_wav
from ..inference.errors import provider_error
from ..inference.providers import Cue, NLLB_LANGUAGES
from ..inference.recognition_cache import RecognitionCache
from .history import InspectionError, create_history, remember_failed_cues, remember_media
from .metrics import SESSION_TIMEOUT, SOURCES, Samples
from .resources import Resources
from .transcription import Transcriptions


BILINGUAL_SUFFIX = "-bilingual-v3"
DISPLAY_SUFFIX = "-display-v1"
DISPLAY_PADDING = 0.6
MAX_DISPLAY_PADDING = 1.0
MIN_DISPLAY_DURATION = 1.4
MAX_CONTEXT_CUES = 8
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
    previous_cues: int = 0
    prompt: str = ""
    context_chars: int = 250

    def __post_init__(self):
        if type(self.previous_cues) is not int or not 0 <= self.previous_cues <= MAX_CONTEXT_CUES:
            raise ValueError(f"Translation context must be between 0 and {MAX_CONTEXT_CUES} previous cues")
        if type(self.context_chars) is not int or not 20 <= self.context_chars <= 1000:
            raise ValueError("前文每段最多字符请填写 20 到 1000 的整数。")
        if len(self.prompt) > 1000:
            raise ValueError("Translation style guidance must be at most 1000 characters")
        object.__setattr__(self, "prompt", self.prompt.strip())

    def for_translator(self, translator):
        count = self.previous_cues if getattr(translator, "supports_neighbor_context", False) is True else 0
        return TranslationSettings(
            count,
            self.prompt if getattr(translator, "supports_style_prompt", False) is True else "",
            self.context_chars if count else TranslationSettings.context_chars,
        )


def extract_audio(path, audio, start, duration):
    # Keep leading audio gaps on the media clock when writing timestamp-less PCM.
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(start), "-i", str(path),
         "-map", f"0:a:{audio}", "-t", str(duration), "-ac", "1",
         "-af", "aresample=16000:async=1:first_pts=0",
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


def _translate_cues(cues, translator, language, target, *, previous=(), prompt=""):
    if not cues or NLLB_LANGUAGES.get(language, language) == NLLB_LANGUAGES.get(target, target):
        return cues
    if len(cues) > 1 and getattr(translator, "per_cue_requests", False) is True:
        return [result for cue in cues
                for result in _translate_cues([cue], translator, language, target, prompt=prompt)]
    lines = [cue.text for cue in cues]
    try:
        if previous or prompt:
            texts = translator.translate_with_context(lines, language, target,
                                                      previous=previous, prompt=prompt)
        else:
            texts = translator.translate(lines, language, target)
        if len(texts) != len(cues) or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("Translation returned incomplete subtitle lines")
    except Exception as exc:
        if provider_error(exc).kind == "content_blocked":
            return [Cue(cue.start, cue.end, "", cue.text, "content_blocked",
                        source_language=cue.source_language or language) for cue in cues]
        raise TranslationFailure(cues) from exc
    return [Cue(cue.start, cue.end, text, cue.text, source_language=cue.source_language or language)
            for cue, text in zip(cues, texts, strict=True)]


def _context_lines(cues, limit, before, max_chars):
    # Bound the request by both cue count and text size, keeping the closest lines.
    selected = []
    remaining = 1000
    for cue in reversed(cues):
        if cue.end > before:
            continue
        if len(selected) == limit or not remaining:
            break
        text = cue.text[-min(max_chars, remaining):].lstrip()
        if text:
            selected.append(text)
            remaining -= len(text)
    return selected[::-1]


def translate_chunk(playback, index, chunk, recognizer, translator, speech_translator=None,
                    segmenter=None, translation_settings=TranslationSettings(), recognition_cache=None,
                    *, observe_audio=None):
    start = index * chunk
    stop = start + chunk
    settings = segmenter.settings if segmenter else Segmentation(enabled=False)
    translation = translation_settings.for_translator(None if speech_translator else translator)
    use_neighbors = bool(translation.previous_cues)
    margin = getattr(segmenter, "planning_margin", 0)
    # At a cold seek, a bounded earlier audio window can supply preceding cues.
    read_start = max(0, start - max(settings.before + margin, translation.previous_cues * 4))
    read_end = stop + settings.after + margin
    wav = extract_audio(playback.path, playback.audio, read_start, read_end - read_start)
    if len(wav) < 400:
        logging.getLogger(__name__).info("No audio samples start=%.1fs audio_stream=%d", start, playback.audio)
        return []
    if observe_audio is not None:
        observe_audio(max(0, min(stop, read_start + (len(wav) - 44) / 32000) - start))
    translated = []
    owned, previous = [], []
    spans = segmenter.iter_spans(wav) if segmenter else ((0, wav),)
    raw_cues = speech_spans = 0
    for offset, speech in spans:
        speech_spans += 1
        base = read_start + offset
        end = base + (len(speech) - 44) / 32000
        span_midpoint = (base + end) / 2
        owns_span = start <= span_midpoint < stop
        if margin and not owns_span and not (use_neighbors and span_midpoint < start):
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
            absolute = Cue(max(base, base + cue.start), min(end, base + cue.end), cue.text,
                           source_language=None if speech_translator else cue.source_language or language)
            if absolute.end <= absolute.start or not clear_dialogue(absolute.text):
                continue
            if (owns_span if margin else start <= midpoint < stop):
                current.append(absolute)
            elif use_neighbors and midpoint < start:
                previous.append(absolute)
        if use_neighbors:
            owned.extend((language, cue) for cue in current)
        elif speech_translator or translator is None:
            translated.extend(current)
        else:
            translated.extend(_translate_cues(current, translator, language, playback.target,
                                              prompt=translation.prompt))
    if use_neighbors and owned:
        for language, group in groupby(owned, key=lambda item: item[0]):
            current = [cue for _, cue in group]
            before = _context_lines(previous, translation.previous_cues, current[0].start, translation.context_chars)
            translated.extend(_translate_cues(current, translator, language, playback.target,
                                              previous=before,
                                              prompt=translation.prompt))
            previous.extend(current)
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


class SubtitlePipeline:
    def __init__(self, recognizer, translator, profile, speech_translator=None,
                 translation_settings=TranslationSettings()):
        self.recognizer = recognizer
        self.translator = translator
        self.profile = profile
        self.speech_translator = speech_translator
        self.source_only = recognizer is not None and translator is None and speech_translator is None
        self.translation_settings = translation_settings.for_translator(None if speech_translator else translator)
        self.recognition_cache = RecognitionCache(recognizer) if recognizer and self.translation_settings.previous_cues else None


@dataclass
class Session:
    playback: Playback
    key: str
    updated: float
    source: str = "http"
    waiting_since: float | None = None
    pipeline: SubtitlePipeline | None = None


@dataclass
class Regeneration:
    key: str
    playback: Playback
    size: int
    mtime_ns: int
    count: int
    index: int = 0

    def check_media(self):
        try:
            info = self.playback.path.stat()
        except OSError as exc:
            raise InspectionError("inspection_media_changed") from exc
        if (info.st_size, info.st_mtime_ns) != (self.size, self.mtime_ns):
            raise InspectionError("inspection_media_changed")
        return info


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
            # Across independent read windows, two aligned cues can still overlap.
            # Keep the later onset and retire the earlier cue at that boundary.
            stop = min(previous.end, cue.start)
            if round(stop * 1000) > round(previous.start * 1000):
                yield replace(previous, end=stop) if stop < previous.end else previous
        previous = cue
    if previous is not None:
        yield previous


def display_cues(cues, duration=None):
    """Give each acoustic cue a reading window without using its neighbor's slot."""
    cues = iter(cues)
    current = next(cues, None)
    if current is None:
        return
    left_bound = 0
    for following in chain(cues, (None,)):
        right_bound = ((current.end + following.start) / 2 if following is not None
                       else duration if duration is not None else math.inf)
        start = max(left_bound, current.start - DISPLAY_PADDING)
        end = min(right_bound, current.end + DISPLAY_PADDING)
        missing = max(0, MIN_DISPLAY_DURATION - (end - start))
        end = min(right_bound, current.end + MAX_DISPLAY_PADDING, end + missing)
        missing = max(0, MIN_DISPLAY_DURATION - (end - start))
        start = max(left_bound, current.start - MAX_DISPLAY_PADDING, start - missing)
        if round(end * 1000) > round(start * 1000):
            yield replace(current, start=start, end=end)
        left_bound = right_bound
        current = following


def render_srt(db, key, path, duration, source, target, *, bilingual=False, require_cues=False):
    with closing(db.execute(
        "SELECT entry.value FROM chunks JOIN json_each(chunks.cues) AS entry "
        "WHERE chunks.key=? AND json_extract(entry.value, '$.status') IS NULL "
        "ORDER BY json_extract(entry.value, '$.start'), json_extract(entry.value, '$.end'), chunks.idx",
        (key,),
    )) as rows:
        cues = merge_ordered_cues(Cue(**json.loads(value)) for (value,) in rows)
        visible = (cue for cue in cues if cue.text.strip() and clear_dialogue(cue.text)
                   and clear_dialogue(cue.original or cue.text))
        displayed = display_cues(visible, duration)
        first = next(displayed, None)
        if first is None and require_cues:
            return False
        output = tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False,
                                             mode="w", encoding="utf-8", newline="\r\n")
        temporary = Path(output.name)
        try:
            with output:
                for index, cue in enumerate(chain((first,), displayed) if first else (), 1):
                    translated = " ".join(cue.text.splitlines())
                    original = " ".join((cue.original or "").splitlines())
                    if bilingual and original:
                        subtitle_source = subtitle_label(cue.source_language or source, "原文")
                        subtitle_target = subtitle_label(target, "译文")
                        translated = f"[{subtitle_source}] {original}\n[{subtitle_target}] {translated}"
                    output.write(f"{index}\n{srt_time(cue.start)} --> {srt_time(cue.end)}\n{translated}\n\n")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return True


class Relay:
    def __init__(self, root, recognizer, translator, profile, workers=4, chunk=8,
                 speech_translator=None, segmenter=None, *, translation_settings=TranslationSettings(),
                 model_status=lambda: [], cloud_usage=None, transcription_profile=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.recognizer, self.translator = recognizer, translator
        self.pipeline = SubtitlePipeline(recognizer, translator, profile, speech_translator, translation_settings)
        self.segmenter = segmenter
        self.workers, self.chunk = workers, chunk
        self.lock = threading.RLock()
        self.status_lock = threading.Lock()
        self.model_status = model_status
        self.cloud_usage = cloud_usage
        self.resources = Resources()
        self.rtf = Samples()
        self.latency = Samples()
        self.text_requests = Counter()
        self.db = sqlite3.connect(self.root / "cache.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA temp_store=FILE")
        self.db.execute("CREATE TABLE IF NOT EXISTS chunks (key TEXT, idx INTEGER, cues TEXT, "
                        "PRIMARY KEY (key, idx))")
        create_history(self.db)
        self.db.execute("UPDATE media SET state='interrupted' WHERE state IN ('queued', 'running')")
        self.db.commit()
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self.sessions = {}
        self.background_session = None
        self.background_models = set()
        self.background_drained = threading.Event()
        self.background_drained.set()
        self.inflight = set()
        self.errors = {}
        self.rendered = {}
        self.regeneration = None
        self.stopping = threading.Event()
        self.transcriptions = Transcriptions(self, profile if transcription_profile is None else transcription_profile)
        self.scheduler = threading.Thread(target=self._run, daemon=True)
        self.scheduler.start()

    def close(self):
        self.stopping.set()
        self.scheduler.join()
        self.pool.shutdown(wait=True)
        with self.lock:
            self.transcriptions.close()
        if self.regeneration is not None:
            self._end_regeneration("interrupted")
        with self.status_lock:
            self.resources.close()
            if self.cloud_usage is not None:
                self.cloud_usage.close()
        self.db.close()

    def _identity(self, playback, info=None, pipeline=None):
        pipeline = pipeline or self.pipeline
        if info is None:
            info = playback.path.stat()
        identity = [pipeline.profile, self.chunk, os.path.normcase(str(playback.path)),
                    info.st_size, info.st_mtime_ns, playback.audio, playback.source, playback.target]
        if pipeline.translation_settings != TranslationSettings():
            identity.append(["translation-context-v3", asdict(pipeline.translation_settings)])
        return hashlib.sha256(json.dumps(identity).encode()).hexdigest()

    def queue_regeneration(self, selected):
        from ..automation import OperationError, media_duration

        with self.lock:
            if self.regeneration is not None:
                raise InspectionError("inspection_busy")
            row = self.db.execute(
                "SELECT path, size, mtime_ns, audio, source, target FROM media WHERE key=?",
                (selected,),
            ).fetchone()
        if not row or not row[0]:
            raise InspectionError("inspection_path_unknown")
        path, size, mtime_ns, audio, source, target = row
        playback = Playback(Path(path), 0, audio, source=source, target=target)
        task = Regeneration(uuid4().hex, playback, size, mtime_ns, 0)
        task.check_media()
        try:
            duration = media_duration(playback.path, audio, 15)
        except (OperationError, subprocess.TimeoutExpired) as exc:
            raise InspectionError("inspection_probe_failed") from exc
        with self.lock:
            if self.regeneration is not None:
                raise InspectionError("inspection_busy")
            info = task.check_media()
            task.playback = replace(playback, duration=duration)
            task.count = math.ceil(duration / self.chunk)
            remember_media(self.db, task.key, task.playback, self.pipeline.speech_translator is None,
                           info, self.chunk, state="queued", translation_available=not self.pipeline.source_only)
            self.regeneration = task
            if self.background_session is not None:
                self.drop(self.background_session)
        return {"key": task.key}

    def _end_regeneration(self, state, error_code=None):
        self.db.execute("UPDATE media SET state=?, error_code=? WHERE key=?",
                        (state, error_code, self.regeneration.key))
        self.db.commit()
        self.regeneration = None

    def _regenerate_chunk(self, task):
        task.check_media()
        try:
            return self._process(task.playback, task.index, reuse_recognition=False)
        finally:
            task.check_media()

    def _render(self, key, playback):
        suffix = BILINGUAL_SUFFIX if playback.bilingual else DISPLAY_SUFFIX
        subtitle_id = f"{key}{suffix}"
        path = self.root / f"{subtitle_id}.srt"
        revision, = self.db.execute("SELECT COUNT(*) FROM chunks WHERE key=?", (key,)).fetchone()
        if not revision:
            return path, 0
        render_key = (key, playback.bilingual)
        if self.rendered.get(render_key) != revision or not path.exists():
            render_srt(self.db, key, path, playback.duration, playback.source, playback.target,
                       bilingual=playback.bilingual)
            self.rendered[render_key] = revision
        return path, revision

    def update(self, identifier, playback, source="http", *, background=False, pipeline=None):
        pipeline = pipeline or self.pipeline
        received = time.monotonic()
        info = playback.path.stat()
        key = self._identity(playback, info, pipeline)
        with self.lock:
            if not background and self.background_session is not None:
                self.drop(self.background_session)
            now = time.monotonic()
            previous = self.sessions.get(identifier)
            if (previous is None or previous.key != key
                    or playback.duration is not None and playback.duration != previous.playback.duration):
                remember_media(self.db, key, playback, pipeline.speech_translator is None, info, self.chunk,
                               translation_available=not pipeline.source_only)
            session = Session(playback, key, now, source if source in SOURCES else "http", pipeline=pipeline)
            self.sessions[identifier] = session
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
            if not background and previous is not None and previous.key == key and now - previous.updated < SESSION_TIMEOUT:
                advance = playback.position - previous.playback.position
                expected = (now - previous.updated) * max(1, playback.speed)
                if int(previous.playback.position // self.chunk) == first and -0.15 <= advance <= expected + 0.55:
                    session.waiting_since = previous.waiting_since
            if nearby and session.waiting_since is not None:
                ready_at = time.monotonic()
                self.latency.add(ready_at, ready_at - session.waiting_since)
                session.waiting_since = None
            elif not background and not nearby and index == first and error is None and session.waiting_since is None:
                session.waiting_since = received
            return {"revision": revision, "subtitle": str(path) if revision else None,
                    "subtitle_generation": path.stem,
                    "subtitle_has_cues": bool(revision and path.stat().st_size),
                    "ready_ahead": max(0, end - playback.position),
                    "nearby_cues": nearby,
                    "error": error[1] if error else None, "error_code": error[2] if error else None}

    def drop(self, identifier):
        with self.lock:
            self.sessions.pop(identifier, None)
            if identifier == self.background_session:
                self.background_session = None

    def active_sessions(self):
        with self.lock:
            return len(self.sessions) - (self.background_session in self.sessions)

    def background_idle(self):
        with self.lock:
            return self.active_sessions() == 0 and self.regeneration is None and not any(self.text_requests.values())

    def update_background(self, identifier, playback, pipeline=None):
        with self.lock:
            if not self.background_idle():
                return None
            self.background_session = identifier
            return self.update(identifier, playback, background=True, pipeline=pipeline)

    def active_background_models(self):
        with self.lock:
            return self.background_models.copy()

    def text_activity(self, source, change):
        with self.lock:
            if change > 0 and self.background_session is not None:
                self.drop(self.background_session)
            self.text_requests[source] += change

    def status(self):
        with self.lock:
            now = time.monotonic()
            playback = Counter(session.source for name, session in self.sessions.items()
                               if name != self.background_session and now - session.updated < SESSION_TIMEOUT)
            sources = [{"source": source, "playback": playback[source], "text": self.text_requests[source]}
                       for source in SOURCES if playback[source] or self.text_requests[source]]
            performance = {"rtf": self.rtf.summary(now), "latency": self.latency.summary(now)}
            workers = {"busy": len(self.inflight), "limit": self.workers}
        with self.status_lock:
            models = self.model_status()
            return {"service": "subtitle-relay", "ready": all(row["state"] != "unavailable" for row in models),
                    "active_sessions": sum(playback.values()), "sources": sources, "workers": workers,
                    "models": models, "resources": self.resources.read(), "performance": performance,
                    "cloud": self.cloud_usage.snapshot() if self.cloud_usage else None}

    def _run(self):
        while not self.stopping.wait(0.1):
            with self.lock:
                self._schedule()

    def _schedule(self):
        now = time.monotonic()
        self.transcriptions.maintain()
        self.sessions = {name: s for name, s in self.sessions.items() if now - s.updated < SESSION_TIMEOUT}
        active = {session.key for session in self.sessions.values()}
        self.rendered = {render_key: revision for render_key, revision in self.rendered.items()
                         if render_key[0] in active}
        self.errors = {job: detail for job, detail in self.errors.items() if job[0] in active}
        if self.pipeline.recognition_cache and not active:
            self.pipeline.recognition_cache.clear_completed()
        if not active and not self.inflight and self.regeneration is not None:
            task = self.regeneration
            if task.index == 0:
                self.db.execute("UPDATE media SET state='running' WHERE key=?", (task.key,))
                self.db.commit()
            job = (task.key, task.index)
            self.inflight.add(job)
            future = self.pool.submit(self._regenerate_chunk, task)
            future.add_done_callback(lambda result: self._finish(job, result, regeneration=task))
            return
        if not active and not self.inflight and not any(self.text_requests.values()):
            task = self.transcriptions.next_chunk()
            if task is not None:
                job = (task.key, task.index)
                self.inflight.add(job)
                future = self.pool.submit(self.transcriptions.process, task)
                future.add_done_callback(lambda result: self._finish_transcription(job, task, result))
                return
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
                        candidates[job] = (distance, playback, session.pipeline)
        background = self.background_session in self.sessions
        limit = 1 if background else self.workers
        for job in sorted(candidates, key=lambda job: candidates[job][0]):
            if len(self.inflight) >= limit:
                break
            self.inflight.add(job)
            _, playback, pipeline = candidates[job]
            if background:
                self.background_drained.clear()
            future = self.pool.submit(self._process, playback, job[1], pipeline=pipeline)
            future.add_done_callback(lambda result, job=job, media=playback if background else None, pipeline=pipeline:
                                     self._finish(job, result, background_media=media, pipeline=pipeline))

    def _finish_transcription(self, job, task, future):
        with self.lock:
            try:
                self.transcriptions.finish(task, future)
            finally:
                self.inflight.remove(job)

    def _process(self, playback, index, *, reuse_recognition=True, pipeline=None):
        pipeline = pipeline or self.pipeline
        audio_seconds = 0

        def observe(seconds):
            nonlocal audio_seconds
            audio_seconds = seconds

        started = time.monotonic()
        cues = translate_chunk(playback, index, self.chunk, pipeline.recognizer, pipeline.translator,
                               pipeline.speech_translator, self.segmenter, pipeline.translation_settings,
                               pipeline.recognition_cache if reuse_recognition else None, observe_audio=observe)
        elapsed = time.monotonic() - started
        return cues, elapsed / audio_seconds if audio_seconds else None

    def _finish(self, job, future, *, regeneration=None, background_media=None, pipeline=None):
        with self.lock:
            try:
                if background_media is not None:
                    try:
                        if self._identity(background_media, pipeline=pipeline) != job[0]:
                            return
                    except OSError:
                        return
                cues, rtf = future.result()
                encoded = json.dumps([asdict(cue) for cue in cues], ensure_ascii=False)
                self.db.execute("INSERT OR REPLACE INTO chunks VALUES (?, ?, ?)", (*job, encoded))
                self.db.execute("DELETE FROM failed_cues WHERE key=? AND idx=?", job)
                self.db.commit()
                if rtf is not None:
                    self.rtf.add(time.monotonic(), rtf)
                self.errors.pop(job, None)
                if regeneration is not None:
                    regeneration.index += 1
                    if regeneration.index == regeneration.count:
                        self._end_regeneration("complete")
                logging.getLogger(__name__).info("Processed media=%s start=%.1fs cues=%d",
                                                 job[0][:10], job[1] * self.chunk, len(cues))
            except Exception as exc:
                error = provider_error(exc)
                if isinstance(exc, TranslationFailure):
                    exc = exc.__cause__ or exc
                    error = provider_error(exc, default="translation_failed")
                    remember_failed_cues(self.db, job, [replace(cue, status=error.kind) for cue in exc.cues])
                detail = f"{error}（{error.http_status}）" if error.http_status else str(error)
                if regeneration is not None:
                    self._end_regeneration("failed", str(exc) if isinstance(exc, InspectionError) else error.kind)
                else:
                    retry_at = math.inf if error.kind == "content_blocked" else time.monotonic() + 15
                    self.errors[job] = (retry_at, detail, error.kind)
                logging.getLogger(__name__).warning("Chunk failed media=%s start=%.1fs error=%s type=%s status=%s",
                                                    job[0][:10], job[1] * self.chunk, error.kind,
                                                    type(exc).__name__, error.http_status)
            finally:
                self.inflight.remove(job)
                if background_media is not None:
                    self.background_drained.set()
