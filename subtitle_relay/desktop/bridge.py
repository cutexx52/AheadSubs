"""JSON desktop control interface. Model inference stays in the Relay service."""
import argparse
import json
import shutil
import sys
from contextlib import redirect_stdout

from . import assets, credentials, runtime
from ..inference.dashscope import DASHSCOPE_ASR_MODELS
from ..inference.providers import QWEN_MT_MODELS, qwen_mt_credentials
from ..server.engine import TranslationSettings
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
    integrations = {player: assets.integration_status(player) for player in ("potplayer", "mpv")}
    return {"running": health is not None, "active_sessions": (health or {}).get("active_sessions"),
            "settings": {key: settings[key] for key in runtime.DEFAULTS},
            "credentials": credentials.public_state(settings),
            "models": {model: assets.model_ready(label) for model, label in MODELS.items()},
            "potplayer_detected": integrations["potplayer"]["detected"], "integrations": integrations,
            "ffmpeg_detected": bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))}


def apply(updates):
    if not isinstance(updates, dict) or not updates.keys() <= (runtime.DEFAULTS.keys() | {"credentials"}):
        raise ValueError("设置包含未知选项。")
    settings = runtime.config()
    for key, value in updates.items():
        if key == "credentials":
            credentials.update(settings, value)
            continue
        if key == "translation_enhancements":
            settings[key] = validate_enhancements(value)
            continue
        if isinstance(value, bool) and key in {"diagnostics", "pot_hotkey", "bilingual"}:
            value = "1" if value else "0"
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise ValueError(f"无效的设置项 {key}。")
        settings[key] = str(value).strip()
    for key, options in {
        "asr": {"local", "openai", "compatible", "qwen", "dashscope"}, "qwen_size": {"0.6b", "1.7b"},
        "mt": {"local", "openai", "compatible", "qwen-mt"}, "device": {"cpu", "cuda"},
        "diagnostics": {"0", "1"}, "pot_hotkey": {"0", "1"}, "vad_model": {"silero", "fsmn"},
        "bilingual": {"0", "1"},
        "route": {"asr+mt", "OpenAI AST (English)"}, "qwen_mt_model": QWEN_MT_MODELS,
        "dashscope_asr_model": DASHSCOPE_ASR_MODELS,
    }.items():
        if settings[key] not in options:
            raise ValueError(f"不支持的设置值 {key}。")
    if not settings["target"]:
        raise ValueError("请选择字幕目标语言。")
    try:
        numbers = {key: float(settings[key]) for key in (
            "chunk", "before", "after", "min_speech", "max_speech", "min_silence_ms", "pad_ms", "vad_threshold", "backfill")}
    except ValueError as exc:
        raise ValueError("高级时间轴设置需要填写数字。") from exc
    if not (4 <= numbers["chunk"] <= 20 and 0 <= numbers["before"] <= 5 and 0 <= numbers["after"] <= 5
            and 0.2 <= numbers["min_speech"] <= numbers["max_speech"] and 2 <= numbers["max_speech"] <= 20
            and 40 <= numbers["min_silence_ms"] <= 2000
            and 0 <= numbers["pad_ms"] <= 500 and 0 < numbers["vad_threshold"] < 1
            and 0 <= numbers["backfill"] <= 30):
        raise ValueError("高级时间轴设置超出支持范围。")
    for key in ("chunk", "min_silence_ms", "pad_ms"):
        if not numbers[key].is_integer():
            raise ValueError(f"{key} 必须是整数。")
        settings[key] = str(int(numbers[key]))
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise ValueError("未找到 FFmpeg 和 FFprobe。请使用 Windows 发布包，或为源码运行配置 PATH。")
    ast = settings["route"] == "OpenAI AST (English)"
    if ast or "openai" in (settings["asr"], settings["mt"]):
        credentials.resolve(settings, "openai")
    if not ast:
        if settings["mt"] == "qwen-mt" or settings["asr"] == "dashscope":
            qwen_mt_credentials(settings["qwen_mt_url"], api_key=credentials.resolve(settings, "dashscope"))
        if settings["asr"] == "compatible":
            credentials.resolve(settings, "compatible-asr", settings["asr_url"])
        if settings["mt"] == "compatible":
            credentials.resolve(settings, "compatible-mt", settings["llm_url"])
    runtime.save_config(settings)
    runtime.PAUSED.unlink(missing_ok=True)
    runtime.background_start(restart=True)
    return status()


def validate_enhancements(values):
    if not isinstance(values, dict):
        raise ValueError("翻译增强设置格式无效。")
    for model, value in values.items():
        if not (model.partition(":")[0] in {"openai", "compatible", "qwen-mt"}
                and isinstance(value, dict)
                and value.keys() - {"context_chars"} == {"enabled", "previous_cues", "prompt"}
                and isinstance(value["enabled"], bool) and isinstance(value["prompt"], str)):
            raise ValueError("翻译增强设置格式无效。")
        TranslationSettings(value["previous_cues"], value["prompt"],
                            value.get("context_chars", TranslationSettings.context_chars))
    return values


def run_command(command, item=None, folder=None):
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
    if command == "save-credentials":
        settings = runtime.config()
        credentials.update(settings, json.load(sys.stdin))
        runtime.save_config(settings)
        return {"credentials": credentials.public_state(settings)}
    if command == "stop":
        runtime.background_stop()
        return {"running": False}
    if command in {"pot-windows", "pot-start", "pot-stop"}:
        from ..adapters.potplayer import list_windows

        windows = list_windows()
        if command == "pot-windows":
            return {"windows": [{"id": hwnd, "title": title} for hwnd, title in windows]}
        if not item or not any(str(hwnd) == item for hwnd, _ in windows):
            raise ValueError("该 PotPlayer 窗口已关闭。")
        switches = {"pot-start": "--pot-hwnd", "pot-stop": "--pot-stop-hwnd"}
        runtime.spawn([str(runtime.LAUNCHER), switches[command], item], runtime.DATA / "potplayer.log")
        return {}
    if command == "integrate":
        assets.configure_player(item, folder)
        return {"installed": item}
    if command == "unintegrate":
        assets.unconfigure_player(item)
        return {"removed": item}
    return {"logs": {"server": str(runtime.LOG), "player": str(runtime.DATA / "potplayer.log"),
                     "setup": str(runtime.DATA / "setup.log")}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("status", "install", "apply", "save-credentials", "stop", "integrate", "unintegrate", "logs", "inspect",
                                           "pot-windows", "pot-start", "pot-stop"))
    parser.add_argument("item", nargs="?")
    parser.add_argument("--folder")
    args = parser.parse_args()
    result = {"ok": True}
    try:
        with redirect_stdout(sys.stderr):
            result.update(run_command(args.command, args.item, args.folder))
    except (ValueError, RuntimeError) as exc:
        result = {"ok": False, "error": str(exc)}
    except Exception as exc:
        result = {"ok": False, "error": f"操作失败（{type(exc).__name__}）。请检查网络、文件和运行环境。"}
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
