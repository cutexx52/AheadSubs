import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from subtitle_relay.providers import QwenMtTranslation, qwen_mt_credentials


class QwenMtTest(unittest.TestCase):
    endpoint = "https://workspace.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"

    def test_uses_one_plain_translation_request_per_cue(self):
        client = Mock()
        create = client.chat.completions.create
        create.side_effect = [SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=line))])
                              for line in ("你好。", "再見。")]
        translator = QwenMtTranslation(client, "qwen-mt-flash")
        self.assertEqual(translator.translate(["こんにちは。", "またね。"], "ja", "zh-TW"), ["你好。", "再見。"])
        for line, request in zip(("こんにちは。", "またね。"), create.call_args_list, strict=True):
            self.assertEqual(request.kwargs, {
                "model": "qwen-mt-flash", "messages": [{"role": "user", "content": line}],
                "extra_body": {"translation_options": {"source_lang": "Japanese",
                                                       "target_lang": "Traditional Chinese"}},
            })

    def test_accepts_workspace_endpoint_and_dedicated_key(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "sk-example-dedicated"}):
            self.assertEqual(qwen_mt_credentials(self.endpoint + "/"), (self.endpoint, "sk-example-dedicated"))
        with tempfile.TemporaryDirectory() as folder:
            key = Path(folder) / "model-studio-key.txt"
            key.write_text("DASHSCOPE_API_KEY=sk-example-file", encoding="utf-8")
            self.assertEqual(qwen_mt_credentials(self.endpoint, key), (self.endpoint, "sk-example-file"))
            key.write_text("LTAIexample\nexample-secret", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Qwen-MT"):
                qwen_mt_credentials(self.endpoint, key)

    def test_rejects_lookalike_endpoint(self):
        with self.assertRaisesRegex(ValueError, "Base URL"):
            qwen_mt_credentials(self.endpoint.replace(".com/", ".com.example.invalid/"))
