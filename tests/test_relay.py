import io
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import wave
from dataclasses import replace
from concurrent.futures import Future
from types import SimpleNamespace
from pathlib import Path
from struct import iter_unpack
from unittest.mock import Mock, patch

from subtitle_relay.inference.audio import Segmentation, Segmenter, make_wav
from subtitle_relay.inference.errors import provider_error
from subtitle_relay.server.engine import (
    Playback, Relay, TranslationFailure, _translate_cues, clear_dialogue, extract_audio, merge_cues,
)
from subtitle_relay.server.history import inspect_cache
from subtitle_relay.adapters.players import run_adapter
from subtitle_relay.server.protocol import playback_from_json
from subtitle_relay.inference.providers import Cue, OpenAIWhisper


class RelayTest(unittest.TestCase):
    def test_explicit_content_block_is_normalized_without_guessing_from_http_400(self):
        block = SimpleNamespace(status_code=400, body={
            "error": {"code": "data_inspection_failed", "message": "request body sample"}})
        self.assertEqual(provider_error(block).kind, "content_blocked")
        self.assertEqual(provider_error(SimpleNamespace(status_code=400)).kind, "invalid_request")
        unavailable = SimpleNamespace(status_code=500, code="InternalError.DataInspection")
        self.assertEqual(provider_error(unavailable).kind, "moderation_unavailable")
        self.assertEqual(provider_error(SimpleNamespace(status_code=429)).kind, "rate_limited")

    def test_inspector_marks_blocked_original_and_publishes_other_cues(self):
        from subtitle_relay.inference.providers import QwenMtTranslation

        denied = ValueError("private upstream details")
        denied.body = {"error": {"code": "data_inspection_failed"}}
        denied.status_code = 400
        client = Mock()
        client.chat.completions.create.side_effect = [
            denied, SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="译文"))])]
        translator = QwenMtTranslation(client, "qwen-mt-flash")
        result = _translate_cues([Cue(1, 2, "原句甲"), Cue(3, 4, "原句乙")], translator, "ja", "zh")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "movie.mp4"
            path.touch()
            playback = Playback(path, 0, duration=8)
            relay = Relay(root, None, None, "test")
            try:
                with relay.lock:
                    job = (relay._identity(playback), 0)
                    relay.inflight.add(job)
                    relay.update("test", playback)
                    future = Future()
                    future.set_result(result)
                    relay._finish(job, future)
                    status = relay.update("test", playback)
                rows = inspect_cache(root / "cache.sqlite3")["rows"]
                self.assertEqual(rows[0]["status"], "content_blocked")
                self.assertEqual(rows[0]["original"], "原句甲")
                self.assertIsNone(rows[0]["translation"])
                self.assertEqual(rows[1]["translation"], "译文")
                self.assertNotIn("private upstream details", str(rows))
                subtitle = Path(status["subtitle"]).read_text(encoding="utf-8")
                self.assertIn("译文", subtitle)
                self.assertNotIn("原句甲", subtitle)
            finally:
                relay.close()

    def test_inspector_keeps_original_when_translation_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "movie.mp4"
            video.touch()
            relay = Relay(root, None, None, "test")
            try:
                playback = Playback(video, 0, duration=8)
                with relay.lock:
                    key = relay._identity(playback)
                    job = (key, 0)
                    relay.inflight.add(job)
                    relay.update("test", playback)
                    future = Future()
                    future.set_exception(TranslationFailure([Cue(1, 2, "こんにちは")]))
                    relay._finish(job, future)
                row = inspect_cache(root / "cache.sqlite3")["rows"][0]
                self.assertEqual(row["original"], "こんにちは")
                self.assertIsNone(row["translation"])
                self.assertEqual(row["status"], "translation_failed")
            finally:
                relay.close()

    def test_bilingual_subtitles_and_inspection_reuse_cached_recognition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "movie.mp4"
            video.touch()
            playback = Playback(video, 0, source="ja", target="zh", duration=8)
            relay = Relay(root, None, None, "test")
            try:
                key = relay._identity(playback)
                bilingual = replace(playback, bilingual=True)
                self.assertEqual(relay._identity(bilingual), key)
                relay.db.execute("INSERT INTO chunks VALUES (?, ?, ?)",
                                 (key, 0, '[{"start": 1, "end": 2, "text": "你好", "original": "こんにちは"}]'))
                relay.db.commit()
                single = Path(relay.update("test", playback)["subtitle"])
                dual = Path(relay.update("test", bilingual)["subtitle"])
                self.assertNotEqual(single, dual)
                self.assertNotIn("こんにちは", single.read_text(encoding="utf-8"))
                self.assertIn("[JP] こんにちは\r\n[CN] 你好".encode("utf-8"), dual.read_bytes())
                inspected = inspect_cache(root / "cache.sqlite3")
                self.assertEqual(inspected["media"][0]["display_name"], "movie.mp4")
                self.assertEqual(inspected["rows"][0]["original"], "こんにちは")
                self.assertEqual(inspected["rows"][0]["translation"], "你好")
            finally:
                relay.close()

    def test_bilingual_auto_uses_detected_language_and_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "movie.mp4"
            video.touch()
            playback = Playback(video, 0, target="zh-TW", duration=8, bilingual=True)
            relay = Relay(root, None, None, "test")
            try:
                with relay.lock:
                    key = relay._identity(playback)
                    relay.db.execute("INSERT INTO chunks VALUES (?, ?, ?)",
                                     (key, 0, '[{"start": 1, "end": 2, "text": "DVD", "original": "DVD",'
                                      '"source_language": "jpn_Jpan"},'
                                      '{"start": 2, "end": 3, "text": "你好", "original": "こんにちは"}]'))
                    relay.db.commit()
                    dual = Path(relay.update("test", playback)["subtitle"]).read_text(encoding="utf-8")
                self.assertIn("[JP] DVD\n[TW] DVD", dual)
                self.assertIn("[原文] こんにちは\n[TW] 你好", dual)
            finally:
                relay.close()

    def test_adapter_reports_seek_immediately_then_briefly_polls_faster(self):
        now = 0.0
        sent = []

        def read_state():
            if now >= 8:
                raise EOFError()
            return {"path": "movie.mp4", "position": now + (60 if now >= 3.35 else 0)}

        def send(route, request):
            if route == "playback":
                sent.append((now, request["position"]))
            return {"subtitle": None, "error": None}

        def sleep(seconds):
            nonlocal now
            now += seconds + 1e-9

        with patch("subtitle_relay.adapters.players.time.monotonic", side_effect=lambda: now), \
             patch("subtitle_relay.adapters.players.time.sleep", side_effect=sleep), self.assertRaises(EOFError):
            run_adapter(Mock(state=read_state), Mock(send=send), "ja", "zh", 20, 0.6, seek_interval=0.15)

        after_seek = [time for time, position in sent if position >= 60]
        self.assertLessEqual(after_seek[0] - 3.35, 0.15)
        self.assertAlmostEqual(after_seek[1] - after_seek[0], 0.15)
        self.assertAlmostEqual(after_seek[-1] - after_seek[-2], 0.6)

    @unittest.skipUnless(os.name == "nt", "PotPlayer requires Windows")
    def test_potplayer_playback_status_does_not_open_an_overlay(self):
        from subtitle_relay.desktop.feedback import PotFeedback

        feedback = PotFeedback.__new__(PotFeedback)
        feedback.root = Mock()
        feedback.latest = "on"
        for state in ("buffering", "ready", "silence", "waiting", "reconnecting", "error"):
            feedback.report(state, "Playback status")
        feedback.root.deiconify.assert_not_called()
        self.assertEqual(feedback.latest, "on")

    @unittest.skipUnless(os.name == "nt", "PotPlayer requires Windows")
    def test_potplayer_first_load_waits_for_a_real_subtitle_cue(self):
        from subtitle_relay.adapters.potplayer import PotPlayer

        player = PotPlayer.__new__(PotPlayer)
        player.subtitle = player.track = None
        player.revision = 0
        player.path = Path("episode 1.mp4")
        player.resolve_media = True
        player._title = Mock(return_value="episode 1.mp4 - PotPlayer")
        player.load_subtitle = Mock()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "subtitle.srt"
            path.write_bytes(b"\xef\xbb\xbf\r\n")
            player.publish(str(path), 1)
            player.load_subtitle.assert_not_called()
            path.write_text("1\n00:00:00,100 --> 00:00:01,000\nHello\n", encoding="utf-8")
            player.publish(str(path), 2)
            player.load_subtitle.assert_called_once_with(path)
            player._title.return_value = "episode 2.mp4 - PotPlayer"
            player._send = Mock()
            player.reload_command = 123
            player.publish(str(path), 3)
            player._send.assert_not_called()
            self.assertEqual(player.revision, 2)

    @unittest.skipUnless(os.name == "nt", "PotPlayer requires Windows")
    def test_potplayer_path_access_denied_offers_manual_resolution(self):
        import psutil
        from subtitle_relay.adapters.potplayer import MediaPathUnavailable, current_media

        with patch.object(psutil.Process, "open_files", side_effect=psutil.AccessDenied()):
            with self.assertRaises(MediaPathUnavailable):
                current_media(os.getpid(), "clip.mp4")

    @unittest.skipUnless(os.name == "nt", "PotPlayer requires Windows")
    def test_potplayer_folder_hint_checks_only_the_current_basename(self):
        from subtitle_relay.adapters.potplayer import media_from_folder

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            episode = folder / "episode 2.mp4"
            episode.touch()
            self.assertEqual(media_from_folder(folder, episode.name), episode)
            self.assertIsNone(media_from_folder(folder, str(episode)))
            self.assertIsNone(media_from_folder(folder, "episode 3.mp4"))

    def test_playback_adapter_resumes_same_session_at_latest_position_after_restart(self):
        player = Mock()
        player.state.side_effect = [{"position": 4}, {"position": 8}, {"position": 12}, EOFError]
        client = Mock()
        client.send.side_effect = [
            {"subtitle": "old.srt", "revision": 1, "error": None, "ready_ahead": 4, "nearby_cues": True},
            ConnectionRefusedError,
            {"subtitle": "new.srt", "revision": 1, "error": None, "ready_ahead": 4, "nearby_cues": True},
            {},
        ]
        source = Mock(side_effect=["en", "ja", "ja"])
        report = Mock()
        with patch("subtitle_relay.adapters.players.time.sleep"), self.assertRaises(EOFError):
            run_adapter(player, client, source, "zh", 20, 0.4, report=report)
        requests = [call.args[1] for call in client.send.call_args_list if call.args[0] == "playback"]
        self.assertEqual(len({request["session"] for request in requests}), 1)
        self.assertEqual((requests[-1]["position"], requests[-1]["source"]), (12, "ja"))
        self.assertEqual([call.args[0] for call in report.call_args_list], ["ready", "reconnecting", "ready"])
        self.assertEqual([call.args for call in player.publish.call_args_list], [("old.srt", 1), ("new.srt", 1)])

    def test_dialogue_filter_preserves_normal_repetition(self):
        self.assertTrue(clear_dialogue("はい、はい、わかりました。"))
        self.assertFalse(clear_dialogue("ありがとう、" * 7))

    def test_subtitle_overlap_preserves_the_second_onset_without_flashing_back(self):
        early = Cue(1, 6, "earlier sentence")
        late = Cue(3, 4, "new sentence")
        final = Cue(7, 8, "last sentence")
        self.assertEqual(merge_cues([late, final, early]), [replace(early, end=3), late, final])

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required for media clock test")
    def test_audio_seek_preserves_track_start_offset(self):
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "offset.mkv"
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=160x120:r=20:d=4",
                "-itsoffset", "1.2", "-f", "lavfi", "-i", "sine=440:16000:duration=2",
                "-c:v", "ffv1", "-c:a", "pcm_s16le", str(media),
            ], capture_output=True, check=True, timeout=20)
            for position, expected in ((0, 1.2), (0.5, 0.7), (2.0, 0)):
                with self.subTest(position=position):
                    wav = extract_audio(media, 0, position, 3)
                    with wave.open(io.BytesIO(wav), "rb") as sound:
                        pcm = sound.readframes(sound.getnframes())
                    actual = next(i / 16000 for i, (sample,) in enumerate(iter_unpack("<h", pcm))
                                  if abs(sample) > 500)
                    self.assertAlmostEqual(actual, expected, delta=0.002)

    def test_compatible_asr_requests_segment_timestamps_in_auto_language_mode(self):
        def transcribe(**request):
            self.assertEqual(request["model"], "qwen3-asr")
            self.assertEqual(request["timestamp_granularities"], ["segment"])
            self.assertNotIn("language", request)
            return SimpleNamespace(language="Japanese", text="こんにちは", segments=[
                SimpleNamespace(start=0.3, end=1.2, text="こんにちは"),
            ])

        client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=transcribe)))
        language, cues = OpenAIWhisper(client, "qwen3-asr").recognize(b"audio", None)
        self.assertEqual((language, cues), ("ja", [Cue(0.3, 1.2, "こんにちは")]))

    def test_playback_accepts_lua_integer_values_and_rejects_fractional_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file.mp4"
            path.touch()
            payload = {"path": str(path), "position": 1.5, "audio": 0.0}
            self.assertEqual(playback_from_json(payload).audio, 0)
            with self.assertRaises(ValueError):
                playback_from_json({**payload, "audio": 0.2})

    def test_segmentation_enforces_max_time_without_dropping_samples(self):
        segmenter = Segmenter(Segmentation(max_speech=3, enabled=False))
        spans = segmenter.spans(make_wav(b"\0" * (32000 * 8)))
        self.assertEqual([offset for offset, _ in spans], [0, 3, 6])
        self.assertEqual([len(wav) - 44 for _, wav in spans], [96000, 96000, 64000])

    def test_boundary_dedup_preserves_repeated_dialogue_at_different_times(self):
        partial = Cue(6.9, 8.4, "下午好", "Good afternoon.")
        full = Cue(6.6, 8.55, "大家下午好", "Good afternoon, everyone.")
        repeated = Cue(8.7, 9.4, "下午好", "Good afternoon.")
        self.assertEqual(merge_cues([partial, repeated, full]), [full, repeated])

    def test_two_sessions_deduplicate_and_reuse_persisted_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "clip.mkv"
            path.touch()
            playback = Playback(path=path, position=8, ahead=1, duration=20)
            with patch("subtitle_relay.server.engine.translate_chunk", return_value=[Cue(8.25, 9.5, "你好")]) as job:
                relay = Relay(root, None, None, "test", workers=4)
                try:
                    relay.update("first", playback)
                    result = relay.update("second", playback)
                    deadline = time.monotonic() + 3
                    while not result["revision"] and time.monotonic() < deadline:
                        time.sleep(0.05)
                        result = relay.update("second", playback)
                    self.assertEqual(result["ready_ahead"], 8)
                    self.assertTrue(result["nearby_cues"])
                    self.assertIn("00:00:08,250 --> 00:00:09,500", Path(result["subtitle"]).read_text("utf8"))
                finally:
                    relay.close()
                self.assertEqual(job.call_count, 1)
                relay = Relay(root, None, None, "test", workers=4)
                try:
                    self.assertEqual(relay.update("reopened", playback)["revision"], 1)
                finally:
                    relay.close()
                self.assertEqual(job.call_count, 1)
