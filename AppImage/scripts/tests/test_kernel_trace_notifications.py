import json
import sys
import unittest
from pathlib import Path
from queue import Empty, Queue


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
APPIMAGE_DIR = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import notification_events  # noqa: E402
import notification_templates  # noqa: E402


class KernelTraceNotificationTests(unittest.TestCase):
    def setUp(self):
        self.queue = Queue()
        self.watcher = notification_events.JournalWatcher(self.queue)

    def _check(self, message, *, syslog_id="kernel", transport="kernel"):
        self.watcher._check_kernel_critical(
            message,
            syslog_id,
            4,
            {
                "_TRANSPORT": transport,
                "__REALTIME_TIMESTAMP": "1788883200000000",
            },
        )

    def test_bare_call_trace_is_not_an_event(self):
        self._check("Call Trace:")
        with self.assertRaises(Empty):
            self.queue.get_nowait()

    def test_kernel_warning_carries_attributable_fields(self):
        self._check(
            "WARNING: CPU: 2 PID: 418 Comm: z_wr_iss at arc_evict_state+0x12/0x80"
        )
        event = self.queue.get_nowait()
        self.assertEqual(event.event_type, "kernel_warning")
        self.assertEqual(event.severity, "WARNING")
        self.assertIn("Type: Kernel warning", event.data["kernel_details"])
        self.assertIn("Process: z_wr_iss (PID 418)", event.data["kernel_details"])
        self.assertIn("Component: arc_evict_state", event.data["kernel_details"])
        self.assertIn("Recorded: 2026-", event.data["kernel_details"])
        self.assertIn("WARNING: CPU", event.data["_journal_context"])

        self._check("Call Trace:")
        with self.assertRaises(Empty):
            self.queue.get_nowait()

    def test_application_text_cannot_impersonate_kernel_warning(self):
        self._check(
            "WARNING: CPU: 0 PID: 99 Comm: example at fake_function+0x1/0x2",
            syslog_id="systemd",
            transport="stdout",
        )
        with self.assertRaises(Empty):
            self.queue.get_nowait()

    def test_blocked_task_is_identified(self):
        self._check("INFO: task txg_sync:812 blocked for more than 120 seconds.")
        event = self.queue.get_nowait()
        self.assertEqual(event.event_type, "kernel_warning")
        self.assertIn("Type: Blocked kernel task", event.data["kernel_details"])
        self.assertIn("Process: txg_sync", event.data["kernel_details"])

    def test_event_is_visible_and_translated_in_every_monitor_locale(self):
        services = notification_templates.get_event_types_by_group()["services"]
        self.assertIn("kernel_warning", {item["type"] for item in services})
        for locale in ("en", "es", "de", "fr", "it", "pt", "sk", "sv"):
            messages = json.loads(
                (APPIMAGE_DIR / "messages" / locale / "common.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(
                messages["settings"]["notifications"]["eventTypes"]["kernel_warning"]
            )


if __name__ == "__main__":
    unittest.main()
