from time import monotonic

from .chatgpt_auth import RESOURCE, ChatGPTAccounts
from .errors import ProviderError, provider_error
from .providers import ChatTranslation


class ChatGPTTranslation(ChatTranslation):
    def __init__(self, account, model):
        if not account or not model:
            raise ValueError("请先选择 ChatGPT 账号和模型。")
        self.account = account
        self.model = model
        self.accounts = ChatGPTAccounts()
        self.backoff = (0, "provider_unavailable")

    def complete(self, instructions, payload):
        from openai import OpenAI

        token = self.accounts.access_token(self.account)
        retry_at, retry_kind = self.backoff
        if monotonic() < retry_at:
            raise ProviderError(retry_kind)
        try:
            with OpenAI(api_key=token, base_url=RESOURCE, max_retries=0, timeout=30) as client:
                with client.responses.create(
                    model=self.model, instructions=instructions, input=[{"role": "user", "content": payload}],
                    text={"format": {"type": "json_object"}}, store=False, stream=True,
                ) as stream:
                    return completed_text(stream)
        except Exception as exc:
            error = provider_error(exc, default="translation_failed")
            if error.kind in {"authentication_failed", "chatgpt_sign_in_required"}:
                self.accounts.invalidate(self.account, token)
                error = ProviderError("chatgpt_sign_in_required", error.http_status)
            if error.kind in {"rate_limited", "provider_unavailable"}:
                self.backoff = (monotonic() + 60, error.kind)
            raise error from None


def completed_text(stream):
    chunks = []
    for event in stream:
        if event.type == "response.output_text.delta":
            chunks.append(event.delta)
        elif event.type == "response.completed":
            return "".join(chunks)
        elif event.type == "response.failed":
            raise provider_error(event.response.error, default="translation_failed")
        elif event.type == "error":
            raise provider_error(event, default="translation_failed")
        elif event.type == "response.incomplete":
            details = event.response.incomplete_details
            if getattr(details, "reason", None) == "content_filter":
                raise ProviderError("content_blocked")
            raise ProviderError("translation_failed")
    raise ProviderError("translation_failed")
