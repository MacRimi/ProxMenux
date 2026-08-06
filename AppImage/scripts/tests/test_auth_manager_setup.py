import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "auth_manager.py"
SPEC = importlib.util.spec_from_file_location("auth_manager_under_test", MODULE_PATH)
auth_manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auth_manager)


class SetupAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        config_dir = Path(self.temp_dir.name)
        self.config_patch = mock.patch.multiple(
            auth_manager,
            CONFIG_DIR=config_dir,
            AUTH_CONFIG_FILE=config_dir / "auth.json",
        )
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.hash_patch = mock.patch.object(
            auth_manager, "hash_password", return_value="test-password-hash"
        )
        self.hash_patch.start()
        self.addCleanup(self.hash_patch.stop)

    def read_config(self):
        return json.loads(auth_manager.AUTH_CONFIG_FILE.read_text())

    def write_config(self, config):
        auth_manager.AUTH_CONFIG_FILE.write_text(json.dumps(config))

    def test_fresh_setup_succeeds(self):
        success, message = auth_manager.setup_auth("admin", "StrongPass1!")

        self.assertTrue(success, message)
        config = self.read_config()
        self.assertTrue(config["enabled"])
        self.assertTrue(config["configured"])
        self.assertFalse(config["declined"])
        self.assertEqual(config["username"], "admin")
        self.assertEqual(config["password_hash"], "test-password-hash")

    def test_setup_succeeds_after_decline(self):
        success, message = auth_manager.decline_auth()
        self.assertTrue(success, message)

        success, message = auth_manager.setup_auth("admin", "StrongPass1!")

        self.assertTrue(success, message)
        config = self.read_config()
        self.assertTrue(config["enabled"])
        self.assertFalse(config["declined"])
        self.assertEqual(config["username"], "admin")
        self.assertEqual(config["password_hash"], "test-password-hash")

    def test_existing_credentials_cannot_be_overwritten(self):
        self.write_config({
            "enabled": True,
            "configured": True,
            "declined": False,
            "username": "existing-admin",
            "password_hash": "existing-password-hash",
        })

        success, message = auth_manager.setup_auth("attacker", "StrongPass1!")

        self.assertFalse(success)
        self.assertEqual(message, "Authentication is already configured")
        config = self.read_config()
        self.assertEqual(config["username"], "existing-admin")
        self.assertEqual(config["password_hash"], "existing-password-hash")

    def test_weak_password_is_rejected_without_writing_config(self):
        success, message = auth_manager.setup_auth("admin", "weak")

        self.assertFalse(success)
        self.assertEqual(message, "Password must be at least 10 characters")
        self.assertFalse(auth_manager.AUTH_CONFIG_FILE.exists())

    def test_unrelated_fields_are_preserved(self):
        preserved = {
            "jwt_secret": "s" * 48,
            "api_tokens": [{"id": "token-1"}],
            "revoked_tokens": ["revoked-token-hash"],
            "display_name": "Server Owner",
            "custom_future_field": {"keep": True},
        }
        self.write_config({
            "enabled": False,
            "configured": True,
            "declined": True,
            "username": None,
            "password_hash": None,
            **preserved,
        })

        success, message = auth_manager.setup_auth("admin", "StrongPass1!")

        self.assertTrue(success, message)
        config = self.read_config()
        for key, value in preserved.items():
            self.assertEqual(config[key], value)


if __name__ == "__main__":
    unittest.main()
