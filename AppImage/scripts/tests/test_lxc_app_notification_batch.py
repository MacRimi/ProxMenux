import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import lxc_apps
import notification_templates


def _app(app_id, name, installed, latest, **extra):
    return {
        "id": app_id,
        "name": name,
        "state": {
            "installed_version": installed,
            "latest_version": latest,
            "update_available": True,
        },
        **extra,
    }


class _FakeNotificationManager:
    def __init__(self):
        self.calls = []

    def emit_event(self, **kwargs):
        self.calls.append(kwargs)
        return {"success": True}


class AppUpdateNotificationBatchTests(unittest.TestCase):
    def _write_sidecar(self, directory, vmid, apps):
        Path(directory, f"{vmid}.json").write_text(
            json.dumps({"vmid": vmid, "apps": apps}),
            encoding="utf-8",
        )

    def _emit(self, sidecars):
        fake = _FakeNotificationManager()
        module = types.SimpleNamespace(notification_manager=fake)
        with tempfile.TemporaryDirectory() as directory:
            for vmid, apps in sidecars.items():
                self._write_sidecar(directory, vmid, apps)
            with (
                mock.patch.object(lxc_apps, "_APPS_DIR", directory),
                mock.patch.dict(sys.modules, {"notification_manager": module}),
            ):
                count = lxc_apps.emit_all_pending_updates()
        return count, fake.calls

    def test_multiple_updates_are_sent_as_one_sorted_batch(self):
        count, calls = self._emit({
            115: [
                _app("redis", "Redis", "7.0.15-1", "8.10.1"),
                _app("docmost", "Docmost", "0.23.2", "0.95.0"),
            ],
            100: [_app("adguard", "AdGuard Home", "0.107.78", "0.107.79")],
        })

        self.assertEqual(count, 3)
        self.assertEqual(len(calls), 1)
        event = calls[0]
        self.assertEqual(event["event_type"], "app_update_available")
        self.assertEqual(event["entity"], "node")
        self.assertTrue(event["entity_id"].startswith("batch:"))
        self.assertEqual(event["data"]["count"], 3)
        self.assertEqual(event["data"]["container_count"], 2)
        self.assertEqual(
            [(item["vmid"], item["app_name"]) for item in event["data"]["updates"]],
            [(100, "AdGuard Home"), (115, "Docmost"), (115, "Redis")],
        )

    def test_single_update_keeps_the_individual_event_shape(self):
        count, calls = self._emit({
            101: [_app("npm", "Nginx Proxy Manager", "2.9.19", "2.15.1")],
        })

        self.assertEqual(count, 1)
        self.assertEqual(len(calls), 1)
        event = calls[0]
        self.assertEqual(event["entity"], "ct")
        self.assertNotIn("updates", event["data"])
        self.assertEqual(event["data"]["vmid"], 101)
        self.assertEqual(event["data"]["latest"], "2.15.1")

    def test_batch_respects_opt_outs_and_docker_delegation(self):
        count, calls = self._emit({
            110: [
                _app("silent", "Silent", "1.0", "2.0", notifications_enabled=False),
                _app("docker", "Docker", "1.0", "2.0", helper_slug="docker"),
                _app("portainer", "Portainer", "2.0", "2.1", update_via="docker"),
            ],
        })

        self.assertEqual(count, 0)
        self.assertEqual(calls, [])

    def test_check_all_can_refresh_without_emitting_individual_events(self):
        sidecar = {"vmid": 120, "apps": [{"id": "one"}, {"id": "two"}]}
        with (
            mock.patch.object(lxc_apps, "_read_sidecar", return_value=sidecar),
            mock.patch.object(lxc_apps, "check_app") as check,
        ):
            lxc_apps.check_all(120, force=False, notify=False)

        self.assertEqual(check.call_count, 2)
        check.assert_any_call(120, "one", force=False, notify=False)
        check.assert_any_call(120, "two", force=False, notify=False)

    def test_batch_formatter_groups_versions_by_container(self):
        rendered = notification_templates.render_template(
            "app_update_available",
            {
                "hostname": "pve01",
                "updates": [
                    {"vmid": 115, "app_name": "Redis", "installed": "7.0", "latest": "8.1"},
                    {"vmid": 100, "app_name": "AdGuard Home", "installed": "1.0", "latest": "1.1"},
                    {"vmid": 115, "app_name": "Docmost", "installed": "0.2", "latest": "0.9"},
                ],
            },
        )

        self.assertEqual(rendered["title"], "pve01: 3 application updates available")
        self.assertIn("3 applications in 2 LXC containers", rendered["body"])
        self.assertLess(rendered["body"].index("CT 100"), rendered["body"].index("CT 115"))
        self.assertIn("• Docmost: 0.2 → 0.9", rendered["body"])
        self.assertIn("• Redis: 7.0 → 8.1", rendered["body"])


if __name__ == "__main__":
    unittest.main()
