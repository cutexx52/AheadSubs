from collections.abc import Mapping


ERROR_MESSAGES = {
    "content_blocked": "请求被服务商的内容审核拦截",
    "moderation_unavailable": "服务商的内容审核暂时不可用",
    "authentication_failed": "API 密钥无效，请检查密钥设置",
    "permission_denied": "API 服务拒绝访问，请检查账号或模型权限",
    "not_found": "API 模型或接口不存在，请检查模型名与地址",
    "rate_limited": "API 达到限额，请检查额度、余额或请求频率",
    "provider_unavailable": "API 服务暂时不可用",
    "invalid_request": "API 拒绝了请求参数",
    "request_timeout": "API 请求超时",
    "translation_failed": "翻译失败",
    "processing_failed": "处理失败",
}


class ProviderError(ValueError):
    """A known failure category shared by all inference providers."""

    def __init__(self, kind, http_status=None):
        self.kind = kind
        self.http_status = http_status
        super().__init__(ERROR_MESSAGES[kind])


def provider_error(error, *, default="processing_failed"):
    if isinstance(error, ProviderError):
        return error
    body = getattr(error, "body", None)
    if isinstance(body, Mapping):
        body = body.get("error", body)
    codes = [getattr(error, "code", None)]
    if isinstance(body, Mapping):
        codes.extend((body.get("code"), body.get("type")))
    aliases = {code.lower().replace("_", "") for code in codes if isinstance(code, str)}
    status = getattr(error, "status_code", None)
    status = status if type(status) is int else None
    if aliases & {"datainspectionfailed", "contentfilter", "contentpolicyviolation"}:
        kind = "content_blocked"
    elif "internalerror.datainspection" in aliases:
        kind = "moderation_unavailable"
    elif isinstance(error, TimeoutError) or status == 408:
        kind = "request_timeout"
    elif isinstance(status, int) and 500 <= status <= 599:
        kind = "provider_unavailable"
    else:
        kind = {400: "invalid_request", 401: "authentication_failed", 403: "permission_denied",
                404: "not_found", 429: "rate_limited"}.get(status, default)
    return ProviderError(kind, status)


def completion_text(response):
    choice = next(iter(response.choices), None)
    if getattr(choice, "finish_reason", None) == "content_filter":
        raise ProviderError("content_blocked")
    return choice.message.content if choice else None
