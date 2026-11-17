import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(os.name == "nt", "Desktop runtime requires Windows")
class DiagnosticsTest(unittest.TestCase):
    def test_typed_credentials_are_encrypted_and_redacted_by_the_bridge(self):
        from subtitle_relay.desktop import bridge, credentials, runtime

        test_key = "sk-test-desktop-credential"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(runtime, "DATA", root), patch.object(runtime, "CONFIG", root / "settings.json"), \
                    patch.object(runtime, "service_health", return_value=None):
                with patch("sys.stdin", io.StringIO(json.dumps({
                    "openai": {"mode": "direct", "value": test_key},
                }))):
                    bridge.run_command("save-credentials")
                self.assertNotIn(test_key, runtime.CONFIG.read_text(encoding="utf-8"))
                self.assertEqual(credentials.resolve(runtime.config(), "openai"), test_key)
                status = bridge.run_command("status")
                self.assertEqual(status["credentials"]["openai"], {"mode": "direct", "saved": True, "file": ""})
                self.assertNotIn(credentials.PRIVATE_FIELD, status["settings"])
                self.assertNotIn(test_key, json.dumps(status))

                key_file = root / "test-key.txt"
                key_file.write_text("OPENAI_API_KEY=sk-test-from-file\n", encoding="utf-8")
                settings = runtime.config()
                credentials.update(settings, {"openai": {"mode": "file", "value": str(key_file)}})
                self.assertEqual(credentials.resolve(settings, "openai"), "sk-test-from-file")
                self.assertFalse(credentials.public_state(settings)["openai"]["saved"])
                credentials.update(settings, {"openai": {"mode": "default"}})
                with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-env"}):
                    self.assertEqual(credentials.resolve(settings, "openai"), "sk-test-env")
                self.assertTrue(key_file.is_file())

    def test_compatible_credentials_require_https_away_from_loopback(self):
        from subtitle_relay.desktop import credentials

        settings = {}
        credentials.update(settings, {"compatible-asr": {"mode": "direct", "value": "test-asr-key"}})
        self.assertEqual(credentials.resolve(settings, "compatible-asr", "http://[::1]:8000/v1"), "test-asr-key")
        self.assertEqual(credentials.resolve(settings, "compatible-asr", "https://example.com/v1"), "test-asr-key")
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            credentials.resolve(settings, "compatible-asr", "http://example.com/v1")

    def test_manual_player_folder_is_remembered_and_uninstall_removes_only_integration(self):
        from subtitle_relay.desktop import assets, runtime

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            player = root / "PotPlayer Custom"
            player.mkdir()
            (player / "PotPlayerMini64.exe").touch()
            with patch.object(runtime, "DATA", root), patch.object(runtime, "CONFIG", root / "settings.json"):
                assets.configure_player("potplayer", str(player))
                self.assertEqual(assets.potplayer_directory(), player.resolve())
                self.assertTrue(assets.integration_status("potplayer")["configured"])
                keep = player / "Extension" / "Subtitle" / "Translate" / "Other extension.as"
                keep.touch()
                assets.unconfigure_player("potplayer")
                self.assertTrue(keep.is_file())
                self.assertFalse(assets.integration_status("potplayer")["installed"])

    def test_mpv_manual_portable_configuration_leaves_user_files(self):
        from subtitle_relay.desktop import assets, runtime

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            portable = root / "portable_config"
            portable.mkdir()
            (portable / "mpv.conf").touch()
            with patch.object(runtime, "DATA", root), patch.object(runtime, "CONFIG", root / "settings.json"):
                assets.configure_player("mpv", str(root))
                self.assertEqual(assets.mpv_directory(), portable.resolve())
                self.assertTrue(assets.integration_status("mpv")["configured"])
                assets.unconfigure_player("mpv")
                self.assertTrue((portable / "mpv.conf").is_file())
                self.assertFalse(assets.integration_status("mpv")["installed"])

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
