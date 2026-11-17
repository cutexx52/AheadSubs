import os
import shutil
import winreg
from pathlib import Path

from .runtime import LAUNCHER, PORT, PYTHON, ROOT, QWEN, config, save_config

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
    if directory := config()["mpv_directory"]:
        return Path(directory)
    if executable := shutil.which("mpv.exe"):
        portable = Path(executable).parent / "portable_config"
        if portable.is_dir():
            return portable
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
    if directory := config()["potplayer_directory"]:
        return Path(directory)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\DAUM\PotPlayer") as key:
            return Path(winreg.QueryValueEx(key, "ProgramFolder")[0])
    except OSError:
        return Path(os.environ["ProgramFiles"]) / "DAUM" / "PotPlayer"


def install_potplayer(destination):
    destination.mkdir(parents=True, exist_ok=True)
    for path in (ROOT / "integrations/potplayer").glob("*.as"):
        script = path.read_text(encoding="utf-8").replace("@RELAY_PYTHONW@", PYTHON.as_posix())
        script = script.replace("@RELAY_LAUNCHER@", LAUNCHER.as_posix())
        (destination / path.name).write_text(script, encoding="utf-8")


def integration_directory(player):
    if player == "potplayer":
        return potplayer_directory()
    if player == "mpv":
        return mpv_directory()
    raise ValueError("请选择播放器。")


def integration_files(player, folder):
    if player == "potplayer":
        destination = folder / "Extension" / "Subtitle" / "Translate"
        return [destination / source.name for source in (ROOT / "integrations/potplayer").glob("*.as")]
    return [folder / "scripts/subtitle_relay.lua", folder / "script-opts/subtitle_relay.conf"]


def player_detected(player, folder):
    if player == "potplayer":
        return any((folder / name).is_file() for name in ("PotPlayerMini64.exe", "PotPlayerMini.exe"))
    return folder.is_dir() or bool(shutil.which("mpv.exe"))


def integration_status(player):
    folder = integration_directory(player)
    files = integration_files(player, folder)
    installed = sum(path.is_file() for path in files)
    return {"folder": str(folder), "detected": player_detected(player, folder),
            "installed": installed > 0, "configured": bool(files) and installed == len(files)}


def configure_player(player, folder=None):
    destination = integration_directory(player)
    if folder:
        destination = Path(folder).expanduser()
        if not destination.is_absolute() or not destination.is_dir():
            raise ValueError("请选择存在的文件夹。")
        if player == "mpv" and (destination / "portable_config").is_dir():
            destination /= "portable_config"
    if not player_detected(player, destination):
        raise ValueError("找不到播放器，请手动选择安装或配置文件夹。")
    if player == "potplayer":
        install_potplayer(destination / "Extension" / "Subtitle" / "Translate")
    else:
        install_mpv(destination)
    if folder:
        settings = config()
        settings[f"{player}_directory"] = str(destination.resolve())
        save_config(settings)


def unconfigure_player(player):
    for path in integration_files(player, integration_directory(player)):
        path.unlink(missing_ok=True)
