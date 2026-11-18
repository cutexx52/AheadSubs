"""Loopback file transcription and the OpenAI Audio API subset."""
import os
import re
import select
import socket
import sqlite3
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from threading import BoundedSemaphore

from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser, parse_options_header

from ..inference.audio import SAMPLE_RATE
from .transcription import MODEL, TranscriptionError


COMPATIBLE_ROUTE = "/v1/audio/transcriptions"
CAPABILITIES_ROUTE = "/v1/transcription/capabilities"
JOBS_ROUTE = "/v1/transcription/jobs"
JOB_ROUTE = re.compile(rf"{JOBS_ROUTE}/([0-9a-f]{{32}})(?:/(result|cancel|resume))?")
MAX_UPLOAD_BYTES = 25_000_000
MAX_MULTIPART_OVERHEAD = 16_384
MAX_JOB_DURATION = 7200
MAX_COMPATIBLE_DURATION = 900
MAX_ACTIVE_UPLOADS = 2
UPLOAD_TIMEOUT = 30
DECODE_TIMEOUT = 60
COMPATIBLE_TIMEOUT = 180
POLL_INTERVAL = 0.2
MEDIA_FORMATS = ("aac", "flac", "m4a", "mkv", "mov", "mp3", "mp4", "ogg", "opus", "wav", "webm")
DEMUXERS = "aac,flac,matroska,webm,mov,mp4,m4a,3gp,3g2,mj2,mp3,ogg,wav"


class RequestError(ValueError):
    def __init__(self, status, code, message, param=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.param = param


def invalid_multipart():
    return RequestError(400, "invalid_multipart", "Send one file in a valid multipart/form-data request")


def upload_too_large():
    return RequestError(413, "upload_too_large", "Uploaded audio exceeds the byte limit", "file")


class MultipartUpload:
    """Stream only file data to disk and keep form parameters small."""

    def __init__(self, boundary, upload, allowed_fields):
        self.upload = upload
        self.allowed_fields = allowed_fields
        self.fields = {}
        self.file_size = 0
        self.complete = False
        self.headers = {}
        self.header_name = bytearray()
        self.header_value = bytearray()
        self.name = b""
        self.value = bytearray()
        self.parser = MultipartParser(boundary, {
            "on_part_begin": self.part_begin,
            "on_header_field": self.read_header_name,
            "on_header_value": self.read_header_value,
            "on_header_end": self.header_end,
            "on_headers_finished": self.headers_finished,
            "on_part_data": self.part_data,
            "on_part_end": self.part_end,
            "on_end": self.finish,
        }, max_header_count=2, max_header_size=2048)

    def part_begin(self):
        self.headers.clear()
        self.value.clear()

    def read_header_name(self, data, start, end):
        self.header_name.extend(data[start:end])

    def read_header_value(self, data, start, end):
        self.header_value.extend(data[start:end])

    def header_end(self):
        name = bytes(self.header_name).lower()
        if name not in {b"content-disposition", b"content-type"} or name in self.headers:
            raise invalid_multipart()
        self.headers[name] = bytes(self.header_value)
        self.header_name.clear()
        self.header_value.clear()

    def headers_finished(self):
        media_type, options = parse_options_header(self.headers.get(b"content-disposition"))
        self.name = options.get(b"name", b"")
        if media_type != b"form-data" or not self.name or self.name in self.fields:
            raise invalid_multipart()
        if self.name not in self.allowed_fields:
            raise RequestError(400, "unsupported_parameter", "Unsupported transcription form field")
        if (b"filename" in options) != (self.name == b"file"):
            raise invalid_multipart()

    def part_data(self, data, start, end):
        if self.name == b"file":
            self.file_size += end - start
            if self.file_size > MAX_UPLOAD_BYTES:
                raise upload_too_large()
            self.upload.write(data[start:end])
        else:
            if len(self.value) + end - start > 128:
                raise RequestError(400, "invalid_parameter", "Transcription form field is too long")
            self.value.extend(data[start:end])

    def part_end(self):
        self.fields[self.name] = self.value.decode("utf-8")

    def finish(self):
        self.complete = True


def receive_upload(handler, upload, *, compatible):
    lengths = handler.headers.get_all("Content-Length", [])
    types = handler.headers.get_all("Content-Type", [])
    if (len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,12}", lengths[0]) or len(types) != 1
            or "Transfer-Encoding" in handler.headers or "Content-Encoding" in handler.headers):
        raise invalid_multipart()
    size = int(lengths[0])
    if size > MAX_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD:
        raise upload_too_large()
    media_type, options = parse_options_header(types[0])
    boundary = options.get(b"boundary", b"")
    if media_type != b"multipart/form-data" or not re.fullmatch(rb"[A-Za-z0-9'()+_,./:=? -]{1,70}", boundary):
        raise invalid_multipart()
    if boundary.endswith(b" "):
        raise invalid_multipart()
    fields = {b"file", b"language"}
    if compatible:
        fields |= {b"model", b"response_format", b"stream"}
    form = MultipartUpload(boundary, upload, fields)
    deadline = time.monotonic() + UPLOAD_TIMEOUT
    remaining = size
    try:
        while remaining:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                raise TimeoutError
            handler.connection.settimeout(timeout)
            block = handler.rfile.read1(min(65536, remaining))
            if not block:
                raise invalid_multipart()
            remaining -= len(block)
            form.parser.write(block)
    except (MultipartParseError, UnicodeError) as exc:
        raise invalid_multipart() from exc
    except TimeoutError as exc:
        raise RequestError(408, "upload_timeout", "Audio upload timed out") from exc
    finally:
        handler.connection.settimeout(UPLOAD_TIMEOUT)
    if not form.complete or form.file_size == 0:
        raise invalid_multipart()
    if size - form.file_size > MAX_MULTIPART_OVERHEAD:
        raise invalid_multipart()
    upload.seek(0)
    return form.fields


def request_parameters(fields, *, compatible):
    language = fields.get(b"language")
    if language is not None:
        pattern = r"[a-z]{2}" if compatible else r"(?:auto|[a-z]{2,3}(?:-[a-z0-9]{2,8})*)"
        if len(language) > 32 or not re.fullmatch(pattern, language, re.ASCII | re.IGNORECASE):
            raise RequestError(400, "invalid_language", "Invalid source language", "language")
        language = None if language.lower() == "auto" else language.lower()
    response_format = fields.get(b"response_format", "json")
    if compatible:
        if fields.get(b"model") != MODEL:
            raise RequestError(400, "unsupported_model", f"Use the {MODEL} model", "model")
        if response_format not in {"json", "text"}:
            raise RequestError(400, "unsupported_response_format", "Use json or text", "response_format")
        if fields.get(b"stream", "false") != "false":
            raise RequestError(400, "unsupported_parameter", "Streaming is unsupported", "stream")
    return language, response_format


def invalid_audio():
    return RequestError(415, "invalid_audio", "Audio could not be decoded in a supported format", "file")


def decode_upload(upload, output, limit):
    # FFmpeg can seek within the upload via stdin, so formats such as ordinary MP4
    # can open, but the demuxer cannot open client-directed file or network URLs.
    command = ["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-max_alloc", "67108864",
               "-filter_threads", "1", "-threads", "1", "-max_streams", "16",
               "-protocol_whitelist", "fd", "-format_whitelist", DEMUXERS, "-i", "fd:",
               "-map", "0:a:0", "-map_metadata", "-1", "-map_chapters", "-1",
               "-ac", "1", "-af", f"aresample={SAMPLE_RATE}:async=1:first_pts=0", "-c:a", "pcm_s16le",
               "-t", str(limit + 1), "-fs", str((limit + 2) * SAMPLE_RATE * 2), "-f", "wav", "fd:"]
    try:
        subprocess.run(command, stdin=upload, stdout=output, stderr=subprocess.DEVNULL,
                       check=True, timeout=DECODE_TIMEOUT,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        output.seek(0)
        with wave.open(output, "rb") as audio:
            frames = audio.getnframes()
            if frames == 0:
                raise invalid_audio()
    except FileNotFoundError as exc:
        raise RequestError(503, "decoder_unavailable", "FFmpeg is unavailable") from exc
    except subprocess.TimeoutExpired as exc:
        raise RequestError(408, "decode_timeout", "Audio decoding timed out", "file") from exc
    except (subprocess.CalledProcessError, wave.Error, EOFError) as exc:
        raise invalid_audio() from exc
    if frames > limit * SAMPLE_RATE:
        raise RequestError(413, "audio_too_long", "Decoded audio exceeds the duration limit", "file")
    return frames / SAMPLE_RATE


class TranscriptionHTTP:
    def __init__(self, relay):
        self.relay = relay
        self.slots = BoundedSemaphore(MAX_ACTIVE_UPLOADS)

    def handle(self, handler):
        route = handler.path.partition("?")[0]
        compatible = route == COMPATIBLE_ROUTE
        if not compatible and not route.startswith("/v1/transcription/"):
            return False
        try:
            self.authorize(handler, compatible)
            if route != handler.path:
                raise RequestError(400, "invalid_parameter", "This route does not accept query parameters")
            store = getattr(self.relay, "transcriptions", None)
            if store is None:
                raise RequestError(503, "transcription_unavailable", "File transcription is unavailable")
            if compatible or route == JOBS_ROUTE:
                if handler.command != "POST":
                    raise RequestError(405, "method_not_allowed", "Use POST to upload audio")
                if not store.capabilities()["available"]:
                    raise TranscriptionError("transcription_unavailable")
                self.submit(handler, store, compatible=compatible)
            elif route == CAPABILITIES_ROUTE and handler.command == "GET":
                capabilities = store.capabilities()
                capabilities["upload"] = {
                    "max_bytes": MAX_UPLOAD_BYTES, "max_duration_seconds": MAX_JOB_DURATION,
                    "compatible_max_duration_seconds": MAX_COMPATIBLE_DURATION,
                    "max_concurrent_requests": MAX_ACTIVE_UPLOADS, "formats": MEDIA_FORMATS,
                    "compatible_timeout_seconds": COMPATIBLE_TIMEOUT,
                }
                handler.reply(200, capabilities, headers={"Cache-Control": "no-store"})
            else:
                self.job_request(handler, store, route)
        except (RequestError, TranscriptionError) as exc:
            self.error(handler, exc, compatible=compatible)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (OSError, sqlite3.Error):
            self.error(handler, RequestError(503, "transcription_unavailable", "Transcription storage is unavailable"),
                       compatible=compatible)
        return True

    @staticmethod
    def authorize(handler, compatible):
        hosts = handler.headers.get_all("Host", [])
        port = handler.server.server_port
        if (len(hosts) != 1 or hosts[0].lower() not in {f"127.0.0.1:{port}", f"localhost:{port}"}
                or "Origin" in handler.headers or "Sec-Fetch-Site" in handler.headers):
            raise RequestError(403, "native_loopback_required", "Use a native loopback client")
        if compatible:
            auth = handler.headers.get_all("Authorization", [])
            if len(auth) != 1 or not re.fullmatch(r"Bearer [!-~]+", auth[0], re.IGNORECASE):
                raise RequestError(401, "unauthorized", "Provide a Bearer token for the local client")
        elif handler.headers.get_all("X-AheadSubs-Transcription", []) != ["1"]:
            raise RequestError(403, "native_loopback_required", "Provide X-AheadSubs-Transcription: 1")

    def submit(self, handler, store, *, compatible):
        if not self.slots.acquire(blocking=False):
            raise RequestError(429, "upload_busy", "The file transcription request limit is reached")
        path = None
        try:
            with tempfile.TemporaryFile(dir=store.upload_directory) as upload:
                fields = receive_upload(handler, upload, compatible=compatible)
                language, response_format = request_parameters(fields, compatible=compatible)
                limit = MAX_COMPATIBLE_DURATION if compatible else MAX_JOB_DURATION
                with tempfile.NamedTemporaryFile(dir=store.upload_directory, suffix=".wav", delete=False) as output:
                    path = Path(output.name)
                    duration = decode_upload(upload, output, limit)
            job = store.submit(path, duration, language, ephemeral=compatible)
            path = None
            if compatible:
                self.compatible_result(handler, store, job["id"], response_format)
            else:
                handler.reply(202, job, headers={"Cache-Control": "no-store", "Location": f"{JOBS_ROUTE}/{job['id']}"})
        finally:
            try:
                if path is not None:
                    path.unlink(missing_ok=True)
            finally:
                self.slots.release()

    def compatible_result(self, handler, store, identifier, response_format):
        deadline = time.monotonic() + COMPATIBLE_TIMEOUT
        try:
            while True:
                if self.relay.stopping.is_set():
                    raise RequestError(503, "transcription_unavailable", "Transcription service is stopping")
                readable, _, _ = select.select([handler.connection], [], [], 0)
                if readable and not handler.connection.recv(1, socket.MSG_PEEK):
                    return
                status = store.status(identifier)
                if status["state"] == "completed":
                    transcript = store.result(identifier)["text"]
                    break
                if status["state"] in {"failed", "cancelled"}:
                    code = status.get("error_code") or "transcription_failed"
                    raise RequestError(502, code, "The configured recognizer could not transcribe the file")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RequestError(504, "transcription_timeout", "Waiting for the transcript timed out")
                self.relay.stopping.wait(min(POLL_INTERVAL, remaining))
        finally:
            # The relay reclaims ephemeral inputs when it closes or restarts.
            if not self.relay.stopping.is_set():
                store.discard(identifier)
        headers = {"Cache-Control": "no-store"}
        if response_format == "text":
            handler.respond_bytes(200, transcript.encode("utf-8"), "text/plain; charset=utf-8", headers=headers)
        else:
            handler.reply(200, {"text": transcript}, headers=headers)

    @staticmethod
    def job_request(handler, store, route):
        match = JOB_ROUTE.fullmatch(route)
        if not match:
            raise RequestError(404, "unknown_route", "Unknown transcription route")
        identifier, action = match.groups()
        headers = {"Cache-Control": "no-store"}
        if handler.command == "GET" and action in {None, "result"}:
            result = store.result(identifier) if action else store.status(identifier)
            handler.reply(200, result, headers=headers)
        elif handler.command == "POST" and action in {"cancel", "resume"}:
            result = store.cancel(identifier) if action == "cancel" else store.resume(identifier)
            handler.reply(200, result, headers=headers)
        elif handler.command == "DELETE" and action is None:
            store.discard(identifier)
            handler.send_response(204)
            handler.send_header("Cache-Control", "no-store")
            handler.end_headers()
        else:
            raise RequestError(405, "method_not_allowed", "Unsupported method for this transcription route")

    @staticmethod
    def error(handler, exc, *, compatible):
        if compatible:
            error_type = "invalid_request_error" if exc.status < 500 else "api_error"
            if exc.status == 429:
                error_type = "rate_limit_error"
            payload = {"error": {"message": str(exc), "type": error_type,
                                 "code": exc.code, "param": getattr(exc, "param", None)}}
        else:
            payload = {"error": str(exc), "error_code": exc.code}
        headers = {"Cache-Control": "no-store"}
        if exc.status == 401:
            headers["WWW-Authenticate"] = "Bearer"
        try:
            handler.reply(exc.status, payload, headers=headers)
        except OSError:
            pass
