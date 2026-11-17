import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(os.name == "nt", "Desktop runtime requires Windows")
class DiagnosticsTest(unittest.TestCase):
    def test_legacy_translation_settings_move_into_active_model_only(self):
        from subtitle_relay.desktop import runtime

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"mt": "openai", "llm_model": "gpt-4.1-mini",
                                        "translation_before": "6", "translation_after": "4",
                                        "translation_prompt": "Use casual wording"}), encoding="utf-8")
            with patch.object(runtime, "CONFIG", path):
                settings = runtime.config()
            self.assertEqual(settings["translation_enhancements"], {
                "openai:gpt-4.1-mini": {"enabled": True, "previous_cues": 4, "prompt": "Use casual wording"},
            })
            self.assertNotIn("translation_before", settings)
            self.assertEqual(runtime.enhancement_key({**settings, "mt": "qwen-mt"}), "qwen-mt:qwen-mt-flash")

    def test_logs_are_created_only_when_diagnostics_are_enabled(self):
        from subtitle_relay.desktop import runtime

        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "relay.log"
            with patch.object(runtime, "diagnostics_enabled", return_value=False):
                with runtime.log_output(log, text=True) as output:
                    self.assertIsNone(output)
                self.assertFalse(log.exists())
            with patch.object(runtime, "diagnostics_enabled", return_value=True):
                with runtime.log_output(log, text=True) as output:
                    output.write("diagnostics\n")
                self.assertEqual(log.read_text(encoding="utf-8"), "diagnostics\n")
