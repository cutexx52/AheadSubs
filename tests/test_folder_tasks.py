import io
import json
import os
import shutil
import tempfile
import unittest
from argparse import Namespace
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from pydantic import ValidationError

from aheadsubs.automation import OperationError, generate_subtitles
from aheadsubs.folder_tasks import FolderWorker, RuleSet, TaskFiles, WatchRule
from aheadsubs.inference.providers import Cue
from aheadsubs.server.engine import Playback, Relay, SubtitlePipeline, TranslationSettings
from aheadsubs.server.protocol import playback_from_json


class FolderTaskTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="字幕任务 ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.files = TaskFiles(self.root / "data")
        self.media = self.root / "视频"
        self.media.mkdir()
        self.rule = WatchRule(id=uuid4().hex, folder=str(self.media))
        self.relay = Mock()
        self.relay.background_idle.return_value = True
        self.idle = Mock(return_value=180)
        self.cache = self.root / "cached.srt"
        self.cache.write_text("1\n00:00:00,000 --> 00:00:01,000\n字幕\n", encoding="utf-8")
        self.relay.update_background.return_value = {"ready_ahead": 9, "subtitle": str(self.cache),
            "subtitle_generation": "cache", "subtitle_has_cues": True}
        probe = patch("aheadsubs.automation.media_duration", return_value=9)
        probe.start()
        self.addCleanup(probe.stop)
        self.worker = FolderWorker(self.files, self.relay, {"target": "zh", "source": "ja"}, self.idle)

    def create(self, relative, size=4, *, folder=None):
        path = (folder or self.media) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"X" * size)
        return path

    def configure(self, *rules):
        self.files.save(RuleSet(rules=list(rules)))

    def states(self, rule):
        return self.files.status()["summary"][rule.id]["counts"]

    def test_incremental_rules_persist_and_apply_regex_extension_size_and_recursion(self):
        other_folder = self.root / "another"
        other_folder.mkdir()
        first = self.rule.model_copy(update={"pattern": r"^episode\d+\.", "recursive": True,
            "extensions": "mkv", "min_bytes": 2, "max_bytes": 5})
        second = WatchRule(id=uuid4().hex, folder=str(other_folder), include_existing=True, extensions=".WAV, wav")
        self.configure(first, second)
        previous = self.create("episode1.mkv")
        included = self.create("speech.wav", folder=other_folder)
        self.create("sub/episode5.wav")
        self.create("episode6.mkv", size=6)
        self.create("episode7.mkv", size=1)
        self.create("bonus.mkv")
        with self.files.connect() as db:
            self.worker.scan_rules(db, [first, second], 0)
            self.assertFalse(self.worker.next_job(db, [first, second]))
        new = self.create("sub/EPISODE2.MKV", size=2)
        previous.write_bytes(b"fresh")
        restarted = FolderWorker(self.files, self.relay, {}, self.idle)
        with self.files.connect() as db:
            restarted.scan_rules(db, [first, second], 10)
            self.assertEqual(self.states(first), {"settling": 2})
            self.assertTrue(restarted.next_job(db, [first, second]))
            self.assertTrue(included.with_suffix(".srt").exists())
            self.assertFalse(restarted.next_job(db, [first, second]))
            new.write_bytes(b"new")
            restarted.scan_rules(db, [first, second], 20)
            self.assertTrue(restarted.next_job(db, [first, second]))
            self.assertTrue(previous.with_suffix(".srt").exists())
            self.assertFalse(new.with_suffix(".srt").exists())
            restarted.scan_rules(db, [first, second], 30)
            self.assertTrue(restarted.next_job(db, [first, second]))
            self.assertEqual(new.with_suffix(".srt").read_bytes(), self.cache.read_bytes())
            self.assertFalse(restarted.next_job(db, [first, second]))
            self.assertEqual(self.states(first), {"done": 2})

    def test_idle_and_playback_defer_export_then_resume_with_selected_options(self):
        destination = self.root / "输出"
        destination.mkdir()
        rule = self.rule.model_copy(update={"include_existing": True, "recursive": True, "idle_minutes": 2,
            "source": "auto", "target": "en", "audio": 1, "bilingual": True,
            "suffix": ".en", "destination": str(destination)})
        self.configure(rule)
        self.create("季一/影片.mp4")
        output = destination / "季一" / "影片.en.srt"
        with self.files.connect() as db:
            self.worker.scan(db, rule, 0)
            self.worker.scan(db, rule, 10)
            self.idle.return_value = 119
            self.assertFalse(self.worker.next_job(db, [rule]))
            self.relay.update_background.assert_not_called()
            self.idle.return_value = 120
            # Playback starts after the last window response but before publication.
            self.relay.background_idle.side_effect = [True, True, True, True, False]
            self.assertTrue(self.worker.next_job(db, [rule]))
            self.assertEqual(self.states(rule), {"waiting": 1})
            self.assertFalse(output.exists())
            self.relay.drop.assert_called_once()
            self.relay.background_idle.side_effect = None
            self.assertTrue(self.worker.next_job(db, [rule]))
            self.assertEqual(output.read_bytes(), self.cache.read_bytes())
            playback = self.relay.update_background.call_args.args[1]
            self.assertEqual((playback.source, playback.target, playback.audio, playback.bilingual), (None, "en", 1, True))
            self.assertEqual(self.states(rule), {"done": 1})

    def test_failure_can_be_retried_and_existing_output_is_preserved(self):
        rule = self.rule.model_copy(update={"include_existing": True})
        self.configure(rule)
        media = self.create("film.mp4")
        with self.files.connect() as db:
            self.worker.scan(db, rule, 0)
            self.worker.scan(db, rule, 10)
            valid = self.relay.update_background.return_value
            self.relay.update_background.return_value = {"error": "private", "error_code": "rate_limited"}
            self.assertTrue(self.worker.next_job(db, [rule]))
            status = self.files.status()["summary"][rule.id]
            self.assertEqual(status["items"][0]["issue"], "rate_limited")
            self.assertNotIn("private", json.dumps(status))
            self.assertFalse(self.worker.next_job(db, [rule]))
            self.files.retry(rule.id)
            existing = media.with_suffix(".srt")
            existing.write_text("existing subtitle", encoding="utf-8")
            self.relay.update_background.return_value = valid
            self.assertTrue(self.worker.next_job(db, [rule]))
            self.assertEqual(self.states(rule), {"skipped": 1})
            self.assertEqual(existing.read_text(encoding="utf-8"), "existing subtitle")

            changed = rule.model_copy(update={"suffix": ".new"})
            self.configure(changed)
            self.worker.scan(db, changed, 20)
            self.assertTrue(self.worker.next_job(db, [changed]))
            self.assertTrue(media.with_suffix(".new.srt").is_file())
            self.assertEqual(existing.read_text(encoding="utf-8"), "existing subtitle")

    def test_changed_file_during_export_never_publishes_a_stale_subtitle(self):
        rule = self.rule.model_copy(update={"include_existing": True})
        self.configure(rule)
        media = self.create("changing.mp4")
        output = media.with_suffix(".srt")
        copyfile = shutil.copyfile

        def modify_media_after_staging(source, destination):
            copyfile(source, destination)
            media.write_bytes(b"additional data")

        with self.files.connect() as db:
            self.worker.scan(db, rule, 0)
            self.worker.scan(db, rule, 10)
            with patch("aheadsubs.automation.shutil.copyfile", side_effect=modify_media_after_staging):
                self.assertTrue(self.worker.next_job(db, [rule]))
            self.assertEqual(self.states(rule), {"waiting": 1})
            self.assertFalse(output.exists())
            self.assertEqual(list(self.media.iterdir()), [media])
            self.worker.scan(db, rule, 20)
            self.assertFalse(self.worker.next_job(db, [rule]))
            self.worker.scan(db, rule, 30)
            self.assertTrue(self.worker.next_job(db, [rule]))
            self.assertTrue(output.exists())

    def test_missing_initial_folder_is_reported_and_does_not_establish_baseline(self):
        rule = WatchRule(id=self.rule.id, folder=str(self.media / "unavailable"), include_existing=True)
        self.configure(rule)
        with self.files.connect() as db:
            self.worker.scan(db, rule, 0)
            self.assertEqual(self.files.status()["summary"][rule.id]["issue"], "folder_unavailable")
            self.assertFalse(self.worker.next_job(db, [rule]))
            film = self.create("unavailable/clip.mp4")
            self.worker.scan(db, rule, 10)
            self.worker.scan(db, rule, 20)
            self.assertTrue(self.worker.next_job(db, [rule]))
            self.assertTrue(film.with_suffix(".srt").is_file())

    def test_invalid_destination_is_retryable_and_keeps_media_untouched(self):
        destination = self.create("output", folder=self.root)
        rule = self.rule.model_copy(update={"include_existing": True, "destination": str(destination)})
        self.configure(rule)
        film = self.create("film.mp4")
        with self.files.connect() as db:
            self.worker.scan(db, rule, 0)
            self.worker.scan(db, rule, 10)
            self.assertTrue(self.worker.next_job(db, [rule]))
            status = self.files.status()["summary"][rule.id]
            self.assertEqual(status["items"][0]["issue"], "invalid_output")
            self.assertEqual(self.states(rule), {"failed": 1})
            self.assertFalse(film.with_suffix(".srt").exists())
            self.assertEqual(destination.read_bytes(), b"XXXX")

    def test_invalid_rule_input_is_rejected(self):
        for invalid in ({"pattern": "["}, {"folder": "./media"}, {"extensions": "srt"},
                        {"suffix": "/output"}, {"min_bytes": 2, "max_bytes": 1},
                        {"speech_model": "nllb"}, {"translation_model": "whisper-small"},
                        {"translation_model": "openai:https://example.com"}):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                WatchRule.model_validate({**self.rule.model_dump(), **invalid})

    def test_rule_pipeline_isolated_from_other_rules_and_playback_cache(self):
        path = self.create("film.mp4")
        default_asr = Mock()
        default_asr.recognize.return_value = "ja", [Cue(0, 1, "global speech")]
        other_asr = Mock()
        other_asr.recognize.return_value = "ja", [Cue(0, 1, "rule speech")]
        default_mt = Mock()
        default_mt.translate.side_effect = lambda lines, source, target: ["global: " + line for line in lines]
        other_mt = Mock()
        other_mt.translate.side_effect = lambda lines, source, target: ["rule: " + line for line in lines]
        relay = Relay(self.root / "cache", default_asr, default_mt, "global", chunk=10)
        self.addCleanup(relay.close)
        opened = []

        @contextmanager
        def open_pipeline(rule):
            opened.append(rule.suffix)
            yield SubtitlePipeline(other_asr if rule.speech_model else default_asr,
                                   other_mt if rule.translation_model else default_mt,
                                   [rule.speech_model, rule.translation_model])
            self.assertTrue(relay.background_drained.is_set())

        speech = self.rule.model_copy(update={"include_existing": True, "suffix": ".asr", "speech_model": "openai"})
        translation = speech.model_copy(update={"id": uuid4().hex, "suffix": ".mt", "speech_model": None,
                                                "translation_model": "qwen-mt-flash"})
        inherited = {key: value for key, value in self.rule.model_dump().items()
                     if key not in {"speech_model", "translation_model"}}
        inherited.update(id=uuid4().hex, include_existing=True)
        self.files.directory.mkdir()
        self.files.settings.write_text(json.dumps({"rules": [inherited, speech.model_dump(), translation.model_dump()]}),
                                       encoding="utf-8")
        rules = self.files.load().rules
        worker = FolderWorker(self.files, relay, {"source": "ja", "target": "zh"}, self.idle, open_pipeline)

        def generate_with_timeout(client, args, checkpoint):
            return generate_subtitles(client, args.model_copy(update={"timeout": 5}), checkpoint)

        with self.files.connect() as db, patch("aheadsubs.server.engine.extract_audio", return_value=bytes(32044)), \
                patch("aheadsubs.folder_tasks.generate_subtitles", side_effect=generate_with_timeout):
            worker.scan_rules(db, rules, 0)
            worker.scan_rules(db, rules, 10)
            for _ in rules:
                self.assertTrue(worker.next_job(db, rules))
            self.assertFalse(worker.next_job(db, rules))

        expected = {".srt": "global: global speech", ".asr.srt": "global: rule speech", ".mt.srt": "rule: global speech"}
        for suffix, subtitle in expected.items():
            self.assertIn(subtitle, path.with_suffix(suffix).read_text(encoding="utf-8"))
        self.assertCountEqual(opened, [".asr", ".mt"])
        playback = playback_from_json({"path": str(path), "position": 0, "duration": 9, "source": "ja"}, {})
        result = relay.update("player", playback)
        self.assertEqual(result["ready_ahead"], 9)
        self.assertIn(expected[".srt"], Path(result["subtitle"]).read_text(encoding="utf-8"))

    def test_model_change_requeues_but_does_not_open_model_for_existing_srt(self):
        rule = self.rule.model_copy(update={"include_existing": True})
        self.configure(rule)
        media = self.create("film.mp4")
        worker = self.worker
        worker.open_pipeline = Mock(side_effect=AssertionError("existing SRT must be checked first"))
        with self.files.connect() as db:
            worker.scan(db, rule, 0)
            worker.scan(db, rule, 10)
            self.assertTrue(worker.next_job(db, [rule]))
            previous = media.with_suffix(".srt").read_bytes()
            changed = rule.model_copy(update={"translation_model": "nllb"})
            self.configure(changed)
            worker.scan(db, changed, 20)
            self.assertTrue(worker.next_job(db, [changed]))
            self.assertEqual(self.states(changed), {"skipped": 1})
            self.assertEqual(media.with_suffix(".srt").read_bytes(), previous)
            worker.open_pipeline.assert_not_called()

    def test_real_relay_preempts_the_background_session_and_hides_it_from_player_status(self):
        path = self.create("film.mp4")
        relay = Relay(self.root / "cache", None, None, "test")
        self.addCleanup(relay.close)
        playback = Playback(path, 0, duration=8)
        alternate = SubtitlePipeline(None, None, "rule")
        with relay.lock:
            background = relay.update_background("automatic", playback, alternate)
            self.assertEqual(relay.active_sessions(), 0)
            player = relay.update("player", playback)
            self.assertNotEqual(background["subtitle_generation"], player["subtitle_generation"])
            self.assertEqual(relay.active_sessions(), 1)
            self.assertIsNone(relay.update_background("automatic", playback))
            relay.drop("player")
            self.assertNotIn("automatic", relay.sessions)
            self.assertIsNotNone(relay.update_background("automatic", playback))
            relay.text_activity("http", 1)
            self.assertNotIn("automatic", relay.sessions)
            self.assertIsNone(relay.update_background("automatic", playback))
            relay.text_activity("http", -1)
            self.assertIsNotNone(relay.update_background("automatic", playback))
            relay.queue_regeneration(relay.sessions["automatic"].key)
            self.assertNotIn("automatic", relay.sessions)
            self.assertIsNone(relay.update_background("automatic", playback))

    @unittest.skipUnless(os.name == "nt", "Windows desktop bridge")
    def test_bridge_saves_only_valid_rules_and_round_trips_unicode(self):
        from aheadsubs.desktop import runtime
        from aheadsubs.desktop.bridge import run_command
        from aheadsubs.automation import OperationError

        with patch.object(runtime, "DATA", self.files.directory), patch.object(runtime, "healthy", return_value=False):
            data = {"rules": [dict(self.rule.model_dump(), speech_model="qwen-1.7b", translation_model="nllb")]}
            with patch("sys.stdin", io.StringIO(json.dumps(data, ensure_ascii=False))):
                self.assertEqual(run_command("folder-tasks", "save")["rules"], data["rules"])
            data["rules"][0]["pattern"] = "["
            with patch("sys.stdin", io.StringIO(json.dumps(data))), self.assertRaises(OperationError):
                run_command("folder-tasks", "save")
            self.assertEqual(run_command("folder-tasks")["rules"][0]["pattern"], "")

    @unittest.skipUnless(os.name == "nt", "Windows desktop model configuration")
    def test_desktop_pipeline_uses_selected_provider_and_saved_settings(self):
        from aheadsubs.__main__ import build_folder_pipeline
        from aheadsubs.desktop import assets, runtime
        from aheadsubs.desktop.folder_tasks import folder_pipeline
        from aheadsubs.inference.audio import Segmenter, Segmentation

        self.files.directory.mkdir()
        args = Namespace(asr="local", mt="local", ast=False, device="cpu", asr_device=None, mt_device=None,
                         whisper_model="small", nllb_model="nllb", llm_model="gpt-4.1-mini", llm_url="",
                         qwen_mt_model="qwen-mt-flash", qwen_mt_url="", qwen_mt_key_file=None,
                         dashscope_asr_model="qwen-audio-3.1-asr-flash", vad_model="silero", no_vad=True, workers=2,
                         qwen_size="1.7b", qwen_root=None, desktop_config=self.files.settings)
        relay = Relay(self.root / "cache", Mock(), Mock(), "global", segmenter=Segmenter(Segmentation(enabled=False)))
        self.addCleanup(relay.close)
        settings = {"translation_enhancements": {"qwen-mt:qwen-mt-flash": {
            "enabled": True, "previous_cues": 0, "prompt": "Test guidance"}}}
        build = partial(build_folder_pipeline, relay)
        translation = self.rule.model_copy(update={"translation_model": "qwen-mt-flash"})
        replacement = Mock(model="qwen-mt-flash", supports_style_prompt=True)
        with patch("aheadsubs.desktop.credentials.resolve", return_value="test-key") as credential, \
                patch("aheadsubs.__main__.qwen_mt_client") as client, \
                patch("aheadsubs.__main__.QwenMtTranslation", return_value=replacement) as create:
            with folder_pipeline(relay, args, settings, translation, build) as pipeline:
                self.assertIs(pipeline.recognizer, relay.recognizer)
                self.assertIs(pipeline.translator, replacement)
                self.assertEqual(pipeline.translation_settings, TranslationSettings(prompt="Test guidance"))
                self.assertIsNotNone(replacement.usage_meter)
            self.assertEqual(create.call_args.args[1], "qwen-mt-flash")
            credential.assert_called_once_with(settings, "dashscope", None)
            self.assertEqual(client.call_args.kwargs["api_key"], "test-key")
        self.assertEqual(args.mt, "local")

        speech = self.rule.model_copy(update={"speech_model": "qwen-0.6b"})
        with patch.object(runtime, "DATA", self.files.directory), patch.object(assets, "model_ready", return_value=False):
            with self.assertRaises(OperationError) as error, folder_pipeline(relay, args, settings, speech, build):
                self.fail("the missing model must not be started")
            self.assertEqual(error.exception.code, "folder_model_not_installed")
        self.assertFalse(relay.active_background_models())

        @contextmanager
        def qwen_process(root, size):
            self.assertEqual(size, "0.6b")
            self.assertEqual(relay.active_background_models(), {"qwen-0.6b"})
            yield "http://127.0.0.1:9000/v1"

        with patch.object(runtime, "DATA", self.files.directory), patch.object(assets, "model_ready", return_value=True), \
                patch("aheadsubs.inference.qwen.run", side_effect=qwen_process), \
                patch("aheadsubs.__main__.openai_client") as client:
            with folder_pipeline(relay, args, settings, speech, build) as pipeline:
                self.assertEqual(pipeline.recognizer.model, "qwen3-asr")
                self.assertIs(pipeline.translator, relay.translator)
            self.assertEqual(client.call_args.kwargs["endpoint"], "http://127.0.0.1:9000/v1")
        self.assertFalse(relay.active_background_models())
