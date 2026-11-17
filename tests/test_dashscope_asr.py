import unittest

from subtitle_relay.inference.dashscope import DashScopeAudio
from subtitle_relay.inference.providers import Cue


class DashScopeAudioTest(unittest.TestCase):
    def test_keeps_final_sentence_timestamps_and_deduplicates_stream_updates(self):
        event = {"output": {"text": "こんにちは", "sentence": {
            "begin_time": 200, "end_time": 1250, "sentence_id": 1, "sentence_end": True, "text": "こんにちは",
        }}}
        intermediate = {"output": {"sentence": {"begin_time": 100, "sentence_end": False, "text": "こん"}}}
        self.assertEqual(DashScopeAudio._results([intermediate, event, event], None),
                         ("ja", [Cue(.2, 1.25, "こんにちは")]))

    def test_text_without_sentence_timestamps_is_not_published(self):
        with self.assertRaisesRegex(ValueError, "timestamps"):
            DashScopeAudio._results([{"output": {"text": "字幕"}}], "ja")
