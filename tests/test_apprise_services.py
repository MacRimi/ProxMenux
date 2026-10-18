"""Real Apprise Slack/Matrix plugins with the HTTP boundary replaced.

No provider account or network is used. These contracts run against both
the minimum bundled Apprise version and the current tested version.
"""
import gc
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

import apprise
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "AppImage/scripts"))
from notification_channels import create_channel

SLACK = "https://hooks.slack.com/services/T00000000/B00000000/fixturesecret1234567890"
MATRIX = "matrixs://notify:fixture-password@matrix.example.test/!room:matrix.example.test"


class AppriseServiceTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.status = 200
        self.transport = patch.object(requests.Session, "request", side_effect=self.http)
        self.transport.start()
        self.addCleanup(self.transport.stop)
        self.sleep = patch("notification_channels.time.sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)
        self.addCleanup(gc.collect)

    def http(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = requests.Response()
        response.status_code = self.status
        response.url = url
        response.reason = "OK" if self.status == 200 else "Rejected"
        response._content_consumed = True
        host, path = urlparse(url).hostname, urlparse(url).path
        if host == "hooks.slack.com":
            self.assertTrue(path.startswith("/services/"))
            response._content = b"ok" if self.status == 200 else b"invalid_auth"
        else:
            self.assertEqual(host, "matrix.example.test", "no unexpected destinations")
            if self.status != 200:
                payload = {"errcode": "M_FORBIDDEN", "error": "Invalid credentials"}
            elif path == "/.well-known/matrix/client":
                payload = {"m.homeserver": {"base_url": "https://" + host}}
            elif path.endswith("/login"):
                payload = {"access_token": "fixture-token", "home_server": host, "user_id": "@notify:" + host}
            elif path.endswith("/joined_rooms"):
                payload = {"joined_rooms": ["!room:" + host]}
            elif "/join/" in path:
                payload = {"room_id": "!room:" + host}
            elif "/send/" in path:
                payload = {"event_id": "$fixture"}
            elif path.endswith("/logout"):
                payload = {}
            elif path.endswith("/versions"):
                payload = {"versions": ["v1.1"]}
            else:
                raise AssertionError("Unhandled Matrix request: " + path)
            response._content = json.dumps(payload).encode()
        return response

    def send(self, url):
        channel = create_channel("apprise", {"url": url})
        self.assertIsNotNone(channel)
        return channel.send("ProxMenux probe", "Controlled message", "WARNING")

    def test_slack_accepts_the_native_webhook_without_conversion(self):
        result = self.send(SLACK)
        self.assertTrue(result["success"], result)
        self.assertTrue(any(url == SLACK for _, url, _ in self.calls))
        self.assertIn("Controlled message", str(self.calls))

    def test_slack_apprise_scheme_uses_the_same_transport(self):
        result = self.send(SLACK.replace("https://hooks.slack.com/services/", "slack://"))
        self.assertTrue(result["success"], result)
        self.assertTrue(any(url == SLACK for _, url, _ in self.calls))

    def test_matrix_authenticates_and_delivers_to_the_full_room_id_over_https(self):
        result = self.send(MATRIX)
        self.assertTrue(result["success"], result)
        sends = [(url, kwargs) for _, url, kwargs in self.calls if "/send/" in url]
        self.assertTrue(sends, self.calls)
        self.assertTrue(all(url.startswith("https://matrix.example.test/") for url, _ in sends))
        self.assertTrue(all(kwargs.get("verify", True) for _, kwargs in sends))
        self.assertIn("Controlled message", str(sends))
        self.assertTrue(any(url.endswith("/login") for _, url, _ in self.calls))

    def test_test_button_contract_uses_the_same_provider(self):
        ok, error = create_channel("apprise", {"url": SLACK}).test()
        self.assertTrue(ok, error)
        self.assertTrue(self.calls)

    def test_rejected_slack_webhook_is_not_reported_as_delivered(self):
        self.status = 403
        result = self.send(SLACK)
        self.assertFalse(result["success"])
        self.assertTrue(result["error"])

    def test_invalid_matrix_credentials_are_not_reported_as_delivered(self):
        self.status = 403
        result = self.send(MATRIX)
        self.assertFalse(result["success"])
        self.assertFalse(any("/send/" in url for _, url, _ in self.calls))

    def test_invalid_urls_and_missing_library_fail_before_any_request(self):
        channel = create_channel("apprise", {"url": "not-a-url"})
        self.assertFalse(channel.send("Probe", "Body")["success"])
        channel = create_channel("apprise", {"url": SLACK})
        with patch.object(channel, "_load_apprise", return_value=None):
            self.assertFalse(channel.send("Probe", "Body")["success"])
        self.assertEqual(self.calls, [])

    def test_connection_failure_never_claims_delivery(self):
        for url in (SLACK, MATRIX):
            with patch.object(requests.Session, "request", side_effect=requests.ConnectionError("fixture connection failure")):
                result = self.send(url)
            self.assertFalse(result["success"])
            self.assertTrue(result["error"])

    def test_severity_mapping_keeps_native_notification_semantics(self):
        channel = create_channel("apprise", {"url": SLACK})
        for severity, expected in (("CRITICAL", apprise.NotifyType.FAILURE), ("WARNING", apprise.NotifyType.WARNING),
                                   ("INFO", apprise.NotifyType.INFO), ("OK", apprise.NotifyType.SUCCESS),
                                   ("SUCCESS", apprise.NotifyType.SUCCESS)):
            self.assertEqual(channel._severity_to_notify_type(apprise, severity), expected)


if __name__ == "__main__":
    unittest.main()
