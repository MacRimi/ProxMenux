"""App registrations travel with their container.

A copy goes inside the container and one into the cluster. A container
restored under another VMID, or in another order, gets its own apps back; a
container whose machine ID no longer matches is marked; a copy the container
could have tampered with is validated and never followed outside it."""
import contextlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import app_watch_copies as copies  # noqa: E402
import lxc_apps  # noqa: E402

OWNER = (os.getuid(), os.getgid())


def sidecar(name, watch_id, port, **extra):
    return {"vmid": 111, "watch_id": watch_id, "created_at": "2026-11-01T00:00:00Z",
            "apps": [{"id": "a1b2c3d4e5f6", "name": name, "ports": [{"port": port}], "created_at": "2026-11-01T00:00:00Z",
                      "state": {"latest_version": "1.0"}}], **extra}


class Container:
    """A running container whose root filesystem is a temporary folder."""

    def __init__(self, test):
        temp = tempfile.TemporaryDirectory()
        test.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "root"
        self.root.mkdir()
        self.cluster = Path(temp.name) / "cluster"
        self.outside = Path(temp.name) / "outside"
        self.outside.mkdir()
        self.running = True
        self.mounted = True
        for name, value in (("_root", lambda pid: str(self.root)),
                            ("running_pid", lambda vmid: 4242 if self.running else None),
                            ("mapped_root", lambda vmid: OWNER),
                            ("CLUSTER", self.cluster),
                            ("_cluster_ready", lambda: self.mounted)):
            patcher = mock.patch.object(copies, name, value)
            patcher.start()
            test.addCleanup(patcher.stop)
        copies._written.clear()

    def machine(self, value):
        (self.root / "etc").mkdir(exist_ok=True)
        (self.root / "etc" / "machine-id").write_text(value + "\n")


class CopyTests(unittest.TestCase):
    def setUp(self):
        self.ct = Container(self)

    def test_both_copies_carry_the_configuration_without_results(self):
        copies.write(111, sidecar("Sonarr", "w-sonarr", 8989))
        inside = copies.read_container(111)
        self.assertEqual(inside["watch_id"], "w-sonarr")
        self.assertNotIn("state", inside["apps"][0])
        self.assertEqual(copies.read_cluster(111), inside)
        self.assertEqual(oct((self.ct.root / ".proxmenux").stat().st_mode & 0o777), "0o700")

    def test_a_link_the_container_left_is_never_followed(self):
        os.symlink(self.ct.outside, self.ct.root / ".proxmenux")
        copies.write(111, sidecar("Sonarr", "w-sonarr", 8989))  # never raises
        self.assertEqual(list(self.ct.outside.iterdir()), [])
        self.assertIsNone(copies.read_container(111))
        (self.ct.root / ".proxmenux").unlink()
        (self.ct.root / ".proxmenux").mkdir()
        os.symlink(self.ct.outside / "x.json", self.ct.root / ".proxmenux" / copies.NAME)
        (self.ct.outside / "x.json").write_text(json.dumps(copies.payload(111, sidecar("Evil", "w-evil", 1))))
        self.assertIsNone(copies.read_container(111))

    def test_a_damaged_or_oversized_copy_is_ignored(self):
        (self.ct.root / ".proxmenux").mkdir()
        target = self.ct.root / ".proxmenux" / copies.NAME
        for content in ("{not json", json.dumps({"kind": "other"}), " " * (copies.LIMIT + 1)):
            with self.subTest(content=content[:12]):
                target.write_text(content)
                self.assertIsNone(copies.read_container(111))

    def test_the_cluster_copy_waits_for_a_mounted_etc_pve(self):
        self.ct.mounted = False
        copies.write(111, sidecar("Sonarr", "w-sonarr", 8989))
        self.assertFalse(self.ct.cluster.exists())
        self.ct.mounted = True
        copies.write(111, sidecar("Sonarr", "w-sonarr", 8989))  # not written yet: written now
        self.assertIsNotNone(copies.read_cluster(111))

    def test_new_results_do_not_write_the_copies_again(self):
        data = sidecar("Sonarr", "w-sonarr", 8989)
        copies.write(111, data)
        with mock.patch.object(copies, "write_container") as again:
            data["apps"][0]["state"] = {"latest_version": "2.0"}
            copies.write(111, data)
            again.assert_not_called()
            data["apps"][0]["ports"] = [{"port": 9999}]
            copies.write(111, data)
            again.assert_called_once()

    def test_removing_takes_both_copies(self):
        copies.write(111, sidecar("Sonarr", "w-sonarr", 8989))
        copies.remove(111)
        self.assertIsNone(copies.read_container(111))
        self.assertIsNone(copies.read_cluster(111))


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.ct = Container(self)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.apps = Path(temp.name) / "apps"
        self.apps.mkdir()
        self.events = []

        def validate(payload, *, vmid=None):
            if payload.get("name") == "invalid":
                return False, "invalid app"
            if str(payload.get("logo_url", "")).startswith("/api/vms/") and f"/api/vms/{vmid}/" not in payload["logo_url"]:
                return False, "logo of another container"
            return True, dict(payload)

        access_log = mock.Mock()
        access_log.record = lambda *args, **kwargs: self.events.append(args)
        for name, value in (("_APPS_DIR", str(self.apps)), ("validate_config", validate)):
            patcher = mock.patch.object(lxc_apps, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(lxc_apps.local_app_icons, "protect_references", lambda *a: contextlib.nullcontext())
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.dict(sys.modules, {"access_log": access_log})
        patcher.start()
        self.addCleanup(patcher.stop)
        lxc_apps._sidecar_cache.clear()

    def local(self, data):
        lxc_apps._write_sidecar(111, data)

    def read(self):
        lxc_apps._sidecar_cache.clear()
        return lxc_apps._read_sidecar(111)

    def test_a_container_restored_in_another_order_gets_its_own_apps(self):
        # CT 111 holds Sonarr now, but the node still has Bazarr for 111.
        self.ct.running = False
        self.local(sidecar("Bazarr", "w-bazarr", 6767))
        copies.write_container(111, copies.payload(111, sidecar("Sonarr", "w-sonarr", 8989)), pid=4242)
        self.ct.running = True
        self.assertEqual(lxc_apps.reconcile_copies(111), "adopted-container")
        record = self.read()
        self.assertEqual((record["watch_id"], record["apps"][0]["name"], record["apps"][0]["ports"]),
                         ("w-sonarr", "Sonarr", [{"port": 8989}]))
        self.assertEqual(self.events[0][:3], ("app_watch.adopted", None, "CT 111"))
        self.assertEqual(lxc_apps.reconcile_copies(111), None)  # nothing left to do

    def test_a_copy_that_does_not_validate_is_left_out(self):
        carried = sidecar("Sonarr", "w-sonarr", 8989)
        carried["apps"].append({"id": "../../etc", "name": "invalid"})
        carried["apps"].append({"id": "b2", "name": "Radarr", "logo_url": "/api/vms/110/apps/logo-cache/x.png"})
        copies.write_container(111, copies.payload(111, carried), pid=4242)
        lxc_apps.reconcile_copies(111)
        apps = self.read()["apps"]
        self.assertEqual([a["name"] for a in apps], ["Sonarr", "Radarr"])
        self.assertNotIn("logo_url", apps[1])

    def test_a_container_without_a_copy_and_another_machine_id_is_marked(self):
        self.ct.machine("1" * 32)
        self.local(sidecar("Bazarr", "w-bazarr", 6767, identity={"machine_id": "2" * 32}))
        copies.remove_container(111)
        self.assertEqual(lxc_apps.reconcile_copies(111), "mismatch")
        self.assertTrue(self.read()["registration_mismatch"])
        self.assertTrue(lxc_apps.get_active_apps()["111"][0]["registration_mismatch"])
        self.assertIsNone(copies.read_container(111))  # its wrong apps are not copied into it

    def test_a_registration_from_before_is_given_its_identity_and_copies(self):
        self.ct.machine("1" * 32)
        self.ct.running = False
        self.local(sidecar("Sonarr", "w-sonarr", 8989))
        self.ct.running = True
        self.assertEqual(lxc_apps.reconcile_copies(111), "copied")
        self.assertEqual(self.read()["identity"], {"machine_id": "1" * 32})
        self.assertEqual(copies.read_container(111)["watch_id"], "w-sonarr")

    def test_a_migrated_container_takes_the_cluster_copy_only_if_it_is_the_same(self):
        self.ct.machine("1" * 32)
        copies.write_cluster(111, copies.payload(111, sidecar("Sonarr", "w-sonarr", 8989,
                                                              identity={"machine_id": "1" * 32})))
        for running, machine, expected in ((False, "1" * 32, None), (True, "3" * 32, None),
                                           (True, "1" * 32, "adopted-cluster")):
            with self.subTest(running=running, machine=machine):
                self.ct.running = running
                self.ct.machine(machine)
                self.assertEqual(lxc_apps.reconcile_copies(111), expected)
        self.assertEqual(self.read()["apps"][0]["name"], "Sonarr")


if __name__ == "__main__":
    unittest.main()
