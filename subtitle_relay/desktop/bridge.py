"""JSON desktop control interface. Model inference stays in the Relay service."""
import argparse
import json
import shutil
import sys
from contextlib import redirect_stdout

from . import assets, runtime
from ..inference.providers import QWEN_MT_MODELS, openai_key, qwen_mt_credentials
from ..server.history import inspect_cache


MODELS = {
    "qwen-0.6b": "[本地] Qwen3-ASR 0.6B",
    "qwen-1.7b": "[本地] Qwen3-ASR 1.7B",
    "whisper-small": "[本地] Whisper Small",
    "nllb": "[本地] NLLB-200 600M INT8",
}


def status():
    settings = runtime.config()
    health = runtime.service_health()
    folder = assets.potplayer_directory()
    return {"running": health is not None, "active_sessions": (health or {}).get("active_sessions"),
            "settings": settings, "models": {model: assets.model_ready(label) for model, label in MODELS.items()},
            "potplayer_detected": any((folder / name).is_file() for name in ("PotPlayerMini64.exe", "PotPlayerMini.exe")),
            "ffmpeg_detected": bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))}


def apply(updates):
    if not isinstance(updates, dict) or not updates.keys() <= runtime.DEFAULTS.keys():
        raise ValueError("设置包含未知选项。")
    settings = runtime.config()
    for key, value in updates.items():
        if isinstance(value, bool) and key in {"diagnostics", "pot_hotkey", "bilingual"}:
            value = "1" if value else "0"
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise ValueError(f"无效的设置项 {key}。")
        settings[key] = str(value).strip()
    for key, options in {
        "asr": {"local", "openai", "compatible", "qwen"}, "qwen_size": {"0.6b", "1.7b"},
        "mt": {"local", "openai", "compatible", "qwen-mt"}, "device": {"cpu", "cuda"},
        "diagnostics": {"0", "1"}, "pot_hotkey": {"0", "1"}, "vad_model": {"silero", "fsmn"},
        "bilingual": {"0", "1"},
        "route": {"asr+mt", "OpenAI AST (English)"}, "qwen_mt_model": QWEN_MT_MODELS,
    }.items():
        if settings[key] not in options:
            raise ValueError(f"不支持的设置值 {key}。")
    if not settings["target"]:
        raise ValueError("请选择字幕目标语言。")
    try:
        numbers = {key: float(settings[key]) for key in (
            "chunk", "before", "after", "min_speech", "max_speech", "min_silence_ms", "pad_ms", "vad_threshold", "backfill",
            "translation_before", "translation_after")}
    except ValueError as exc:
        raise ValueError("高级时间轴设置需要填写数字。") from exc
    if not (4 <= numbers["chunk"] <= 20 and 0 <= numbers["before"] <= 5 and 0 <= numbers["after"] <= 5
            and 0.2 <= numbers["min_speech"] <= numbers["max_speech"] and 2 <= numbers["max_speech"] <= 20
            and 40 <= numbers["min_silence_ms"] <= 2000
            and 0 <= numbers["pad_ms"] <= 500 and 0 < numbers["vad_threshold"] < 1
            and 0 <= numbers["backfill"] <= 30 and 0 <= numbers["translation_before"] <= 15
            and 0 <= numbers["translation_after"] <= 15 and len(settings["translation_prompt"]) <= 1000):
        raise ValueError("高级时间轴设置超出支持范围。")
    for key in ("chunk", "min_silence_ms", "pad_ms"):
        if not numbers[key].is_integer():
            raise ValueError(f"{key} 必须是整数。")
        settings[key] = str(int(numbers[key]))
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise ValueError("未找到 FFmpeg 和 FFprobe。请使用 Windows 发布包，或为源码运行配置 PATH。")
    if settings["route"] == "OpenAI AST (English)" or "openai" in (settings["asr"], settings["mt"]):
        openai_key(settings["key_file"])
    if settings["mt"] == "qwen-mt" and settings["route"] != "OpenAI AST (English)":
        qwen_mt_credentials(settings["qwen_mt_url"], settings["qwen_mt_key_file"])
    runtime.save_config(settings)
    runtime.PAUSED.unlink(missing_ok=True)
    runtime.background_start(restart=True)
    return status()


def run_command(command, item=None):
    if command == "status":
        return status()
    if command == "inspect":
        return inspect_cache(runtime.DATA / "cache" / "cache.sqlite3", item)
    if command == "install":
        if item not in MODELS:
            raise ValueError("请选择已支持的本地模型。")
        if not assets.model_ready(MODELS[item]):
            assets.install_model(MODELS[item])
        return status()
    if command == "apply":
        return apply(json.load(sys.stdin))
    if command == "stop":
        runtime.background_stop()
        return {"running": False}
    if command == "integrate":
        if item == "potplayer":
            destination = assets.potplayer_directory() / "Extension" / "Subtitle" / "Translate"
            if not destination.is_dir():
                raise ValueError("未找到 PotPlayer 的扩展目录，请先安装 PotPlayer。")
            assets.install_potplayer(destination)
        elif item == "mpv":
            destination = assets.mpv_directory()
            assets.install_mpv(destination)
        else:
            raise ValueError("请选择 PotPlayer 或 mpv。")
        return {"installed": item}
    return {"logs": {"server": str(runtime.LOG), "player": str(runtime.DATA / "potplayer.log"),
                     "setup": str(runtime.DATA / "setup.log")}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("status", "install", "apply", "stop", "integrate", "logs", "inspect"))
    parser.add_argument("item", nargs="?")
    args = parser.parse_args()
    result = {"ok": True}
    try:
        with redirect_stdout(sys.stderr):
            result.update(run_command(args.command, args.item))
    except (ValueError, RuntimeError) as exc:
        result = {"ok": False, "error": str(exc)}
    except Exception as exc:
        result = {"ok": False, "error": f"操作失败（{type(exc).__name__}）。请检查网络、文件和运行环境。"}
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
