"""Play distinct files in real mpv windows and sample the translated buffer."""
import argparse
import json
import subprocess
import time
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

from aheadsubs.adapters.players import Mpv


def wait_for(check, seconds=25):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.2)
    raise TimeoutError("Expected mpv state did not appear")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mpv", type=Path)
    parser.add_argument("media", type=Path, nargs="+")
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--source", default="en")
    args = parser.parse_args()
    media = [path.resolve(strict=True) for path in args.media]
    if len(set(media)) != len(media):
        parser.error("use different files for each window")
    script = Path(__file__).resolve().parents[1] / "integrations/mpv/aheadsubs.lua"
    with ExitStack() as stack:
        players = []
        processes = []
        try:
            for index, movie in enumerate(media):
                pipe = "relay-smoke-" + uuid4().hex
                process = subprocess.Popen([
                    str(args.mpv.resolve()), "--no-config", "--pause", "--mute=yes",
                    f"--geometry=320x180+{(index % 2) * 340}+{(index // 2) * 220}",
                    f"--input-ipc-server={pipe}", f"--scripts={script}",
                    f"--script-opts=aheadsubs-port={args.port}", str(movie),
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                processes.append(process)

                def connect():
                    try:
                        return stack.enter_context(Mpv(pipe))
                    except OSError:
                        return None

                player = wait_for(connect)
                wait_for(lambda: any(item.get("title") == "AheadSubs"
                                     for item in player.command("get_property", "menu-data") or []))
                player.command("script-message-to", "aheadsubs", "relay-source", args.source,
                               required=True)
                player.command("script-message-to", "aheadsubs", "relay-toggle", required=True)
                players.append(player)

            def lead(player):
                status = player.command("get_property", "user-data/subtitle-relay") or {}
                if status.get("error"):
                    raise RuntimeError(status["error"])
                return status.get("ready_ahead") or 0

            wait_for(lambda: all(lead(player) >= 20 for player in players))
            for player in players:
                player.command("set_property", "pause", False, required=True)
            minimum = [float("inf")] * len(players)
            text_observed = [False] * len(players)
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline:
                for index, player in enumerate(players):
                    minimum[index] = min(minimum[index], lead(player))
                    text = player.command("get_property", "sub-text") or ""
                    text_observed[index] |= any("\u4e00" <= char <= "\u9fff" for char in text)
                time.sleep(0.3)
            positions = [player.command("get_property", "time-pos") for player in players]
            print(json.dumps({"windows": len(players), "positions": positions,
                              "minimum_lead_by_window": minimum,
                              "chinese_subtitle_observed": text_observed}))
            if any(value <= 0 for value in minimum) or not all(text_observed):
                raise SystemExit(1)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()


if __name__ == "__main__":
    main()
