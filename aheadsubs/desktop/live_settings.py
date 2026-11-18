"""Apply desktop playback and timing preferences to an existing model pipeline."""
import hashlib
import hmac
import json

from . import credentials, runtime
from ..server.engine import SubtitlePipeline


def credential_stamp(settings, token):
    # A key file or environment variable can rotate without changing settings.json.
    # Only the authenticated desktop and this service can compare the keyed digest.
    providers = {}
    ast = settings["route"] == "OpenAI AST (English)"
    if ast or "openai" in (settings["asr"], settings["mt"]):
        providers["openai"] = None
    if not ast:
        if settings["asr"] == "dashscope" or settings["mt"] == "qwen-mt":
            providers["dashscope"] = None
        if settings["mt"] == "minimax":
            providers["minimax"] = None
        if settings["asr"] == "compatible":
            providers["compatible-asr"] = settings["asr_url"]
        if settings["mt"] == "compatible":
            providers["compatible-mt"] = settings["llm_url"]
    values = {name: credentials.resolve(settings, name, endpoint) for name, endpoint in providers.items()}
    return hmac.new(token.encode(), json.dumps(values, sort_keys=True).encode(), hashlib.sha256).hexdigest()


def local_models(args):
    speech = None
    if not args.ast and args.asr == "local":
        speech = (args.whisper_model, args.asr_device or args.device)
    elif not args.ast and args.asr == "qwen":
        speech = ("qwen", args.qwen_size)
    translation = (args.nllb_model, args.mt_device or args.device) if not args.ast and args.mt == "local" else None
    return speech, translation, args.vad_model


def provider_settings(args):
    return (args.ast, args.asr, args.mt, args.asr_url, args.asr_model, args.llm_url, args.llm_model,
            args.qwen_mt_url, args.qwen_mt_model, args.dashscope_asr_model, args.chatgpt_account, args.chatgpt_model)


class LiveSettings:
    def __init__(self, args, settings, relay, defaults, token):
        self.args = args
        self.settings = settings
        self.relay = relay
        self.defaults = defaults
        self.token = token
        initial = {**runtime.DEFAULTS, **settings}
        self.stamp = credential_stamp(initial, token) if token else None

    def playback_defaults(self):
        return self.defaults

    def apply(self, stamp):
        from ..__main__ import (dashscope_endpoint, make_backends, monitor_pipeline, parse_command, segmentation,
                                subtitle_profile, transcription_profile, translation_preferences)

        settings = runtime.config(self.args.desktop_config)
        _, updated = parse_command(runtime.service_args(settings))
        models = local_models(updated)
        if (local_models(self.args) != models or updated.diagnostics != self.args.diagnostics
                or updated.pot_hotkey_launcher != self.args.pot_hotkey_launcher):
            return False
        if updated.asr == "qwen" and not updated.ast:
            # The managed child keeps its ephemeral loopback port across live applies.
            updated.asr_url, updated.asr_model = self.args.asr_url, self.args.asr_model
        try:
            service_stamp = credential_stamp(settings, self.token)
        except ValueError:
            return False
        if stamp != service_stamp:
            # An environment credential is only inherited by a newly started process.
            return False
        relay = self.relay
        with relay.lock:
            old = relay.pipeline
            speech, translation, ast = old.recognizer, old.translator, old.speech_translator
            providers_changed = self.stamp != stamp or provider_settings(self.args) != provider_settings(updated)
            if providers_changed:
                speech, translation, ast = make_backends(updated, settings, shared_asr=speech if models[0] else None,
                                                         shared_mt=translation if models[1] else None)
            timing = segmentation(updated)
            preferences = translation_preferences(updated).for_translator(None if ast else translation)
            profile = subtitle_profile(updated, timing, translation)
            if (providers_changed or updated.chunk != old.chunk or timing != old.segmenter.settings
                    or preferences != old.translation_settings or profile != old.profile):
                segmenter = old.segmenter if timing == old.segmenter.settings else old.segmenter.with_settings(timing)
                pipeline = SubtitlePipeline(speech, translation, profile, ast, preferences,
                                            chunk=updated.chunk, segmenter=segmenter)
                if providers_changed:
                    relay.model_status = monitor_pipeline(updated, speech, translation, ast,
                                                          dashscope_endpoint(updated), relay.cloud_usage)
                relay.pipeline = pipeline
                relay.recognizer, relay.translator = speech, translation
                relay.segmenter, relay.chunk = segmenter, updated.chunk
                relay.transcriptions.set_profile(transcription_profile(updated, timing))
            self.stamp = stamp
            self.settings.update(settings)
            updated.desktop_config = self.args.desktop_config
            vars(self.args).update(vars(updated))
            self.defaults = {"source": updated.default_source, "target": updated.default_target,
                             "bilingual": updated.default_bilingual}
        return True
