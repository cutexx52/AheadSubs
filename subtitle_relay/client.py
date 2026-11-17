"""Loopback client shared by desktop controls and player adapters."""
import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener


class RelayHTTPError(RuntimeError):
    def __init__(self, status, message, error_code):
        super().__init__(message)
        self.status = status
        self.error_code = error_code


class RelayClient:
    def __init__(self, port):
        self.url = f"http://127.0.0.1:{port}/v1/"
        self.opener = build_opener(ProxyHandler({}))

    def health(self):
        return self._request(Request(self.url + "health"), timeout=1)

    def translate_text(self, text, source, target):
        request = Request(self.url + "text", data=urlencode({"text": text, "source": source, "target": target}).encode(),
                          headers={"Content-Type": "application/x-subtitle-relay"})
        return self._request(request, timeout=120)

    def send(self, route, data, *, timeout=5):
        request = Request(self.url + route, data=json.dumps(data).encode(),
                          headers={"Content-Type": "application/json"})
        return self._request(request, timeout=timeout)

    def _request(self, request, *, timeout):
        try:
            with self.opener.open(request, timeout=timeout) as result:
                return json.load(result)
        except HTTPError as exc:
            try:
                detail = json.load(exc)
            except ValueError:
                detail = None
            finally:
                exc.close()
            detail = detail if isinstance(detail, dict) else {}
            raise RelayHTTPError(exc.code, detail.get("error") or f"Subtitle Relay HTTP {exc.code}",
                                 detail.get("error_code")) from exc
