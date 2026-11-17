import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from subtitle_relay.inference.audio import Segmentation, make_wav
from subtitle_relay.inference.providers import ChatTranslation, Cue, QwenMtTranslation
from subtitle_relay.server.engine import Playback, Relay, TranslationFailure, TranslationSettings, translate_chunk


def chat_response(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def silence(seconds):
    return make_wav(b"\0" * (seconds * 32000))


class TranslationContextTest(unittest.TestCase):
    def test_contextual_seek_sends_only_the_requested_number_of_preceding_cues(self):
        media = Path("movie.mp4")
        segmenter = SimpleNamespace(settings=Segmentation(), iter_spans=lambda _: [
            (0, silence(4)), (4, silence(10)), (14, silence(6)),
        ])
        recognizer = Mock()
        recognizer.recognize.side_effect = [
            ("ja", [Cue(0.1, 0.4, "older"), Cue(0.5, 1.5, "preamble with a long preceding cue")]),
            ("ja", [Cue(0.8, 1.6, "one"), Cue(2, 3.4, "two")]),
            ("ja", [Cue(0.4, 1, "following")]),
        ]
        client = Mock()
        client.chat.completions.create.return_value = chat_response('{"1":"二","0":"一"}')
        translator = ChatTranslation(client, "gpt-test")
        with patch("subtitle_relay.server.engine.extract_audio", return_value=silence(20)) as extract:
            result = translate_chunk(Playback(media, 22, source="ja"), 2, 10, recognizer, translator,
                                     segmenter=segmenter,
                                     translation_settings=TranslationSettings(1, "Use casual wording", 20))

        extract.assert_called_once_with(media, 0, 16, 16)
        payload = json.loads(client.chat.completions.create.call_args.kwargs["messages"][1]["content"])
        self.assertEqual(payload, {
            "source": "ja", "target": "zh", "lines": {"0": "one", "1": "two"},
            "previous": ["a long preceding cue"], "style": "Use casual wording",
        })
        self.assertEqual(result, [Cue(20.8, 21.6, "一", "one", source_language="ja"),
                                  Cue(22, 23.4, "二", "two", source_language="ja")])

    def test_adaptive_span_crossing_chunk_boundary_is_recognized_only_by_its_owner(self):
        segmenter = SimpleNamespace(settings=Segmentation(), planning_margin=12,
                                    iter_spans=lambda _: [(7, silence(4))])
        recognizer = Mock()
        recognizer.recognize.return_value = "ja", [Cue(0.25, 1.5, "始まり")]
        translator = Mock()
        translator.translate.return_value = ["开头"]
        with patch("subtitle_relay.server.engine.extract_audio", return_value=silence(22)):
            playback = Playback(Path("movie.mp4"), 7.5, source="ja")
            self.assertEqual(translate_chunk(playback, 0, 8, recognizer, translator, segmenter=segmenter), [])
            actual = translate_chunk(playback, 1, 8, recognizer, translator, segmenter=segmenter)
        self.assertEqual(actual, [Cue(7.25, 8.5, "开头", "始まり", source_language="ja")])
        self.assertEqual(recognizer.recognize.call_count, 1)

    def test_rejects_chat_output_that_includes_context_or_omits_a_line(self):
        client = Mock()
        translator = ChatTranslation(client, "gpt-test")
        for payload in ('{"0":"甲","1":"乙"}', '{}'):
            with self.subTest(payload=payload):
                client.chat.completions.create.return_value = chat_response(payload)
                with self.assertRaisesRegex(ValueError, "line IDs"):
                    translator.translate_with_context(["main"], "ja", "zh", previous=["previous"])

    def test_chat_completion_filter_uses_same_category_as_a_provider_error_code(self):
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="content_filter")])
        translator = ChatTranslation(client, "test-chat")
        recognizer = Mock()
        recognizer.recognize.return_value = "ja", [Cue(2, 3, "recognized line")]
        with patch("subtitle_relay.server.engine.extract_audio", return_value=silence(8)):
            result = translate_chunk(Playback(Path("movie.mp4"), 0, source="ja"),
                                     0, 8, recognizer, translator)
        self.assertEqual(result, [Cue(2, 3, "", "recognized line", "content_blocked", "ja")])

    def test_failed_translation_retains_original_cue_and_provider_cause(self):
        recognizer = Mock()
        recognizer.recognize.return_value = "ja", [Cue(2, 3, "recognized line")]
        provider_error = RuntimeError("upstream failed")
        translator = Mock()
        translator.translate.side_effect = provider_error
        with patch("subtitle_relay.server.engine.extract_audio", return_value=silence(12)), \
             self.assertRaises(TranslationFailure) as failure:
            translate_chunk(Playback(Path("movie.mp4"), 9, source="ja"), 1, 8, recognizer, translator)
        self.assertIs(failure.exception.__cause__, provider_error)
        self.assertEqual(failure.exception.cues, [Cue(8, 9, "recognized line", source_language="ja")])

    def test_qwen_flash_sends_english_style_separately_and_lite_omits_it(self):
        prompt = "Use conversational subtitle wording."
        for model in ("qwen-mt-flash", "qwen-mt-plus", "qwen-mt-lite"):
            with self.subTest(model=model):
                client = Mock()
                client.chat.completions.create.return_value = chat_response("你好")
                translator = QwenMtTranslation(client, model)
                settings = TranslationSettings(3, prompt).for_translator(translator)
                self.assertEqual(settings.previous_cues, 0)
                self.assertEqual(translator.translate_with_context(["main"], "ja", "zh", previous=["past"],
                                                                 prompt=prompt), ["你好"])
                request = client.chat.completions.create.call_args.kwargs
                self.assertEqual(request["messages"], [{"role": "user", "content": "main"}])
                domains = request["extra_body"]["translation_options"].get("domains")
                self.assertEqual(domains, None if model.endswith("lite") else prompt)

    def test_context_and_style_have_stable_cache_identity_without_changing_default_key(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            file = root / "movie.mp4"
            file.touch()
            playback = Playback(file, 22, source="ja")
            metadata = file.stat()
            old_identity = ["test", 8, os.path.normcase(str(file)), 0, metadata.st_mtime_ns, 0, "ja", "zh"]
            old_key = hashlib.sha256(json.dumps(old_identity).encode()).hexdigest()
            translator = ChatTranslation(Mock(), "gpt-test")

            def identity(settings):
                relay = Relay(root, None, translator, "test", translation_settings=settings)
                try:
                    return relay._identity(playback)
                finally:
                    relay.close()

            self.assertEqual(identity(TranslationSettings()), old_key)
            contextual = identity(TranslationSettings(3, "plain"))
            self.assertEqual(contextual, identity(TranslationSettings(3, " plain ")))
            self.assertNotEqual(contextual, old_key)
            self.assertNotEqual(contextual, identity(TranslationSettings(4, "plain")))
            self.assertNotEqual(contextual, identity(TranslationSettings(3, "plain", 120)))
            self.assertNotEqual(contextual, identity(TranslationSettings(3, "formal")))
