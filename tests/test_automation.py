import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from subtitle_relay.automation import invoke
from subtitle_relay.cli import main
from subtitle_relay.client import RelayHTTPError


class AutomationTest(unittest.TestCase):
    def test_cli_and_shared_operation_preserve_provider_error_code(self):
        client = Mock()
        client.translate_text.side_effect = RelayHTTPError(502, "Provider denied this request", "content_blocked")
        with patch("subtitle_relay.automation.RelayClient", return_value=client) as factory:
            expected = invoke("translate_text", {"text": "こんにちは", "source": "ja", "target": "zh"}, 9001)
            with redirect_stdout(StringIO()) as output:
                code = main(["translate-text", "こんにちは", "ja", "zh", "--port", "9001"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue()), expected)
        self.assertEqual(expected["error_code"], "content_blocked")
        factory.assert_called_with(9001)

    def test_generate_advances_bounded_windows_and_exports_after_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media, output, cached = (root / name for name in ("film.mkv", "film.zh.srt", "cached.srt"))
            media.touch()
            cached.write_bytes(b"srt data\r\n")
            client = Mock()
            client.send.side_effect = [
                {"ready_ahead": ready, "subtitle": str(cached), "subtitle_generation": "video",
                 "subtitle_has_cues": True} for ready in (64, 64, 2)
            ] + [{}]
            args = {"path": str(media), "output": str(output), "source": "auto"}
            with patch("subtitle_relay.automation.RelayClient", return_value=client), \
                 patch("subtitle_relay.automation.media_duration", return_value=130):
                result = invoke("generate_subtitles", args)
                duplicate = invoke("generate_subtitles", args)
            self.assertEqual(result, {"ok": True, "subtitle": str(output.resolve()), "duration": 130, "has_cues": True})
            self.assertEqual(duplicate["error_code"], "output_exists")
            self.assertEqual(output.read_bytes(), cached.read_bytes())
            calls = client.send.call_args_list
            windows = [call.args[1] for call in calls[:-1]]
            self.assertEqual([window["position"] for window in windows], [0, 64, 128])
            self.assertTrue(all(window["ahead"] == 60 for window in windows))
            self.assertIsNone(windows[0]["source"])
            self.assertNotIn("target", windows[0])
            self.assertEqual(calls[-1].args, ("close", {"session": windows[0]["session"]}))

    def test_generate_closes_session_and_leaves_destination_on_generation_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media, output = root / "film.mkv", root / "film.srt"
            media.touch()
            output.write_bytes(b"existing subtitle")
            client = Mock()
            client.send.side_effect = [
                {"ready_ahead": 64, "subtitle_generation": "old"},
                {"ready_ahead": 8, "subtitle_generation": "new"},
                {},
            ]
            with patch("subtitle_relay.automation.RelayClient", return_value=client), \
                 patch("subtitle_relay.automation.media_duration", return_value=72):
                result = invoke("generate_subtitles", {"path": str(media), "output": str(output), "overwrite": True})
            self.assertEqual(result["error_code"], "generation_changed")
            self.assertEqual(output.read_bytes(), b"existing subtitle")
            self.assertEqual(client.send.call_args.args[0], "close")
