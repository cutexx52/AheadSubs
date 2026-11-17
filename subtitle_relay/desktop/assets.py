import os
import winreg
from pathlib import Path

from .runtime import LAUNCHER, PORT, PYTHON, ROOT, QWEN

LOCAL_MODELS = {
    "[本地] Whisper Small": "Systran/faster-whisper-small",
    "[本地] NLLB-200 600M INT8": "Adom4600/nllb-200-distilled-600M-ct2-int8",
}
QWEN_LABELS = {"[本地] Qwen3-ASR 0.6B": "0.6b", "[本地] Qwen3-ASR 1.7B": "1.7b"}


def model_ready(label):
    from subtitle_relay.inference.qwen import installed

    if label in QWEN_LABELS:
        return installed(QWEN, QWEN_LABELS[label])
    if label in LOCAL_MODELS:
        hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
        hub = Path(os.environ.get("HF_HUB_CACHE", hf_home / "hub"))
        snapshots = hub / ("models--" + LOCAL_MODELS[label].replace("/", "--")) / "snapshots"
        return any(path.is_file() for path in snapshots.glob("*/model.bin"))
    return True


def install_model(label):
    if label in QWEN_LABELS:
        from subtitle_relay.inference.qwen import install

        install(QWEN, QWEN_LABELS[label])
    else:
        from huggingface_hub import snapshot_download

        snapshot_download(LOCAL_MODELS[label])


def mpv_directory():
    return Path(os.environ["APPDATA"]) / "mpv"


def install_mpv(destination):
    scripts = destination / "scripts"
    opts = destination / "script-opts"
    scripts.mkdir(parents=True, exist_ok=True)
    opts.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "integrations/mpv/subtitle_relay.lua", scripts)
    (opts / "subtitle_relay.conf").write_text(
        f"pythonw={PYTHON.as_posix()}\nlauncher={LAUNCHER.as_posix()}\nport={PORT}\n",
        encoding="utf-8",
    )


def potplayer_directory():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\DAUM\PotPlayer") as key:
            return Path(winreg.QueryValueEx(key, "ProgramFolder")[0])
    except OSError:
        return Path(os.environ["ProgramFiles"]) / "DAUM" / "PotPlayer"


def install_potplayer(destination):
    for path in (ROOT / "integrations/potplayer").glob("*.as"):
        script = path.read_text(encoding="utf-8").replace("@RELAY_PYTHONW@", PYTHON.as_posix())
        script = script.replace("@RELAY_LAUNCHER@", LAUNCHER.as_posix())
        (destination / path.name).write_text(script, encoding="utf-8")
