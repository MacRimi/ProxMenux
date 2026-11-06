"""Every delivery path obeys the global switch and each channel's category
and event switches: direct sends, scripts, recoveries, health summaries,
shutdown notices and the digest and quiet-hours buffers."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = SCRIPTS_DIR.parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import notification_events  # noqa: E402
import notification_manager  # noqa: E402
import notification_templates  # noqa: E402


class RecordingChannel:
    def __init__(self):
        self.sent = []

    def send(self, title, body, severity, data):
        self.sent.append((title, body, severity))
        return {"success": True, "error": ""}


class SwitchTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = Path(folder.name) / "health.db"
        conn = sqlite3.connect(self.db)
        for table in ("digest_pending", "quiet_pending"):
            conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT, "
                         "event_type TEXT, event_group TEXT, severity TEXT, ts INTEGER, title TEXT, body TEXT)")
        conn.commit()
        conn.close()
        patcher = patch.object(notification_manager, "DB_PATH", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.email, self.telegram = RecordingChannel(), RecordingChannel()
        self.manager = notification_manager.NotificationManager()
        self.manager._channels = {"email": self.email, "telegram": self.telegram}
        self.manager._enabled = True
        self.manager._config = {
            "enabled": "true", "email.enabled": "true", "telegram.enabled": "true",
            "ai_enabled": "false", "language": "en",
        }

    def dispatch(self, event_type, data, severity="WARNING", title="host: title", body="body"):
        return self.manager._dispatch_to_channels(title, body, severity, event_type,
                                                  dict(data, hostname="host"), "test")

    def test_script_event_follows_each_channel_switch(self):
        self.manager._config["email.event.gpu_mode_switch"] = "false"
        result = self.manager.send_notification("gpu_mode_switch", "INFO", "host: GPU mode changed",
                                                "GPU passthrough mode switched.", source="cli")
        self.assertEqual(result["channels_sent"], ["telegram"])
        self.assertEqual(self.email.sent, [])

    def test_scripts_use_the_event_type_of_what_they_report(self):
        for script in ("scripts/gpu_tpu/switch_gpu_mode.sh", "scripts/gpu_tpu/switch_gpu_mode_direct.sh",
                       "scripts/storage/smart-disk-test.sh"):
            text = (REPO_DIR / script).read_text(encoding="utf-8")
            self.assertNotIn("send-raw", text, script)
        smart = (REPO_DIR / "scripts/storage/smart-disk-test.sh").read_text(encoding="utf-8")
        self.assertIn("--type smart_test_failed --severity CRITICAL", smart)
        self.assertIn("--type smart_test_complete", smart)

    def test_untemplated_and_custom_notifications_have_a_visible_switch(self):
        groups = notification_templates.get_event_types_by_group()
        self.assertIn("custom", [event["type"] for event in groups["system"]])
        self.manager._config.update({"email.event.custom": "false", "telegram.events.system": "false"})
        for event_type in ("custom", "my_backup_script"):
            with self.subTest(event_type=event_type):
                result = self.manager.send_notification(event_type, "INFO", "host: done", "finished")
                self.assertTrue(result.get("skipped"))
        self.assertEqual(self.email.sent + self.telegram.sent, [])
        self.manager._config["telegram.events.system"] = "true"
        self.assertEqual(self.manager.send_raw("host: done", "finished")["channels_sent"], ["telegram"])

    def test_recovery_reaches_only_channels_that_accept_the_alert(self):
        self.manager._config["email.event.lxc_disk_low"] = "false"
        self.assertTrue(self.dispatch("error_resolved", {"alert_event_type": "lxc_disk_low",
                                                         "category": "storage"}, severity="OK"))
        self.assertEqual(len(self.telegram.sent), 1)
        self.assertEqual(self.email.sent, [])

    def test_resolved_events_name_the_alert_they_close(self):
        collector = object.__new__(notification_events.PollingCollector)
        self.assertEqual(collector._alert_event_type("storage", "lxc_disk_101_rootfs"), "lxc_disk_low")
        self.assertEqual(collector._alert_event_type("storage", "other_key"),
                         collector._CATEGORY_TO_EVENT_TYPE["storage"])
        self.assertEqual(collector._alert_event_type("memory", "memory"), "ram_high")

    def test_health_summary_keeps_only_the_categories_each_channel_accepts(self):
        degraded = {"categories": [
            {"cat_key": "memory", "category": "Memory", "status": "CRITICAL", "reason": "RAM 97%"},
            {"cat_key": "cpu", "category": "CPU", "status": "WARNING", "reason": "CPU >90% sustained for 300s"},
        ]}
        self.manager._config.update({"email.event.ram_high": "false",
                                     "telegram.event.ram_high": "false", "telegram.event.cpu_high": "false"})
        self.assertTrue(self.dispatch("health_degraded", {"health_degraded": degraded, "title": "host: 2 checks",
                                                          "_notification_language": "en"}, severity="CRITICAL"))
        self.assertEqual(self.telegram.sent, [])
        [(title, body, severity)] = self.email.sent
        self.assertEqual(severity, "WARNING")
        self.assertIn("CPU", title + body)
        self.assertNotIn("RAM 97%", body)

    def test_global_switch_also_stops_shutdown_and_direct_sends(self):
        self.manager._enabled = False
        self.assertTrue(self.manager.emit_event("system_shutdown", "WARNING", {"reason": "poweroff"})["skipped"])
        self.assertTrue(self.manager.send_notification("custom", "INFO", "host: t", "m")["skipped"])
        self.assertEqual(self.email.sent + self.telegram.sent, [])

    def test_buffered_rows_are_dropped_when_their_switch_is_turned_off(self):
        conn = sqlite3.connect(self.db)
        for table in ("digest_pending", "quiet_pending"):
            conn.executemany(f"INSERT INTO {table} (channel, event_type, event_group, severity, ts, title, body) "
                             "VALUES ('email', ?, ?, 'INFO', 1000, ?, 'b')",
                             [("backup_complete", "backup", "host: backup ok"),
                              ("update_summary", "updates", "host: updates")])
        conn.commit()
        conn.close()
        self.manager._config.update({"email.events.updates": "false"})
        with patch.object(self.manager, "_save_setting"):
            from datetime import datetime
            self.manager._flush_digest_for_channel("email", self.email, datetime(2026, 11, 6, 9, 0))
        self.manager._config.update({"email.event.backup_complete": "false"})
        self.manager._flush_quiet_for_channel("email", self.email)
        [(digest_title, digest_body, _)] = self.email.sent
        self.assertIn("backup ok", digest_body)
        self.assertNotIn("updates", digest_body.split("\n", 1)[1])
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM quiet_pending").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM digest_pending").fetchone()[0], 0)
        conn.close()


if __name__ == "__main__":
    unittest.main()
