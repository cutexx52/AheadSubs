"""Local Sign in with ChatGPT for subscription-backed text inference."""

import base64
import ctypes
import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid
import webbrowser
from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..paths import user_data_directory
from .errors import ProviderError, provider_error


ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
TOKEN_ENDPOINT = ISSUER + "/api/accounts/oauth/token"
DISCOVERY = ISSUER + "/.well-known/openid-configuration"
JWKS = ISSUER + "/.well-known/jwks.json"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = "openid profile email offline_access resource.invoke " + PLAN_SCOPE
DYNAMIC_CLIENT = "dynamic_agent_client"
CALLBACK = "/auth/callback"


class _Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.c_void_p)]


def _dpapi(data, decrypt=False):
    buffer = ctypes.create_string_buffer(data)
    source, result = _Blob(len(data), ctypes.addressof(buffer)), _Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        free = ctypes.WinDLL("kernel32").LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(result.data)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _RemoteError(Exception):
    def __init__(self, code=None, status_code=None):
        self.code, self.status_code = code, status_code


def _request(url, *, form=None, token=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = urlencode(form).encode("ascii") if form is not None else None
    try:
        with build_opener(_NoRedirect()).open(Request(url, data, headers), timeout=12) as response:
            raw = response.read(2**20)
        return json.loads(raw) if raw else {}
    except HTTPError as exc:
        code = None
        with exc:
            try:
                error = json.loads(exc.read(65536)).get("error")
                code = error.get("code") if isinstance(error, dict) else error
            except (ValueError, AttributeError):
                pass
        raise _RemoteError(code, exc.code) from None
    except URLError as exc:
        kind = "request_timeout" if isinstance(exc.reason, TimeoutError) else "provider_unavailable"
        raise ProviderError(kind) from None
    except TimeoutError:
        raise ProviderError("request_timeout") from None
    except (OSError, ValueError):
        raise ProviderError("provider_unavailable") from None


def _authorize(client_id, host, previous):
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode().rstrip("=")
    result = None

    class Handler(BaseHTTPRequestHandler):
        timeout = 2

        def log_message(self, *args):
            pass

        def do_GET(self):
            nonlocal result
            path, _, search = self.path.partition("?")
            query = parse_qs(search)
            valid = (self.headers.get("Host") == f"127.0.0.1:{server.server_port}"
                     and path == CALLBACK and query.get("state") == [state])
            if valid:
                result = query
            response = (b"Return to AheadSubs to see the sign-in result." if valid
                        else b"Invalid sign-in callback.")
            self.send_response(200 if valid else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(response)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            try:
                self.wfile.write(response)
            except OSError:
                pass

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        server.timeout = 0.5
        redirect = f"http://127.0.0.1:{server.server_port}{CALLBACK}"
        params = {
            "client_id": client_id, "ext_agent_host_id": host, "redirect_uri": redirect,
            "response_type": "code", "scope": SCOPES, "resource": RESOURCE,
            "state": state, "nonce": nonce, "code_challenge_method": "S256", "code_challenge": challenge,
        }
        if client_id == DYNAMIC_CLIENT:
            params["agent_name_hint"] = "AheadSubs"
        elif previous.get("id_token"):
            params["id_token_hint"] = previous["id_token"]
        if "scopes" in previous and PLAN_SCOPE not in previous["scopes"]:
            params["prompt"] = "consent"
        if not webbrowser.open(ISSUER + "/api/accounts/authorize?" + urlencode(params)):
            raise ValueError("无法打开默认浏览器。")
        deadline = time.monotonic() + 180
        while result is None and time.monotonic() < deadline:
            server.handle_request()
    if result is None:
        raise ValueError("ChatGPT 登录超时，请重试。")
    if result.get("error"):
        raise ValueError("ChatGPT 未完成授权，请重新登录。")
    ids = result.get("client_id", [] if client_id == DYNAMIC_CLIENT else [client_id])
    codes = result.get("code", [])
    if (len(codes) != 1 or len(ids) != 1 or not ids[0].startswith("oaiapp_")
            or (client_id != DYNAMIC_CLIENT and ids[0] != client_id)):
        raise ValueError("ChatGPT 登录回调无效，请重试。")
    return ids[0], {"grant_type": "authorization_code", "client_id": ids[0], "code": codes[0],
                    "code_verifier": verifier, "redirect_uri": redirect, "resource": RESOURCE}, nonce


def _identity(data, client_id, nonce):
    import jwt

    try:
        token = data["id_token"]
        keys = jwt.PyJWKSet.from_dict(_request(JWKS))
        kid = jwt.get_unverified_header(token)["kid"]
        key = next(key for key in keys.keys if key.key_id == kid and key.key_type == "RSA")
        claims = jwt.decode(token, key.key, algorithms=["RS256"], issuer=ISSUER, audience=client_id,
                            options={"require": ["exp", "iss", "sub", "aud", "nonce"]})
        if (claims["nonce"] != nonce or not claims["sub"]
                or (isinstance(claims["aud"], list) and len(claims["aud"]) > 1 and claims.get("azp") != client_id)
                or ("azp" in claims and claims["azp"] != client_id)):
            raise ValueError
    except (jwt.PyJWTError, ValueError, TypeError, KeyError, StopIteration):
        raise ValueError("无法验证 ChatGPT 账号，请重新登录。") from None
    email = claims.get("email")
    return {"subject": claims["sub"], "email": email if isinstance(email, str) else ""}


def _token_record(data, previous=None):
    try:
        if data.get("token_type", "").lower() != "bearer":
            raise ValueError
        scope = data["scope"].split() if "scope" in data else (previous or {}).get("scopes", [])
        expires = int(data["expires_in"])
        access = data["access_token"]
        refresh = data.get("refresh_token", (previous or {}).get("refresh_token"))
        if expires <= 0 or not isinstance(access, str) or not access:
            raise ValueError
        if PLAN_SCOPE in scope and (not isinstance(refresh, str) or not refresh):
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError("ChatGPT 返回了无效的登录状态，请重新登录。") from None
    if PLAN_SCOPE not in scope:
        return {"scopes": scope}
    return {"access_token": access, "refresh_token": refresh, "expires_at": time.time() + expires,
            "scopes": scope, "id_token": data.get("id_token", (previous or {}).get("id_token"))}


def _without_tokens(profile):
    return {key: profile[key] for key in ("subject", "email") if key in profile}


class ChatGPTAccounts:
    def __init__(self, directory=None):
        if directory is None:
            if os.name != "nt":
                raise ValueError("ChatGPT 登录目前支持 Windows。")
            directory = user_data_directory()
        self.path = directory / "chatgpt.sqlite3"

    @contextmanager
    def _store(self, write=False):
        if not write and not self.path.exists():
            yield {"profiles": {}}
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=60)) as db, db:
            if write:
                db.execute("BEGIN IMMEDIATE")
                db.execute("CREATE TABLE IF NOT EXISTS credentials (id INTEGER PRIMARY KEY, state BLOB)")
            initialized = write or db.execute(
                "SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = 'credentials'"
            ).fetchone()
            row = db.execute("SELECT state FROM credentials WHERE id = 1").fetchone() if initialized else None
            state = json.loads(_dpapi(row[0], decrypt=True)) if row else {"profiles": {}}
            yield state
            if write:
                db.execute("INSERT OR REPLACE INTO credentials VALUES (1, ?)",
                           (_dpapi(json.dumps(state).encode("utf-8")),))

    def status(self):
        with self._store() as state:
            return [
                {"id": key, "email": profile.get("email") or "ChatGPT", "connected": bool(profile.get("refresh_token")),
                 "models": profile.get("models", [])}
                for key, profile in state["profiles"].items() if profile.get("subject")
            ]

    def sign_in(self, account=None):
        try:
            from jwt.algorithms import get_default_algorithms
        except ImportError:
            raise ValueError("请安装云端依赖（pip install .[cloud]）后再登录 ChatGPT。") from None

        if "RS256" not in get_default_algorithms():
            raise ValueError("请安装支持 RS256 的 PyJWT（PyJWT[crypto]）。")
        with self._store(write=True) as state:
            if "host" not in state:
                state["host"] = uuid.uuid4().urn
            host = state["host"]
            client_id = account or state.get("pending_client", DYNAMIC_CLIENT)
            previous = state["profiles"].get(client_id, {})
            if account and not previous:
                raise ValueError("找不到此 ChatGPT 账号。")
        issued, form, nonce = _authorize(client_id, host, previous)
        if client_id == DYNAMIC_CLIENT:
            with self._store(write=True) as state:
                state["pending_client"] = issued
        try:
            data = _request(TOKEN_ENDPOINT, form=form)
            identity = _identity(data, issued, nonce)
        except _RemoteError as exc:
            raise provider_error(exc) from None
        if previous.get("subject", identity["subject"]) != identity["subject"]:
            raise ValueError("返回的 ChatGPT 账号与所选账号不同。")
        record = _token_record(data)
        with self._store(write=True) as state:
            state["profiles"][issued] = {**identity, **record, "models": previous.get("models", [])}
            if state.get("pending_client") == issued:
                state.pop("pending_client")
        return issued

    def access_token(self, account):
        with self._store() as state:
            profile = state["profiles"].get(account, {})
        if not profile.get("refresh_token"):
            raise ProviderError("chatgpt_sign_in_required")
        if profile["expires_at"] > time.time() + 60:
            return profile["access_token"]
        with self._store(write=True) as state:
            profile = state["profiles"].get(account, {})
            if not profile.get("refresh_token"):
                raise ProviderError("chatgpt_sign_in_required")
            if profile["expires_at"] > time.time() + 60:
                return profile["access_token"]
            try:
                data = _request(TOKEN_ENDPOINT, form={"grant_type": "refresh_token", "client_id": account,
                                "refresh_token": profile["refresh_token"], "resource": RESOURCE})
                tokens = _token_record(data, profile)
            except _RemoteError as exc:
                if exc.code not in {"invalid_grant", "invalid_client", "invalid_token", "invalid_refresh_token",
                                    "token_expired", "refresh_token_expired", "refresh_token_invalidated",
                                    "refresh_token_reused"}:
                    raise provider_error(exc) from None
                tokens = {}
            # Retain the previously verified ID token for reauthorization.
            if tokens.get("access_token"):
                tokens["id_token"] = profile.get("id_token")
            state["profiles"][account] = {**_without_tokens(profile), **tokens, "models": profile.get("models", [])}
        if not tokens.get("access_token"):
            raise ProviderError("chatgpt_sign_in_required")
        return tokens["access_token"]

    def invalidate(self, account, token):
        with self._store(write=True) as state:
            profile = state["profiles"].get(account, {})
            if profile.get("access_token") == token:
                state["profiles"][account] = _without_tokens(profile)

    def models(self, account):
        token = self.access_token(account)
        try:
            data = _request(RESOURCE + "/models", token=token)
        except _RemoteError as exc:
            if exc.status_code == 401:
                self.invalidate(account, token)
                raise ProviderError("chatgpt_sign_in_required") from None
            raise provider_error(exc) from None
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            raise ValueError("ChatGPT 返回了无法读取的模型列表。")
        models = [
            {"id": model["slug"], "name": model["display_name"]}
            for model in data["models"] if isinstance(model, dict) and model.get("visibility") == "list"
            and isinstance(model.get("slug"), str) and isinstance(model.get("display_name"), str)
        ]
        with self._store(write=True) as state:
            profile = state["profiles"].get(account, {})
            if profile.get("access_token") == token:
                profile["models"] = models
        return models

    def sign_out(self, account):
        confirmed = True
        with self._store(write=True) as state:
            profile = state["profiles"].get(account, {})
            if not (token := profile.get("refresh_token")):
                return confirmed
            form = {"token": token, "token_type_hint": "refresh_token", "client_id": account}
            for attempt in range(2):
                try:
                    discovery = _request(DISCOVERY)
                    endpoint = discovery.get("revocation_endpoint") if isinstance(discovery, dict) else None
                    if not isinstance(endpoint, str) or not endpoint.startswith(ISSUER + "/"):
                        confirmed = False
                        break
                    _request(endpoint, form=form)
                    confirmed = True
                    break
                except (_RemoteError, ProviderError):
                    confirmed = False
                    if attempt == 0:
                        time.sleep(0.5)
            state["profiles"][account] = _without_tokens(profile)
        return confirmed
