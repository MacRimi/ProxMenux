import sys
import unittest
import urllib.parse
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from notification_channels import PushoverChannel, create_channel


class PushoverChannelTests(unittest.TestCase):
    USER_KEY = "u" * 30
    API_TOKEN = "a" * 30

    def make_channel(self, **kwargs):
        channel = PushoverChannel(
            user_key=kwargs.pop("user_key", self.USER_KEY),
            api_token=kwargs.pop("api_token", self.API_TOKEN),
            **kwargs,
        )
        channel.MAX_RETRIES = 1
        return channel

    def test_requires_valid_user_key_and_api_token(self):
        channel = self.make_channel(user_key="")
        self.assertEqual(channel.validate_config(), (
            False, "Pushover user or group key is required"
        ))

        channel = self.make_channel(api_token="short")
        self.assertEqual(channel.validate_config(), (
            False, "Invalid Pushover application API token format"
        ))

    def test_optional_device_sound_and_factory(self):
        channel = create_channel("pushover", {
            "user_key": self.USER_KEY,
            "api_token": self.API_TOKEN,
            "device": "iphone_15",
            "sound": "magic",
            "critical_priority": "false",
        })

        self.assertIsInstance(channel, PushoverChannel)
        self.assertEqual(channel.validate_config(), (True, ""))
        self.assertFalse(channel.critical_priority)

    def test_critical_alert_uses_high_priority_and_api_limits(self):
        channel = self.make_channel(
            device="iphone_15",
            sound="magic",
            critical_priority="true",
        )
        request = {}

        def fake_http(url, data, headers):
            request["url"] = url
            request["payload"] = urllib.parse.parse_qs(data.decode("utf-8"))
            request["headers"] = headers
            return 200, '{"status":1,"request":"test"}'

        channel._http_request = fake_http
        result = channel.send("T" * 300, "M" * 1200, "critical")

        self.assertTrue(result["success"])
        self.assertEqual(request["url"], PushoverChannel.API_URL)
        self.assertEqual(request["payload"]["priority"], ["1"])
        self.assertEqual(request["payload"]["device"], ["iphone_15"])
        self.assertEqual(request["payload"]["sound"], ["magic"])
        self.assertEqual(len(request["payload"]["title"][0]), 250)
        self.assertEqual(len(request["payload"]["message"][0]), 1024)
        self.assertTrue(request["payload"]["message"][0].endswith("…"))

    def test_noncritical_alert_uses_normal_priority(self):
        channel = self.make_channel(critical_priority="true")
        request = {}

        def fake_http(url, data, headers):
            request["payload"] = urllib.parse.parse_qs(data.decode("utf-8"))
            return 200, '{"status":1}'

        channel._http_request = fake_http
        result = channel.send("Warning", "Message", "WARNING")

        self.assertTrue(result["success"])
        self.assertEqual(request["payload"]["priority"], ["0"])

    def test_api_error_does_not_expose_credentials(self):
        channel = self.make_channel()
        channel._http_request = lambda *args: (
            400, '{"status":0,"errors":["user identifier is invalid"]}'
        )

        result = channel.send("Title", "Message")

        self.assertFalse(result["success"])
        self.assertIn("user identifier is invalid", result["error"])
        self.assertNotIn(self.USER_KEY, result["error"])
        self.assertNotIn(self.API_TOKEN, result["error"])


if __name__ == "__main__":
    unittest.main()
