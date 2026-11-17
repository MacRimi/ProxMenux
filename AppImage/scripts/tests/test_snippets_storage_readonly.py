"""Reading the snippets storage never changes the storage configuration of
Proxmox, and it is reserved to administrators."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from flask import Flask

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import auth_manager  # noqa: E402
from test_access_modes import PASSWORD  # noqa: E402

STATUS_EMPTY = "Name Type Status Total Used Available %\n"


class SnippetsStorageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        patch = mock.patch.multiple(auth_manager, CONFIG_DIR=self.root, AUTH_CONFIG_FILE=self.root / "auth.json",
                                    SETUP_CODE_FILE=self.root / "monitor-setup-code")
        patch.start()
        self.addCleanup(patch.stop)
        auth_manager._invalidate_revoked_cache()
        spec = importlib.util.spec_from_file_location("snippets_routes", SCRIPTS / "flask_proxmenux_routes.py")
        self.routes = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.routes)
        app = Flask(__name__)
        app.register_blueprint(self.routes.proxmenux_bp)
        self.client = app.test_client()
        self.assertTrue(auth_manager.setup_auth("admin", PASSWORD)[0])
        self.token = auth_manager.generate_token("admin")
        self.commands = []

        def run(args, **kwargs):
            self.commands.append(list(args))
            return subprocess.CompletedProcess(args, 0, stdout=STATUS_EMPTY, stderr="")
        patch = mock.patch.object(subprocess, "run", side_effect=run)
        patch.start()
        self.addCleanup(patch.stop)

    def get(self, token=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.get("/api/proxmenux/snippets-storage", headers=headers)

    def test_without_a_session_nothing_is_read_or_changed(self):
        self.assertEqual(self.get().status_code, 401)
        self.assertEqual(self.commands, [])

    def test_a_host_without_snippets_storage_lists_none_and_changes_nothing(self):
        answer = self.get(self.token)
        self.assertEqual(answer.status_code, 200, answer.json)
        self.assertEqual(answer.json["candidates"], [])
        self.assertTrue(self.commands)
        self.assertFalse([c for c in self.commands if c[:2] == ["pvesm", "set"]], self.commands)


if __name__ == "__main__":
    unittest.main()
