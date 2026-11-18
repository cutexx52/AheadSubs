import io
import tempfile
import threading
import time
import unittest
import wave
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from subtitle_relay.inference.audio import SAMPLE_RATE, Segmentation, Segmenter, make_wav
from subtitle_relay.inference.providers import Cue
from subtitle_relay.inference.segmentation import plan_spans
from subtitle_relay.server.engine import Playback, Relay
from subtitle_relay.server.history import inspect_cache
from subtitle_relay.server.transcription import RETENTION_SECONDS, TranscriptionError


def samples(seconds, value=1):
    return make_wav(value.to_bytes(2, "little") * round(seconds * SAMPLE_RATE))


class FileTranscriptionTest(unittest.TestCase):
    def setUp(self):
        self.resources = self.enterContext(ExitStack())
        self.root = Path(self.resources.enter_context(tempfile.TemporaryDirectory()))

    def relay(self, recognizer, translator=None, *, chunk=1, **options):
        relay = Relay(self.root, recognizer, translator, "playback", workers=1, chunk=chunk, **options)
        self.resources.callback(relay.close)
        return relay

    def submit(self, relay, duration, language=None, value=1):
        with tempfile.NamedTemporaryFile(dir=relay.transcriptions.upload_directory, suffix=".wav",
                                         delete=False) as upload:
            upload.write(samples(duration, value))
        return relay.transcriptions.submit(Path(upload.name), duration, language)["id"]

    def wait_for(self, get_status, ready):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = get_status()
            if ready(status):
                return status
            time.sleep(0.02)
        self.fail(f"Timed out waiting for background work. Last status: {status}")

    def job_state(self, store, identifier, state):
        return self.wait_for(lambda: store.status(identifier), lambda status: status["state"] == state)

    def test_multichunk_automatic_transcription_keeps_overlapping_recognition_times(self):
        recognizer = Mock()
        recognizer.recognize.side_effect = [
            ("ja", [Cue(0.1, 0.4, "こんにちは"), Cue(0.3, 0.5, "hello", source_language="en")]),
            ("es", [Cue(0.05, 0.42, "hola")]),
            ("en", [Cue(0.02, 0.2, "goodbye")]),
        ]
        translator = Mock()
        relay = self.relay(recognizer, translator)
        store = relay.transcriptions
        identifier = self.submit(relay, 2.25, "auto")
        completed = self.job_state(store, identifier, "completed")
        self.assertEqual((completed["completed_chunks"], completed["total_chunks"]), (3, 3))
        self.assertIsNone(completed["language"])
        self.assertEqual(store.result(identifier), {
            "duration": 2.25, "text": "こんにちは hello hola goodbye",
            "segments": [
                {"start": 0.1, "end": 0.4, "text": "こんにちは"},
                {"start": 0.3, "end": 0.5, "text": "hello", "language": "en"},
                {"start": 1.05, "end": 1.42, "text": "hola"},
                {"start": 2.02, "end": 2.2, "text": "goodbye"},
            ],
        })
        self.assertEqual([call.args[1] for call in recognizer.recognize.call_args_list], [None] * 3)
        translator.translate.assert_not_called()
        self.assertEqual(list(store.inputs.iterdir()), [])

    def test_silence_completes_without_a_provider_call(self):
        recognizer = Mock()
        relay = self.relay(recognizer)
        store = relay.transcriptions
        identifier = self.submit(relay, 0.1, value=0)
        self.job_state(store, identifier, "completed")
        self.assertEqual(store.result(identifier), {"duration": 0.1, "text": "", "segments": []})
        recognizer.recognize.assert_not_called()

    def test_continuous_speech_has_no_duplicate_or_missing_input_at_chunk_edges(self):
        segmenter = Segmenter(Segmentation(enabled=False))
        segmenter.settings = Segmentation()

        def plan(pcm):
            frames = len(pcm) // 2
            return plan_spans(pcm, [(0, frames)], minimum=3 * SAMPLE_RATE, maximum=12 * SAMPLE_RATE,
                              preferred_pause=7200, padding=1280)

        segmenter._plan = plan
        recognizer = Mock()

        def recognize(wav, _):
            with wave.open(io.BytesIO(wav)) as audio:
                return "en", [Cue(0, audio.getnframes() / SAMPLE_RATE, "speech")]

        recognizer.recognize.side_effect = recognize
        relay = self.relay(recognizer, chunk=8, segmenter=segmenter)
        identifier = self.submit(relay, 48, value=1200)
        self.job_state(relay.transcriptions, identifier, "completed")
        segments = relay.transcriptions.result(identifier)["segments"]
        self.assertEqual([(segment["start"], segment["end"]) for segment in segments],
                         [(start, start + 8) for start in range(0, 48, 8)])

    def test_failed_job_can_resume_from_a_committed_chunk_after_service_restart(self):
        recognizer = Mock()
        recognizer.recognize.side_effect = [("en", [Cue(0.1, 0.3, "first")]), RuntimeError("private input")]
        first = Relay(self.root, recognizer, None, "profile", workers=1, chunk=1)
        try:
            identifier = self.submit(first, 1.5, "en")
            failed = self.job_state(first.transcriptions, identifier, "failed")
            self.assertEqual(failed["completed_chunks"], 1)
            self.assertEqual(failed["error_code"], "processing_failed")
            with self.assertRaisesRegex(TranscriptionError, "not completed"):
                first.transcriptions.result(identifier)
        finally:
            first.close()
        recognizer.reset_mock()
        recognizer.recognize.side_effect = None
        recognizer.recognize.return_value = "en", [Cue(0.1, 0.3, "second")]
        second = self.relay(recognizer, transcription_profile="profile")
        self.assertEqual(second.transcriptions.resume(identifier)["state"], "queued")
        self.job_state(second.transcriptions, identifier, "completed")
        self.assertEqual(second.transcriptions.result(identifier)["text"], "first second")
        self.assertEqual(recognizer.recognize.call_count, 1)
        self.assertEqual(recognizer.recognize.call_args.args[1], "en")

    def test_inflight_cancelled_chunk_does_not_commit(self):
        entered, release = threading.Event(), threading.Event()
        recognizer = Mock()

        def recognize(*_):
            entered.set()
            release.wait(5)
            return "en", [Cue(0.1, 0.3, "speech")]

        recognizer.recognize.side_effect = recognize
        relay = self.relay(recognizer)
        store = relay.transcriptions
        identifier = self.submit(relay, 0.5)
        try:
            self.assertTrue(entered.wait(5))
            self.assertEqual(store.cancel(identifier)["state"], "cancelled")
            with self.assertRaisesRegex(TranscriptionError, "cancelled chunk"):
                store.resume(identifier)
        finally:
            release.set()
        self.wait_for(lambda: store.inflight, lambda outstanding: outstanding is None)
        self.assertEqual(store.status(identifier)["completed_chunks"], 0)
        store.resume(identifier)
        self.job_state(store, identifier, "completed")
        self.assertEqual(store.result(identifier)["text"], "speech")
        self.assertEqual(recognizer.recognize.call_count, 2)

    def test_playback_takes_the_next_worker_slot_and_retains_its_srt_cache(self):
        entered, release = threading.Event(), threading.Event()
        order = []
        recognizer = Mock()

        def recognize(wav, source):
            order.append(source)
            if len(order) == 1:
                entered.set()
                release.wait(5)
            return source, [Cue(0.2, 0.3, "spoken")]

        recognizer.recognize.side_effect = recognize
        self.resources.enter_context(patch("subtitle_relay.server.engine.extract_audio", return_value=samples(1)))
        relay = self.relay(recognizer)
        store = relay.transcriptions
        identifier = self.submit(relay, 1.5, "ja")
        media = self.root / "playback.wav"
        media.write_bytes(samples(1))
        playback = Playback(media, 0, duration=1, source="en")
        try:
            self.assertTrue(entered.wait(5))
            relay.update("player", playback)
            self.assertEqual(relay.status()["workers"], {"busy": 1, "limit": 1})
        finally:
            release.set()
        visible = self.wait_for(lambda: relay.update("player", playback), lambda status: status["revision"] == 1)
        self.assertEqual(order, ["ja", "en"])
        self.assertEqual(store.status(identifier)["completed_chunks"], 1)
        srt = Path(visible["subtitle"]).read_text(encoding="utf-8")
        self.assertIn("00:00:00,000 --> 00:00:01,000", srt)
        inspection = inspect_cache(self.root / "cache.sqlite3")
        self.assertEqual(inspection["files"][0]["target_languages"], [])
        self.assertEqual(inspection["rows"][0]["original"], "spoken")
        self.assertIsNone(inspection["rows"][0]["translation"])
        self.assertEqual(relay.update("another-player", playback)["subtitle"], visible["subtitle"])
        relay.drop("player")
        relay.drop("another-player")
        self.job_state(store, identifier, "completed")
        self.assertEqual(order, ["ja", "en", "ja"])
        self.assertEqual(store.result(identifier)["segments"][0]["start"], 0.2)

    def test_expired_cancelled_input_is_purged(self):
        relay = self.relay(Mock())
        store = relay.transcriptions
        with relay.lock:
            identifier = self.submit(relay, 1)
            store.cancel(identifier)
            with relay.db:
                relay.db.execute("UPDATE transcription_jobs SET updated=?", (time.time() - RETENTION_SECONDS - 1,))
            store.next_maintenance = 0
            store.maintain()
        with self.assertRaisesRegex(TranscriptionError, "not found"):
            store.status(identifier)
        self.assertEqual(list(store.inputs.iterdir()), [])

    def test_audio_translation_only_profile_exposes_no_transcription_backend(self):
        speech_translator = Mock()
        relay = self.relay(None, speech_translator=speech_translator)
        self.assertFalse(relay.transcriptions.capabilities()["available"])
        with self.assertRaises(TranscriptionError) as error:
            self.submit(relay, 0.1)
        self.assertEqual(error.exception.code, "transcription_unavailable")
        speech_translator.speech_translate.assert_not_called()

    def test_second_service_cannot_recover_the_first_services_live_job(self):
        entered, release = threading.Event(), threading.Event()
        first_recognizer, second_recognizer = Mock(), Mock()

        def run_first(*_):
            entered.set()
            release.wait(5)
            return "en", [Cue(0.1, 0.3, "owner")]

        first_recognizer.recognize.side_effect = run_first
        first = Relay(self.root, first_recognizer, None, "playback", workers=1, chunk=1)
        try:
            identifier = self.submit(first, 0.5)
            self.assertTrue(entered.wait(5))
            second = self.relay(second_recognizer)
            self.assertFalse(second.transcriptions.capabilities()["available"])
            with self.assertRaises(TranscriptionError) as error:
                second.transcriptions.status(identifier)
            self.assertEqual(error.exception.code, "transcription_cache_in_use")
            media = self.root / "playback.wav"
            media.write_bytes(samples(0.5))
            second.update("second-player", Playback(media, 0, duration=0.5))
            second.drop("second-player")
            release.set()
            self.job_state(first.transcriptions, identifier, "completed")
            self.assertEqual(first.transcriptions.result(identifier)["text"], "owner")
        finally:
            release.set()
            first.close()
        restarted = self.relay(Mock())
        self.assertEqual(restarted.transcriptions.result(identifier)["text"], "owner")
