import asyncio
import importlib.util
import io
import json
import shutil
import subprocess
import time
import unittest
import wave
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.client import HTTPConnection
from pathlib import Path
from queue import Queue
from tempfile import TemporaryDirectory
from threading import Barrier, Event, Thread, current_thread
from unittest.mock import Mock, patch

from subtitle_relay.inference.providers import Cue
from subtitle_relay.server import transcription_http
from subtitle_relay.server.engine import Playback, Relay
from subtitle_relay.server.protocol import create_server


JOBS = "/v1/transcription/jobs"
NATIVE_HEADERS = {"X-AheadSubs-Transcription": "1"}
OPENAI_PATH = "/v1/audio/transcriptions"
OPENAI_HEADERS = {"Authorization": "Bearer local"}
BOUNDARY = "aheadsubs-test-boundary"
UPLOAD_HEADERS = {"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"}
TEXT = "こんにちは hello"


def make_input_wav(pcm):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        audio.writeframes(pcm)
    return buffer.getvalue()


def multipart(fields, media, filename="private recording.wav", media_type="audio/wav"):
    body = bytearray()
    for name, value in fields:
        body.extend(f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                    f'{value}\r\n'.encode())
    if media is not None:
        body.extend(f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="file"; '
                    f'filename="{filename}"\r\nContent-Type: {media_type}\r\n\r\n'.encode())
        body.extend(media)
        body.extend(b"\r\n")
    body.extend(f"--{BOUNDARY}--\r\n".encode())
    return bytes(body)


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required for HTTP upload tests")
class TranscriptionHTTPTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.media = make_input_wav(b"\x80\x01\x80\xfe" * 4000)
        self.recognizer = Mock()
        self.recognizer.recognize.side_effect = self.recognize
        self.translator = Mock()
        self.relay = Relay(self.root, self.recognizer, self.translator, "test", workers=1)
        self.addCleanup(self.relay.close)
        self.server = create_server(self.relay, 0)
        self.addCleanup(self.server.server_close)
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def recognize(self, wav, source):
        with wave.open(io.BytesIO(wav), "rb") as audio:
            self.assertEqual((audio.getnchannels(), audio.getsampwidth(), audio.getframerate()), (1, 2, 16000))
        return source or "ja", [Cue(0.23, 0.61, "こんにちは", source_language="ja"),
                                Cue(0.52, 0.80, "hello", source_language="en")]

    def stop_server(self):
        self.server.shutdown()
        self.thread.join(5)
        self.assertFalse(self.thread.is_alive())

    def request(self, method, path, *, headers=None, body=None):
        client = HTTPConnection("127.0.0.1", self.server.server_port, timeout=8)
        try:
            client.request(method, path, body=body, headers=headers or {})
            with client.getresponse() as response:
                data = response.read()
                if response.headers.get_content_type() == "application/json" and data:
                    data = json.loads(data)
                return response.status, data
        finally:
            client.close()

    def upload(self, path, fields=(), *, media=None, headers=None, **file_options):
        return self.request("POST", path, headers=UPLOAD_HEADERS | (headers or {}),
                            body=multipart(fields, self.media if media is None else media, **file_options))

    def native(self, method, path):
        return self.request(method, path, headers=NATIVE_HEADERS)

    def wait_until_completed(self, path):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            status, data = self.native("GET", path)
            self.assertEqual(status, 200, data)
            if data["state"] == "completed":
                return
            self.assertIn(data["state"], {"queued", "running"}, data)
            time.sleep(0.05)
        self.fail("Transcription did not complete")

    def attach_player(self):
        player_media = self.root / "existing.wav"
        player_media.write_bytes(self.media)
        self.relay.update("player", Playback(player_media, 32, duration=1))
        self.addCleanup(self.relay.drop, "player")

    def test_job_cancel_resume_and_unpadded_result(self):
        self.attach_player()
        status, submitted = self.upload(JOBS, [("language", "auto")], headers=NATIVE_HEADERS)
        self.assertEqual(status, 202, submitted)
        job = f"{JOBS}/{submitted['id']}"
        self.assertEqual(submitted["state"], "queued")
        self.assertEqual(self.native("GET", f"{job}/result")[0], 409)
        self.assertEqual(self.native("POST", f"{job}/cancel")[1]["state"], "cancelled")
        self.recognizer.recognize.assert_not_called()
        for path in self.relay.transcriptions.upload_directory.iterdir():
            self.assertNotIn("private recording", path.name)
        self.assertEqual(self.native("POST", f"{job}/resume")[1]["state"], "queued")
        self.relay.drop("player")
        self.wait_until_completed(job)
        status, result = self.native("GET", f"{job}/result")
        self.assertEqual(status, 200, result)
        self.assertEqual(result["text"], TEXT)
        self.assertAlmostEqual(result["duration"], 1, places=3)
        self.assertEqual(result["segments"], [
            {"start": 0.23, "end": 0.61, "text": "こんにちは", "language": "ja"},
            {"start": 0.52, "end": 0.80, "text": "hello", "language": "en"},
        ])
        self.assertTrue({"words", "speakers", "confidence"}.isdisjoint(result))
        self.assertNotIn("private recording", str(submitted) + str(result))
        self.assertNotIn(str(self.root), str(submitted) + str(result))
        self.assertIsNone(self.recognizer.recognize.call_args.args[1])
        self.translator.translate.assert_not_called()
        self.assertEqual(self.native("DELETE", job)[0], 204)
        self.assertEqual(self.native("GET", job)[0], 404)
        self.assertEqual(list(self.relay.transcriptions.upload_directory.iterdir()), [])

    def test_loopback_request_boundary(self):
        capabilities = "/v1/transcription/capabilities"
        self.assertEqual(self.request("GET", capabilities)[0], 403)
        status, data = self.native("GET", capabilities)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["model"], "aheadsubs")
        self.assertEqual(data["task"], "transcribe")
        self.assertTrue(data["segment_timestamps"])
        self.assertEqual(set(data["response_formats"]), {"json", "text"})
        self.assertTrue({"word_timestamps", "diarization", "confidence"}.isdisjoint(data))
        self.assertEqual(self.upload(JOBS)[0], 403)
        self.assertEqual(self.upload(OPENAI_PATH, [("model", "aheadsubs")])[0], 401)
        for header in ({"Origin": "https://example.test"}, {"Sec-Fetch-Site": "same-origin"},
                       {"Host": "example.test"}):
            with self.subTest(header=header):
                self.assertEqual(self.upload(OPENAI_PATH, [("model", "aheadsubs")],
                                             headers=OPENAI_HEADERS | header)[0], 403)
        self.recognizer.recognize.assert_not_called()

    def test_rejected_uploads_leave_no_staged_audio(self):
        for fields in ([("model", "other")], [("model", "aheadsubs"), ("stream", "true")],
                       [("model", "aheadsubs"), ("timestamp_granularities[]", "word")],
                       [("model", "aheadsubs"), ("response_format", "verbose_json")],
                       [("model", "aheadsubs"), ("model", "aheadsubs")],
                       [("model", "aheadsubs"), ("path", "C:/private.wav")]):
            with self.subTest(fields=fields):
                status, data = self.upload(OPENAI_PATH, fields, headers=OPENAI_HEADERS)
                self.assertEqual(status, 400, data)
                self.assertIsInstance(data["error"]["code"], str)
        status, data = self.upload(JOBS, media=b"this is not audio", headers=NATIVE_HEADERS)
        self.assertEqual(status, 415, data)
        self.assertIsInstance(data["error_code"], str)
        self.assertNotIn("this is not audio", str(data))
        self.assertNotIn(str(self.root), str(data))
        status, data = self.request("POST", JOBS, headers=NATIVE_HEADERS | UPLOAD_HEADERS
                                    | {"Content-Length": "99999999"}, body=b"")
        self.assertEqual(status, 413, data)
        self.assertEqual(list(self.relay.transcriptions.upload_directory.iterdir()), [])
        self.recognizer.recognize.assert_not_called()

    def test_m4a_upload_with_metadata_at_end(self):
        media = self.root / "input.m4a"
        # Ordinary M4A puts the metadata atom after the audio and needs seekable input.
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", "pipe:0", "-c:a", "aac", str(media)],
                       input=self.media, check=True, timeout=10)
        content = media.read_bytes()
        self.assertLess(content.index(b"mdat"), content.index(b"moov"))
        status, data = self.upload(OPENAI_PATH, [("model", "aheadsubs")], media=content, headers=OPENAI_HEADERS,
                                   filename="recording.m4a", media_type="audio/mp4")
        self.assertEqual(status, 200, data)
        self.assertEqual(data, {"text": TEXT})

    def test_decoded_duration_is_bounded_before_queueing(self):
        long_audio = make_input_wav(b"\x80\x01\x80\xfe" * 8000)
        with patch.object(transcription_http, "MAX_JOB_DURATION", 1):
            status, data = self.upload(JOBS, media=long_audio, headers=NATIVE_HEADERS)
        self.assertEqual(status, 413, data)
        self.assertEqual(data["error_code"], "audio_too_long")
        self.assertEqual(list(self.relay.transcriptions.upload_directory.iterdir()), [])
        self.recognizer.recognize.assert_not_called()

    def test_concurrent_upload_limit_releases_slots_after_failure(self):
        entered = Barrier(3)
        release = Event()
        decode_upload = transcription_http.decode_upload

        def hold_decode(*args):
            entered.wait(timeout=5)
            if not release.wait(5):
                raise TimeoutError("Test did not release decoder")
            return decode_upload(*args)

        with patch.object(transcription_http, "decode_upload", side_effect=hold_decode):
            with ThreadPoolExecutor(max_workers=2) as clients:
                uploads = [clients.submit(self.upload, JOBS, media=b"invalid", headers=NATIVE_HEADERS)
                           for _ in range(2)]
                try:
                    entered.wait(timeout=5)
                    status, data = self.upload(JOBS, headers=NATIVE_HEADERS)
                    self.assertEqual(status, 429, data)
                    self.assertEqual(data["error_code"], "upload_busy")
                finally:
                    release.set()
                for upload in uploads:
                    self.assertEqual(upload.result(timeout=5)[0], 415)
        self.assertEqual(self.upload(JOBS, media=b"invalid", headers=NATIVE_HEADERS)[0], 415)
        self.assertEqual(list(self.relay.transcriptions.upload_directory.iterdir()), [])

    def test_compatible_wait_timeout_discards_queued_media(self):
        self.attach_player()
        with patch.object(transcription_http, "COMPATIBLE_TIMEOUT", 0.1):
            status, data = self.upload(OPENAI_PATH, [("model", "aheadsubs")], headers=OPENAI_HEADERS)
        self.assertEqual(status, 504, data)
        self.assertEqual(data["error"]["code"], "transcription_timeout")
        self.assertEqual(list(self.relay.transcriptions.upload_directory.iterdir()), [])
        self.recognizer.recognize.assert_not_called()

    def test_disconnect_during_upload_removes_staged_media(self):
        receiving = Queue()
        receive_upload = transcription_http.receive_upload

        def observe_upload(*args, **kwargs):
            receiving.put(current_thread())
            return receive_upload(*args, **kwargs)

        partial = multipart([], self.media)[:512]
        with patch.object(transcription_http, "receive_upload", side_effect=observe_upload):
            with closing(HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)) as client:
                client.request("POST", JOBS, body=partial, headers=NATIVE_HEADERS | UPLOAD_HEADERS
                               | {"Content-Length": str(len(partial) + 1000)})
                handler = receiving.get(timeout=5)
            handler.join(5)
        self.assertFalse(handler.is_alive())
        self.assertEqual(list(self.relay.transcriptions.upload_directory.iterdir()), [])
        self.assertEqual(list(self.relay.transcriptions.inputs.iterdir()), [])
        self.recognizer.recognize.assert_not_called()

    def test_compatible_client_disconnect_discards_queued_media(self):
        self.attach_player()
        submitted = Queue()
        store = self.relay.transcriptions
        submit = store.submit

        def observe_job(*args, **kwargs):
            job = submit(*args, **kwargs)
            submitted.put((current_thread(), job["id"]))
            return job

        payload = multipart([("model", "aheadsubs")], self.media)
        with patch.object(store, "submit", side_effect=observe_job):
            with closing(HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)) as client:
                client.request("POST", OPENAI_PATH, body=payload, headers=OPENAI_HEADERS | UPLOAD_HEADERS)
                handler, identifier = submitted.get(timeout=5)
                self.assertEqual(store.status(identifier)["state"], "queued")
            handler.join(5)
        self.assertFalse(handler.is_alive())
        self.assertEqual(self.native("GET", f"{JOBS}/{identifier}")[0], 404)
        self.assertEqual(list(store.inputs.iterdir()), [])
        self.recognizer.recognize.assert_not_called()

    @unittest.skipUnless(importlib.util.find_spec("openai"), "OpenAI SDK is not installed")
    def test_openai_sdk_json_text_and_no_speech(self):
        from openai import BadRequestError, DefaultHttpxClient, OpenAI

        with OpenAI(api_key="local", base_url=self.base_url, max_retries=0, timeout=8,
                    http_client=DefaultHttpxClient(trust_env=False)) as sdk:
            files = {"file": ("recording.wav", self.media, "audio/wav"), "model": "aheadsubs"}
            result = sdk.audio.transcriptions.create(**files)
            self.assertEqual(result.model_dump(exclude_none=True), {"text": TEXT})
            self.assertIsNone(self.recognizer.recognize.call_args.args[1])
            plain = sdk.audio.transcriptions.create(**files, response_format="text", language="ja", stream=False)
            self.assertEqual(plain, TEXT)
            self.assertEqual(self.recognizer.recognize.call_args.args[1], "ja")
            with self.assertRaises(BadRequestError) as rejected:
                sdk.audio.transcriptions.create(**files, response_format="verbose_json",
                                                timestamp_granularities=["word"])
            self.assertIsInstance(rejected.exception.code, str)
            self.recognizer.recognize.side_effect = None
            self.recognizer.recognize.return_value = ("", [])
            silence = sdk.audio.transcriptions.create(
                file=("silence.wav", make_input_wav(bytes(16000))), model="aheadsubs",
            )
            self.assertEqual(silence.text, "")
        self.translator.translate.assert_not_called()
        self.assertEqual(list(self.relay.transcriptions.upload_directory.iterdir()), [])

    @unittest.skipUnless(importlib.util.find_spec("pipecat"), "Pipecat is not installed")
    def test_pipecat_segmented_openai_stt(self):
        from openai import DefaultAsyncHttpxClient
        from pipecat.frames.frames import TranscriptionFrame
        from pipecat.services.openai.stt import OpenAISTTService

        async def transcribe():
            async with DefaultAsyncHttpxClient(trust_env=False, timeout=8) as http_client:
                service = OpenAISTTService(
                    api_key="local", base_url=self.base_url, http_client=http_client,
                    settings=OpenAISTTService.Settings(model="aheadsubs", language="ja"),
                )
                return [frame async for frame in service.run_stt(self.media)]

        frame, = asyncio.run(transcribe())
        self.assertIsInstance(frame, TranscriptionFrame)
        self.assertEqual(frame.text, TEXT)
        self.assertIsNone(getattr(frame, "speaker", None))
        self.assertEqual(self.recognizer.recognize.call_args.args[1], "ja")
