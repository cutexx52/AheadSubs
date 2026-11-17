import tempfile
import time
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from subtitle_relay.audio import Segmentation, Segmenter, make_wav
from subtitle_relay.engine import Playback, Relay, clear_dialogue, merge_cues
from subtitle_relay.protocol import playback_from_json
from subtitle_relay.providers import Cue, OpenAIWhisper


class RelayTest(unittest.TestCase):
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
