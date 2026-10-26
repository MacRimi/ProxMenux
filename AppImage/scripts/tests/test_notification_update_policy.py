import json
import sys
import tempfile
import unittest
from pathlib import Path
from queue import Queue
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import notification_events  # noqa: E402
import notification_templates  # noqa: E402
import post_install_versions  # noqa: E402


class NotificationUpdatePolicyTests(unittest.TestCase):
    def test_apt_listchanges_system_mail_has_its_own_update_event(self):
        watcher = notification_events.ProxmoxHookWatcher(Queue())
        classified = watcher._classify_pve(
            "system-mail",
            "info",
            "Novedades de apt-listchanges para amd",
            "zfs-linux recommends that all users update absolute paths",
        )
        self.assertEqual(classified, ("apt_listchanges", "node", ""))

    def test_regular_system_mail_remains_available(self):
        watcher = notification_events.ProxmoxHookWatcher(Queue())
        with mock.patch.object(notification_events, "_record_smartd_observation_impl"):
            classified = watcher._classify_pve(
                "system-mail",
                "warning",
                "SMART error (CurrentPendingSector) detected on host",
                "Device: /dev/sda",
            )
        self.assertEqual(classified, ("system_mail", "node", ""))

    def test_apt_listchanges_body_is_preserved_and_attributed(self):
        watcher = notification_events.ProxmoxHookWatcher(Queue())
        upstream = (
            "zfs-linux (2.2.4-2) unstable; urgency=medium\n\n"
            "  Package-maintainer recommendation.\n\n"
            " -- Maintainer <maintainer@example.com>"
        )
        result = watcher.process_webhook({
            "title": "apt-listchanges: News for host",
            "message": upstream,
            "severity": "info",
            "fields": {"type": "system-mail", "hostname": "pve-test"},
        })
        self.assertTrue(result["accepted"])
        event = watcher._queue.get_nowait()
        self.assertEqual(event.event_type, "apt_listchanges")
        self.assertEqual(event.data["reason"], upstream)

        rendered = notification_templates.render_template(
            event.event_type,
            event.data,
        )
        self.assertIn("not a ProxMenux recommendation", rendered["body_text"])
        self.assertIn(upstream, rendered["body_text"])

    def test_smaller_pending_subset_does_not_notify_again(self):
        updates = [
            {"key": "persistent_network", "available_version": "1.2"},
        ]
        notified = {
            "log2ram": {"1.4"},
            "persistent_network": {"1.2"},
        }
        self.assertEqual(
            notification_events._new_post_install_update_versions(updates, notified),
            {},
        )

    def test_new_version_of_existing_tool_is_detected(self):
        updates = [
            {"key": "persistent_network", "available_version": "1.3"},
        ]
        notified = {"persistent_network": {"1.2"}}
        self.assertEqual(
            notification_events._new_post_install_update_versions(updates, notified),
            {"persistent_network": "1.3"},
        )

    def test_notified_versions_share_the_existing_snapshot_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            snapshot_path = Path(temporary) / "updates_available.json"
            cache = {
                "scanned_at": 123.0,
                "updates": [
                    {"key": "log2ram", "available_version": "1.4"},
                ],
            }
            with mock.patch.object(post_install_versions, "_UPDATES_JSON", snapshot_path), \
                    mock.patch.object(post_install_versions, "_cache", cache):
                post_install_versions.save_notified_versions(
                    {"log2ram": {"1.3", "1.4"}}
                )
                self.assertEqual(
                    post_install_versions.load_notified_versions(),
                    {"log2ram": {"1.3", "1.4"}},
                )
                payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["scanned_at"], 123.0)
                self.assertEqual(payload["updates"], cache["updates"])
                self.assertEqual(payload["notified_versions"]["log2ram"], ["1.3", "1.4"])


if __name__ == "__main__":
    unittest.main()
