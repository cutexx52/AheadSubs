import json
import math
import os
import re
from secrets import compare_digest
from threading import BoundedSemaphore, Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from ..inference.errors import provider_error
from .engine import Playback
from .history import InspectionError
from .metrics import SOURCES
from .transcription_http import TranscriptionHTTP


def playback_from_json(data, defaults=None):
    defaults = defaults or {}
    path = Path(data["path"])
    if not path.is_absolute() or not path.is_file():
        raise ValueError("Choose an accessible file on a local drive or Windows share")
    position = float(data["position"])
    speed = float(data.get("speed", 1))
    ahead = float(data.get("ahead", 20))
    duration = data.get("duration")
    audio = data.get("audio", 0)
    if not math.isfinite(position) or not 0 <= position <= 10_000_000:
        raise ValueError("invalid position")
    if not 0.1 <= speed <= 5 or not 1 <= ahead <= 120:
        raise ValueError("invalid speed or look-ahead")
    if duration is not None and not 0 < float(duration) <= 10_000_000:
        raise ValueError("invalid duration")
    if type(audio) not in (int, float) or not 0 <= audio <= 255 or audio != int(audio):
        raise ValueError("invalid audio stream ordinal")
    source = data.get("source", defaults.get("source"))
    target = data.get("target", defaults.get("target", "zh"))
    bilingual = data.get("bilingual", defaults.get("bilingual", False))
    if not isinstance(target, str) or not target or (source is not None and not isinstance(source, str)):
        raise ValueError("invalid language")
    if type(bilingual) is not bool:
        raise ValueError("invalid bilingual setting")
    return Playback(path.resolve(), position, int(audio), speed, float(duration) if duration else None,
                    source or None, target, ahead, bilingual)


def create_server(relay, port, control_token=None, playback_defaults=None, *, local_models=None):
    text_slots = BoundedSemaphore(2)
    transcription = TranscriptionHTTP(relay)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if transcription.handle(self):
                return
            if self.path == "/v1/health":
                self.reply(200, {"service": "subtitle-relay", "pid": os.getpid(),
                                 "active_sessions": relay.active_sessions(), "local_models": local_models})
            elif self.path == "/v1/status":
                if self.headers.get("Origin") or self.headers.get("X-AheadSubs-Status") != "1":
                    self.reply(403, {"error": "native loopback clients only"})
                    return
                self.reply(200, relay.status())
            else:
                self.reply(404, {"error": "unknown route"})

        def entry(self, session=""):
            source = self.headers.get("X-AheadSubs-Entry", "")
            if source in SOURCES:
                return source
            if self.path == "/v1/text" and self.headers.get("User-Agent") == "SubtitleRelay/1":
                return "potplayer"
            if not source and re.fullmatch(r"mpv-[0-9]+-[0-9]+", session):
                return "mpv"
            return "http"

        def do_POST(self):
            if transcription.handle(self):
                return
            try:
                expected = ("application/x-subtitle-relay" if self.path == "/v1/text"
                            else "application/json")
                if self.headers.get("Origin") or self.headers.get_content_type() != expected:
                    self.reply(403, {"error": "JSON loopback clients only"})
                    return
                size = int(self.headers.get("Content-Length", 0))
                limit = 51_200 if self.path == "/v1/text" else 32_768
                if not 1 <= size <= limit:
                    raise ValueError("invalid request size")
                body = self.rfile.read(size)
                if self.path == "/v1/text":
                    self.translate_text(body)
                    return
                data = json.loads(body)
                if self.path in {"/v1/shutdown", "/v1/inspection/regenerate"}:
                    supplied = data.get("token")
                    if not control_token or not isinstance(supplied, str) or not compare_digest(
                        control_token.encode(), supplied.encode()
                    ):
                        self.reply(403, {"error": "service control not authorized"})
                        return
                    if self.path == "/v1/inspection/regenerate":
                        key = data.get("key")
                        if not isinstance(key, str) or not 1 <= len(key) <= 64:
                            raise ValueError("invalid subtitle version")
                        self.reply(202, relay.queue_regeneration(key))
                        return
                    self.reply(200, {})
                    Thread(target=self.server.shutdown, daemon=True).start()
                    return
                identifier = data["session"]
                if not isinstance(identifier, str) or not 1 <= len(identifier) <= 100:
                    raise ValueError("invalid session")
                if self.path == "/v1/playback":
                    self.reply(200, relay.update(identifier, playback_from_json(data, playback_defaults),
                                                 self.entry(identifier)))
                elif self.path == "/v1/close":
                    relay.drop(identifier)
                    self.reply(200, {})
                else:
                    self.reply(404, {"error": "unknown route"})
            except InspectionError as exc:
                self.reply(409, {"error": str(exc), "error_code": str(exc)})
            except ValueError as exc:
                self.reply(400, {"error": str(exc)})
            except (TypeError, KeyError, FileNotFoundError):
                self.reply(400, {"error": "invalid playback request"})
            except PermissionError:
                self.reply(503, {"error": "subtitle file temporarily in use"})

        def do_DELETE(self):
            if not transcription.handle(self):
                self.send_error(501, "Unsupported method ('DELETE')")

        def translate_text(self, body):
            if not relay.translator:
                self.reply(409, {"error": "this profile does not include text translation"})
                return
            payload = parse_qs(body.decode("utf-8"), max_num_fields=3, strict_parsing=True)
            source, target, content = (payload[key][0] for key in ("source", "target", "text"))
            if len(content) > 4000:
                raise ValueError("subtitle line too long")
            if not text_slots.acquire(blocking=False):
                self.reply(503, {"error": "translation busy"})
                return
            source_app = self.entry()
            relay.text_activity(source_app, 1)
            try:
                translated = relay.translator.translate([content], source, target)[0]
            except Exception as exc:
                error = provider_error(exc, default="translation_failed")
                self.reply(502, {"error": str(error), "error_code": error.kind})
            else:
                self.reply(200, {"translation": translated})
            finally:
                relay.text_activity(source_app, -1)
                text_slots.release()

        def reply(self, code, data, *, headers=None):
            if self.path == "/v1/status":
                headers = {"Cache-Control": "no-store", **(headers or {})}
            self.respond_bytes(code, json.dumps(data).encode(), "application/json", headers=headers)

        def respond_bytes(self, code, body, content_type, *, headers=None):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(relay, port, control_token=None, playback_defaults=None, *, local_models=None):
    with create_server(relay, port, control_token, playback_defaults, local_models=local_models) as server:
        print(f"AheadSubs listening on 127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()
