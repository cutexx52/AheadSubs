"""Measure four or more independent real-time sessions through the public API."""
import argparse
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from aheadsubs.client import RelayClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", type=Path, nargs="+")
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--source", default="en")
    parser.add_argument("--target", default="zh")
    args = parser.parse_args()
    files = [file.resolve(strict=True) for file in args.files]
    if len(set(files)) != len(files):
        parser.error("pass distinct paths so the benchmark cannot share chunk work")
    sessions = []
    for file in files:
        duration = float(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(file),
        ]))
        if duration < args.seconds + 20:
            parser.error(f"{file.name} needs at least {args.seconds + 20:g} seconds of media")
        sessions.append((RelayClient(args.port), {
            "session": uuid4().hex, "path": str(file), "duration": duration,
            "source": args.source, "target": args.target, "ahead": 20,
        }))

    with ThreadPoolExecutor(max_workers=len(sessions)) as pool:
        def poll(position):
            responses = list(pool.map(lambda pair: pair[0].send(
                "playback", {**pair[1], "position": position}), sessions))
            for response in responses:
                if response["error"]:
                    raise RuntimeError(response["error"])
            return responses

        try:
            warmup_start = time.monotonic()
            while min(r["ready_ahead"] for r in poll(0)) < 20:
                if time.monotonic() - warmup_start > 120:
                    raise TimeoutError("four-stream prebuffer did not fill")
                time.sleep(0.2)
            start = time.monotonic()
            minimum = [float("inf")] * len(sessions)
            underruns = [0] * len(sessions)
            while (position := time.monotonic() - start) < args.seconds:
                for index, response in enumerate(poll(position)):
                    lead = response["ready_ahead"]
                    minimum[index] = min(minimum[index], lead)
                    underruns[index] += lead == 0
                time.sleep(0.2)
            print(json.dumps({"streams": len(sessions), "seconds": args.seconds,
                              "prebuffer_seconds": round(start - warmup_start, 2),
                              "minimum_lead_by_stream": [round(x, 2) for x in minimum],
                              "underrun_samples_by_stream": underruns}))
            if any(underruns):
                raise SystemExit(1)
        finally:
            for client, session in sessions:
                client.send("close", {"session": session["session"]})


if __name__ == "__main__":
    main()
