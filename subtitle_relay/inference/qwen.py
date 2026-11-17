"""Managed local Qwen3-ASR using the Windows CrispASR runtime."""
import hashlib
import os
import socket
import subprocess
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path
from urllib.request import ProxyHandler, build_opener


RUNTIME = "crispasr-windows-x86_64-vulkan"
RUNTIME_SHA = "a05f479cf27842d053b2ba416a537fc0fee830dade1fdd94c4f7688f3c7685ef"
RUNTIME_URL = f"https://github.com/CrispStrobe/CrispASR/releases/download/v0.8.54/{RUNTIME}.zip"
ALIGNER = "qwen3-forced-aligner-0.6b-q4_k.gguf"
ALIGNER_URL = "https://huggingface.co/cstr/qwen3-forced-aligner-0.6b-GGUF/resolve/1ec5110/" + ALIGNER
MODELS = {
    "0.6b": "https://huggingface.co/cstr/qwen3-asr-0.6b-GGUF/resolve/main/",
    "1.7b": "https://huggingface.co/cstr/qwen3-asr-1.7b-GGUF/resolve/dc93371563f728f1a791e3764d0989f881dec0d6/",
}
MODEL_FILES = {
    "0.6b": (631026336, "f63771c02dfa486d9399d41ab6ab8cd2d8ca24e077cd32130ea1f67f4fd8dade"),
    "1.7b": (1334415232, "1f1d26ee044f0f041b0a7bfcf6d560996103c951acbde6eb48ccb24e7edfc69c"),
}
ALIGNER_FILE = (529001216, "a7bb4cbeacc6414f11a5d23dc7661a51a941a71e6d559dc7b408b52473f2ae84")


def paths(root, size):
    root = Path(root) if root is not None else Path(os.environ["LOCALAPPDATA"]) / "Subtitle Relay" / "qwen"
    return (root / RUNTIME / "crispasr.exe", root / f"qwen3-asr-{size}-q4_k.gguf", root / ALIGNER)


def installed(root, size):
    executable, model, aligner = paths(root, size)
    return executable.is_file() and complete(model, MODEL_FILES[size]) and complete(aligner, ALIGNER_FILE)


def complete(path, spec):
    return path.is_file() and path.stat().st_size == spec[0]


def download(url, path, digest):
    temporary = path.with_suffix(".part")
    subprocess.run(["curl.exe", "-fL", "--retry", "2", "--output", str(temporary), url],
                   creationflags=subprocess.CREATE_NO_WINDOW, check=True, timeout=900)
    with temporary.open("rb") as file:
        if hashlib.file_digest(file, "sha256").hexdigest() != digest:
            raise ValueError(f"Download checksum did not match for {path.name}")
    temporary.replace(path)


def install(root, size):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    executable, model, aligner = paths(root, size)
    if not executable.is_file():
        archive = root / f"{RUNTIME}.zip"
        download(RUNTIME_URL, archive, RUNTIME_SHA)
        with zipfile.ZipFile(archive) as packaged:
            packaged.extractall(root)
        archive.unlink()
    if not complete(model, MODEL_FILES[size]):
        download(MODELS[size] + model.name, model, MODEL_FILES[size][1])
    if not complete(aligner, ALIGNER_FILE):
        download(ALIGNER_URL, aligner, ALIGNER_FILE[1])


@contextmanager
def run(root, size):
    executable, model, aligner = paths(root, size)
    if not installed(root, size):
        raise RuntimeError("Install the selected Qwen3-ASR model in the Relay app first")
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    server = subprocess.Popen([
        str(executable), "--server", "--host", "127.0.0.1", "--port", str(port),
        "--backend", "qwen3", "-m", str(model), "-am", str(aligner), "--force-aligner",
    ], cwd=executable.parent, creationflags=subprocess.CREATE_NO_WINDOW)
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    opener = build_opener(ProxyHandler({}))
    try:
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError(f"Qwen3-ASR failed to start (exit {server.returncode}); see service.log")
            try:
                with opener.open(url + "/health", timeout=0.5):
                    break
            except OSError:
                time.sleep(0.25)
        else:
            raise RuntimeError("Qwen3-ASR startup timed out; see service.log")
        yield url + "/v1"
    finally:
        if server.poll() is None:
            server.terminate()
            server.wait(timeout=10)
