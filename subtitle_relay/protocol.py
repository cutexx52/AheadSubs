import json
import math
from secrets import compare_digest
from threading import BoundedSemaphore, Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler
from urllib.parse import parse_qs

from .engine import Playback


def playback_from_json(data):
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
    source = data.get("source")
    target = data.get("target", "zh")
    if not isinstance(target, str) or not target or (source is not None and not isinstance(source, str)):
        raise ValueError("invalid language")
    return Playback(path.resolve(), position, int(audio), speed, float(duration) if duration else None,
                    source, target, ahead)


def serve(relay, port, control_token=None):
    text_slots = BoundedSemaphore(2)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/v1/health":
                self.reply(200, {"service": "subtitle-relay"})
            else:
                self.reply(404, {"error": "unknown route"})

        def do_POST(self):
            try:
                expected = ("application/x-subtitle-relay" if self.path == "/v1/text"
                            else "application/json")
                if self.headers.get("Origin") or self.headers.get_content_type() != expected:
                    self.reply(403, {"error": "JSON loopback clients only"})
                    return
                size = int(self.headers.get("Content-Length", 0))
                if not 1 <= size <= 32_768:
                    raise ValueError("invalid request size")
                body = self.rfile.read(size)
                if self.path == "/v1/text":
                    self.translate_text(body)
                    return
                data = json.loads(body)
                if self.path == "/v1/shutdown":
                    supplied = data.get("token")
                    if not control_token or not isinstance(supplied, str) or not compare_digest(
                        control_token, supplied
                    ):
                        self.reply(403, {"error": "shutdown not authorized"})
                        return
                    self.reply(200, {})
                    Thread(target=self.server.shutdown, daemon=True).start()
                    return
                identifier = data["session"]
                if not isinstance(identifier, str) or not 1 <= len(identifier) <= 100:
                    raise ValueError("invalid session")
                if self.path == "/v1/playback":
                    self.reply(200, relay.update(identifier, playback_from_json(data)))
                elif self.path == "/v1/close":
                    relay.drop(identifier)
                    self.reply(200, {})
                else:
                    self.reply(404, {"error": "unknown route"})
            except ValueError as exc:
                self.reply(400, {"error": str(exc)})
            except (TypeError, KeyError, FileNotFoundError):
                self.reply(400, {"error": "invalid playback request"})
            except PermissionError:
                self.reply(503, {"error": "subtitle file temporarily in use"})

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
            try:
                translated = relay.translator.translate([content], source, target)[0]
            except Exception as exc:
                self.reply(502, {"error": type(exc).__name__})
            else:
                self.reply(200, {"translation": translated})
            finally:
                text_slots.release()

        def reply(self, code, data):
            body = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        print(f"Subtitle Relay listening on 127.0.0.1:{port}", flush=True)
        server.serve_forever()


class RelayClient:
    def __init__(self, port):
        self.url = f"http://127.0.0.1:{port}/v1/"
        self.opener = build_opener(ProxyHandler({}))

    def send(self, route, data):
        req = Request(self.url + route, data=json.dumps(data).encode(),
                      headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=5) as result:
                return json.load(result)
        except HTTPError as exc:
            try:
                detail = json.load(exc).get("error")
            except (ValueError, AttributeError):
                detail = None
            raise RuntimeError(detail or f"Subtitle Relay HTTP {exc.code}") from exc
