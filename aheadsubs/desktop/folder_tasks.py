"""Windows idle detection and the desktop bridge for folder tasks."""
import ctypes
import json
import logging
from argparse import Namespace
from contextlib import ExitStack, contextmanager
from ctypes import wintypes

from pydantic import ValidationError

from ..automation import OperationError
from ..folder_tasks import FolderWorker, RuleSet, TaskFiles
from ..inference.dashscope import DASHSCOPE_ASR_MODELS
from ..inference.errors import provider_error
from ..inference.providers import QWEN_MT_MODELS
from ..server.engine import TranslationSettings
from . import assets, runtime


class LastInput(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def windows_idle_seconds():
    state = LastInput(ctypes.sizeof(LastInput), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(state)):
        return 0
    uptime = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    return ((uptime - state.dwTime) & 0xFFFFFFFF) / 1000


def folder_model_args(args, settings, rule):
    selected = Namespace(**vars(args))
    selected.ast = False
    speech, translation = rule.speech_model, rule.translation_model
    if speech == "whisper-small":
        selected.asr, selected.whisper_model = "local", "small"
    elif speech in {"qwen-0.6b", "qwen-1.7b"}:
        selected.asr, selected.qwen_size, selected.asr_model = "qwen", speech[5:], "qwen3-asr"
    elif speech in DASHSCOPE_ASR_MODELS:
        selected.asr, selected.dashscope_asr_model = "dashscope", speech
    elif speech == "compatible":
        selected.asr = speech
        if args.asr == "qwen" and not args.ast:
            selected.asr_url = settings.get("asr_url", runtime.DEFAULTS["asr_url"])
            selected.asr_model = settings.get("asr_model", runtime.DEFAULTS["asr_model"])
    elif speech is not None:
        selected.asr = speech
    if translation == "nllb":
        selected.mt = "local"
    elif translation in QWEN_MT_MODELS:
        selected.mt, selected.qwen_mt_model = "qwen-mt", translation
    elif translation in {"compatible", "chatgpt", "minimax"}:
        selected.mt = translation
    elif translation is not None:
        selected.mt, selected.llm_model = "openai", translation.removeprefix("openai:")
    return selected


@contextmanager
def folder_pipeline(relay, args, settings, rule, build_pipeline):
    selected = folder_model_args(args, settings, rule)
    asr_fields = ("asr", {"local": "whisper_model", "qwen": "qwen_size", "dashscope": "dashscope_asr_model",
                          "compatible": "asr_model"}.get(selected.asr, "asr"))
    mt_fields = ("mt", {"openai": "llm_model", "qwen-mt": "qwen_mt_model"}.get(selected.mt, "mt"))
    shared_asr = relay.recognizer if not args.ast and all(getattr(args, key) == getattr(selected, key) for key in asr_fields) else None
    shared_mt = relay.translator if not args.ast and all(getattr(args, key) == getattr(selected, key) for key in mt_fields) else None
    if shared_asr is not None and (shared_mt is not None or selected.mt == args.mt == "none"):
        yield None
        return

    local_models = set()
    if shared_asr is None and selected.asr == "qwen":
        local_models.add(f"qwen-{selected.qwen_size}")
    if shared_asr is None and selected.asr == "local":
        local_models.add("whisper-small")
    if shared_mt is None and selected.mt == "local":
        local_models.add("nllb")
    with ExitStack() as resources:
        try:
            if local_models:
                with runtime.lock_model_use(runtime.DATA):
                    if not all(assets.model_ready(assets.MODELS[model]) for model in local_models):
                        raise OperationError("folder_model_not_installed")
                    with relay.lock:
                        relay.background_models.update(local_models)

                def release_models():
                    with relay.lock:
                        relay.background_models.difference_update(local_models)

                resources.callback(release_models)
            if shared_asr is None and selected.asr == "qwen":
                from ..inference.qwen import run

                selected.asr_url = resources.enter_context(run(selected.qwen_root, selected.qwen_size))
                selected.asr_model = "qwen3-asr"
            key = runtime.enhancement_key(vars(selected))
            saved = settings.get("translation_enhancements", {}).get(key, {})
            if shared_mt is not None:
                enhancements = relay.pipeline.translation_settings
            elif saved.get("enabled"):
                enhancements = TranslationSettings(saved["previous_cues"], saved["prompt"],
                                                   saved.get("context_chars", TranslationSettings.context_chars))
            else:
                enhancements = TranslationSettings()
            pipeline = build_pipeline(selected, enhancements, shared_asr, shared_mt)
        except OperationError:
            raise
        except Exception as exc:
            logging.getLogger(__name__).warning("Folder model setup failed (%s)", type(exc).__name__)
            error = provider_error(exc, default="processing_failed")
            code = "folder_model_unavailable" if error.kind == "processing_failed" else error.kind
            raise OperationError(code) from exc
        yield pipeline


def background_worker(relay, defaults, args, settings, build_pipeline):
    def open_pipeline(rule):
        return folder_pipeline(relay, args, settings, rule, build_pipeline)

    return FolderWorker(TaskFiles(runtime.DATA), relay, defaults, windows_idle_seconds, open_pipeline).running()


def configure(action, stream):
    files = TaskFiles(runtime.DATA)
    if action == "save":
        try:
            config = RuleSet.model_validate(json.load(stream))
        except ValidationError as exc:
            field = ".".join(map(str, exc.errors(include_input=False)[0]["loc"])) or "rules"
            raise OperationError("folder_task_invalid", field=field) from exc
        files.save(config)
    elif action == "retry":
        request = json.load(stream)
        identifier = request.get("id") if isinstance(request, dict) else None
        if not any(rule.id == identifier for rule in files.load().rules):
            raise OperationError("folder_task_invalid", field="id")
        files.retry(identifier)
    elif action is not None:
        raise OperationError("folder_task_invalid", field="action")
    return {**files.status(), "running": runtime.healthy()}
