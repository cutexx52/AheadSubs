import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

from aheadsubs.inference import chatgpt_auth as auth
from aheadsubs.inference.chatgpt import completed_text
from aheadsubs.inference.errors import ProviderError


class ChatGPTTest(unittest.TestCase):
    @unittest.skipUnless(find_spec("jwt") and find_spec("cryptography"), "Cloud dependencies")
    def test_validates_id_token_signature_and_nonce(self):
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        account = "oaiapp_test"
        claims = {"iss": auth.ISSUER, "aud": account, "nonce": "nonce", "exp": time.time() + 60,
                  "sub": "user", "email": "example@example.com"}
        token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
        with patch.object(auth, "_request", return_value={"keys": [{**jwk, "kid": "test"}]}):
            self.assertEqual(auth._identity({"id_token": token}, account, "nonce")["subject"], "user")
            for client, nonce in [("other_client", "nonce"), (account, "wrong_nonce")]:
                with self.assertRaises(ValueError):
                    auth._identity({"id_token": token}, client, nonce)

    def test_callback_ignores_wrong_state_and_returns_pkce_exchange(self):
        def callback(url):
            params = parse_qs(urlsplit(url).query)
            redirect = params["redirect_uri"][0]
            self.assertEqual(urlsplit(redirect).hostname, "127.0.0.1")
            self.assertIn(auth.PLAN_SCOPE, params["scope"][0].split())

            def send():
                with self.assertRaises(HTTPError) as invalid:
                    urlopen(redirect + "?state=incorrect&code=wrong", timeout=5)
                self.assertEqual(invalid.exception.code, 400)
                data = {"state": params["state"][0], "code": "code", "client_id": "oaiapp_test"}
                with urlopen(redirect + "?" + urlencode(data), timeout=5) as response:
                    self.assertEqual(response.status, 200)

            pending.append(executor.submit(send))
            return True

        pending = []
        with ThreadPoolExecutor(1) as executor, patch.object(auth.webbrowser, "open", callback):
            issued, form, nonce = auth._authorize(auth.DYNAMIC_CLIENT, "urn:uuid:test", {})
            pending[0].result()
        self.assertEqual(issued, "oaiapp_test")
        self.assertEqual(form["code"], "code")
        self.assertTrue(form["code_verifier"])
        self.assertTrue(nonce)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_refresh_rotates_once_and_logout_preserves_registration(self):
        account = "oaiapp_test"
        with TemporaryDirectory() as directory:
            accounts = auth.ChatGPTAccounts(Path(directory))
            with accounts._store(write=True) as state:
                state["profiles"][account] = {
                    "subject": "user", "email": "example@example.com",
                    "expires_at": time.time() - 5, "scopes": [auth.PLAN_SCOPE],
                    "access_token": "expired-token", "refresh_token": "initial-refresh-token",
                }
            self.assertNotIn(b"initial-refresh-token", accounts.path.read_bytes())
            with patch.object(auth, "_request", return_value={
                "token_type": "Bearer", "access_token": "renewed", "refresh_token": "new-refresh", "expires_in": 3600,
            }) as request, ThreadPoolExecutor(4) as pool:
                self.assertEqual(list(pool.map(accounts.access_token, [account] * 8)), ["renewed"] * 8)
                request.assert_called_once()
            self.assertEqual(accounts.status(), [
                {"id": account, "email": "example@example.com", "connected": True, "models": []},
            ])
            with patch.object(auth, "_request", side_effect=[{"revocation_endpoint": auth.ISSUER + "/revoke"}, {}]) as request:
                self.assertTrue(accounts.sign_out(account))
                self.assertEqual(request.call_args.kwargs["form"]["token"], "new-refresh")
            self.assertFalse(accounts.status()[0]["connected"])
            with self.assertRaises(ProviderError):
                accounts.access_token(account)

    def test_only_completed_streams_produce_translations(self):
        delta = SimpleNamespace(type="response.output_text.delta", delta='{"0":"Hi"}')
        done = SimpleNamespace(type="response.completed")
        self.assertEqual(completed_text([delta, done]), '{"0":"Hi"}')
        rejected = SimpleNamespace(type="response.failed", response=SimpleNamespace(
            error=SimpleNamespace(code="subscription_sharing_usage_limit_exceeded")))
        for stream, expected in [([delta], "translation_failed"), ([delta, rejected], "rate_limited")]:
            with self.assertRaises(ProviderError) as failure:
                completed_text(stream)
            self.assertEqual(failure.exception.kind, expected)
