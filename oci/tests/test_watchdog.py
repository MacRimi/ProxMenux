"""The watchdog starts again what stopped on its own, and nothing else."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_watchdog as watchdog

ACTIVE = """UPID:amd:001C34BC:01A809CF:6AC55103:vzshutdown:109:root@pam: 1 6AC55105 OK
UPID:amd:001C3370:01A80568:6AC550F8:vzstart:109:root@pam: 1 6AC550FA OK
UPID:amd:001C32AC:01A80211:6AC550EF:vzstop:108:root@pam: 1 6AC550F1 unable to stop: timeout
UPID:amd:001C3999:01A80999:6AC55200:vzdump:110:root@pam: 0
"""
INDEX = """UPID:amd:001C32AC:01A80211:6AC550EF:vzstop:109:root@pam: 6AC550F1 OK
UPID:amd:001C3370:01A80568:6AC550F8:stopall::root@pam: 6AC55300 unable to stop every guest
"""


def never():
    raise AssertionError("not expected to be asked")


class Watch:
    """One container seen through the decisions of the watchdog."""
    def __init__(self):
        self.state = watchdog.new_state()

    def look(self, running, now, busy=False, requested=False):
        return watchdog.decide(self.state, running, now, lambda: busy, lambda seen: requested)


class TaskList(unittest.TestCase):
    def test_both_lists_are_read_with_their_own_columns(self):
        self.assertEqual(watchdog.parse_tasks(ACTIVE, True), [
            ("vzshutdown", "109", 0x6AC55105), ("vzstart", "109", 0x6AC550FA),
            ("vzstop", "108", 0x6AC550F1), ("vzdump", "110", None)])
        self.assertEqual(watchdog.parse_tasks(INDEX, False), [("vzstop", "109", 0x6AC550F1), ("stopall", "", 0x6AC55300)])

    def test_a_request_counts_when_it_ended_after_the_container_was_last_seen_running(self):
        tasks = watchdog.parse_tasks(ACTIVE, True)
        self.assertTrue(watchdog.stop_requested(tasks, 109, 0x6AC55104))
        self.assertFalse(watchdog.stop_requested(tasks, 109, 0x6AC55110))
        self.assertFalse(watchdog.stop_requested(tasks, 111, 0x6AC55000))

    def test_a_running_request_and_a_stop_of_every_guest_count(self):
        self.assertTrue(watchdog.stop_requested(watchdog.parse_tasks(ACTIVE, True), 110, 0x6AC55900))
        self.assertTrue(watchdog.stop_requested(watchdog.parse_tasks(INDEX, False), 555, 0x6AC552F0))

    def test_starting_a_container_is_not_a_request_to_stop_it(self):
        self.assertFalse(watchdog.stop_requested([("vzstart", "109", None)], 109, 0))


class Decisions(unittest.TestCase):
    def test_a_container_never_seen_running_is_left_alone(self):
        watch = Watch()
        self.assertIsNone(watchdog.decide(watch.state, False, 100, never, never))
        self.assertIsNone(watchdog.decide(watch.state, False, 5000, never, never))

    def test_a_container_that_stops_on_its_own_is_started_again(self):
        watch = Watch()
        watch.look(True, 100)
        self.assertEqual(watch.look(False, 110), "start")
        self.assertEqual(watch.state["attempts"], 1)

    def test_a_requested_stop_is_never_undone(self):
        watch = Watch()
        watch.look(True, 100)
        self.assertIsNone(watch.look(False, 110, requested=True))
        self.assertIsNone(watchdog.decide(watch.state, False, 9000, never, never))
        watch.look(True, 9100)
        self.assertEqual(watch.look(False, 9110), "start")

    def test_nothing_is_decided_while_something_works_on_the_container(self):
        watch = Watch()
        watch.look(True, 100)
        self.assertIsNone(watchdog.decide(watch.state, False, 110, lambda: True, never))
        self.assertIsNone(watch.look(False, 120, requested=True))
        watch.look(True, 300)
        self.assertIsNone(watchdog.decide(watch.state, False, 310, lambda: True, never))
        self.assertEqual(watch.look(False, 320), "start")

    def test_a_stop_asked_after_a_restart_is_respected(self):
        watch = Watch()
        watch.look(True, 100)
        self.assertEqual(watch.look(False, 110), "start")
        watch.look(True, 120)
        self.assertIsNone(watch.look(False, 130, requested=True))
        self.assertIsNone(watchdog.decide(watch.state, False, 5000, never, never))

    def test_an_application_that_keeps_stopping_is_tried_with_longer_waits_and_then_left(self):
        watch, now, actions = Watch(), 100, []
        watch.look(True, now)
        for _ in range(200):
            now += 10
            action = watch.look(False, now)
            if action:
                actions.append((action, now))
        self.assertEqual([name for name, _ in actions], ["start"] * 5 + ["give-up"])
        waits = [later - earlier for (_, earlier), (_, later) in zip(actions, actions[1:])]
        self.assertEqual(waits, [30, 60, 120, 300, 300])
        self.assertIsNone(watchdog.decide(watch.state, False, now + 9000, never, never))

    def test_an_application_that_restarts_itself_now_and_then_is_always_started_at_once(self):
        watch, now = Watch(), 100
        watch.look(True, now)
        for _ in range(12):
            now += 10
            self.assertEqual(watch.look(False, now), "start")
            for _ in range(4):
                now += 10
                watch.look(True, now)
        self.assertEqual(watch.state["attempts"], 0)

    def test_a_restart_is_told_once_in_a_while(self):
        state = watchdog.new_state()
        self.assertTrue(watchdog.notice_due(state, 1000))
        self.assertFalse(watchdog.notice_due(state, 1000 + watchdog.NOTICE_EVERY - 1))
        self.assertTrue(watchdog.notice_due(state, 1000 + watchdog.NOTICE_EVERY))

    def test_running_for_a_while_forgets_the_earlier_attempts(self):
        watch = Watch()
        watch.look(True, 100)
        self.assertEqual(watch.look(False, 110), "start")
        watch.look(True, 120)
        watch.look(True, 120 + watchdog.STABLE)
        self.assertEqual(watch.state["attempts"], 0)
        self.assertEqual(watch.look(False, 400), "start")
        self.assertEqual(watch.state["attempts"], 1)


class Registry(unittest.TestCase):
    def test_only_installed_applications_that_asked_for_it_are_watched(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            records = {
                101: {"status": "installed", "deployment": {"watchdog": True},
                      "template": {"catalog_ui": {"title": {"en_US": "Jellyfin"}}}},
                102: {"status": "installed", "deployment": {"watchdog": False}},
                103: {"status": "installed", "deployment": {}},
                104: {"status": "updating", "deployment": {"watchdog": True}},
                105: {"status": "installed", "deployment": {"watchdog": True}, "pending_stack_transaction": "/journal"},
                106: {"status": "installed", "deployment": {"watchdog": True}},
            }
            for vmid, record in records.items():
                (root / str(vmid)).mkdir()
                (root / str(vmid) / "oci-compose.json").write_text(json.dumps({
                    "schema_version": 1, "vmid": vmid,
                    "installation_id": "11111111-1111-4111-8111-111111111111", **record}))
            (root / "107").mkdir()
            (root / "107" / "oci-compose.json").write_text("{broken")
            self.assertEqual(watchdog.watched(root), {
                101: ("Jellyfin", "11111111-1111-4111-8111-111111111111"),
                106: ("CT 106", "11111111-1111-4111-8111-111111111111")})

    def test_a_record_without_a_valid_installation_identity_is_not_watched(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "109" / "oci-compose.json"
            path.parent.mkdir()
            for identity in (None, "", "not-a-uuid", 123, []):
                with self.subTest(identity=identity):
                    path.write_text(json.dumps({
                        "schema_version": 1, "vmid": 109, "status": "installed",
                        "installation_id": identity, "deployment": {"watchdog": True}}))
                    self.assertEqual(watchdog.watched(root), {})


class Start(unittest.TestCase):
    def test_the_container_is_started_outside_the_service(self):
        from unittest.mock import patch
        with patch.object(watchdog.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertTrue(watchdog.start(109))
            run.return_value.returncode = 255
            self.assertFalse(watchdog.start(109))
        self.assertEqual(run.call_args.args[0], ["systemd-run", "--scope", "--quiet", "--collect", "pct", "start", "109"])


class InstallationIdentity(unittest.TestCase):
    """A recycled VMID is not the application the watchdog saw running."""
    VMID = 109
    ORIGINAL = "11111111-1111-4111-8111-111111111111"
    REPLACEMENT = "22222222-2222-4222-8222-222222222222"

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.base = Path(folder.name)
        self.registry = self.base / "instances"
        self.configs = self.base / "lxc"
        self.cgroups = self.base / "cgroups"
        for path in (self.registry, self.configs, self.cgroups):
            path.mkdir()
        for target, value in (("CONFIGS", self.configs), ("CGROUPS", self.cgroups)):
            patcher = patch.object(watchdog, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(watchdog.instances, "ROOT", self.registry)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name, target, kwargs in (
                ("start", watchdog, {"return_value": True}),
                ("is_busy", watchdog, {"return_value": False}),
                ("read_tasks", watchdog, {"return_value": []}),
                ("notify", watchdog.oci_operation_notice, {}),
                ("run", watchdog.subprocess, {"side_effect": self.command})):
            patcher = patch.object(target, name, **kwargs)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.states = {}
        self.record()
        self.config(self.ORIGINAL)

    def record(self, identity=None, **extra):
        path = self.registry / str(self.VMID) / "oci-compose.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({
            "schema_version": 1, "vmid": self.VMID,
            "installation_id": identity or self.ORIGINAL,
            "status": "installed", "deployment": {"watchdog": True},
            "template": {"catalog_ui": {"title": {"en_US": "Example"}}}, **extra}))

    def config(self, identity):
        self.config_text(f"description: proxmenux-instance={identity}\narch: amd64\n")

    def config_text(self, text):
        (self.configs / f"{self.VMID}.conf").write_text(text)

    def command(self, argv, **kwargs):
        self.assertEqual(argv, ["pct", "config", str(self.VMID)])
        return subprocess.CompletedProcess(argv, 0, (self.configs / f"{self.VMID}.conf").read_bytes(), b"")

    def seen_running(self):
        (self.cgroups / str(self.VMID)).mkdir()
        watchdog.look(self.states, 100)
        (self.cgroups / str(self.VMID)).rmdir()

    def assert_left_alone(self):
        watchdog.look(self.states, 110)
        self.start.assert_not_called()
        self.notify.assert_not_called()

    def test_transaction_holder_is_not_started_for_a_stale_application_record(self):
        self.seen_running()
        self.config_text("description: proxmenux-transaction=example-update\nhostname: oci-data-holder\n")
        self.assert_left_alone()

    def test_another_installation_at_the_same_vmid_is_not_started(self):
        self.seen_running()
        self.config(self.REPLACEMENT)
        self.assert_left_alone()

    def test_a_marker_in_old_snapshot_notes_does_not_own_the_live_guest(self):
        self.seen_running()
        self.config_text("description: unrelated container\n\n[old]\n"
                         f"description: proxmenux-instance={self.ORIGINAL}\n")
        self.assert_left_alone()

    def test_an_unreadable_live_configuration_is_not_started(self):
        self.seen_running()
        self.run.side_effect = None
        self.run.return_value = subprocess.CompletedProcess([], 2, b"", b"missing config")
        self.assert_left_alone()
        self.run.side_effect = self.command
        watchdog.look(self.states, 111)
        self.start.assert_called_once_with(self.VMID)
        self.assertEqual(self.states[self.VMID]["attempts"], 1)

    def test_a_removed_guest_drops_its_running_history_without_a_pve_query(self):
        self.seen_running()
        (self.configs / f"{self.VMID}.conf").unlink()
        self.assert_left_alone()
        self.run.assert_not_called()
        self.assertNotIn(self.VMID, self.states)

    def test_a_configuration_timeout_is_retried_without_consuming_an_attempt(self):
        self.seen_running()
        self.run.side_effect = subprocess.TimeoutExpired("pct", 30)
        self.assert_left_alone()
        self.run.side_effect = self.command
        watchdog.look(self.states, 111)
        self.start.assert_called_once_with(self.VMID)
        self.assertEqual(self.states[self.VMID]["attempts"], 1)

    def test_a_new_installation_does_not_inherit_running_history(self):
        self.seen_running()
        self.record(self.REPLACEMENT)
        self.config(self.REPLACEMENT)
        self.assert_left_alone()
        (self.cgroups / str(self.VMID)).mkdir()
        watchdog.look(self.states, 120)
        (self.cgroups / str(self.VMID)).rmdir()
        watchdog.look(self.states, 130)
        self.start.assert_called_once_with(self.VMID)

    def test_a_transaction_started_after_the_scan_is_respected(self):
        self.seen_running()

        def updating(vmid):
            self.record(status="updating", pending_transaction="/journal")
            return False

        with patch.object(watchdog, "is_running", side_effect=updating):
            self.assert_left_alone()

    def test_a_busy_registry_does_not_start_or_consume_a_restart_attempt(self):
        self.seen_running()
        with watchdog.instances.locked(self.registry):
            self.assert_left_alone()
        watchdog.look(self.states, 111)
        self.start.assert_called_once_with(self.VMID)
        self.assertEqual(self.states[self.VMID]["attempts"], 1)

    def test_the_same_installation_is_still_restarted_after_a_crash(self):
        self.seen_running()
        watchdog.look(self.states, 110)
        self.start.assert_called_once_with(self.VMID)
        self.notify.assert_called_once()

    def test_a_recycled_vmid_does_not_receive_a_crash_loop_alert(self):
        self.seen_running()
        self.states[self.VMID].update(attempts=len(watchdog.DELAYS), retry_at=0)
        self.config(self.REPLACEMENT)
        self.assert_left_alone()


class Switch(unittest.TestCase):
    """Turning the watchdog on or off for a whole application."""
    def registry(self, folder):
        root = Path(folder)
        ids = {101: "11111111-1111-4111-8111-111111111111", 102: "22222222-2222-4222-8222-222222222222",
               103: "33333333-3333-4333-8333-333333333333"}
        stack = {"members": [{"vmid": 101}, {"vmid": 102}]}
        records = {101: {"stack": stack, "stack_member": {"primary_vmid": 101}},
                   102: {"stack_member": {"primary_vmid": 101}}, 103: {}}
        for vmid, extra in records.items():
            (root / str(vmid)).mkdir()
            (root / str(vmid) / "oci-compose.json").write_text(json.dumps({
                "schema_version": 1, "vmid": vmid, "installation_id": ids[vmid], "status": "installed",
                "deployment": {"onboot": True}, **extra}))
        return root

    def flags(self, root):
        return {int(path.parent.name): json.loads(path.read_text())["deployment"].get("watchdog")
                for path in root.glob("*/oci-compose.json")}

    def test_completed_jobs_never_receive_or_use_watchdog(self):
        with tempfile.TemporaryDirectory() as folder:
            root=self.registry(folder)
            path=root/'102'/'oci-compose.json'
            record=json.loads(path.read_text())
            record['deployment'].update(execution_mode='one-shot',watchdog=True)
            path.write_text(json.dumps(record))
            self.assertNotIn(102,watchdog.watched(root))
            with patch.object(watchdog,'ensure_service'),patch('oci_carried_record.carry'):
                watchdog.set_watchdog(root,101,True)
            self.assertEqual(self.flags(root)[101],True)
            self.assertEqual(self.flags(root)[102],False)

    def test_every_container_of_the_application_takes_the_choice_and_keeps_the_rest_of_its_record(self):
        from unittest.mock import patch
        import oci_carried_record
        with tempfile.TemporaryDirectory() as folder:
            root = self.registry(folder)
            with patch.object(watchdog, "ensure_service") as service, \
                    patch.object(oci_carried_record, "carry", return_value="carried") as carry:
                self.assertEqual(watchdog.set_watchdog(root, 102, True), [101, 102])
                self.assertEqual(self.flags(root), {101: True, 102: True, 103: None})
                service.assert_called_once_with()
                self.assertEqual([call.args[1] for call in carry.call_args_list], [101, 102])
                self.assertEqual(watchdog.set_watchdog(root, 103, True), [103])
                self.assertEqual(watchdog.set_watchdog(root, 101, False), [101, 102])
                self.assertEqual(self.flags(root), {101: False, 102: False, 103: True})
                self.assertEqual(service.call_count, 2)
            record = json.loads((root / "101" / "oci-compose.json").read_text())
            self.assertEqual(record["deployment"]["onboot"], True)
            self.assertEqual(record["stack"]["members"], [{"vmid": 101}, {"vmid": 102}])


class DependencyLocks(unittest.TestCase):
    """A multi-container application waits while a container it depends on is busy."""
    def setUp(self):
        from unittest.mock import patch
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / "lxc").mkdir()
        (self.root / "priv").mkdir()
        for target, value in (("CONFIGS", self.root / "lxc"), ("STACK_CONTRACTS", self.root / "priv"),
                              ("HA_RESOURCES", self.root / "resources.cfg")):
            patcher = patch.object(watchdog, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(watchdog.oci_operation_notice, "MARKERS", self.root / "markers")
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(watchdog.subprocess, "run")
        run = patcher.start()
        run.return_value.stdout = "running\n"
        self.addCleanup(patcher.stop)
        for vmid in (110, 111, 112):
            self.config(vmid, "arch: amd64\n")
        (self.root / "priv" / "proxmenux-stack-110.json").write_text(json.dumps(
            {"schema": 1, "dependencies": [{"vmid": 112, "label": "PostgreSQL"}, {"vmid": 111, "label": "ML"}]}))

    def config(self, vmid, text):
        (self.root / "lxc" / f"{vmid}.conf").write_text(text)

    def test_a_dependency_being_backed_up_keeps_the_application_waiting(self):
        self.assertFalse(watchdog.is_busy(110, 1000))
        self.config(111, "arch: amd64\nlock: backup\n")
        self.assertTrue(watchdog.is_busy(110, 1000))

    def test_a_lock_in_a_snapshot_of_a_dependency_does_not_count(self):
        self.config(111, "arch: amd64\n\n[before]\nlock: backup\n")
        self.assertFalse(watchdog.is_busy(110, 1000))

    def test_a_removed_dependency_does_not_keep_the_application_waiting(self):
        (self.root / "lxc" / "112.conf").unlink()
        self.assertFalse(watchdog.is_busy(110, 1000))

    def test_an_application_without_dependencies_only_looks_at_itself(self):
        self.config(111, "arch: amd64\nlock: backup\n")
        self.assertFalse(watchdog.is_busy(112, 1000))
        (self.root / "lxc" / "112.conf").unlink()
        self.assertTrue(watchdog.is_busy(112, 1000))


if __name__ == "__main__":
    unittest.main()
