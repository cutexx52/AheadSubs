import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from aheadsubs.client import RelayClient
from aheadsubs.inference.audio import Segmenter, Segmentation
from aheadsubs.server.engine import Relay
from aheadsubs.server.protocol import create_server


@unittest.skipUnless(os.name == "nt", "Windows desktop apply")
class LiveSettingsTest(unittest.TestCase):
    def setUp(self):
        from aheadsubs.__main__ import parse_command, segmentation, subtitle_profile
        from aheadsubs.desktop import runtime
        from aheadsubs.desktop.live_settings import LiveSettings

        self.runtime = runtime
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for name, value in {"DATA": self.root, "CONFIG": self.root / "settings.json",
                            "CONTROL": self.root / "token", "PAUSED": self.root / "paused"}.items():
            self.enterContext(patch.object(runtime, name, value))
        self.token = "test-control"
        runtime.CONTROL.write_text(self.token)
        settings = {**runtime.DEFAULTS, "asr": "local", "mt": "compatible", "pot_hotkey": "0"}
        self.enterContext(patch.dict(os.environ, RELAY_LLM_API_KEY=""))
        runtime.save_config(settings)
        _, args = parse_command(runtime.service_args(settings))
        self.speech, self.translation = Mock(), Mock(supports_style_prompt=True)
        # Keep model imports offline. Only the scheduler and HTTP service run in this fixture.
        segmenter = Segmenter(Segmentation(enabled=False))
        segmenter.settings = segmentation(args)
        profile = subtitle_profile(args, segmenter.settings, self.translation)
        self.relay = Relay(self.root / "cache", self.speech, self.translation, profile, segmenter=segmenter)
        self.addCleanup(self.relay.close)
        self.relay.stopping.set()
        self.relay.scheduler.join()
        live = LiveSettings(args, settings, self.relay, {"target": "zh"}, self.token)
        server = create_server(self.relay, 0, self.token, live.playback_defaults, apply_settings=live.apply)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.enterContext(patch.object(runtime, "PORT", server.server_port))
        self.client = RelayClient(server.server_port)
        self.enterContext(patch("aheadsubs.desktop.bridge.shutil.which", return_value="ffmpeg"))
        self.video = self.root / "movie.mp4"
        self.video.touch()

    def playback(self, **fields):
        return self.client.send("playback", {"session": "player", "path": str(self.video),
                                            "position": 0, "duration": 12, **fields})

    def test_running_service_applies_defaults_and_preserves_models_and_existing_work(self):
        from aheadsubs.desktop.bridge import apply

        before = self.playback()
        old = self.relay.pipeline
        spawn = self.enterContext(patch.object(self.runtime, "spawn"))
        progress = Mock()
        apply({"source": "ja", "target": "en", "bilingual": True}, progress, include_status=False)
        apply({}, progress, include_status=False)
        self.assertIs(self.relay.pipeline, old)
        self.assertNotEqual(before["subtitle_generation"], self.playback()["subtitle_generation"])
        playback = self.relay.sessions["player"].playback
        self.assertEqual((playback.source, playback.target, playback.bilingual), ("ja", "en", True))
        explicit = self.playback(source=None, target="zh", bilingual=False)
        self.assertEqual(before["subtitle_generation"], explicit["subtitle_generation"])

        apply({"chunk": "12", "vad_threshold": "0.65", "translation_enhancements": {
            "compatible:gpt-4.1-mini": {"enabled": True, "previous_cues": 0, "prompt": "Formal"}}},
            progress, include_status=False)
        current = self.relay.pipeline
        self.assertIs(current.recognizer, old.recognizer)
        self.assertIs(current.translator, old.translator)
        self.assertEqual(current.translation_settings.prompt, "Formal")
        self.assertEqual(current.segmenter.settings.vad_threshold, 0.65)
        self.assertNotEqual(explicit["subtitle_generation"],
                            self.playback(source=None, target="zh", bilingual=False)["subtitle_generation"])
        with patch("aheadsubs.server.engine.translate_chunk", return_value=[]) as process:
            self.relay._process(playback, 1, pipeline=old)
            self.relay._process(playback, 1, pipeline=current)
        self.assertEqual([(call.args[2], call.args[6].settings.vad_threshold)
                          for call in process.call_args_list], [(8, 0.5), (12, 0.65)])
        progress.assert_not_called()
        spawn.assert_not_called()

    def test_cloud_model_and_rotated_file_key_reuse_local_recognition(self):
        from aheadsubs.desktop.bridge import apply

        key = self.root / "key.txt"
        key.write_text("test-first")
        with patch("aheadsubs.__main__.openai_client") as client, patch.object(self.runtime, "spawn") as spawn:
            apply({"llm_model": "another-model", "credentials": {
                "compatible-mt": {"mode": "file", "value": str(key)}}}, include_status=False)
            self.assertEqual(self.relay.translator.model, "another-model")
            self.assertEqual(client.call_args.kwargs["api_key"], "test-first")
            key.write_text("test-second")
            apply({}, include_status=False)
            self.assertEqual(client.call_args.kwargs["api_key"], "test-second")
            self.assertIs(self.relay.recognizer, self.speech)
            spawn.assert_not_called()

    def test_local_device_change_requires_restart_on_every_attempt_until_service_changes(self):
        from aheadsubs.desktop.live_settings import credential_stamp

        self.runtime.save_config({**self.runtime.config(), "asr_device": "cuda"})
        for _ in range(2):
            reply = self.client.send("settings/apply", {"token": self.token,
                                     "credentials": credential_stamp(self.runtime.config(), self.token)})
            self.assertFalse(reply["applied"])
        self.assertIs(self.relay.recognizer, self.speech)

    def test_stopped_and_legacy_service_report_real_startup_stages(self):
        from aheadsubs.desktop.bridge import apply

        for health, expected in ((None, ["load-models"]), ({"pid": None}, ["restart-models", "load-models"])):
            stages = []
            with patch.object(self.runtime, "service_health", return_value=health), \
                    patch.object(self.runtime, "healthy", side_effect=[False, True] if health else [True]), \
                    patch("aheadsubs.client.RelayClient.send") as send, patch.object(self.runtime, "spawn") as spawn:
                spawn.return_value.poll.return_value = 0
                apply({}, stages.append, include_status=False)
                self.assertEqual(stages, expected)
                self.assertEqual([call.args[0] for call in send.call_args_list], ["shutdown"] if health else [])
                spawn.assert_called_once()
