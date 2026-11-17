import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack, closing
from datetime import date, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from queue import Queue
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request

from subtitle_relay.__main__ import monitor_pipeline
from subtitle_relay.client import RelayClient
from subtitle_relay.inference.audio import make_wav
from subtitle_relay.inference.providers import Cue, QwenMtTranslation
from subtitle_relay.inference.usage import CloudMeter, CloudUsage, read_usage
from subtitle_relay.server.engine import Playback, Relay
from subtitle_relay.server.metrics import SAMPLE_LIMIT, WINDOW, Samples
from subtitle_relay.server.protocol import serve
from subtitle_relay.server.resources import gpu_totals


class CloudUsageTest(unittest.TestCase):
    def test_counts_cloud_requests_and_prices_only_known_quantities(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as databases:
            store = databases.enter_context(closing(CloudUsage(directory, today=lambda: date(2026, 11, 16))))
            provider = QwenMtTranslation(Mock(), "qwen-mt-flash")
            provider.usage_meter = CloudMeter(store, "dashscope", provider.model,
                                             "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
            reply = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="译文"))])
            provider.client.chat.completions.create.side_effect = [
                SimpleNamespace(**vars(reply), usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20)),
                reply,
                TimeoutError("private upstream details"),
            ]
            self.assertEqual(provider.translate(["private cue one", "private cue two"], "ja", "zh"), ["译文", "译文"])
            with self.assertRaises(TimeoutError):
                provider.translate(["private cue three"], "ja", "zh")

            chat = CloudMeter(store, "chatgpt", "gpt-test")
            with chat.call("mt") as usage:
                usage.tokens({"input_tokens": 30, "output_tokens": 5}, "input_tokens", "output_tokens")
            whisper = CloudMeter(store, "openai", "whisper-1")
            with whisper.call("asr") as usage:
                usage.audio = 30.5
            store.close()

            result = read_usage(store.path, date(2026, 11, 16))
            self.assertFalse(result["incomplete"])
            self.assertEqual(result["weeks"][0], "2026-11-16")
            rows = {row["provider"]: row for row in result["rows"]}
            dash = rows["dashscope"]
            self.assertEqual((dash["calls"], dash["failed"], dash["priced_calls"]), (3, 1, 1))
            self.assertEqual((dash["input_tokens"], dash["output_tokens"]), (100, 20))
            self.assertAlmostEqual(dash["estimated_usd"], (100 * 0.16 + 20 * 0.49) / 1_000_000)
            self.assertEqual(rows["chatgpt"]["priced_calls"], 0)
            self.assertEqual(rows["chatgpt"]["input_tokens"], 30)
            self.assertAlmostEqual(rows["openai"]["estimated_usd"], 0.00305)
            self.assertNotIn("private", str(result))

    def test_preserves_concurrent_counts_and_expires_week_on_startup(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as databases:
            day = date(2026, 1, 4)  # Sunday
            store = databases.enter_context(closing(CloudUsage(directory, today=lambda: day)))
            meter = CloudMeter(store, "openai", "gpt-4.1-mini")

            def call():
                with meter.call("mt") as usage:
                    usage.tokens(SimpleNamespace(prompt_tokens=100, completion_tokens=20,
                                                 prompt_tokens_details=SimpleNamespace(cached_tokens=60)))

            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda _: call(), range(24)))
            row, = store.snapshot()["rows"]
            self.assertEqual((row["week"], row["calls"], row["priced_calls"]), ("2025-12-29", 24, 24))
            self.assertAlmostEqual(row["estimated_usd"], 24 * (40 * 0.4 + 60 * 0.1 + 20 * 1.6) / 1_000_000)
            day += timedelta(weeks=7, days=1)
            self.assertEqual(store.snapshot()["rows"], [])
            store.close()

            reopened = databases.enter_context(closing(CloudUsage(directory, today=lambda: day)))
            with closing(sqlite3.connect(reopened.path)) as db:
                self.assertEqual(db.execute("SELECT week FROM weekly").fetchall(), [])

    def test_unavailable_usage_storage_cannot_fail_model_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "cache"
            root.touch()
            store = CloudUsage(root)
            with closing(store):
                with CloudMeter(store, "compatible", "model").call("mt"):
                    pass
                self.assertTrue(store.snapshot()["incomplete"])


class StatusTest(unittest.TestCase):
    def test_rollup_expires_samples_and_uses_nearest_rank(self):
        samples = Samples()
        for i in range(1, 101):
            samples.add(100, i)
        self.assertEqual(samples.summary(100), {"p50": 50, "p95": 95, "p99": 99, "count": 100})
        self.assertEqual(samples.summary(100 + WINDOW), {"p50": None, "p95": None, "p99": None, "count": 0})
        for i in range(SAMPLE_LIMIT + 2):
            samples.add(1000, i)
        self.assertEqual(samples.summary(1000)["count"], SAMPLE_LIMIT)
        self.assertEqual(samples.summary(1000)["p50"], SAMPLE_LIMIT // 2 + 1)

    def test_gpu_uses_service_pids_and_combines_percentages_on_shared_engine(self):
        result = gpu_totals([("pid_1_A", 20), ("pid_2_A", 30), ("pid_1_B", 40), ("pid_3_A", 99)],
                            [("pid_1_gpu", 1024), ("pid_2_gpu", 2048), ("pid_3_gpu", 4096)], {"1", "2"})
        self.assertEqual(result, {"gpu_percent": 50, "vram_bytes": 3072})
        self.assertEqual(gpu_totals(None, None, {"1"}), {"gpu_percent": None, "vram_bytes": None})

    def test_model_readiness_distinguishes_loaded_cloud_and_qwen_failure(self):
        args = SimpleNamespace(asr="qwen", asr_url="http://127.0.0.1:9001/v1", qwen_size="1.7b",
                               mt="compatible", llm_url="http://[::1]:9002/v1", no_vad=False,
                               vad_model="silero")
        backend = SimpleNamespace(model="test-model")
        read = monitor_pipeline(args, backend, backend, None, "", None)
        with patch("subtitle_relay.__main__.qwen_ready", side_effect=[True, False]):
            self.assertEqual([row["state"] for row in read()], ["loaded", "unverified", "loaded"])
            self.assertEqual(read()[0]["state"], "unavailable")
        self.assertFalse(hasattr(backend, "usage_meter"))

    def test_rtf_uses_actual_eof_duration_and_latency_ignores_immediate_cache_hits(self):
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "private movie.mkv"
            media.touch()
            now = 100

            def recognize(*_):
                nonlocal now
                now += 2
                return "ja", [Cue(0.25, 0.75, "test")]

            relay = Relay(directory, SimpleNamespace(recognize=recognize), None, "test")
            try:
                with relay.lock, patch("subtitle_relay.server.engine.time.monotonic", side_effect=lambda: now), \
                        patch("subtitle_relay.server.engine.extract_audio", return_value=make_wav(bytes(32000 * 4))):
                    playback = Playback(media, 0, target="ja", duration=4)
                    self.assertFalse(relay.update("first", playback, "potplayer")["nearby_cues"])
                    work = (relay._identity(playback), 0)
                    relay.inflight.add(work)
                    future = Future()
                    future.set_result(relay._process(playback, 0))
                    relay._finish(work, future)
                    now += 0.5
                    self.assertTrue(relay.update("first", playback, "potplayer")["nearby_cues"])
                    self.assertTrue(relay.update("cache hit", playback, "mpv")["nearby_cues"])
                    performance = relay.status()["performance"]
                    self.assertEqual(performance["rtf"]["p50"], 0.5)
                    self.assertEqual(performance["latency"], {"p50": 2.5, "p95": 2.5, "p99": 2.5, "count": 1})
                    self.assertEqual(relay.status()["active_sessions"], 2)
                    now += 10
                    self.assertEqual(relay.status()["active_sessions"], 0)
            finally:
                relay.close()

    def test_native_http_status_and_source_counts(self):
        events = Queue()
        translating, release = Event(), Event()

        class Translator:
            def translate(self, *_):
                translating.set()
                if not release.wait(5):
                    raise TimeoutError
                return ["text"]

        def bind(address, handler):
            server = ThreadingHTTPServer(address, handler)
            events.put(server.server_port)
            return server

        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "private movie.mkv"
            media.touch()
            relay = Relay(directory, None, Translator(), "test")
            with patch("subtitle_relay.server.protocol.ThreadingHTTPServer", side_effect=bind):
                thread = Thread(target=serve, args=(relay, 0, "test-token"), daemon=True)
                thread.start()
                port = events.get(timeout=5)
                client = RelayClient(port, "mpv")

                def status(**headers):
                    request = Request(client.url + "status", headers=headers)
                    with client.opener.open(request, timeout=3) as response:
                        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
                        return json.load(response)

                try:
                    for headers in ({}, {"X-AheadSubs-Status": "1", "Origin": "https://example.test"}):
                        with self.assertRaises(HTTPError) as error:
                            status(**headers)
                        self.assertEqual(error.exception.code, 403)
                        error.exception.close()
                    # Duration precedes the current playhead so the scheduler does not need media or a model.
                    client.send("playback", {"session": "mpv-1", "path": str(media), "position": 8, "duration": 4})
                    RelayClient(port, "private process").send(
                        "playback", {"session": "private session", "path": str(media), "position": 8, "duration": 4})
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        translation = pool.submit(RelayClient(port, "mcp").translate_text, "secret", "en", "zh")
                        try:
                            self.assertTrue(translating.wait(3))
                            active = status(**{"X-AheadSubs-Status": "1"})
                            self.assertEqual(active["active_sessions"], 2)
                            self.assertEqual(active["sources"], [
                                {"source": "mpv", "playback": 1, "text": 0},
                                {"source": "mcp", "playback": 0, "text": 1},
                                {"source": "http", "playback": 1, "text": 0},
                            ])
                            self.assertNotIn("private", str(active))
                        finally:
                            release.set()
                        self.assertEqual(translation.result(timeout=3), {"translation": "text"})
                    client.send("close", {"session": "mpv-1"})
                    self.assertEqual(status(**{"X-AheadSubs-Status": "1"})["sources"],
                                     [{"source": "http", "playback": 1, "text": 0}])
                    self.assertEqual(client.health()["active_sessions"], 1)
                finally:
                    client.send("shutdown", {"token": "test-token"})
                    thread.join(5)
                    relay.close()
