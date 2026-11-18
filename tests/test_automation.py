import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from string import Formatter
from unittest.mock import MagicMock, Mock, patch

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from aheadsubs.automation import invoke
from aheadsubs.automation_text import MESSAGES
from aheadsubs.cli import main
from aheadsubs.client import RelayHTTPError


class AutomationTest(unittest.TestCase):
    def test_locales_preserve_protocol_and_fall_back_to_english(self):
        messages = []
        for language in ("en", "zh-CN", "fr-FR"):
            with patch.dict(os.environ, {"AHEADSUBS_UI_LOCALE": language}):
                result = invoke("close_playback", {})
                self.assertEqual(result["error_code"], "invalid_arguments")
                self.assertIn("session", result["error"])
                messages.append(result["error"])
        self.assertNotEqual(messages[0], messages[1])
        self.assertEqual(messages[0], messages[2])
        for key, variants in MESSAGES.items():
            fields = [{name for _, name, _, _ in Formatter().parse(value) if name} for value in variants]
            self.assertEqual(fields[0], fields[1], key)

    def test_mcp_discovers_localized_schema_and_returns_shared_error(self):
        async def check():
            params = StdioServerParameters(command=sys.executable, args=["-m", "aheadsubs.cli", "mcp"],
                                           cwd=Path(__file__).resolve().parents[1],
                                           env={"AHEADSUBS_UI_LOCALE": "zh-CN"})
            with anyio.fail_after(20):
                async with stdio_client(params) as streams, ClientSession(*streams) as client:
                    await client.initialize()
                    tools = {tool.name: tool for tool in (await client.list_tools()).tools}
                    generation = tools["aheadsubs_generate_subtitles"]
                    self.assertEqual(set(generation.input_schema["required"]), {"path", "output"})
                    self.assertEqual(generation.input_schema["properties"]["path"]["description"], "本机媒体文件路径")
                    result = await client.call_tool("aheadsubs_close_playback", {})
                    self.assertTrue(result.is_error)
                    with patch.dict(os.environ, {"AHEADSUBS_UI_LOCALE": "zh-CN"}):
                        self.assertEqual(result.structured_content, invoke("close_playback", {}))

        anyio.run(check)

    @unittest.skipUnless(os.name == "nt", "Windows user PATH registration")
    def test_desktop_bridge_registers_cli_without_changing_other_path_entries(self):
        from aheadsubs.desktop import automation
        from aheadsubs.desktop.bridge import run_command

        with tempfile.TemporaryDirectory(prefix="接入 ") as directory:
            root = Path(directory)
            cli = root / "cli"
            cli.mkdir()
            (cli / "aheadsubs.exe").touch()
            original = r"%SystemRoot%\Other;C:\Tools"
            entries = {"Path": original}
            registry = automation.winreg

            def write(_, name, __, kind, value):
                self.assertEqual(kind, registry.REG_EXPAND_SZ)
                entries[name] = value

            with patch.object(automation.runtime, "ROOT", root), patch.object(automation.runtime, "DATA", root / "data"), \
                 patch.object(registry, "OpenKey", return_value=MagicMock()), \
                 patch.object(registry, "CreateKeyEx", return_value=MagicMock()), \
                 patch.object(registry, "QueryValueEx", side_effect=lambda _, name: (entries[name], registry.REG_EXPAND_SZ)), \
                 patch.object(registry, "SetValueEx", side_effect=write), patch.object(automation.ctypes, "windll", MagicMock()):
                initial = run_command("automation")
                self.assertFalse(initial["cli_installed"])
                self.assertFalse(initial["mcp_enabled"])
                for _ in range(2):
                    self.assertTrue(run_command("automation", "cli-install")["cli_installed"])
                self.assertEqual(entries["Path"], f"{cli};{original}")
                self.assertFalse(run_command("automation", "cli-remove")["cli_installed"])
                self.assertEqual(entries["Path"], original)
                self.assertTrue(run_command("automation", "mcp-enable")["mcp_enabled"])
                self.assertFalse(run_command("automation", "mcp-disable")["mcp_enabled"])

    def test_cli_and_shared_operation_preserve_provider_error_code(self):
        client = Mock()
        client.translate_text.side_effect = RelayHTTPError(502, "Provider denied this request", "content_blocked")
        with patch("aheadsubs.automation.RelayClient", return_value=client) as factory:
            expected = invoke("translate_text", {"text": "こんにちは", "source": "ja", "target": "zh"}, 9001)
            with redirect_stdout(StringIO()) as output:
                code = main(["translate-text", "こんにちは", "ja", "zh", "--port", "9001"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue()), expected)
        self.assertEqual(expected["error_code"], "content_blocked")
        factory.assert_called_with(9001, "cli")

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
            with patch("aheadsubs.automation.RelayClient", return_value=client), \
                 patch("aheadsubs.automation.media_duration", return_value=130):
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
            with patch("aheadsubs.automation.RelayClient", return_value=client), \
                 patch("aheadsubs.automation.media_duration", return_value=72):
                result = invoke("generate_subtitles", {"path": str(media), "output": str(output), "overwrite": True})
            self.assertEqual(result["error_code"], "generation_changed")
            self.assertEqual(output.read_bytes(), b"existing subtitle")
            self.assertEqual(client.send.call_args.args[0], "close")
