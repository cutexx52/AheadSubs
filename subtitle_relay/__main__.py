import argparse
import json
import time
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path

from .audio import Segmentation, Segmenter
from .engine import Relay
from .players import Mpv, run_adapter
from .protocol import RelayClient, serve
from .providers import (ChatTranslation, FasterWhisper, NllbTranslation, OpenAIWhisper,
                        configure_cuda, openai_client)


class ClockPlayer:
    def __init__(self, path, position, duration, audio, realtime):
        self.path, self.position, self.duration, self.audio = path, position, duration, audio
        self.started = time.monotonic() if realtime else None
        self.last_subtitle = None

    def state(self):
        position = self.position
        if self.started is not None:
            position += time.monotonic() - self.started
        if self.duration is not None and position >= self.duration:
            raise EOFError
        return {"path": str(Path(self.path).resolve()), "position": position,
                "duration": self.duration, "audio": self.audio}

    def publish(self, path, revision):
        if self.last_subtitle != (path, revision):
            print(json.dumps({"subtitle": path, "revision": revision}), flush=True)
            self.last_subtitle = path, revision


def make_relay(args):
    settings = Segmentation(args.before, args.after, args.max_speech, args.min_silence_ms,
                            args.pad_ms, args.vad_threshold, not args.no_vad, args.backfill)
    if args.device == "cuda" and (args.asr == "local" or args.mt == "local"):
        configure_cuda()
    cloud = openai_client(args.key_file) if "openai" in (args.asr, args.mt) or args.ast else None
    recognizer = None
    translator = None
    if not args.ast:
        if args.asr == "local":
            recognizer = FasterWhisper(args.whisper_model, args.device, min(args.workers, 2))
        elif args.asr in {"compatible", "qwen"}:
            client = openai_client(endpoint=args.asr_url, endpoint_key="RELAY_ASR_API_KEY")
            recognizer = OpenAIWhisper(client, args.asr_model)
        else:
            recognizer = OpenAIWhisper(cloud)
        if args.mt == "local":
            translator = NllbTranslation(args.nllb_model, args.device, min(args.workers, 2))
        else:
            client = cloud if args.mt == "openai" else openai_client(endpoint=args.llm_url)
            translator = ChatTranslation(client, args.llm_model)
    profile = ["v2", args.asr, args.mt, args.ast, args.whisper_model, args.nllb_model,
               args.llm_model, args.llm_url, args.device, asdict(settings)]
    if args.asr in {"compatible", "qwen"} and not args.ast:
        profile.extend([args.asr_url if args.asr == "compatible" else args.qwen_size, args.asr_model])
    return Relay(args.cache, recognizer, translator, profile, args.workers, args.chunk,
                 OpenAIWhisper(cloud) if args.ast else None, Segmenter(settings))


def main():
    parser = argparse.ArgumentParser(prog="python -m subtitle_relay")
    commands = parser.add_subparsers(dest="mode", required=True)
    server = commands.add_parser("serve")
    server.add_argument("--asr", choices=["local", "openai", "compatible", "qwen"], default="local")
    server.add_argument("--qwen-size", choices=["0.6b", "1.7b"], default="1.7b")
    server.add_argument("--qwen-root", type=Path)
    server.add_argument("--asr-url", default="http://127.0.0.1:8000/v1")
    server.add_argument("--asr-model", default="qwen3-asr")
    server.add_argument("--mt", choices=["local", "openai", "compatible"], default="local")
    server.add_argument("--ast", action="store_true", help="Use OpenAI speech translation to English")
    server.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    server.add_argument("--whisper-model", default="small")
    server.add_argument("--nllb-model", default="Adom4600/nllb-200-distilled-600M-ct2-int8")
    server.add_argument("--llm-model", default="gpt-4.1-mini")
    server.add_argument("--llm-url", default="http://127.0.0.1:11434/v1")
    server.add_argument("--key-file")
    server.add_argument("--control-token-file", type=Path)
    server.add_argument("--pot-hotkey-launcher", type=Path)
    server.add_argument("--cache", default=".relay")
    server.add_argument("--workers", type=int, choices=range(1, 17), default=4)
    server.add_argument("--chunk", type=int, choices=range(4, 21), default=8)
    server.add_argument("--before", type=float, default=2)
    server.add_argument("--after", type=float, default=2)
    server.add_argument("--max-speech", type=float, default=12)
    server.add_argument("--min-silence-ms", type=int, default=450)
    server.add_argument("--pad-ms", type=int, default=160)
    server.add_argument("--vad-threshold", type=float, default=0.5)
    server.add_argument("--backfill", type=float, default=4)
    server.add_argument("--no-vad", action="store_true")
    mpv = commands.add_parser("mpv")
    mpv.add_argument("pipe")
    pot = commands.add_parser("potplayer")
    pot.add_argument("hwnd", type=lambda value: int(value, 0))
    pot.add_argument("path")
    pot.add_argument("--reload-command", type=lambda value: int(value, 0))
    pot_open = commands.add_parser("potplayer-open")
    pot_open.add_argument("executable", type=Path)
    pot_open.add_argument("path", type=Path)
    pot_open.add_argument("--muted", action="store_true")
    clock = commands.add_parser("clock")
    clock.add_argument("path")
    clock.add_argument("--position", type=float, default=0)
    clock.add_argument("--duration", type=float)
    clock.add_argument("--realtime", action="store_true")
    for command in (server, mpv, pot, pot_open, clock):
        command.add_argument("--port", type=int, default=8769)
    for command in (mpv, pot, pot_open, clock):
        command.add_argument("--source")
        command.add_argument("--target", default="zh")
        command.add_argument("--ahead", type=float, default=20)
        command.add_argument("--interval", type=float, default=0.4)
    for command in (pot, pot_open, clock):
        command.add_argument("--audio", type=int, default=0)
    args = parser.parse_args()
    if args.mode == "serve":
        if not (0 <= args.before <= 5 and 0 <= args.after <= 5 and
                2 <= args.max_speech <= 20 and 40 <= args.min_silence_ms <= 2000 and
                0 <= args.pad_ms <= 500 and 0 < args.vad_threshold < 1 and
                0 <= args.backfill <= 30):
            parser.error("invalid VAD parameters or audio context")
        with ExitStack() as resources:
            if args.asr == "qwen" and not args.ast:
                from .qwen import run as run_qwen

                args.asr_url = resources.enter_context(run_qwen(args.qwen_root, args.qwen_size))
                args.asr_model = "qwen3-asr"
            relay = make_relay(args)
            resources.callback(relay.close)
            if args.pot_hotkey_launcher:
                from .potplayer import start_hotkey

                start_hotkey(args.pot_hotkey_launcher)
            token = args.control_token_file.read_text(encoding="ascii").strip() if args.control_token_file else None
            serve(relay, args.port, token)
        return
    if args.interval <= 0:
        parser.error("--interval must be positive")
    options = (RelayClient(args.port), args.source, args.target, args.ahead, args.interval)
    if args.mode == "mpv":
        with Mpv(args.pipe) as player:
            run_adapter(player, *options)
    elif args.mode == "potplayer":
        from .potplayer import PotPlayer

        run_adapter(PotPlayer(args.hwnd, args.path, args.audio, args.reload_command), *options)
    elif args.mode == "potplayer-open":
        from .potplayer import open_with_subtitles

        open_with_subtitles(args.executable, args.path, options[0], args.audio, args.source,
                            args.target, args.ahead, args.muted)
    else:
        run_adapter(ClockPlayer(args.path, args.position, args.duration, args.audio, args.realtime),
                    *options)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        pass
