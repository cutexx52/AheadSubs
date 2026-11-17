import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

from subtitle_relay.audio import Segmentation, Segmenter, make_wav
from subtitle_relay.engine import Playback, Relay, clear_dialogue, merge_cues
from subtitle_relay.players import run_adapter
from subtitle_relay.protocol import playback_from_json
from subtitle_relay.providers import Cue, OpenAIWhisper


class RelayTest(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "PotPlayer requires Windows")
    def test_potplayer_playback_status_does_not_open_an_overlay(self):
        from subtitle_relay.feedback import PotFeedback

        feedback = PotFeedback.__new__(PotFeedback)
        feedback.root = Mock()
        feedback.latest = "on"
        for state in ("buffering", "ready", "silence", "waiting", "reconnecting", "error"):
            feedback.report(state, "Playback status")
        feedback.root.deiconify.assert_not_called()
        self.assertEqual(feedback.latest, "on")

    @unittest.skipUnless(os.name == "nt", "PotPlayer requires Windows")
    def test_potplayer_first_load_waits_for_a_real_subtitle_cue(self):
        from subtitle_relay.potplayer import PotPlayer

        player = PotPlayer.__new__(PotPlayer)
        player.subtitle = player.track = None
        player.load_subtitle = Mock()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "subtitle.srt"
            path.write_bytes(b"\xef\xbb\xbf\r\n")
            player.publish(str(path), 1)
            player.load_subtitle.assert_not_called()
            path.write_text("1\n00:00:00,100 --> 00:00:01,000\nHello\n", encoding="utf-8")
            player.publish(str(path), 2)
            player.load_subtitle.assert_called_once_with(path)

    @unittest.skipUnless(os.name == "nt", "PotPlayer requires Windows")
    def test_potplayer_path_access_denied_offers_manual_resolution(self):
        import psutil
        from subtitle_relay.potplayer import MediaPathUnavailable, current_media

        with patch.object(psutil.Process, "open_files", side_effect=psutil.AccessDenied()):
            with self.assertRaises(MediaPathUnavailable):
                current_media(os.getpid(), "clip.mp4")

    @unittest.skipUnless(os.name == "nt", "PotPlayer requires Windows")
    def test_potplayer_folder_hint_checks_only_the_current_basename(self):
        from subtitle_relay.potplayer import media_from_folder

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
        with patch("subtitle_relay.players.time.sleep"), self.assertRaises(EOFError):
            run_adapter(player, client, source, "zh", 20, 0.4, report=report)
        requests = [call.args[1] for call in client.send.call_args_list if call.args[0] == "playback"]
        self.assertEqual(len({request["session"] for request in requests}), 1)
        self.assertEqual((requests[-1]["position"], requests[-1]["source"]), (12, "ja"))
        self.assertEqual([call.args[0] for call in report.call_args_list], ["ready", "reconnecting", "ready"])
        self.assertEqual([call.args for call in player.publish.call_args_list], [("old.srt", 1), ("new.srt", 1)])

    def test_dialogue_filter_preserves_normal_repetition(self):
        self.assertTrue(clear_dialogue("はい、はい、わかりました。"))
        self.assertFalse(clear_dialogue("ありがとう、" * 7))

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
            with patch("subtitle_relay.engine.translate_chunk", return_value=[Cue(8.25, 9.5, "你好")]) as job:
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
