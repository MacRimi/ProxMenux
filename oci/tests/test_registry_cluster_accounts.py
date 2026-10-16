"""Registry accounts are kept for the whole cluster, offered when a registry
refuses an image, and read by every program that downloads images."""

from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci import custom, registry_accounts, registry_auth
from proxmenux_oci.ui import UserCancelled

CLUSTER_FILE = "/etc/pve/priv/proxmenux/registry-auth.json"
GHCR_PRIVATE = ('time="2026-10-16T18:06:24+02:00" level=fatal msg="Error parsing image name '
                '\\"docker://ghcr.io/macrimi/private-test:latest\\": Requesting bearer token: '
                'invalid status code from registry 403 (Forbidden)"')
HUB_PRIVATE = 'reading manifest latest in docker.io/macrimi/private-test: requested access to the resource is denied'


class FakeUI:
    def __init__(self, answers=(), confirms=(True,)):
        self.answers = list(answers)
        self.confirms = list(confirms)
        self.messages = []

    def ask(self, text, default=None, required=True):
        answer = self.answers.pop(0)
        if answer is UserCancelled:
            raise UserCancelled(text)
        return answer

    def password(self, text, required=True):
        return self.answers.pop(0)

    def confirm(self, text, default=False, title=None):
        return self.confirms.pop(0)

    def info(self, text, title=None):
        pass

    def message(self, text, title=None):
        self.messages.append(text)


class ClusterFile(unittest.TestCase):
    def test_the_cluster_file_is_used_when_the_cluster_filesystem_is_mounted(self):
        environment = {}
        with patch.object(registry_auth.os.path, "ismount", return_value=True):
            registry_auth.use_cluster_auth_file(environment)
        self.assertEqual(environment, {"REGISTRY_AUTH_FILE": CLUSTER_FILE})

    def test_nothing_is_chosen_without_the_cluster_filesystem(self):
        environment = {}
        with patch.object(registry_auth.os.path, "ismount", return_value=False):
            registry_auth.use_cluster_auth_file(environment)
        self.assertEqual(environment, {})

    def test_a_file_chosen_by_the_user_is_kept(self):
        environment = {"REGISTRY_AUTH_FILE": "/root/own.json"}
        with patch.object(registry_auth.os.path, "ismount", return_value=True):
            registry_auth.use_cluster_auth_file(environment)
        self.assertEqual(environment, {"REGISTRY_AUTH_FILE": "/root/own.json"})

    def test_the_accounts_menu_reads_and_writes_the_cluster_file(self):
        with patch.dict(registry_auth.os.environ, {"REGISTRY_AUTH_FILE": CLUSTER_FILE}):
            self.assertEqual(str(registry_auth.RegistryAuth().path), CLUSTER_FILE)


class RefusedAccess(unittest.TestCase):
    def test_a_refusal_is_told_apart_from_other_failures(self):
        for text in (GHCR_PRIVATE, HUB_PRIVATE, "unauthorized: authentication required"):
            self.assertTrue(registry_auth.refuses_access(text), text)
        for text in ("dial tcp: lookup ghcr.io: no such host", "manifest unknown", ""):
            self.assertFalse(registry_auth.refuses_access(text), text)

    def test_the_classifier_still_names_the_refusal(self):
        self.assertIn("Access denied by ghcr.io", registry_auth.registry_error("ghcr.io", GHCR_PRIVATE))


class SignInFromTheImporter(unittest.TestCase):
    def sign_in(self, ui, login=None):
        auth = MagicMock()
        if login:
            auth.login.side_effect = login
        with patch.object(registry_accounts, "require_root"), \
                patch.object(registry_accounts, "RegistryAuth", return_value=auth):
            result = registry_accounts.offer_sign_in(ui, "ghcr.io/macrimi/app:latest", "Title")
        return result, auth

    def test_an_accepted_account_is_saved(self):
        ui = FakeUI(["macrimi", "ghp_secret"])
        result, auth = self.sign_in(ui)
        self.assertTrue(result)
        auth.login.assert_called_once_with("ghcr.io", "macrimi", "ghp_secret")

    def test_a_declined_offer_asks_nothing(self):
        ui = FakeUI([], confirms=[False])
        result, auth = self.sign_in(ui)
        self.assertFalse(result)
        auth.login.assert_not_called()

    def test_a_cancelled_question_returns_without_signing_in(self):
        ui = FakeUI([UserCancelled])
        result, auth = self.sign_in(ui)
        self.assertFalse(result)
        auth.login.assert_not_called()

    def test_a_refused_account_is_explained(self):
        ui = FakeUI(["macrimi", "wrong"])
        refused = registry_auth.RegistryError("Authentication failed for ghcr.io.")
        result, _ = self.sign_in(ui, login=refused)
        self.assertFalse(result)
        self.assertEqual(ui.messages, ["Authentication failed for ghcr.io."])

    def test_a_refused_image_is_checked_again_after_signing_in(self):
        compose = "services:\n  app:\n    image: ghcr.io/macrimi/app:latest\n"
        reports = iter([(False, "Could not inspect the image in its registry"), (True, "The image is in its registry")])
        ui = SimpleNamespace(message=lambda *a, **k: None, review=lambda *a, **k: False)
        with patch.object(custom, "read_definition", return_value=(compose, "pasted Compose file")), \
                patch.object(custom, "registry_report", side_effect=lambda _: next(reports)) as report, \
                patch.object(custom, "_registry_refused", return_value=True), \
                patch.object(registry_accounts, "offer_sign_in", return_value=True) as offer:
            custom.explore(ui)
        offer.assert_called_once()
        self.assertEqual(report.call_count, 2)


class EveryImageReaderUsesTheAccounts(unittest.TestCase):
    def test_every_program_that_runs_skopeo_reads_the_cluster_file(self):
        readers = [path for path in sorted((ROOT / "remote").iterdir())
                   if path.suffix in {".sh", ".py"}
                   and re.search(r"skopeo['\",]*\s+(inspect|copy)|'skopeo',\s*'(inspect|copy)'", path.read_text())]
        self.assertGreaterEqual(len(readers), 7)
        for path in readers:
            with self.subTest(path=path.name):
                self.assertIn(CLUSTER_FILE, path.read_text())
        self.assertIn("_use_cluster_auth_file()", (ROOT / "src/proxmenux_oci/__init__.py").read_text())


if __name__ == "__main__":
    unittest.main()
