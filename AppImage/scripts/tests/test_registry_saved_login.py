"""The update check of a private image uses the login saved in ProxMenux:
it is sent to the token service the registry names, or to the registry
itself when it asks for Basic authentication, and never anywhere else."""

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import lxc_apps

CREDENTIAL = base64.b64encode(b"macrimi:ghp_secret").decode()
MANIFEST = "https://ghcr.io/v2/macrimi/app/manifests/latest"


class SavedLoginTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.auth_file = Path(self.folder.name) / "registry-auth.json"
        self.auth_file.write_text(json.dumps({"auths": {"ghcr.io": {"auth": CREDENTIAL},
                                                        "docker.io": {"auth": CREDENTIAL},
                                                        "registry.example.com:5000": {"auth": CREDENTIAL}}}))
        patcher = mock.patch.object(lxc_apps, "_REGISTRY_AUTH_FILE", str(self.auth_file))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.folder.cleanup)

    def test_the_login_is_found_by_registry_host(self):
        self.assertEqual(lxc_apps._registry_saved_login("ghcr.io"), f"Basic {CREDENTIAL}")
        self.assertEqual(lxc_apps._registry_saved_login("registry-1.docker.io"), f"Basic {CREDENTIAL}")
        self.assertEqual(lxc_apps._registry_saved_login("registry.example.com:5000"), f"Basic {CREDENTIAL}")
        self.assertIsNone(lxc_apps._registry_saved_login("quay.io"))

    def test_without_the_file_nothing_is_sent(self):
        self.auth_file.unlink()
        self.assertIsNone(lxc_apps._registry_saved_login("ghcr.io"))

    def test_a_bearer_challenge_asks_the_token_with_the_saved_login(self):
        challenge = 'Bearer realm="https://ghcr.io/token",service="ghcr.io",scope="repository:macrimi/app:pull"'
        answers = [({"WWW-Authenticate": challenge}, b"", 401, None, None),
                   ({"Docker-Content-Digest": "sha256:abc"}, b"", 200, None, None)]
        sent = []

        def token_service(request, timeout):
            sent.append(dict(request.header_items()))
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = b'{"token": "pull-token"}'
            return response

        with mock.patch.object(lxc_apps, "_registry_open", side_effect=answers) as registry, \
                mock.patch.object(lxc_apps.urllib.request, "urlopen", side_effect=token_service):
            headers, _body, token, error = lxc_apps._registry_request(MANIFEST, {"Accept": "*/*"})
        self.assertIsNone(error)
        self.assertEqual(token, "pull-token")
        self.assertEqual(sent[0]["Authorization"], f"Basic {CREDENTIAL}")
        self.assertEqual(registry.call_args_list[1].args[1]["Authorization"], "Bearer pull-token")

    def test_a_basic_challenge_is_answered_with_the_saved_login(self):
        answers = [({"WWW-Authenticate": 'Basic realm="registry"'}, b"", 401, None, None),
                   ({"Docker-Content-Digest": "sha256:abc"}, b"", 200, None, None)]
        url = "https://registry.example.com:5000/v2/team/app/manifests/latest"
        with mock.patch.object(lxc_apps, "_registry_open", side_effect=answers) as registry:
            _headers, _body, _token, error = lxc_apps._registry_request(url, {"Accept": "*/*"})
        self.assertIsNone(error)
        self.assertEqual(registry.call_args_list[1].args[1]["Authorization"], f"Basic {CREDENTIAL}")

    def test_a_basic_challenge_over_http_gets_no_login(self):
        answers = [({"WWW-Authenticate": 'Basic realm="registry"'}, b"", 401, None, None)]
        url = "http://registry.example.com:5000/v2/team/app/manifests/latest"
        with mock.patch.object(lxc_apps, "_registry_open", side_effect=answers) as registry:
            _headers, _body, _token, error = lxc_apps._registry_request(url, {"Accept": "*/*"})
        self.assertEqual(error, "registry authentication required")
        self.assertEqual(registry.call_count, 1)

    def test_a_public_image_asks_its_token_without_a_login(self):
        challenge = 'Bearer realm="https://auth.example.org/token",service="example",scope="repository:x:pull"'
        answers = [({"WWW-Authenticate": challenge}, b"", 401, None, None),
                   ({"Docker-Content-Digest": "sha256:abc"}, b"", 200, None, None)]
        sent = []

        def token_service(request, timeout):
            sent.append(dict(request.header_items()))
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = b'{"token": "t"}'
            return response

        with mock.patch.object(lxc_apps, "_registry_open", side_effect=answers), \
                mock.patch.object(lxc_apps.urllib.request, "urlopen", side_effect=token_service):
            lxc_apps._registry_request("https://quay.io/v2/x/manifests/latest", {})
        self.assertNotIn("Authorization", sent[0])


if __name__ == "__main__":
    unittest.main()
