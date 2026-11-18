"""Versioned subtitle inspection over the normal cue cache."""
import json
import os
import sqlite3
import time
from contextlib import closing, contextmanager
from dataclasses import asdict
from pathlib import Path

from ..inference.errors import ERROR_MESSAGES


class InspectionError(ValueError):
    pass


# Existing rows lack path and timeline metadata. A playback cache hit can fill those fields in.
MEDIA_COLUMNS = {
    "path": "TEXT", "path_key": "TEXT", "size": "INTEGER", "mtime_ns": "INTEGER",
    "audio": "INTEGER", "duration": "REAL", "chunk": "REAL", "created": "REAL",
    "state": "TEXT", "error_code": "TEXT",
}


def create_history(db):
    db.execute("CREATE TABLE IF NOT EXISTS media (key TEXT PRIMARY KEY, display_name TEXT, "
               "source TEXT, target TEXT, original_available INTEGER, updated REAL)")
    columns = {row[1] for row in db.execute("PRAGMA table_info(media)")}
    for name, kind in MEDIA_COLUMNS.items():
        if name not in columns:
            db.execute(f"ALTER TABLE media ADD COLUMN {name} {kind}")
    db.execute("CREATE TABLE IF NOT EXISTS failed_cues (key TEXT, idx INTEGER, cues TEXT, PRIMARY KEY (key, idx))")


def remember_media(db, key, playback, original_available, info, chunk, *, state=None):
    now = time.time()
    db.execute("""
        INSERT INTO media (key, display_name, source, target, original_available, updated,
                           path, path_key, size, mtime_ns, audio, duration, chunk, created, state)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET updated=excluded.updated, path=excluded.path,
            path_key=excluded.path_key, size=excluded.size, mtime_ns=excluded.mtime_ns,
            audio=excluded.audio, duration=COALESCE(excluded.duration, media.duration),
            chunk=excluded.chunk, created=COALESCE(media.created, media.updated)
        """, (key, playback.path.name, playback.source, playback.target, original_available, now,
              str(playback.path), os.path.normcase(str(playback.path)), info.st_size, info.st_mtime_ns,
              playback.audio, playback.duration, chunk, now, state))
    db.commit()


def remember_failed_cues(db, job, cues):
    db.execute("INSERT OR REPLACE INTO failed_cues VALUES (?, ?, ?)",
               (*job, json.dumps([asdict(cue) for cue in cues], ensure_ascii=False)))
    db.commit()


@contextmanager
def read_history(path):
    if not path.is_file():
        yield None
        return
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        yield db if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media'").fetchone() else None


def catalog(db):
    columns = {row[1] for row in db.execute("PRAGMA table_info(media)")}
    legacy = "".join(f", NULL AS {name}" for name in MEDIA_COLUMNS if name not in columns)
    versions = [dict(row) for row in db.execute(f"SELECT media.*{legacy} FROM media")]
    # Measure processed timeline independently of speech and subtitle availability.
    spans = dict(db.execute("""
        SELECT c.key, SUM(MAX(0, MIN(m.chunk, m.duration - c.idx * m.chunk)))
        FROM chunks AS c JOIN (SELECT media.*""" + legacy + """ FROM media) AS m ON m.key=c.key
        GROUP BY c.key
        """))
    subtitles = {row[0] for row in db.execute("""
        SELECT DISTINCT chunks.key FROM media JOIN chunks ON chunks.key=media.key, json_each(chunks.cues) AS cue
        WHERE json_extract(cue.value, '$.status') IS NULL
            AND trim(json_extract(cue.value, '$.text')) <> ''
        """)}
    sources = {}
    for key, language, _ in db.execute("""
        SELECT history.key, lower(replace(json_extract(cue.value, '$.source_language'), '_', '-')) AS lang,
            SUM(json_extract(cue.value, '$.end') - json_extract(cue.value, '$.start')) AS seconds
        FROM (SELECT key, cues FROM chunks UNION ALL SELECT key, cues FROM failed_cues) AS history
        JOIN media ON media.key=history.key,
            json_each(history.cues) AS cue
        WHERE lang IS NOT NULL AND lang NOT IN ('', 'auto', 'und')
        GROUP BY history.key, lang ORDER BY seconds DESC, lang
        """):
        sources.setdefault(key, language)
    failures = {row[0] for row in db.execute("SELECT DISTINCT key FROM failed_cues")}
    groups = {}
    for version in sorted(versions, key=lambda v: (v["created"] or v["updated"], v["key"]), reverse=True):
        key = version["key"]
        if key not in spans and key not in failures and version["state"] is None:
            continue
        group_id = version["path_key"] or key
        group = groups.setdefault(group_id, {
            "id": group_id, "display_name": version["display_name"], "path": version["path"],
            "target_languages": [], "versions": [],
        })
        known_timeline = version["duration"] and version["chunk"]
        version["coverage"] = (spans.get(key, 0) or 0) / version["duration"] if known_timeline else None
        version["primary_source"] = sources.get(key)
        version["has_subtitles"] = key in subtitles
        version["can_regenerate"] = version["path"] is not None
        del version["size"], version["mtime_ns"], version["path_key"]
        group["versions"].append(version)
        if key in subtitles and version["target"] not in group["target_languages"]:
            group["target_languages"].append(version["target"])
    for group in groups.values():
        group["primary_source"] = next((v["primary_source"] for v in group["versions"] if v["primary_source"]), None)
    return list(groups.values())


def inspect_rows(db, active):
    from .engine import merge_cues
    from ..inference.providers import Cue

    chunks = db.execute("SELECT cues FROM chunks WHERE key=? ORDER BY idx DESC LIMIT 100", (active["key"],))
    recent = [Cue(**cue) for (encoded,) in chunks for cue in json.loads(encoded)]
    rows = [{"start": cue.start, "end": cue.end, "translation": cue.text,
             "original": (cue.original or cue.text) if active["original_available"] else None}
            for cue in merge_cues(cue for cue in recent if not cue.status)[-300:]]
    failed = db.execute("SELECT cues FROM failed_cues WHERE key=? ORDER BY idx DESC LIMIT 100", (active["key"],))
    failures = [cue for cue in recent if cue.status]
    failures.extend(Cue(**cue) for (encoded,) in failed for cue in json.loads(encoded))
    for cue in failures:
        status = cue.status or "translation_failed"
        rows.append({"start": cue.start, "end": cue.end, "translation": None,
                     "original": cue.original or cue.text, "status": status,
                     "status_message": ERROR_MESSAGES.get(status, ERROR_MESSAGES["processing_failed"])})
    return sorted(rows, key=lambda row: row["start"])[-300:]


def inspect_cache(path, selected=None, *, catalog_only=False, rows_only=False):
    with read_history(path) as db:
        groups = catalog(db) if db is not None and not rows_only else []
        if catalog_only:
            return {"files": groups}
        media = [version for group in groups for version in group["versions"]]
        if rows_only and db is not None:
            row = db.execute("SELECT key, original_available FROM media WHERE key=?", (selected,)).fetchone()
            return {"rows": inspect_rows(db, row) if row is not None else []}
        active = next((item for item in media if item["key"] == selected), media[0] if media else None)
        return {"files": groups, "media": media, "key": active["key"] if active else None,
                "rows": inspect_rows(db, active) if active else []}


def inspection_subtitle(path, key, output=None):
    from .engine import render_srt

    with read_history(path) as db:
        if db is None:
            raise InspectionError("inspection_no_subtitles")
        has_duration = any(row[1] == "duration" for row in db.execute("PRAGMA table_info(media)"))
        fields = "source, target, duration, path" if has_duration else "source, target, NULL, NULL"
        version = db.execute(f"SELECT {fields} FROM media WHERE key=?", (key,)).fetchone()
        if version is None:
            raise InspectionError("inspection_no_subtitles")
        source, target, duration, media_path = version
        if output is None:
            folder = path.parent / "inspection"
            folder.mkdir(exist_ok=True)
            output = folder / f"{key}.srt"
        else:
            output = Path(output)
            if (not output.is_absolute() or output.suffix.lower() != ".srt"
                    or output.resolve().is_relative_to(path.parent.resolve())
                    or (media_path and output.resolve() == Path(media_path).resolve())):
                raise InspectionError("inspection_invalid_output")
        if not render_srt(db, key, output, duration, source, target, require_cues=True):
            raise InspectionError("inspection_no_subtitles")
        return {"subtitle": str(output)}
