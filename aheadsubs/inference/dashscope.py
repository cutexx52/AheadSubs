import base64
import json
import re
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .errors import provider_error
from .providers import Cue, OpenAIWhisper, qwen_mt_credentials
from .usage import measured_call


DASHSCOPE_ASR_MODELS = ("qwen-audio-3.1-asr-flash", "qwen-audio-3.0-asr-flash")


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class DashScopeAudio:
    """Use the native short-audio API, which supplies actual sentence timestamps."""

    def __init__(self, endpoint, key_file, model, *, api_key=None):
        compatible, self.key = qwen_mt_credentials(endpoint, key_file, api_key=api_key)
        self.endpoint = (f"https://{urlsplit(compatible).netloc}"
                         "/api/v1/services/aigc/multimodal-generation/generation")
        self.model = model
        self.opener = build_opener(NoRedirects())

    def recognize(self, wav, source):
        parameters = {"format": "wav", "sample_rate": "16000"}
        if source:
            parameters["language_hints"] = [source]
        data = "data:audio/wav;base64," + base64.b64encode(wav).decode("ascii")
        payload = {"model": self.model, "parameters": parameters, "input": {"messages": [
            {"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": data}}]},
        ]}}
        request = Request(self.endpoint, json.dumps(payload).encode("utf-8"), headers={
            "Authorization": f"Bearer {self.key}", "X-DashScope-SSE": "enable", "Content-Type": "application/json",
        })
        try:
            with measured_call(self, "asr") as usage:
                with self.opener.open(request, timeout=30) as response:
                    if response.headers.get_content_type() == "text/event-stream":
                        events = (json.loads(line[5:]) for line in response if line.startswith(b"data:")
                                  and line[5:].strip() not in {b"", b"[DONE]"})
                    else:
                        events = (json.load(response),)
                    result = self._results(events, source, usage)
                    usage.audio = max(0, len(wav) - 44) / 32000
                    return result
        except HTTPError as exc:
            with exc:
                try:
                    body = json.load(exc)
                except (ValueError, UnicodeError):
                    body = {}
            raise provider_error(SimpleNamespace(status_code=exc.code, body=body)) from None

    @staticmethod
    def _results(events, source, usage=None):
        sentences = {}
        transcript = ""
        detected = ""
        for event in events:
            if usage is not None and isinstance(event.get("usage"), dict):
                usage.tokens(event["usage"], "input_tokens", "output_tokens")
            if event.get("code"):
                raise provider_error(SimpleNamespace(body=event))
            output = event.get("output") or {}
            transcript = output.get("text") or transcript
            detected = output.get("language") or detected
            for sentence in output.get("sentences") or [output.get("sentence") or {}]:
                start, end = sentence.get("begin_time"), sentence.get("end_time")
                text = (sentence.get("text") or "").strip()
                if sentence.get("sentence_end") is True and text and isinstance(start, int) and isinstance(end, int) and end > start:
                    key = (sentence.get("channel_id", 0), sentence.get("sentence_id", start))
                    sentences[key] = Cue(start / 1000, end / 1000, text)
        if transcript.strip() and not sentences:
            raise ValueError("DashScope did not return final sentence timestamps")
        if not source and not detected:
            # The native endpoint can omit its language code. Prefer unambiguous scripts.
            if re.search("[ぁ-ゖァ-ヺ]", transcript):
                detected = "ja"
            elif re.search("[가-힣]", transcript):
                detected = "ko"
        language = detected.lower() if isinstance(detected, str) else ""
        return source or OpenAIWhisper.LANGUAGE_NAMES.get(language, language) or "und", sorted(
            sentences.values(), key=lambda cue: cue.start)
