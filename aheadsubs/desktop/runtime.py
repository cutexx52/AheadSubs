import json
import msvcrt
import os
import secrets
import subprocess
import sys
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

from ..inference.providers import MINIMAX_MODEL
from ..user_errors import ServiceStateError
from ..paths import user_data_directory

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "AheadSubs.pyw"
DATA = user_data_directory()
QWEN = DATA / "qwen"
CONFIG = DATA / "settings.json"
PORTABLE_PYTHON = ROOT / "runtime" / "pythonw.exe"
PYTHON = PORTABLE_PYTHON if PORTABLE_PYTHON.is_file() else ROOT / ".venv" / "Scripts" / "pythonw.exe"
LOG = DATA / "service.log"
PORT = 8769
CONTROL = DATA / "control-token"
PAUSED = DATA / "service-stopped"
DEFAULTS = {
    "route": "asr+mt",
    "pot_hotkey": "1",
    "diagnostics": "0",
    "qwen_size": "1.7b", "source": "",
    "target": "zh", "bilingual": "0",
    "translation_enhancements": {},
    "asr_url": "http://127.0.0.1:8000/v1", "asr_model": "qwen3-asr",
    "asr": "local", "mt": "local", "device": "cpu", "whisper_model": "small",
    "asr_device": "", "mt_device": "",
    "llm_model": "gpt-4.1-mini", "llm_url": "http://127.0.0.1:11434/v1", "key_file": "",
    "chatgpt_account": "", "chatgpt_model": "",
    "minimax_key_file": "",
    "qwen_mt_model": "qwen-mt-flash", "qwen_mt_url": "", "qwen_mt_key_file": "",
    "dashscope_asr_model": "qwen-audio-3.1-asr-flash",
    "potplayer_directory": "", "mpv_directory": "",
    "chunk": "8", "before": "2", "after": "2", "min_speech": "3", "max_speech": "12",
    "min_silence_ms": "450", "pad_ms": "80", "vad_threshold": "0.5", "backfill": "4",
    "vad_model": "silero",
}


def enhancement_key(settings):
    provider = settings["mt"]
    if provider == "qwen-mt":
        return f"qwen-mt:{settings['qwen_mt_model']}"
    if provider in {"openai", "compatible"}:
        return f"{provider}:{settings['llm_model']}"
    if provider == "chatgpt" and settings["chatgpt_model"]:
        return f"chatgpt:{settings['chatgpt_model']}"
    if provider == "minimax":
        return f"minimax:{MINIMAX_MODEL}"
    return None


def config():
    if not CONFIG.is_file():
        return DEFAULTS.copy()
    saved = json.loads(CONFIG.read_text(encoding="utf-8"))
    if "min_speech" not in saved:
        if str(saved.get("pad_ms")) == "160":
            saved["pad_ms"] = DEFAULTS["pad_ms"]
        try:
            saved["min_speech"] = str(min(float(saved.get("max_speech", 12)), 3))
        except (TypeError, ValueError):
            pass
    prompt = str(saved.pop("translation_prompt", "")).strip()
    context_times = [saved.pop(name, "0") for name in ("translation_before", "translation_after")]
    settings = {**DEFAULTS, **saved}
    if "translation_enhancements" not in saved and (key := enhancement_key(settings)):
        try:
            context = any(float(value) > 0 for value in context_times)
        except (TypeError, ValueError):
            context = False
        if context or prompt:
            settings["translation_enhancements"] = {
                key: {"enabled": True, "previous_cues": 4 if context else 0, "prompt": prompt[:1000]},
            }
    return settings


def save_config(settings):
    DATA.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    temporary.replace(CONFIG)


def diagnostics_enabled():
    return config()["diagnostics"] == "1"


def log_output(path, *, text=False):
    if not diagnostics_enabled():
        return nullcontext(None)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("a", encoding="utf-8") if text else path.open("ab")


def service_health():
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{PORT}/v1/health", timeout=0.3) as response:
            health = json.load(response)
            return health if health.get("service") == "subtitle-relay" else None
    except (OSError, URLError, ValueError):
        return None


def healthy():
    return service_health() is not None


def spawn(arguments, log=LOG):
    if not PYTHON.is_file():
        raise RuntimeError("Install Python dependencies in the project .venv first.")
    DATA.mkdir(parents=True, exist_ok=True)
    with log_output(log) as output:
        return subprocess.Popen([str(PYTHON), "-m", "aheadsubs", *arguments],
                                cwd=ROOT, stdout=output or subprocess.DEVNULL, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)


def lock_service(stream, wait=False):
    deadline = time.monotonic() + 120
    while True:
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            if not wait:
                return False
            if time.monotonic() >= deadline:
                raise ServiceStateError("service-busy", "等待上一项服务操作超时。")
            time.sleep(0.25)


@contextmanager
def lock_model_use(directory):
    with (directory / "model-use.lock").open("a+b") as lock:
        lock_service(lock, wait=True)
        yield


def background_stop():
    from aheadsubs.client import RelayClient

    DATA.mkdir(parents=True, exist_ok=True)
    PAUSED.touch()
    with (DATA / "starting.lock").open("a+b") as startup:
        lock_service(startup, wait=True)
        for lock in DATA.glob("pot-*-*.lock"):
            lock.with_suffix(".stop").touch()
        health = service_health()
        if not health:
            return
        if not CONTROL.is_file():
            raise ServiceStateError("service-owned", "当前字幕服务由另一个程序启动，请从原来的启动方式关闭。")
        import psutil

        try:
            process = psutil.Process(health["pid"]) if health.get("pid") else None
            RelayClient(PORT).send("shutdown", {"token": CONTROL.read_text(encoding="ascii")})
            if process:
                try:
                    process.wait(timeout=10)
                except psutil.TimeoutExpired:
                    # The authenticated service can be stuck on an upstream request.
                    children = process.children(recursive=True)
                    for child in reversed(children):
                        try:
                            child.terminate()
                        except psutil.NoSuchProcess:
                            pass
                    process.terminate()
                    process.wait(timeout=5)
        except psutil.NoSuchProcess:
            pass
        if healthy():
            raise ServiceStateError("service-busy", "字幕服务尚未退出，请查看后台日志。")


def background_start(on_wait=None, restart=False):
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / "starting.lock").open("a+b") as startup:
        if not lock_service(startup, wait=restart) or PAUSED.exists():
            return
        health = service_health()
        if health:
            if not restart:
                return
            from aheadsubs.client import RelayClient

            if not CONTROL.is_file():
                raise ServiceStateError("service-owned", "当前字幕服务由另一个程序启动，请先关闭该服务。")
            RelayClient(PORT).send("shutdown", {"token": CONTROL.read_text(encoding="ascii")})
            if pid := health.get("pid"):
                import psutil

                try:
                    psutil.Process(pid).wait(timeout=100)
                except psutil.NoSuchProcess:
                    pass
            deadline = time.monotonic() + 5
            while healthy():
                if time.monotonic() >= deadline:
                    raise ServiceStateError("service-busy", "旧字幕服务尚未退出。")
                time.sleep(0.25)
        settings = config()
        CONTROL.write_text(secrets.token_urlsafe(32), encoding="ascii")
        args = ["serve", "--port", str(PORT), "--cache", str(DATA / "cache"), "--control-token-file", str(CONTROL),
                "--desktop-config", str(CONFIG),
                "--default-target", settings["target"]]
        if settings["source"]:
            args.extend(["--default-source", settings["source"]])
        if settings["bilingual"] == "1":
            args.append("--default-bilingual")
        for name in DEFAULTS:
            if name in {"source", "target", "bilingual", "translation_enhancements",
                        "potplayer_directory", "mpv_directory", "key_file", "qwen_mt_key_file", "minimax_key_file"}:
                continue
            if name == "pot_hotkey":
                if settings[name] == "1":
                    args.extend(["--pot-hotkey-launcher", str(LAUNCHER)])
                continue
            if name == "diagnostics":
                if settings[name] == "1":
                    args.append("--diagnostics")
                continue
            if name == "route":
                if settings[name] == "OpenAI AST (English)":
                    args.append("--ast")
                continue
            value = settings[name]
            if value:
                args.extend(["--" + name.replace("_", "-"), value])
        enhancement = settings["translation_enhancements"].get(enhancement_key(settings), {})
        if enhancement.get("enabled"):
            args.extend(["--translation-previous-cues", str(enhancement["previous_cues"]),
                         f"--translation-prompt={enhancement['prompt']}"])
            if "context_chars" in enhancement:
                args.extend(["--translation-context-chars", str(enhancement["context_chars"])])
        if settings["asr"] == "qwen":
            args.extend(["--qwen-root", str(QWEN)])
        process = spawn(args)
        while process.poll() is None and not healthy():
            if on_wait:
                on_wait()
            time.sleep(0.4)
        if not healthy():
            raise ServiceStateError("service-start", f"字幕服务启动失败，请查看 {LOG}。" if diagnostics_enabled()
                               else "字幕服务启动失败。开启诊断模式后重试可查看日志。")


def prepare():
    DATA.mkdir(parents=True, exist_ok=True)
    with log_output(DATA / "setup.log") as log:
        options = {"cwd": ROOT, "stdout": log or subprocess.DEVNULL, "stderr": subprocess.STDOUT,
                   "creationflags": subprocess.CREATE_NO_WINDOW, "check": True}
        if not PYTHON.is_file():
            subprocess.run([sys._base_executable, "-m", "venv", ".venv"], **options)
        subprocess.run([str(PYTHON.with_name("python.exe")), "-m", "pip", "install", "-e",
                        ".[local,cloud,desktop,fsmn-vad]", "nvidia-cublas-cu12==12.8.4.1",
                        "nvidia-cudnn-cu12==9.10.2.21"], **options)
