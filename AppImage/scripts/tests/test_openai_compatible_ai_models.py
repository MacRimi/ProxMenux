import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import ai_providers
import notification_manager
from ai_providers.openai_provider import OpenAIProvider


class CapturingOpenAIProvider(OpenAIProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.captured_payload = None

    def _make_request(self, url, payload, headers):
        self.captured_payload = payload
        return {"choices": [{"message": {"content": "ok"}}]}


class FakeProvider:
    last_kwargs = None
    models = []

    def __init__(self, **kwargs):
        FakeProvider.last_kwargs = kwargs

    def list_models(self):
        return list(FakeProvider.models)


class OpenAICompatibleModelTests(unittest.TestCase):
    def setUp(self):
        FakeProvider.last_kwargs = None
        FakeProvider.models = []
        self.provider_patch = mock.patch.dict(
            ai_providers.PROVIDERS,
            {"openai": FakeProvider},
        )
        self.provider_patch.start()
        self.addCleanup(self.provider_patch.stop)

    def _manager(self, config):
        manager = notification_manager.NotificationManager()
        manager._config = dict(config)
        manager._enabled = manager._config.get("enabled", "false") == "true"
        return manager

    def _temp_db_patch(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db_path = Path(temp_dir.name) / "health_monitor.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE user_settings (setting_key TEXT PRIMARY KEY, "
            "setting_value TEXT, updated_at TEXT)"
        )
        conn.commit()
        conn.close()
        patcher = mock.patch.object(notification_manager, "DB_PATH", db_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        return db_path

    def test_custom_openai_endpoint_omits_temperature_for_opaque_alias(self):
        provider = CapturingOpenAIProvider(
            api_key="token",
            model="opaque-gpt5-alias",
            base_url="https://litellm.example",
        )

        self.assertEqual(provider.generate("system", "user", max_tokens=123), "ok")

        self.assertEqual(provider.captured_payload["model"], "opaque-gpt5-alias")
        self.assertEqual(provider.captured_payload["max_tokens"], 123)
        self.assertNotIn("temperature", provider.captured_payload)
        self.assertNotIn("reasoning_effort", provider.captured_payload)
        self.assertNotIn("max_completion_tokens", provider.captured_payload)

    def test_official_openai_reasoning_model_still_uses_reasoning_contract(self):
        provider = CapturingOpenAIProvider(
            api_key="token",
            model="gpt-5-mini",
        )

        self.assertEqual(provider.generate("system", "user", max_tokens=123), "ok")

        self.assertEqual(provider.captured_payload["model"], "gpt-5-mini")
        self.assertEqual(provider.captured_payload["max_completion_tokens"], 123)
        self.assertEqual(provider.captured_payload["reasoning_effort"], "minimal")
        self.assertNotIn("temperature", provider.captured_payload)
        self.assertNotIn("max_tokens", provider.captured_payload)

    def test_runtime_ai_config_prefers_provider_specific_model(self):
        manager = self._manager({
            "ai_enabled": "true",
            "ai_provider": "openai",
            "ai_api_key_openai": "token",
            "ai_model": "gpt-4.1-nano",
            "ai_model_openai": "proxy-alias",
            "ai_openai_base_url": "https://litellm.example",
        })

        ai_config = manager._build_ai_config()

        self.assertEqual(ai_config["ai_model"], "proxy-alias")
        self.assertEqual(ai_config["ai_openai_base_url"], "https://litellm.example")

    def test_model_verifier_uses_custom_endpoint_alias_without_migration(self):
        manager = self._manager({
            "ai_enabled": "true",
            "ai_provider": "openai",
            "ai_api_key_openai": "token",
            "ai_model": "gpt-4.1-nano",
            "ai_model_openai": "proxy-alias",
            "ai_openai_base_url": "https://litellm.example",
        })
        FakeProvider.models = ["proxy-alias"]

        result = manager.verify_and_update_ai_model()

        self.assertTrue(result["checked"])
        self.assertFalse(result["migrated"])
        self.assertEqual(result["new_model"], "proxy-alias")
        self.assertEqual(FakeProvider.last_kwargs["model"], "proxy-alias")
        self.assertEqual(FakeProvider.last_kwargs["base_url"], "https://litellm.example")

    def test_custom_endpoint_does_not_fallback_to_official_model_catalogue(self):
        manager = self._manager({
            "ai_enabled": "true",
            "ai_provider": "openai",
            "ai_api_key_openai": "token",
            "ai_model": "gpt-4.1-nano",
            "ai_model_openai": "proxy-alias",
            "ai_openai_base_url": "https://litellm.example",
        })
        FakeProvider.models = []

        result = manager.verify_and_update_ai_model()

        self.assertTrue(result["checked"])
        self.assertFalse(result["migrated"])
        self.assertEqual(result["new_model"], "proxy-alias")
        self.assertEqual(result["message"], "Could not retrieve custom endpoint model list")

    def test_model_migration_updates_legacy_and_provider_specific_keys(self):
        db_path = self._temp_db_patch()
        manager = self._manager({
            "ai_enabled": "true",
            "ai_provider": "openai",
            "ai_api_key_openai": "token",
            "ai_model": "old-generic",
            "ai_model_openai": "old-alias",
            "ai_openai_base_url": "https://litellm.example",
        })
        FakeProvider.models = ["new-alias"]

        result = manager.verify_and_update_ai_model()

        self.assertTrue(result["checked"])
        self.assertTrue(result["migrated"])
        self.assertEqual(result["old_model"], "old-alias")
        self.assertEqual(result["new_model"], "new-alias")
        self.assertEqual(manager._config["ai_model"], "new-alias")
        self.assertEqual(manager._config["ai_model_openai"], "new-alias")

        conn = sqlite3.connect(str(db_path))
        rows = dict(conn.execute(
            "SELECT setting_key, setting_value FROM user_settings"
        ).fetchall())
        conn.close()

        self.assertEqual(rows["notification.ai_model"], "new-alias")
        self.assertEqual(rows["notification.ai_model_openai"], "new-alias")


if __name__ == "__main__":
    unittest.main()
