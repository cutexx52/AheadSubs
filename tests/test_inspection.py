import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import Future
from contextlib import closing
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from subtitle_relay.inference.providers import Cue
from subtitle_relay.server.engine import Playback, Relay, TranslationFailure
from subtitle_relay.server.history import InspectionError, inspect_cache, inspection_subtitle


class InspectionTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.cache = self.root / "cache"
        self.database = self.cache / "cache.sqlite3"
        self.media = self.root / "影片"
        self.media.mkdir()
        self.video = self.media / "样本.mkv"
        self.video.write_bytes(b"original media")

    def relay(self):
        relay = Relay(self.cache, None, None, "test", workers=2)
        self.addCleanup(relay.close)
        # Advance scheduling explicitly while retaining normal chunk completion handling.
        relay.stopping.set()
        relay.scheduler.join()
        return relay

    def publish(self, relay, key, index, cues):
        with relay.lock:
            job = (key, index)
            relay.inflight.add(job)
            result = Future()
            if isinstance(cues, Exception):
                result.set_exception(cues)
            else:
                result.set_result((cues, None))
            relay._finish(job, result)

    def files(self):
        return inspect_cache(self.database, catalog_only=True)["files"]

    def test_groups_by_path_and_reports_timeline_coverage_and_available_languages(self):
        relay = self.relay()
        playback = Playback(self.video, 0, duration=18, target="zh")
        key = relay._identity(playback)
        relay.update("viewer", playback)
        self.publish(relay, key, 0, [
            Cue(1, 3, "字幕", "原文", source_language="ja"),
            Cue(3, 4, "line", "source", source_language="EN"),
        ])
        self.publish(relay, key, 2, [])
        english = replace(playback, target="en")
        relay.update("viewer", english)
        self.publish(relay, relay._identity(english), 0, [Cue(1, 3, "Subtitle")])
        failed = replace(playback, target="fr")
        relay.update("viewer", failed)
        self.publish(relay, relay._identity(failed), 0, TranslationFailure([Cue(1, 3, "Original")]))
        relay.update("viewer", playback)

        other_dir = self.root / "another"
        other_dir.mkdir()
        other = other_dir / self.video.name
        other.touch()
        different = replace(playback, path=other, duration=None)
        relay.update("viewer", different)
        self.publish(relay, relay._identity(different), 0, [])
        relay.update("viewer", replace(different, duration=18))

        files = {file["path"]: file for file in self.files()}
        self.assertEqual(set(files), {str(self.video), str(other)})
        file = files[str(self.video)]
        self.assertEqual([version["target"] for version in file["versions"]], ["fr", "en", "zh"])
        self.assertEqual(file["target_languages"], ["en", "zh"])
        self.assertEqual(file["primary_source"], "ja")
        self.assertAlmostEqual(file["versions"][-1]["coverage"], 10 / 18)
        self.assertEqual(file["versions"][0]["coverage"], 0)
        self.assertAlmostEqual(files[str(other)]["versions"][0]["coverage"], 8 / 18)

    def test_legacy_history_is_readable_before_migration_and_path_backfills_on_playback(self):
        self.cache.mkdir()
        playback = Playback(self.video, 0, duration=24)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("CREATE TABLE media (key TEXT PRIMARY KEY, display_name TEXT, source TEXT, "
                       "target TEXT, original_available INTEGER, updated REAL)")
            db.execute("CREATE TABLE chunks (key TEXT, idx INTEGER, cues TEXT, PRIMARY KEY (key, idx))")
            db.execute("CREATE TABLE failed_cues (key TEXT, idx INTEGER, cues TEXT, PRIMARY KEY (key, idx))")
            db.execute("INSERT INTO media VALUES (?, ?, NULL, 'zh', 1, 1)", ("unmatched", self.video.name))
            db.execute("INSERT INTO chunks VALUES ('unmatched', 0, '[]')")
        file, = self.files()
        self.assertIsNone(file["path"])
        self.assertIsNone(file["versions"][0]["coverage"])

        relay = self.relay()
        key = relay._identity(playback)
        with relay.db:
            relay.db.execute("INSERT INTO media (key, display_name, target, original_available, updated) "
                             "VALUES (?, ?, 'zh', 1, 2)", (key, self.video.name))
            relay.db.execute("INSERT INTO chunks VALUES (?, 0, '[]')", (key,))
        relay.update("viewer", playback)
        files = {file["id"]: file for file in self.files()}
        self.assertIsNone(files["unmatched"]["path"])
        repaired = next(file for file in files.values() if file["path"] == str(self.video))
        self.assertEqual(repaired["versions"][0]["key"], key)
        self.assertAlmostEqual(repaired["versions"][0]["coverage"], 1 / 3)

    def test_export_reads_full_selected_version_and_preserves_destination_on_failure(self):
        relay = self.relay()
        playback = Playback(self.video, 0, duration=8 * 310)
        relay.update("viewer", playback)
        key = relay._identity(playback)
        with relay.db:
            relay.db.executemany("INSERT INTO chunks VALUES (?, ?, ?)", (
                (key, i, json.dumps([asdict(Cue(i * 8 + 1, i * 8 + 2, f"字幕 {i}", "source"))]))
                for i in range(310)
            ))
        self.assertEqual(len(inspect_cache(self.database, key, rows_only=True)["rows"]), 100)
        exported = self.root / "导出.srt"
        inspection_subtitle(self.database, key, exported)
        data = exported.read_bytes()
        self.assertIn("字幕 0\r\n\r\n".encode(), data)
        self.assertIn("字幕 309\r\n\r\n".encode(), data)
        self.assertNotIn(b"source", data)
        self.assertTrue(Path(inspection_subtitle(self.database, key)["subtitle"]).is_file())
        with self.assertRaisesRegex(InspectionError, "inspection_no_subtitles"):
            inspection_subtitle(self.database, "missing", exported)
        self.assertEqual(exported.read_bytes(), data)
        with self.assertRaisesRegex(InspectionError, "inspection_invalid_output"):
            inspection_subtitle(self.database, key, self.cache / "overlap.srt")

    def test_regeneration_yields_to_playback_and_keeps_previous_subtitle(self):
        relay = self.relay()
        playback = Playback(self.video, 0, duration=12, ahead=12)
        old_key = relay._identity(playback)
        relay.update("viewer", playback)
        self.publish(relay, old_key, 0, [Cue(1, 2, "old")])
        self.publish(relay, old_key, 1, [])

        with patch("subtitle_relay.automation.media_duration", return_value=12):
            new_key = relay.queue_regeneration(old_key)["key"]
            with self.assertRaisesRegex(InspectionError, "inspection_busy"):
                relay.queue_regeneration(old_key)

        pending = []

        def submit(run, *args):
            future = Future()
            pending.append((run, args, future))
            return future

        with patch.object(relay.pool, "submit", side_effect=submit), patch(
            "subtitle_relay.server.engine.translate_chunk",
            side_effect=[[Cue(1, 2, "new", source_language="ja")], []],
        ) as translate:
            relay._schedule()
            self.assertFalse(pending)
            self.assertEqual(self.files()[0]["versions"][0]["state"], "queued")
            relay.drop("viewer")
            relay._schedule()
            relay._schedule()
            self.assertEqual(len(pending), 1)
            relay.update("viewer", playback)
            run, args, future = pending.pop()
            future.set_result(run(*args))
            relay._schedule()
            self.assertFalse(pending)
            self.assertAlmostEqual(self.files()[0]["versions"][0]["coverage"], 2 / 3)
            relay.drop("viewer")
            relay._schedule()
            run, args, future = pending.pop()
            future.set_result(run(*args))
            self.assertEqual([call.args[1] for call in translate.call_args_list], [0, 1])

        latest, previous = self.files()[0]["versions"]
        self.assertEqual((latest["key"], latest["state"], latest["coverage"]), (new_key, "complete", 1))
        self.assertEqual(previous["key"], old_key)
        self.assertEqual(inspect_cache(self.database, old_key, rows_only=True)["rows"][0]["translation"], "old")
        self.assertEqual(inspect_cache(self.database, new_key, rows_only=True)["rows"][0]["translation"], "new")

    def test_regeneration_refuses_changed_media_and_records_mid_chunk_replacement(self):
        relay = self.relay()
        playback = Playback(self.video, 0, duration=8)
        old_key = relay._identity(playback)
        relay.update("viewer", playback)
        with patch("subtitle_relay.automation.media_duration", return_value=8):
            new_key = relay.queue_regeneration(old_key)["key"]
        relay.drop("viewer")

        def replace_input(*_, **_options):
            self.video.write_bytes(b"a replacement with a different length")
            raise TranslationFailure([Cue(1, 2, "replacement content")])

        def submit(run, task):
            future = Future()
            try:
                future.set_result(run(task))
            except Exception as exc:
                future.set_exception(exc)
            return future

        with patch.object(relay.pool, "submit", side_effect=submit), patch(
            "subtitle_relay.server.engine.translate_chunk", side_effect=replace_input,
        ):
            relay._schedule()
        version = self.files()[0]["versions"][0]
        self.assertEqual((version["key"], version["state"], version["error_code"]),
                         (new_key, "failed", "inspection_media_changed"))
        self.assertEqual(inspect_cache(self.database, new_key, rows_only=True)["rows"], [])
        with self.assertRaisesRegex(InspectionError, "inspection_media_changed"):
            relay.queue_regeneration(old_key)
