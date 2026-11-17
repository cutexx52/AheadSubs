import io
import json
import os
import socket
import time
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4


class Mpv:
    def __init__(self, address):
        self.address = address
        self.subtitle = None
        self.revision = None
        self.request_id = 0

    def __enter__(self):
        self.stack = ExitStack()
        if os.name == "nt":
            pipe = self.address if self.address.startswith("\\\\") else "\\\\.\\pipe\\" + self.address
            raw = self.stack.enter_context(open(pipe, "r+b", buffering=0))
            self.reader = io.BufferedReader(raw)
            self.write = raw.write
        else:
            client = self.stack.enter_context(socket.socket(socket.AF_UNIX))
            client.settimeout(5)
            client.connect(self.address)
            self.reader = self.stack.enter_context(client.makefile("rb"))
            self.write = client.sendall
        return self

    def __exit__(self, *exc):
        self.stack.close()

    def command(self, *command, required=False):
        self.request_id += 1
        payload = {"command": command, "request_id": self.request_id}
        self.write(json.dumps(payload).encode() + b"\n")
        while line := self.reader.readline():
            response = json.loads(line)
            if response.get("request_id") == self.request_id:
                if response["error"] == "success":
                    return response.get("data")
                if required:
                    raise RuntimeError(f"mpv {command[0]}: {response['error']}")
                return None
        raise EOFError("mpv disconnected")

    def state(self):
        filename = self.command("get_property", "path")
        position = self.command("get_property", "time-pos")
        tracks = self.command("get_property", "track-list") or []
        track = next((t for t in tracks if t["type"] == "audio" and t.get("selected")), None)
        if not filename or position is None or not track or track.get("external"):
            return None
        path = Path(self.command("get_property", "working-directory") or ".") / filename
        if not path.is_file():
            return None
        audio = sorted((t for t in tracks if t["type"] == "audio" and not t.get("external")),
                       key=lambda t: t.get("ff-index", t["id"]))
        # A loadfile/playlist transition may occur while reading separate properties.
        duration = self.command("get_property", "duration")
        speed = self.command("get_property", "speed") or 1
        if self.command("get_property", "path") != filename:
            return None
        self.filename = filename
        return {"path": str(path.resolve()), "position": position, "audio": audio.index(track),
                "duration": duration, "speed": speed}

    def publish(self, path, revision):
        if self.subtitle == path and self.revision == revision:
            return
        if self.command("get_property", "path") != self.filename:
            return
        tracks = self.command("get_property", "track-list") or []
        existing = next((t for t in tracks if t["type"] == "sub" and t.get("external-filename")
                         and Path(t["external-filename"]) == Path(path)), None)
        old = next((t for t in tracks if self.subtitle and self.subtitle != path and t["type"] == "sub"
                    and t.get("external-filename")
                    and Path(t["external-filename"]) == Path(self.subtitle)), None)
        if old:
            self.command("sub-remove", old["id"])
        if existing:
            self.command("sub-reload", existing["id"], required=True)
        elif Path(path).stat().st_size > 1:
            self.command("sub-add", path, "select", "Subtitle Relay", required=True)
        self.subtitle, self.revision = path, revision


def run_adapter(player, client, source, target, ahead, interval, stop=None, idle_limit=None):
    session = uuid4().hex
    previous_error = None
    last_active = time.monotonic()
    try:
        while stop is None or not stop.exists():
            state = player.state()
            if state:
                last_active = time.monotonic()
                response = client.send("playback", {
                    **state, "session": session, "source": source, "target": target, "ahead": ahead,
                })
                if response["subtitle"]:
                    player.publish(response["subtitle"], response["revision"])
                if response["error"] and response["error"] != previous_error:
                    print(response["error"], flush=True)
                previous_error = response["error"]
            else:
                client.send("close", {"session": session})
                if idle_limit is not None and time.monotonic() - last_active >= idle_limit:
                    return
            time.sleep(interval)
    finally:
        try:
            client.send("close", {"session": session})
        except (OSError, RuntimeError):
            pass
