"""OIDC protocol/Flask integration tests using real RSA/EC signatures, no external IdP."""

import base64
import hashlib
import json
from pathlib import Path
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from cryptography.hazmat.primitives.asymmetric import rsa, ec
from flask import Flask
import jwt
import pyotp
import requests
import auth_manager
import oidc_manager as oidc
from flask_oidc_routes import oidc_bp


class OIDCTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.ec_key = ec.generate_private_key(ec.SECP256R1())
        cls.password = "LocalRecoveryPassword42!"
        cls.password_hash = auth_manager.hash_password(cls.password)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        patch = mock.patch.multiple(auth_manager, CONFIG_DIR=self.root,
                                    AUTH_CONFIG_FILE=self.root / "auth.json")
        patch.start()
        self.addCleanup(patch.stop)
        self.local = {"enabled": True, "configured": True, "username": "local-admin",
                      "password_hash": self.password_hash, "jwt_secret": "s" * 48,
                      "api_tokens": [], "revoked_tokens": []}
        auth_manager.save_auth_config(self.local)
        auth_manager._invalidate_revoked_cache()
        oidc._flows.clear()
        oidc._exchanges.clear()
        oidc._documents.clear()
        self.config = {"enabled": True, "provider_name": "Test IdP",
                       "issuer": "https://identity.test/application/o/monitor/",
                       "public_url": "https://monitor.test", "client_id": "monitor-client",
                       "client_secret": "private-client-secret", "allowed_subjects": ["subject-1"],
                       "token_auth_method": "client_secret_basic"}
        self.claim_overrides = {}
        self.omit_claims = set()
        self.algorithm = "RS256"
        self.signing_key = self.rsa_key
        self.metadata_overrides = {}
        self.jwks_override = None
        self.token_response = None
        self.nonce = ""
        self.challenge = ""
        network = mock.patch.object(requests, "request", side_effect=self.provider_request)
        self.network = network.start()
        self.addCleanup(network.stop)
        oidc.save_config(self.config)
        self.app = Flask(__name__)
        self.app.register_blueprint(oidc_bp)
        self.client = self.app.test_client()

    def provider_request(self, method, url, **kwargs):
        self.assertEqual(kwargs["timeout"], 10)
        self.assertFalse(kwargs["allow_redirects"])
        if url.endswith("/.well-known/openid-configuration"):
            self.assertEqual(method, "GET")
            document = {
                "issuer": self.config["issuer"],
                "authorization_endpoint": "https://identity.test/authorize",
                "token_endpoint": "https://identity.test/token",
                "jwks_uri": "https://identity.test/jwks",
                "response_types_supported": ["code"],
                "code_challenge_methods_supported": ["S256"],
                "id_token_signing_alg_values_supported": ["RS256", "ES256"],
                "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post", "none"],
                **self.metadata_overrides,
            }
        elif url.endswith("/jwks"):
            self.assertEqual(method, "GET")
            rsa_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self.rsa_key.public_key(), as_dict=True)
            ec_jwk = jwt.algorithms.ECAlgorithm.to_jwk(self.ec_key.public_key(), as_dict=True)
            document = self.jwks_override or {"keys": [
                {**rsa_jwk, "kid": "rsa-key", "alg": "RS256", "use": "sig"},
                {**ec_jwk, "kid": "ec-key", "alg": "ES256", "use": "sig"},
            ]}
        elif url.endswith("/token"):
            self.assertEqual(method, "POST")
            form = kwargs["data"]
            self.assertEqual(form["grant_type"], "authorization_code")
            self.assertEqual(form["code"], "provider-code")
            self.assertEqual(form["redirect_uri"], self.config["public_url"] + "/api/auth/oidc/callback")
            actual = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).decode().rstrip("=")
            self.assertEqual(actual, self.challenge)
            method = self.config["token_auth_method"]
            if method == "client_secret_basic":
                self.assertEqual(kwargs["auth"], (self.config["client_id"], self.config["client_secret"]))
                self.assertNotIn("client_secret", form)
            else:
                self.assertNotIn("auth", kwargs)
                self.assertEqual(form["client_id"], self.config["client_id"])
                if method == "client_secret_post":
                    self.assertEqual(form["client_secret"], self.config["client_secret"])
                else:
                    self.assertNotIn("client_secret", form)
            payload = {"iss": self.config["issuer"], "aud": self.config["client_id"],
                       "sub": "subject-1", "exp": int(time.time()) + 300,
                       "iat": int(time.time()), "nonce": self.nonce, **self.claim_overrides}
            for name in self.omit_claims:
                payload.pop(name, None)
            key = self.signing_key if self.algorithm == "RS256" else self.ec_key
            document = self.token_response or {"id_token": jwt.encode(
                payload, key, algorithm=self.algorithm,
                headers={"kid": "rsa-key" if self.algorithm == "RS256" else "ec-key"})}
        else:
            raise AssertionError("Unexpected outbound request: " + url)
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(document).encode()
        return response

    def begin(self):
        location, binding = oidc.begin_login()
        parameters = parse_qs(urlsplit(location).query)
        self.nonce = parameters["nonce"][0]
        self.challenge = parameters["code_challenge"][0]
        self.assertEqual(parameters["code_challenge_method"], ["S256"])
        self.assertEqual(parameters["response_type"], ["code"])
        return parameters["state"][0], binding

    def finish(self):
        state, binding = self.begin()
        location = oidc.finish_login(state, binding, "provider-code")
        return parse_qs(urlsplit(location).fragment)["oidc_code"][0], binding

    def test_signed_code_flow_creates_a_monitor_session(self):
        for method in ("client_secret_basic", "client_secret_post", "none"):
            with self.subTest(method=method):
                self.config["token_auth_method"] = method
                oidc.save_config(self.config)
                ticket, binding = self.finish()
                token = oidc.exchange(ticket, binding)
                self.assertEqual(auth_manager.verify_token(token), "local-admin")
                self.assertEqual(auth_manager.verify_token_full(token), ("local-admin", "full_admin"))
                with self.assertRaises(oidc.OIDCError):
                    oidc.exchange(ticket, binding)

    def test_ec_provider_signature_is_supported(self):
        self.algorithm = "ES256"
        ticket, binding = self.finish()
        self.assertEqual(auth_manager.verify_token(oidc.exchange(ticket, binding)), "local-admin")

    def test_wrong_signature_is_rejected(self):
        self.signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with self.assertRaises(oidc.OIDCError):
            self.finish()
        self.assertEqual(oidc._exchanges, {})

    def test_unsigned_and_symmetric_provider_tokens_are_rejected(self):
        for algorithm, key in (("none", None), ("HS256", "attacker-secret" * 4)):
            with self.subTest(algorithm=algorithm):
                self.token_response = {"id_token": jwt.encode(
                    {"sub": "subject-1"}, key, algorithm=algorithm, headers={"kid": "rsa-key"})}
                with self.assertRaises(oidc.OIDCError):
                    self.finish()
        self.assertEqual(oidc._exchanges, {})

    def test_callback_without_browser_cookie_cannot_complete_login(self):
        state, _ = self.begin()
        result = self.client.get("/api/auth/oidc/callback", base_url="https://monitor.test",
                                 query_string={"state": state, "code": "provider-code"})
        self.assertEqual(result.status_code, 303)
        self.assertEqual(result.location, "https://monitor.test/#oidc_error=login_failed")
        self.assertEqual(oidc._exchanges, {})

    def test_invalid_claims_are_rejected(self):
        for claims in ({"iss": "https://other.test"}, {"aud": "another-client"},
                       {"sub": "unlisted-subject"}, {"nonce": "wrong-nonce"},
                       {"exp": int(time.time()) - 60}, {"iat": int(time.time()) + 120},
                       {"aud": ["monitor-client", "other"]}, {"azp": "another-client"}):
            with self.subTest(claims=claims):
                self.claim_overrides = claims
                with self.assertRaises(oidc.OIDCError):
                    self.finish()
                self.assertEqual(oidc._exchanges, {})

    def test_missing_required_claims_are_rejected(self):
        for claim in ("iss", "aud", "sub", "nonce", "exp", "iat"):
            with self.subTest(claim=claim):
                self.omit_claims = {claim}
                with self.assertRaises(oidc.OIDCError):
                    self.finish()

    def test_missing_id_token_cannot_be_replaced_by_userinfo(self):
        self.token_response = {"access_token": "not-an-id-token", "sub": "subject-1"}
        with self.assertRaises(oidc.OIDCError):
            self.finish()

    def test_browser_binding_and_state_are_required(self):
        state, binding = self.begin()
        for bad_state, bad_binding in (("unknown-state", binding), (state, "wrong-browser"), (state, "ñ")):
            with self.subTest(state=bad_state, binding=bad_binding):
                with self.assertRaises(oidc.OIDCError):
                    oidc.finish_login(bad_state, bad_binding, "provider-code")
        oidc.finish_login(state, binding, "provider-code")
        with self.assertRaises(oidc.OIDCError):
            oidc.finish_login(state, binding, "provider-code")

    def test_expired_flow_and_exchange_are_rejected(self):
        state, binding = self.begin()
        oidc._flows[state]["expires"] = 0
        with self.assertRaises(oidc.OIDCError):
            oidc.finish_login(state, binding, "provider-code")
        ticket, binding = self.finish()
        with self.assertRaises(oidc.OIDCError):
            oidc.exchange(ticket, "wrong-browser")
        oidc._exchanges[ticket]["expires"] = 0
        with self.assertRaises(oidc.OIDCError):
            oidc.exchange(ticket, binding)

    def test_configuration_change_revokes_oidc_but_preserves_local_login(self):
        ticket, binding = self.finish()
        oidc_token = oidc.exchange(ticket, binding)
        local_token = auth_manager.generate_token("local-admin")
        oidc.save_config({**self.config, "allowed_subjects": ["different-subject"]})
        self.assertIsNone(auth_manager.verify_token(oidc_token))
        self.assertEqual(auth_manager.verify_token_full(oidc_token), (None, None))
        self.assertEqual(auth_manager.verify_token(local_token), "local-admin")
        oidc.save_config({"enabled": False})
        success, _, requires_totp, _ = auth_manager.authenticate("local-admin", self.password)
        self.assertTrue(success)
        self.assertFalse(requires_totp)

    def test_existing_password_totp_still_applies_to_local_login(self):
        secret = pyotp.random_base32()
        auth_manager.save_auth_config({**self.local, "totp_enabled": True, "totp_secret": secret})
        success, _, requires_totp, _ = auth_manager.authenticate("local-admin", self.password)
        self.assertFalse(success)
        self.assertTrue(requires_totp)
        success, _, _, _ = auth_manager.authenticate("local-admin", self.password, pyotp.TOTP(secret).now())
        self.assertTrue(success)

    def test_config_validates_discovery_and_protects_secrets(self):
        self.assertEqual(stat.S_IMODE((self.root / "oidc.json").stat().st_mode), 0o600)
        self.assertNotIn("client_secret", oidc.public_config())
        self.assertTrue(oidc.public_config()["has_client_secret"])
        original = (self.root / "oidc.json").read_bytes()
        for changes in ({"issuer": "http://identity.test"}, {"allowed_subjects": []},
                        {"public_url": "https://user:pass@monitor.test"}, {"issuer": None}):
            with self.subTest(changes=changes), self.assertRaises(oidc.OIDCError):
                oidc.save_config({**self.config, **changes})
            self.assertEqual((self.root / "oidc.json").read_bytes(), original)
        self.metadata_overrides = {"issuer": "https://different.test"}
        with self.assertRaises(oidc.OIDCError):
            oidc.save_config(self.config)

    def test_provider_errors_do_not_reveal_credentials(self):
        with mock.patch.object(requests, "request", side_effect=requests.Timeout("private-client-secret")):
            with self.assertRaises(oidc.OIDCError) as caught:
                oidc.save_config(self.config)
        self.assertNotIn("private-client-secret", str(caught.exception))

    def test_flask_browser_redirect_and_single_use_exchange(self):
        start = self.client.get("/api/auth/oidc/start", base_url="https://monitor.test")
        self.assertEqual(start.status_code, 302)
        cookie = start.headers["Set-Cookie"]
        for attribute in ("Secure", "HttpOnly", "SameSite=Lax"):
            self.assertIn(attribute, cookie)
        parameters = parse_qs(urlsplit(start.location).query)
        self.nonce = parameters["nonce"][0]
        self.challenge = parameters["code_challenge"][0]
        callback = self.client.get("/api/auth/oidc/callback", base_url="https://monitor.test",
                                   query_string={"state": parameters["state"][0], "code": "provider-code"})
        self.assertEqual(callback.status_code, 303)
        self.assertTrue(callback.location.startswith("https://monitor.test/#oidc_code="))
        self.assertNotIn("eyJ", callback.location)
        ticket = parse_qs(urlsplit(callback.location).fragment)["oidc_code"][0]
        exchange = self.client.post("/api/auth/oidc/exchange", base_url="https://monitor.test", json={"code": ticket})
        self.assertEqual(exchange.status_code, 200)
        self.assertEqual(exchange.headers["Cache-Control"], "no-store")
        self.assertEqual(auth_manager.verify_token(exchange.json["token"]), "local-admin")
        self.assertEqual(self.client.post("/api/auth/oidc/exchange", base_url="https://monitor.test",
                                          json={"code": ticket}).status_code, 401)

    def test_config_api_requires_admin_and_never_returns_secret(self):
        self.assertEqual(self.client.get("/api/auth/oidc/config").status_code, 401)
        local_token = auth_manager.generate_token("local-admin")
        headers = {"Authorization": "Bearer " + local_token}
        response = self.client.get("/api/auth/oidc/config", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("private-client-secret", response.text)
        payload = jwt.decode(local_token, "s" * 48, algorithms=["HS256"], audience=auth_manager.JWT_AUDIENCE)
        payload["scope"] = "read_only"
        read_only = jwt.encode(payload, "s" * 48, algorithm="HS256")
        response = self.client.put("/api/auth/oidc/config", headers={"Authorization": "Bearer " + read_only}, json={"enabled": False})
        self.assertEqual(response.status_code, 403)
        public = self.client.get("/api/auth/oidc/status").json
        self.assertEqual(set(public), {"enabled", "provider_name", "login_url"})
        auth_manager.save_auth_config({**self.local, "enabled": False})
        self.assertFalse(self.client.get("/api/auth/oidc/status").json["enabled"])
        self.assertEqual(self.client.put("/api/auth/oidc/config", json={"enabled": True}).status_code, 409)


if __name__ == "__main__":
    unittest.main()
