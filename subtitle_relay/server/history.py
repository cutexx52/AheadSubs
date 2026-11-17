"""Local read-only subtitle inspection backed by the normal cue cache."""
import json
import sqlite3
import time
from contextlib import closing
from dataclasses import asdict

from ..inference.errors import ERROR_MESSAGES


def create_history(db):
    db.execute("CREATE TABLE IF NOT EXISTS media (key TEXT PRIMARY KEY, display_name TEXT, "
               "source TEXT, target TEXT, original_available INTEGER, updated REAL)")
    db.execute("CREATE TABLE IF NOT EXISTS failed_cues (key TEXT, idx INTEGER, cues TEXT, PRIMARY KEY (key, idx))")


def remember_media(db, key, playback, original_available):
    db.execute("INSERT OR REPLACE INTO media VALUES (?, ?, ?, ?, ?, ?)",
               (key, playback.path.name, playback.source, playback.target, original_available, time.time()))
    db.commit()


def remember_failed_cues(db, job, cues):
    db.execute("INSERT OR REPLACE INTO failed_cues VALUES (?, ?, ?)",
               (*job, json.dumps([asdict(cue) for cue in cues], ensure_ascii=False)))
    db.commit()


def inspect_cache(path, selected=None):
    if not path.is_file():
        return {"media": [], "key": None, "rows": []}
    from .engine import merge_cues
    from ..inference.providers import Cue

    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media'").fetchone():
            return {"media": [], "key": None, "rows": []}
        media = [dict(row) for row in db.execute(
            "SELECT * FROM media WHERE EXISTS(SELECT 1 FROM chunks WHERE chunks.key=media.key) "
            "OR EXISTS(SELECT 1 FROM failed_cues WHERE failed_cues.key=media.key) ORDER BY updated DESC LIMIT 50")]
        active = next((item for item in media if item["key"] == selected), media[0] if media else None)
        if active is None:
            return {"media": media, "key": None, "rows": []}
        chunks = db.execute("SELECT cues FROM chunks WHERE key=? ORDER BY idx DESC LIMIT 100", (active["key"],))
        recent = [Cue(**cue) for (encoded,) in chunks for cue in json.loads(encoded)]
        cues = merge_cues(cue for cue in recent if not cue.status)[-300:]
        rows = [{"start": cue.start, "end": cue.end, "translation": cue.text,
                 "original": (cue.original or cue.text) if active["original_available"] else None}
                for cue in cues]
        failed = db.execute("SELECT cues FROM failed_cues WHERE key=? ORDER BY idx DESC LIMIT 100", (active["key"],))
        failures = [cue for cue in recent if cue.status]
        failures.extend(Cue(**cue) for (encoded,) in failed for cue in json.loads(encoded))
        for cue in failures:
            status = cue.status or "translation_failed"
            rows.append({"start": cue.start, "end": cue.end, "translation": None,
                         "original": cue.original or cue.text, "status": status,
                         "status_message": ERROR_MESSAGES[status]})
        return {"media": media, "key": active["key"], "rows": sorted(rows, key=lambda row: row["start"])[-300:]}
