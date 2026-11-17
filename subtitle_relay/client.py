"""Loopback client shared by desktop controls and player adapters."""
import json
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener


class RelayClient:
    def __init__(self, port):
        self.url = f"http://127.0.0.1:{port}/v1/"
        self.opener = build_opener(ProxyHandler({}))

    def send(self, route, data):
        request = Request(self.url + route, data=json.dumps(data).encode(),
                          headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=5) as result:
                return json.load(result)
        except HTTPError as exc:
            try:
                detail = json.load(exc).get("error")
            except (ValueError, AttributeError):
                detail = None
            raise RuntimeError(detail or f"Subtitle Relay HTTP {exc.code}") from exc
