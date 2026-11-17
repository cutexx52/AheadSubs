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


def run_adapter(player, client, source, target, ahead, interval, stop=None, idle_limit=None,
                report=None, session=None, seek_interval=None):
    session = session or uuid4().hex
    previous_error = None
    last_active = time.monotonic()
    disconnected_at = None
    attached = False
    previous_position = None
    next_poll = fast_until = 0
    try:
        while stop is None or not stop.exists():
            state = player.state()
            delay = interval
            if state:
                now = last_active = time.monotonic()
                if seek_interval is not None:
                    media = (state.get("path"), state.get("audio"))
                    position = state["position"]
                    if previous_position is None:
                        jumped = True
                    else:
                        old_media, old_time, old_position = previous_position
                        elapsed = (now - old_time) * max(1, state.get("speed", 1))
                        advance = position - old_position
                        jumped = media != old_media or advance < -0.15 or advance > elapsed + 0.55
                    previous_position = (media, now, position)
                    if jumped:
                        fast_until, next_poll = now + 2.5, now
                    if now < next_poll:
                        time.sleep(min(seek_interval, next_poll - now))
                        continue
                    delay = seek_interval
                    next_poll = now + (seek_interval if now < fast_until else interval)
            elif idle_limit is not None and time.monotonic() - last_active >= idle_limit:
                return
            else:
                previous_position = None
            try:
                if state:
                    response = client.send("playback", {
                        **state, "session": session, "source": source() if callable(source) else source,
                        "target": target, "ahead": ahead,
                    })
                    attached = True
                elif attached and disconnected_at is None:
                    client.send("close", {"session": session})
                    attached = False
            except OSError:
                if disconnected_at is None:
                    disconnected_at = time.monotonic()
                if time.monotonic() - disconnected_at >= 165:
                    raise RuntimeError("字幕服务未恢复，请在设置中查看服务日志。") from None
                if report:
                    report("reconnecting", "正在等待字幕服务恢复，随后会从当前播放位置继续…")
                time.sleep(interval)
                continue
            if state:
                disconnected_at = None
                if response["subtitle"]:
                    player.publish(response["subtitle"], response["revision"])
                if response["error"] and response["error"] != previous_error:
                    print(response["error"], flush=True)
                previous_error = response["error"]
                if report:
                    if response["error"]:
                        report("error", f"这一段处理失败，稍后重试：{response['error']}")
                    elif response["ready_ahead"] <= 0:
                        report("buffering", "正在识别和缓冲…")
                    elif player.subtitle and response.get("nearby_cues"):
                        report("ready", f"字幕已加载 · 已处理后续 {response['ready_ahead']:.0f} 秒")
                    else:
                        report("silence", "这一段已处理，暂未生成字幕")
            else:
                if report:
                    report("waiting", "等待活动音轨或播放位置…")
            time.sleep(delay)
    finally:
        try:
            client.send("close", {"session": session})
        except (OSError, RuntimeError):
            pass
