"""Removing an OCI application leaves nothing of it on the host, and nothing another guest still uses is touched."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_remove
import oci_runtime_settings as runtime_settings

HOOK = """#!/usr/bin/env bash
inside=/data/mounts/drive
published={shared}/rw/drive
published_ro={shared}/ro/drive
"""


class RemovalCleanupTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.nodes = self.root / "nodes"
        (self.nodes / "amd/lxc").mkdir(parents=True)
        (self.nodes / "pve2/lxc").mkdir(parents=True)
        self.snippets = self.root / "snippets"
        self.snippets.mkdir()
        self.apps = self.root / "apps"
        self.apps.mkdir()
        self.records = self.root / "cluster-records"
        self.records.mkdir()
        self.cluster = self.root / "proxmenux"
        self.cluster.mkdir()
        self.legacy = self.root / "legacy"
        self.legacy.mkdir()
        self.host_monitor = (self.cluster / "host-monitor", self.legacy / "proxmenux-host-monitor")
        patches = [
            patch.object(oci_remove, "CLUSTER_NODES", self.nodes),
            patch.object(oci_remove, "SNIPPETS", self.snippets),
            patch.object(oci_remove, "MONITOR_APPS", self.apps),
            patch.object(oci_remove, "CLUSTER_RECORDS", self.records),
            patch.object(oci_remove, "HOST_MONITOR_INCLUDES", self.host_monitor),
            patch.object(runtime_settings, "include_path", lambda vmid: self.cluster / f"{vmid}.sysctls"),
            patch.object(runtime_settings, "legacy_include_path", lambda vmid: self.legacy / f"{vmid}.proxmenux-sysctls"),
            patch.object(oci_remove.subprocess, "run"),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_every_file_of_the_container_is_removed(self):
        (self.cluster / "113.sysctls").write_text("lxc.sysctl.net.ipv4.ip_unprivileged_port_start = 0\n")
        (self.legacy / "113.proxmenux-sysctls").write_text("x\n")
        shared = self.root / "shared"
        for view in ("rw/drive", "ro/drive"):
            (shared / view).mkdir(parents=True)
        (self.snippets / "proxmenux-rclone-113-fuse-hook.sh").write_text(HOOK.format(shared=shared))
        (self.apps / "113.json").write_text("{}")
        (self.apps / ".oci-dismissed.json").write_text(json.dumps({"113": "a", "112": "b"}))
        oci_remove.remove_host_state(113)
        self.assertFalse((self.cluster / "113.sysctls").exists())
        self.assertFalse((self.legacy / "113.proxmenux-sysctls").exists())
        self.assertFalse((self.snippets / "proxmenux-rclone-113-fuse-hook.sh").exists())
        self.assertFalse((shared / "rw/drive").exists() or (shared / "ro/drive").exists())
        self.assertFalse((self.apps / "113.json").exists())
        self.assertEqual(json.loads((self.apps / ".oci-dismissed.json").read_text()), {"112": "b"})

    def test_the_copy_of_the_record_in_the_cluster_goes_with_the_container(self):
        (self.records / "120.json").write_text("{}")
        (self.records / "121.json").write_text("{}")
        oci_remove.remove_host_state(120)
        self.assertEqual([path.name for path in self.records.iterdir()], ["121.json"])

    def test_a_published_view_with_content_is_kept(self):
        shared = self.root / "shared"
        (shared / "rw/drive").mkdir(parents=True)
        (shared / "rw/drive/file").write_text("data")
        (self.snippets / "proxmenux-rclone-113-fuse-hook.sh").write_text(HOOK.format(shared=shared))
        oci_remove.remove_host_state(113)
        self.assertTrue((shared / "rw/drive/file").exists())

    def test_other_containers_are_not_touched(self):
        (self.cluster / "114.sysctls").write_text("x\n")
        (self.apps / "114.json").write_text("{}")
        oci_remove.remove_host_state(113)
        self.assertTrue((self.cluster / "114.sysctls").exists() and (self.apps / "114.json").exists())

    def test_shared_host_monitor_include_is_kept_while_a_guest_uses_it(self):
        self.host_monitor[0].write_text("lxc.namespace.share.net = 1\n")
        (self.nodes / "pve2/lxc/120.conf").write_text(f"arch: amd64\nlxc.include: {self.host_monitor[0]}\n")
        oci_remove.release_shared_host_files([])
        self.assertTrue(self.host_monitor[0].exists())
        (self.nodes / "pve2/lxc/120.conf").unlink()
        oci_remove.release_shared_host_files([])
        self.assertFalse(self.host_monitor[0].exists())

    def test_stack_hookscript_is_removed_only_when_no_guest_uses_it(self):
        hook = self.snippets / "proxmenux-stack-dependencies.sh"
        hook.write_text("#!/bin/sh\n")
        volume = "local:snippets/proxmenux-stack-dependencies.sh"
        with patch.object(oci_remove.instances, "command", return_value=f"{hook}\n".encode()):
            (self.nodes / "amd/lxc/130.conf").write_text(f"hookscript: {volume}\n")
            oci_remove.release_shared_host_files([volume])
            self.assertTrue(hook.exists())
            (self.nodes / "amd/lxc/130.conf").unlink()
            oci_remove.release_shared_host_files([volume, "local:snippets/someone-else.sh"])
        self.assertFalse(hook.exists())

    def sweep(self, existing=()):
        registry = self.root / "instances"
        registry.mkdir(exist_ok=True)
        logs = self.root / "logs"
        logs.mkdir(exist_ok=True)
        with patch.object(oci_remove.oci_console, "LOG_DIR", logs), \
             patch.object(oci_remove.instances, "guest_exists", lambda vmid: vmid in existing), \
             patch.object(oci_remove.instances, "has_contract", lambda root, vmid: (root / str(vmid) / "oci-compose.json").exists()), \
             patch.object(oci_remove.instances, "release_orphan", self.retire):
            return oci_remove.sweep_orphans(registry), registry, logs

    def retire(self, root, vmid):
        record = root / str(vmid) / "oci-compose.json"
        if json.loads(record.read_text()).get("pending_transaction"):
            return False
        record.replace(record.with_name("retired-x.json"))
        return True

    def test_sweep_removes_what_is_left_of_containers_that_no_longer_exist(self):
        registry = self.root / "instances"
        (registry / "151").mkdir(parents=True)
        (registry / "151/oci-compose.json").write_text("{}")
        (self.legacy / "9901.proxmenux-sysctls").write_text("x\n")
        (self.cluster / "100.sysctls").write_text("x\n")
        cleaned, registry, logs = self.sweep(existing={100})
        self.assertEqual(cleaned, [151, 9901])
        self.assertTrue((registry / "151/retired-x.json").exists())
        self.assertFalse((self.legacy / "9901.proxmenux-sysctls").exists())
        # A container that exists keeps everything.
        self.assertTrue((self.cluster / "100.sysctls").exists())
        # Nothing left: the next visit cleans and reports nothing.
        self.assertEqual(self.sweep(existing={100})[0], [])

    def test_sweep_finds_oci_registrations_of_the_app_tab_only(self):
        (self.apps / "113.json").write_text(json.dumps({"apps": [{"installed_via": "oci_image"}]}))
        (self.apps / "114.json").write_text(json.dumps({"apps": [{"installed_via": "dpkg"}]}))
        self.assertEqual(self.sweep()[0], [113])
        self.assertFalse((self.apps / "113.json").exists())
        self.assertTrue((self.apps / "114.json").exists())

    def test_sweep_keeps_an_operation_left_halfway(self):
        registry = self.root / "instances"
        (registry / "152").mkdir(parents=True)
        (registry / "152/oci-compose.json").write_text(json.dumps({"pending_transaction": "x"}))
        (self.cluster / "152.sysctls").write_text("x\n")
        self.assertEqual(self.sweep()[0], [])
        self.assertTrue((self.cluster / "152.sysctls").exists())

    def test_private_network_of_a_stack_and_of_an_arr_suite_application(self):
        stack = {"stack": {"deployment": {"network": {"private_bridge": "vmbr10", "private_subnet": "10.77.0.0/24"}}}}
        suite = {"deployment": {"network": {"bridge": "vmbr11", "ipv4": "10.77.1.31/24"}}}
        lan = {"deployment": {"network": {"bridge": "vmbr0", "ipv4": "192.168.0.40/24"}}}
        dhcp = {"deployment": {"network": {"bridge": "vmbr0", "ipv4": "dhcp"}}}
        self.assertEqual(oci_remove.private_bridge(stack), "vmbr10")
        self.assertEqual(oci_remove.private_bridge(suite), "vmbr11")
        self.assertIsNone(oci_remove.private_bridge(lan))
        self.assertIsNone(oci_remove.private_bridge(dhcp))

    def test_the_suite_network_is_kept_while_another_application_uses_it(self):
        (self.nodes / "amd/lxc/180.conf").write_text("net0: name=eth0,bridge=vmbr11,ip=10.77.1.30/24\n")
        (self.nodes / "amd/lxc/181.conf").write_text("net0: name=eth0,bridge=vmbr11,ip=10.77.1.31/24\n")
        with patch.object(oci_remove, "Path", lambda value: self.nodes if value == "/etc/pve/nodes" else Path(value)):
            self.assertTrue(oci_remove.bridge_in_use("vmbr11", {181}))
            self.assertFalse(oci_remove.bridge_in_use("vmbr11", {180, 181}))

    def test_a_container_on_another_node_is_found(self):
        (self.nodes / "pve2/lxc/113.conf").write_text("arch: amd64\n")
        self.assertEqual(oci_remove.guest_node(113), "pve2")
        self.assertIsNone(oci_remove.guest_node(114))


if __name__ == "__main__":
    unittest.main()
