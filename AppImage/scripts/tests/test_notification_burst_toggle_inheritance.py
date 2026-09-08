import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import notification_manager  # noqa: E402


class RecordingChannel:
    def __init__(self):
        self.calls = 0

    def send(self, title, body, severity, data):
        self.calls += 1
        return {"success": True, "error": ""}


class NotificationBurstToggleInheritanceTests(unittest.TestCase):
    def setUp(self):
        self.channel = RecordingChannel()
        self.manager = notification_manager.NotificationManager()
        self.manager._channels = {"email": self.channel}
        self.manager._config = {
            "email.enabled": "true",
            "email.events.services": "true",
            "email.rich_format": "false",
            "email.event.kernel_warning": "false",
            "ai_enabled": "false",
        }

    def test_hidden_summary_inherits_source_event_toggle(self):
        delivered = self.manager._dispatch_to_channels(
            "host: +1 more system problem",
            "One additional issue",
            "WARNING",
            "burst_system",
            {"event_type": "kernel_warning", "hostname": "host"},
            "aggregator",
        )
        self.assertFalse(delivered)
        self.assertEqual(self.channel.calls, 0)

    def test_generic_summary_inherits_source_event_category(self):
        self.manager._config.update({
            "email.event.oom_kill": "true",
            "email.events.services": "false",
            "email.events.other": "true",
        })
        delivered = self.manager._dispatch_to_channels(
            "host: related events",
            "One additional issue",
            "WARNING",
            "burst_generic",
            {"event_type": "oom_kill", "hostname": "host"},
            "aggregator",
        )
        self.assertFalse(delivered)
        self.assertEqual(self.channel.calls, 0)


if __name__ == "__main__":
    unittest.main()
