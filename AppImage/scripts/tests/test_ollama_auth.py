"""Optional Ollama gateway authentication, with no real keys or network calls."""

import ast
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import urllib.error


SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from ai_providers.ollama_provider import OllamaProvider, ollama_headers
from ai_providers.base import AIProviderError
import notification_manager as manager_module

TOKEN = "test-only-ollama-token"
MODEL = "test-model:latest"


def routes(manager, payload):
    """Use the actual handlers without importing Flask or starting a server."""
    source = SCRIPTS / "flask_notification_routes.py"
    names = {"_resolve_masked_api_key", "get_provider_models",
             "test_ai_connection", "reveal_notification_secret"}
    functions = []
    for node in ast.parse(source.read_text()).body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            node.decorator_list = []
            functions.append(node)
    scope = {
        "__file__": str(source), "json": json,
        "request": SimpleNamespace(get_json=lambda **kwargs: payload),
        "jsonify": lambda value: value,
        "notification_manager": manager,
        "SENSITIVE_PLACEHOLDER": manager_module.SENSITIVE_PLACEHOLDER,
        "validate_external_url": manager_module.validate_external_url,
        "load_verified_models": lambda: {},
    }
    module = ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))
    exec(compile(module, str(source), "exec"), scope)
    return scope


class OllamaAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.required_token = TOKEN
        patcher = mock.patch("urllib.request.urlopen", side_effect=self.respond)
        patcher.start()
        self.addCleanup(patcher.stop)

    def respond(self, request, timeout=None):
        self.requests.append(request)
        if self.required_token and request.get_header("Authorization") != "Bearer " + self.required_token:
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {},
                                         io.BytesIO(b"sensitive response body"))
        if request.full_url.endswith("/api/tags"):
            data = {"models": [{"name": MODEL}]}
        elif request.full_url.endswith("/api/chat"):
            data = {"message": {"content": "CONNECTION_OK"}}
        else:
            raise AssertionError("Unexpected endpoint: " + request.full_url)
        return io.BytesIO(json.dumps(data).encode())

    def test_key_is_optional_and_no_authorization_header_is_sent_when_empty(self):
        self.required_token = ""
        for key in ("", "   "):
            provider = OllamaProvider(api_key=key, model=MODEL)
            self.assertTrue(provider.test_connection()["success"])
        self.assertTrue(self.requests)
        self.assertTrue(all(r.get_header("Authorization") is None for r in self.requests))
        self.assertFalse(OllamaProvider.REQUIRES_API_KEY)

    def test_connection_authenticates_both_model_lookup_and_generation(self):
        result = OllamaProvider(api_key=TOKEN, model=MODEL).test_connection()
        self.assertTrue(result["success"], result)
        self.assertEqual([r.get_method() for r in self.requests], ["GET", "POST"])
        self.assertTrue(all(r.get_header("Authorization") == "Bearer " + TOKEN for r in self.requests))

    def test_authentication_failure_is_not_reported_as_an_unreachable_server(self):
        result = OllamaProvider(api_key="wrong-test-token", model=MODEL).test_connection()
        self.assertFalse(result["success"])
        self.assertIn("HTTP 401", result["message"])
        self.assertNotIn("Cannot connect", result["message"])
        self.assertNotIn("wrong-test-token", json.dumps(result))
        self.assertNotIn("sensitive response", json.dumps(result))

    def test_invalid_header_values_are_rejected_without_echoing_them(self):
        for value in ("test-secret\r\nInjected: header", "x" * 513, None):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaisesRegex(AIProviderError, "^Invalid Ollama API key$"):
                    ollama_headers(value)
        self.assertEqual(self.requests, [])

    def test_model_loading_uses_the_saved_key_when_the_browser_sends_a_mask(self):
        manager = SimpleNamespace(_config={"ai_api_key_ollama": TOKEN})
        handlers = routes(manager, {"provider": "ollama", "api_key": manager_module.SENSITIVE_PLACEHOLDER,
                                    "ollama_url": "http://localhost:11434"})
        result = handlers["get_provider_models"]()
        self.assertTrue(result["success"], result)
        self.assertEqual(result["models"], [MODEL])
        self.assertEqual(self.requests[0].get_header("Authorization"), "Bearer " + TOKEN)
        self.assertNotIn(TOKEN, json.dumps(result))

    def test_model_loading_without_a_key_still_works_for_native_ollama(self):
        self.required_token = ""
        handlers = routes(SimpleNamespace(_config={}), {
            "provider": "ollama", "ollama_url": "http://localhost:11434"})
        result = handlers["get_provider_models"]()
        self.assertTrue(result["success"], result)
        self.assertIsNone(self.requests[0].get_header("Authorization"))

    def test_test_ai_route_reuses_the_saved_key(self):
        handlers = routes(SimpleNamespace(_config={"ai_api_key_ollama": TOKEN}), {
            "provider": "ollama", "model": MODEL,
            "api_key": manager_module.SENSITIVE_PLACEHOLDER,
            "ollama_url": "http://localhost:11434"})
        result = handlers["test_ai_connection"]()
        self.assertTrue(result["success"], result)
        self.assertTrue(all(r.get_header("Authorization") == "Bearer " + TOKEN for r in self.requests))

    def test_reveal_endpoint_recognizes_the_ollama_secret(self):
        handlers = routes(SimpleNamespace(_config={"ai_api_key_ollama": TOKEN}), {"ai_provider": "ollama"})
        self.assertEqual(handlers["reveal_notification_secret"](), ({"value": TOKEN}, 200))

    def test_real_notification_provider_receives_the_ollama_key(self):
        manager = manager_module.NotificationManager()
        manager._config = {"ai_enabled": "true", "ai_provider": "ollama",
                           "ai_api_key_ollama": TOKEN, "ai_model_ollama": MODEL,
                           "ai_ollama_url": "http://localhost:11434"}
        from notification_templates import AIEnhancer
        rewriter = AIEnhancer(manager._build_ai_config())
        self.assertIsInstance(rewriter._provider, OllamaProvider)
        self.assertEqual(rewriter._provider.generate("system", "user"), "CONNECTION_OK")
        self.assertEqual(self.requests[0].get_header("Authorization"), "Bearer " + TOKEN)


class OllamaKeyStorageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / "settings.db"
        with sqlite3.connect(str(self.db)) as conn:
            conn.execute("CREATE TABLE user_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT, updated_at TEXT)")
        for name, value in (("DB_PATH", self.db), ("ENCRYPTION_KEY_FILE", Path(directory.name) / "key")):
            patcher = mock.patch.object(manager_module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.manager = manager_module.NotificationManager()
        self.manager._rebuild_channels = mock.Mock()

    def stored_value(self):
        with sqlite3.connect(str(self.db)) as conn:
            return conn.execute("SELECT setting_value FROM user_settings WHERE setting_key = ?",
                                ("notification.ai_api_key_ollama",)).fetchone()[0]

    def test_key_is_encrypted_masked_and_loaded_for_runtime_use(self):
        result = self.manager.save_settings({"ai_provider": "ollama", "ai_api_key_ollama": TOKEN})
        self.assertTrue(result["success"], result)
        stored = self.stored_value()
        self.assertTrue(stored.startswith("ENC2:"))
        self.assertNotIn(TOKEN, stored)
        self.assertEqual(manager_module.decrypt_sensitive_value(stored), TOKEN)
        self.assertEqual(self.manager.get_settings()["config"]["ai_api_keys"]["ollama"],
                         manager_module.SENSITIVE_PLACEHOLDER)
        fresh = manager_module.NotificationManager()
        fresh._load_config()
        self.assertEqual(fresh._build_ai_config()["ai_api_key"], TOKEN)

    def test_masked_round_trip_keeps_the_key_and_an_empty_value_removes_it(self):
        self.assertTrue(self.manager.save_settings({"ai_api_key_ollama": TOKEN})["success"])
        stored = self.stored_value()
        self.assertTrue(self.manager.save_settings({"ai_api_key_ollama": manager_module.SENSITIVE_PLACEHOLDER})["success"])
        self.assertEqual(self.stored_value(), stored)
        self.assertTrue(self.manager.save_settings({"ai_api_key_ollama": ""})["success"])
        self.assertEqual(self.stored_value(), "")
        self.assertEqual(self.manager.get_settings()["config"]["ai_api_keys"]["ollama"], "")


if __name__ == "__main__":
    unittest.main()
