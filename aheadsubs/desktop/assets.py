import os
import shutil
import winreg
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path

from .runtime import DATA, LAUNCHER, PORT, PYTHON, ROOT, QWEN, config, lock_model_use, lock_service, save_config, service_health

MODELS = {
    "qwen-0.6b": "[本地] Qwen3-ASR 0.6B",
    "qwen-1.7b": "[本地] Qwen3-ASR 1.7B",
    "whisper-small": "[本地] Whisper Small",
    "nllb": "[本地] NLLB-200 600M INT8",
}

LOCAL_MODELS = {
    "[本地] Whisper Small": "Systran/faster-whisper-small",
    "[本地] NLLB-200 600M INT8": "Adom4600/nllb-200-distilled-600M-ct2-int8",
}
MODEL_ASSETS = {
    "[本地] Whisper Small": ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt"),
    "[本地] NLLB-200 600M INT8": ("config.json", "model.bin", "tokenizer.json", "shared_vocabulary.json"),
}
QWEN_LABELS = {"[本地] Qwen3-ASR 0.6B": "0.6b", "[本地] Qwen3-ASR 1.7B": "1.7b"}


class ModelRemovalError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def model_hub():
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    return Path(os.environ.get("HF_HUB_CACHE", os.environ.get("HUGGINGFACE_HUB_CACHE", hf_home / "hub")))


def model_ready(label):
    from aheadsubs.inference.qwen import installed

    if label in QWEN_LABELS:
        return installed(QWEN, QWEN_LABELS[label])
    if label in LOCAL_MODELS:
        snapshots = model_hub() / ("models--" + LOCAL_MODELS[label].replace("/", "--")) / "snapshots"
        return any(all((snapshot / name).is_file() for name in MODEL_ASSETS[label])
                   for snapshot in snapshots.glob("*"))
    return True


def install_model(label):
    if label in QWEN_LABELS:
        from aheadsubs.inference.qwen import install

        install(QWEN, QWEN_LABELS[label])
    else:
        from huggingface_hub import snapshot_download

        snapshot_download(LOCAL_MODELS[label])


def active_models(health):
    if health is None:
        return set()
    active = health.get("local_models")
    if isinstance(active, list) and all(isinstance(model, str) for model in active):
        return set(active) & MODELS.keys()
    # An older service cannot report its loaded models.
    return set(MODELS)


def uninstall_model(model_id, label):
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / "starting.lock").open("a+b") as startup, ExitStack() as locks:
        lock_service(startup, wait=True)
        locks.enter_context(lock_model_use(DATA))
        if model_id in active_models(service_health()):
            raise ModelRemovalError("uninstall-active", "请先切换模型或停止字幕服务，再卸载这个模型。")
        if label in QWEN_LABELS:
            from ..inference.qwen import paths

            _, model, _ = paths(QWEN, QWEN_LABELS[label])
            model.unlink(missing_ok=True)
            return
        from huggingface_hub import scan_cache_dir

        hub = model_hub().resolve()
        repository = hub / ("models--" + LOCAL_MODELS[label].replace("/", "--"))
        if not repository.is_dir():
            return
        cache = scan_cache_dir(hub)
        repos = frozenset(repo for repo in cache.repos if repo.repo_path == repository)
        cache = replace(cache, repos=repos)
        commits = {revision.commit_hash for repo in repos for revision in repo.revisions}
        if not commits:
            raise ModelRemovalError("uninstall-incomplete", "缓存不完整，无法卸载这个模型。")
        removal = cache.delete_revisions(*commits)
        for path in removal.repos | removal.snapshots | removal.refs | removal.blobs:
            if not path.resolve().is_relative_to(repository) or not path.resolve().is_relative_to(hub):
                raise ModelRemovalError("uninstall-location", "缓存位置不属于这个模型，无法卸载。")
        for path in getattr(removal, "files", ()):
            if not path.parent.resolve().is_relative_to(repository):
                raise ModelRemovalError("uninstall-location", "缓存位置不属于这个模型，无法卸载。")
        removal.execute()
        if repository.exists():
            raise ModelRemovalError("uninstall-failed", "模型缓存未能完全删除，请关闭其他正在使用它的应用后重试。")


def mpv_directory():
    if directory := config()["mpv_directory"]:
        return Path(directory)
    if executable := shutil.which("mpv.exe"):
        portable = Path(executable).parent / "portable_config"
        if portable.is_dir():
            return portable
    return Path(os.environ["APPDATA"]) / "mpv"


def mpv_files(folder):
    scripts = folder / "scripts"
    legacy = scripts / "subtitle_relay.lua"
    script = legacy if legacy.is_file() else scripts / "aheadsubs.lua"
    return script, folder / "script-opts" / f"{script.stem}.conf"


def install_mpv(destination):
    script, options = mpv_files(destination)
    script.parent.mkdir(parents=True, exist_ok=True)
    options.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "integrations/mpv/aheadsubs.lua", script)
    options.write_text(
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


def potplayer_files(destination):
    legacy = {
        "SubtitleTranslate - AheadSubs.as": "SubtitleTranslate - Subtitle Relay.as",
        "SubtitleTranslate - AheadSubs Audio.as": "SubtitleTranslate - Subtitle Relay Audio.as",
    }
    for source in (ROOT / "integrations/potplayer").glob("*.as"):
        name = legacy.get(source.name)
        previous = destination / name if name else None
        target = previous if previous and previous.is_file() else destination / source.name
        yield source, target


def install_potplayer(destination):
    destination.mkdir(parents=True, exist_ok=True)
    for source, target in potplayer_files(destination):
        script = source.read_text(encoding="utf-8").replace("@RELAY_PYTHONW@", PYTHON.as_posix())
        script = script.replace("@RELAY_LAUNCHER@", LAUNCHER.as_posix())
        target.write_text(script, encoding="utf-8")


def integration_directory(player):
    if player == "potplayer":
        return potplayer_directory()
    if player == "mpv":
        return mpv_directory()
    raise ValueError("请选择播放器。")


def integration_files(player, folder):
    if player == "potplayer":
        destination = folder / "Extension" / "Subtitle" / "Translate"
        return [target for _, target in potplayer_files(destination)]
    return mpv_files(folder)


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
