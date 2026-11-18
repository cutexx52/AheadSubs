import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(os.name == "nt", "Desktop runtime requires Windows")
class DiagnosticsTest(unittest.TestCase):
    def test_user_data_is_shared_by_models_credentials_and_desktop(self):
        from aheadsubs.inference.chatgpt_auth import ChatGPTAccounts
        from aheadsubs.inference.qwen import paths
        from aheadsubs.paths import user_data_directory

        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"LOCALAPPDATA": folder}):
            current = Path(folder) / "AheadSubs"
            legacy = Path(folder) / "Subtitle Relay"

            self.assertEqual(user_data_directory(), current)
            legacy.mkdir()
            self.assertEqual(user_data_directory(), legacy)
            self.assertEqual(ChatGPTAccounts().path.parent, legacy)
            self.assertEqual(paths(None, "1.7b")[1].parent, legacy / "qwen")
            current.mkdir()
            self.assertEqual(user_data_directory(), current)

    def test_preset_preflight_reports_only_requested_missing_requirements(self):
        from aheadsubs.desktop import bridge, runtime

        with patch.object(bridge.shutil, "which", return_value="ffmpeg"), \
                patch.object(bridge.hardware, "vulkan_available", return_value=True) as vulkan, \
                patch.object(bridge.hardware, "cuda_available", return_value=False) as cuda, \
                patch.object(runtime, "config", return_value=runtime.DEFAULTS), \
                patch.dict(os.environ, {"DASHSCOPE_API_KEY": ""}):
            self.assertEqual(bridge.check_requirements(None), {"missing": []})
            vulkan.assert_not_called()
            cuda.assert_not_called()
            self.assertEqual(bridge.check_requirements("vulkan,cuda,dashscope"), {"missing": ["cuda", "dashscope"]})
            with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "sk-test-preset"}):
                self.assertEqual(bridge.check_requirements("dashscope"), {"missing": []})
                self.assertEqual(bridge.check_requirements("dashscope", "https://example.org"), {"missing": ["dashscope"]})

    def test_qwen_model_uninstall_protects_running_route_and_shared_assets(self):
        from aheadsubs.desktop import assets, bridge
        from aheadsubs.inference.qwen import paths

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable, model, aligner = paths(root, "1.7b")
            executable.parent.mkdir()
            smaller = paths(root, "0.6b")[1]
            for path in (executable, model, aligner, smaller):
                path.touch()
            with patch.object(assets, "DATA", root), patch.object(assets, "QWEN", root), \
                    patch.object(assets, "service_health", side_effect=[{}, {"local_models": ["qwen-1.7b"]},
                                                                       {"local_models": ["qwen-0.6b"]}]):
                for _ in range(2):
                    with self.assertRaises(assets.ModelRemovalError) as error:
                        assets.uninstall_model("qwen-1.7b", bridge.MODELS["qwen-1.7b"])
                    self.assertEqual(error.exception.code, "uninstall-active")
                self.assertTrue(model.exists())
                assets.uninstall_model("qwen-1.7b", bridge.MODELS["qwen-1.7b"])
            self.assertFalse(model.exists())
            self.assertTrue(all(path.exists() for path in (executable, aligner, smaller)))

    def test_uninstall_targets_only_the_selected_hugging_face_repository(self):
        from huggingface_hub.utils import DeleteCacheStrategy
        from aheadsubs.desktop import assets, bridge

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            hub = root / "hub"
            for name in ("models--Systran--faster-whisper-small", "models--Adom4600--nllb-200-distilled-600M-ct2-int8"):
                model = hub / name / "snapshots" / "a1b2c3" / "model.bin"
                model.parent.mkdir(parents=True)
                model.touch()
            with patch.object(assets, "DATA", root), patch.object(assets, "model_hub", return_value=hub), \
                    patch.object(assets, "service_health", return_value=None):
                with patch.object(DeleteCacheStrategy, "execute"), self.assertRaises(assets.ModelRemovalError) as error:
                    assets.uninstall_model("whisper-small", bridge.MODELS["whisper-small"])
                self.assertEqual(error.exception.code, "uninstall-failed")
                assets.uninstall_model("whisper-small", bridge.MODELS["whisper-small"])
            self.assertFalse((hub / "models--Systran--faster-whisper-small").exists())
            self.assertTrue((hub / "models--Adom4600--nllb-200-distilled-600M-ct2-int8").exists())

    def test_apply_minimax_with_protected_key_and_context_limit(self):
        from aheadsubs.desktop import bridge, credentials, runtime
        from aheadsubs.inference.providers import MINIMAX_MODEL

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            enhancement_key = f"minimax:{MINIMAX_MODEL}"
            enhancements = {"enabled": True, "previous_cues": 2, "prompt": "", "context_chars": 120}
            test_key = "sk-test-minimax"
            with patch.object(runtime, "DATA", root), patch.object(runtime, "CONFIG", root / "settings.json"), \
                    patch.object(runtime, "PAUSED", root / "paused"), patch.object(runtime, "service_health", return_value=None), \
                    patch.object(runtime, "start_locked") as start, patch.object(bridge.shutil, "which", return_value="ffmpeg"):
                status = bridge.apply({
                    "mt": "minimax",
                    "credentials": {"minimax": {"mode": "direct", "value": test_key}},
                    "translation_enhancements": {enhancement_key: enhancements},
                })
                start.assert_called_once_with(True, apply_saved=True, progress=None)
                self.assertEqual(runtime.enhancement_key(runtime.config()), enhancement_key)
                self.assertEqual(status["settings"]["translation_enhancements"][enhancement_key], enhancements)
                self.assertEqual(credentials.resolve(runtime.config(), "minimax"), test_key)
                self.assertEqual(status["credentials"]["minimax"]["mode"], "direct")
                self.assertNotIn(test_key, json.dumps(status))
                self.assertNotIn(test_key, runtime.CONFIG.read_text(encoding="utf-8"))

    def test_typed_credentials_are_encrypted_and_redacted_by_the_bridge(self):
        from aheadsubs.desktop import bridge, credentials, runtime

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
        from aheadsubs.desktop import credentials

        settings = {}
        credentials.update(settings, {"compatible-asr": {"mode": "direct", "value": "test-asr-key"}})
        self.assertEqual(credentials.resolve(settings, "compatible-asr", "http://[::1]:8000/v1"), "test-asr-key")
        self.assertEqual(credentials.resolve(settings, "compatible-asr", "https://example.com/v1"), "test-asr-key")
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            credentials.resolve(settings, "compatible-asr", "http://example.com/v1")

    def test_manual_player_folder_is_remembered_and_uninstall_removes_only_integration(self):
        from aheadsubs.desktop import assets, runtime

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            player = root / "PotPlayer Custom"
            player.mkdir()
            (player / "PotPlayerMini64.exe").touch()
            with patch.object(runtime, "DATA", root), patch.object(runtime, "CONFIG", root / "settings.json"):
                assets.configure_player("potplayer", str(player))
                self.assertEqual(assets.potplayer_directory(), player.resolve())
                self.assertTrue(assets.integration_status("potplayer")["configured"])
                extensions = player / "Extension" / "Subtitle" / "Translate"
                self.assertTrue((extensions / "SubtitleTranslate - AheadSubs.as").is_file())
                keep = extensions / "Other extension.as"
                keep.touch()
                assets.unconfigure_player("potplayer")
                self.assertTrue(keep.is_file())
                self.assertFalse(assets.integration_status("potplayer")["installed"])

    def test_mpv_manual_portable_configuration_leaves_user_files(self):
        from aheadsubs.desktop import assets, runtime

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            portable = root / "portable_config"
            portable.mkdir()
            (portable / "mpv.conf").touch()
            with patch.object(runtime, "DATA", root), patch.object(runtime, "CONFIG", root / "settings.json"):
                assets.configure_player("mpv", str(root))
                self.assertEqual(assets.mpv_directory(), portable.resolve())
                self.assertTrue(assets.integration_status("mpv")["configured"])
                self.assertTrue((portable / "scripts/aheadsubs.lua").is_file())
                self.assertTrue((portable / "script-opts/aheadsubs.conf").is_file())
                assets.unconfigure_player("mpv")
                self.assertTrue((portable / "mpv.conf").is_file())
                self.assertFalse(assets.integration_status("mpv")["installed"])

    def test_player_setup_reuses_installed_script_names(self):
        from aheadsubs.desktop import assets

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old_mpv = root / "scripts/subtitle_relay.lua"
            old_mpv.parent.mkdir()
            old_mpv.touch()
            old_potplayer = root / "SubtitleTranslate - Subtitle Relay Audio.as"
            old_potplayer.touch()

            assets.install_mpv(root)
            assets.install_potplayer(root)

            self.assertIn("AheadSubs", old_mpv.read_text(encoding="utf-8"))
            self.assertTrue((root / "script-opts/subtitle_relay.conf").is_file())
            self.assertFalse((old_mpv.parent / "aheadsubs.lua").exists())
            self.assertIn("AheadSubs.pyw", old_potplayer.read_text(encoding="utf-8"))
            self.assertFalse((root / "SubtitleTranslate - AheadSubs Audio.as").exists())

    def test_legacy_translation_settings_move_into_active_model_only(self):
        from aheadsubs.desktop import runtime

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
        from aheadsubs.desktop import runtime

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
