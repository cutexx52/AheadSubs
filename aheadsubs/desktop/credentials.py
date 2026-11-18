"""Resolve desktop credential sources and protect typed keys with Windows DPAPI."""

import base64
import ctypes
import ipaddress
import os
from ctypes import wintypes
from pathlib import Path
from urllib.parse import urlsplit

from ..user_errors import UserInputError
from ..inference.providers import provider_key


SOURCES = {
    "openai": ("key_file", "OPENAI_API_KEY", "OpenAI"),
    "dashscope": ("qwen_mt_key_file", "DASHSCOPE_API_KEY", "百炼"),
    "minimax": ("minimax_key_file", "MINIMAX_API_KEY", "MiniMax"),
    "compatible-asr": ("asr_key_file", "RELAY_ASR_API_KEY", "自定义识别"),
    "compatible-mt": ("mt_key_file", "RELAY_LLM_API_KEY", "自定义翻译"),
}
PRIVATE_FIELD = "protected_credentials"
PREFIX = "dpapi-v1:"


class DataBlob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(value, *, decrypt=False):
    crypt = ctypes.WinDLL("crypt32")
    local_free = ctypes.WinDLL("kernel32").LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    description = ctypes.c_void_p if decrypt else wintypes.LPCWSTR
    operation.argtypes = [ctypes.POINTER(DataBlob), description, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
    operation.restype = wintypes.BOOL
    buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    source, result = DataBlob(len(value), buffer), DataBlob()
    try:
        if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
            raise UserInputError("key-protection", "Windows 无法读取或保护 API Key，请重新输入后保存。")
        return ctypes.string_at(result.data, result.size)
    finally:
        ctypes.memset(buffer, 0, len(value))
        if result.data:
            ctypes.memset(result.data, 0, result.size)
            local_free(result.data)


def public_state(settings):
    protected = settings.get(PRIVATE_FIELD, {})
    return {provider: {"mode": "direct" if protected.get(provider) else "file" if settings.get(field) else "default",
                       "saved": bool(protected.get(provider)), "file": settings.get(field, "")}
            for provider, (field, _, _) in SOURCES.items()}


def update(settings, changes):
    if not isinstance(changes, dict) or not changes.keys() <= SOURCES.keys():
        raise UserInputError("key-settings", "密钥设置格式无效。")
    protected = dict(settings.get(PRIVATE_FIELD, {}))
    for provider, change in changes.items():
        if not isinstance(change, dict) or not change.keys() <= {"mode", "value"}:
            raise UserInputError("key-settings", "密钥设置格式无效。")
        mode, value = change.get("mode"), change.get("value", "")
        if not isinstance(value, str):
            raise UserInputError("key-settings", "密钥设置格式无效。")
        value = value.strip()
        field, _, label = SOURCES[provider]
        if mode == "direct":
            if value:
                if any(char.isspace() or ord(char) < 32 for char in value):
                    raise UserInputError("key-single-line", f"{label} API Key 应为一行，且不含空格。", provider)
                protected[provider] = PREFIX + base64.b64encode(dpapi(value.encode())).decode("ascii")
            elif not protected.get(provider):
                raise UserInputError("key-required", f"请输入 {label} API Key。", provider)
            settings[field] = ""
        elif mode in {"file", "default"}:
            if mode == "file":
                if not value:
                    raise UserInputError("key-file-required", f"请选择 {label} API Key 文件。", provider)
                read_file(provider, value)
            settings[field] = value if mode == "file" else ""
            protected.pop(provider, None)
        else:
            raise UserInputError("key-settings", "密钥设置格式无效。")
    settings[PRIVATE_FIELD] = protected


def read_file(provider, path):
    _, variable, label = SOURCES[provider]
    if not provider.startswith("compatible-"):
        return provider_key(path, variable, label)
    try:
        value = Path(path).read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeError):
        raise UserInputError("key-file-invalid", f"无法读取 {label} API Key 文件。", provider) from None
    if value.startswith(f"{variable}="):
        value = value.partition("=")[2].strip().strip("\"'")
    if not value or any(char.isspace() or ord(char) < 32 for char in value):
        raise UserInputError("key-file-invalid", f"{label} API Key 文件应包含一行有效的密钥。", provider)
    return value


def resolve(settings, provider, endpoint=None):
    field, variable, label = SOURCES[provider]
    stored = settings.get(PRIVATE_FIELD, {}).get(provider)
    path = settings.get(field)
    if stored:
        try:
            if not stored.startswith(PREFIX):
                raise ValueError
            value = dpapi(base64.b64decode(stored[len(PREFIX):], validate=True), decrypt=True).decode()
            if not value:
                raise ValueError
        except (AttributeError, ValueError, OSError):
            raise UserInputError("key-decryption", f"无法解密 {label} API Key，请在云端模型页重新输入。", provider) from None
    elif path:
        value = read_file(provider, path)
    else:
        value = os.getenv(variable, "").strip()
        if not value and not provider.startswith("compatible-"):
            raise UserInputError("key-required", f"请在云端模型页配置 {label} API Key。", provider)
    if value and provider.startswith("compatible-"):
        url = urlsplit(endpoint or "")
        local = url.hostname == "localhost"
        if url.hostname and not local:
            try:
                local = ipaddress.ip_address(url.hostname).is_loopback
            except ValueError:
                pass
        if not url.hostname or url.username is not None or url.password is not None or (
                url.scheme != "https" and not (local and url.scheme == "http")):
            raise UserInputError("key-https", f"{label}的远程地址需要使用 HTTPS 才能发送 API Key。", provider)
    return value or None
