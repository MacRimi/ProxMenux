"""A container restored from a backup is found, checked against what this
host has, and registered again only when its whole application can be."""

import copy
import ipaddress
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_carried_record as carried
import oci_instances as instances
import oci_restore_recovery as recovery

APP = "83e373f2-5ccc-4548-9b89-22d0956d1c77"
DB = "488ed3cb-1145-477a-b90f-c46777d69fb2"


def saved(identity, hostname, extra=""):
    return f"#<div>Tandoor</div>\n#<!-- proxmenux-instance={identity} -->\narch: amd64\nhostname: {hostname}\n{extra}"


def config(identity, extra=""):
    return (f"arch: amd64\ndescription: <!-- proxmenux-instance={identity} -->\nhostname: app\nmemory: 2048\n"
            f"rootfs: local-lvm:vm-119-disk-0,size=8G\nunprivileged: 1\n{extra}")


CONSOLE = ("lxc.console.logfile: /var/log/proxmenux/oci/{0}.console.log\n"
           "lxc.hook.pre-start: /bin/sh -c 'mkdir -p /var/log/proxmenux/oci; "
           "test -x /usr/local/share/proxmenux/oci/engine/remote/oci_console_mark.sh "
           "&& /usr/local/share/proxmenux/oci/engine/remote/oci_console_mark.sh {0}; exit 0'\n")


def record(vmid, identity, **extra):
    return {"schema_version": 1, "vmid": vmid, "installation_id": identity, "status": "installed",
            "template": {"catalog_ui": {"title": {"en_US": "Tandoor Recipes"}}},
            "deployment": {"vmid": vmid, "hostname": "app", "rootfs": {"storage": "local-lvm", "size_gb": 8}},
            "observed": {"config": config(identity), "config_sha256": "old", "api_config_sha256": "old",
                         "image": {"manifest_digest": "sha256:1"}, "archive_path": "/gone.tar",
                         "resolved_registry_digest": "sha256:1"}, **extra}


def entry(vmid, identity, value, text=None):
    return {"vmid": vmid, "installation_id": identity, "hostname": f"ct{vmid}", "problem": None,
            "config": text if text is not None else config(identity),
            "copy": {"schema_version": 1, "kind": carried.KIND, "node": "old", "vmid": vmid, "record": value}}


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def register(self, vmid, identity):
        with patch.object(instances, "private_directory", lambda path: path.mkdir(parents=True, exist_ok=True)):
            instances.write(instances.location(self.root, vmid), record(vmid, identity))

    def pending(self, guests):
        with patch.object(recovery, "local_guests", return_value=guests):
            return [row["vmid"] for row in recovery.pending(self.root)]

    def test_the_mark_is_read_from_the_saved_configuration(self):
        self.assertEqual(recovery.marker(saved(APP, "app")), APP)
        self.assertIsNone(recovery.marker("arch: amd64\nhostname: plain\n"))

    def test_a_marked_container_without_record_waits_for_recovery(self):
        guests = {119: saved(APP, "app"), 120: saved(DB, "db"), 100: "arch: amd64\nhostname: plain\n"}
        self.assertEqual(self.pending(guests), [119, 120])
        self.register(119, APP)
        self.assertEqual(self.pending(guests), [120])

    def test_the_record_of_another_installation_does_not_count(self):
        self.register(119, DB)
        self.assertEqual(self.pending({119: saved(APP, "app")}), [119])

    def test_a_container_that_carries_no_record_is_not_offered_again(self):
        guests = {119: saved(APP, "app"), 120: saved(DB, "db")}
        with patch.object(instances, "private_directory", lambda path: path.mkdir(parents=True, exist_ok=True)), \
                patch.object(recovery, "local_guests", return_value=guests):
            recovery.set_unrecoverable(self.root, [{"vmid": 119, "installation_id": APP}])
        self.assertEqual(self.pending(guests), [120])
        # Another installation restored on that ID is a new case.
        self.assertEqual(self.pending({119: saved(DB, "other")}), [119])

    def test_a_clone_of_a_registered_container_is_left_alone(self):
        self.register(119, APP)
        self.assertEqual(self.pending({119: saved(APP, "app"), 130: saved(APP, "copy")}), [])


class ApplicationTests(unittest.TestCase):
    def stack(self):
        database = record(120, DB, stack_member={"stack_id": APP, "primary_vmid": 119, "name": "database"})
        application = record(119, APP, stack_member={"stack_id": APP, "primary_vmid": 119, "name": "application"})
        application["stack"] = {"id": APP, "template": {"catalog_ui": {"title": {"en_US": "Tandoor Recipes"}}},
                                "members": [copy.deepcopy(application), copy.deepcopy(database)]}
        return application, database

    def plans(self, found, guests, known=None):
        with patch.object(recovery, "local_guests", return_value=guests), \
                patch.object(recovery, "registered_identities", return_value=known or {}):
            return recovery.applications(Path("/nonexistent"), found)

    def test_the_containers_of_one_application_are_recovered_together(self):
        application, database = self.stack()
        plans = self.plans([entry(120, DB, database), entry(119, APP, application)],
                           {119: saved(APP, "app"), 120: saved(DB, "db")})
        self.assertEqual(len(plans), 1)
        self.assertEqual((plans[0]["title"], plans[0]["primary"], plans[0]["blockers"]), ("Tandoor Recipes", 119, []))
        self.assertEqual([m["state"] for m in plans[0]["members"]], ["restored", "restored"])

    def test_an_application_with_a_container_missing_is_not_recovered(self):
        application, _ = self.stack()
        plans = self.plans([entry(119, APP, application)], {119: saved(APP, "app")})
        self.assertEqual(len(plans[0]["blockers"]), 1)
        self.assertIn("CT 120 (database)", plans[0]["blockers"][0])

    def test_containers_restored_with_other_ids_keep_their_application(self):
        application, database = self.stack()
        application["stack"]["deployment"] = {"base_vmid": 119, "services": [
            {"vmid": 119, "name": "application"},
            {"vmid": 120, "name": "database", "healthcheck": {"timeout_seconds": 120}}]}
        application["deployment"]["create_arguments"] = ["119", "local:vztmpl/app.tar"]
        application["observed"]["config"] = config(APP, CONSOLE.format(119))
        found = [entry(140, APP, application), entry(135, DB, database)]
        found[0]["copy"]["stack_contract"] = {"schema": 1, "dependencies": [
            {"vmid": 120, "label": "PostgreSQL", "healthcheck": {"type": "running", "timeout_seconds": 120}}]}
        plans = self.plans(found, {140: saved(APP, "app"), 135: saved(DB, "db")})
        plan = plans[0]
        self.assertEqual((plan["blockers"], plan["renumbered"], plan["primary"]), ([], {119: 140, 120: 135}, 140))
        self.assertEqual([m["vmid"] for m in plan["members"]], [140, 135])
        main, other = (e["copy"]["record"] for e in plan["restored"])
        self.assertEqual((main["vmid"], main["deployment"]["vmid"], main["stack_member"]["primary_vmid"]), (140, 140, 140))
        self.assertEqual((other["vmid"], other["stack_member"]["primary_vmid"]), (135, 140))
        self.assertEqual([m["vmid"] for m in main["stack"]["members"]], [140, 135])
        self.assertEqual(main["stack"]["deployment"]["base_vmid"], 140)
        services = main["stack"]["deployment"]["services"]
        self.assertEqual([s["vmid"] for s in services], [140, 135])
        # A number that is not an ID stays: 120 seconds is not CT 120.
        self.assertEqual(services[1]["healthcheck"]["timeout_seconds"], 120)
        contract = plan["restored"][0]["copy"]["stack_contract"]["dependencies"][0]
        self.assertEqual((contract["vmid"], contract["healthcheck"]["timeout_seconds"]), (135, 120))
        self.assertEqual(main["deployment"]["create_arguments"][0], "140")
        self.assertIn("/var/log/proxmenux/oci/140.console.log", main["observed"]["config"])
        self.assertIn("oci_console_mark.sh 140; exit 0", main["observed"]["config"])
        self.assertNotIn("119", main["observed"]["config"].replace("vm-119-disk", ""))
        self.assertEqual(plan["restored"][0]["recorded"], 119)

    def test_the_lines_of_a_configuration_that_carry_the_id(self):
        text = config(APP, CONSOLE.format(119) + "lxc.include: /etc/pve/proxmenux/119.sysctls\nmemory: 119\n")
        result = recovery.renumbered_lines(text, 119, 140)
        self.assertIn("lxc.console.logfile: /var/log/proxmenux/oci/140.console.log\n", result)
        self.assertIn("oci_console_mark.sh 140; exit 0'\n", result)
        self.assertIn("lxc.include: /etc/pve/proxmenux/140.sysctls\n", result)
        # Proxmox renames the volumes; anything else that happens to read 119 stays.
        self.assertIn("rootfs: local-lvm:vm-119-disk-0,size=8G\n", result)
        self.assertIn("memory: 119\n", result)
        self.assertTrue(result.endswith("\n"))
        legacy = recovery.renumbered_lines("lxc.include: /etc/pve/lxc/119.proxmenux-sysctls\n", 119, 140)
        self.assertEqual(legacy, "lxc.include: /etc/pve/proxmenux/140.sysctls\n")

    def test_a_container_without_its_copy_stops_the_recovery(self):
        broken = dict(entry(119, APP, record(119, APP)), copy=None, problem="no copy")
        plans = self.plans([broken], {119: saved(APP, "app")})
        self.assertEqual(plans[0]["blockers"], ["CT 119: no copy"])


class NetworkTests(unittest.TestCase):
    def check(self, text, links=("lo", "vmbr0"), addresses=None, routes=(), defined=None, guests=None):
        plan = {"restored": [entry(119, APP, record(119, APP), text)], "members": [{"vmid": 119}],
                "blockers": [], "notes": [], "bridges": {}}
        with patch.object(recovery, "links", return_value=set(links)), \
                patch.object(recovery, "host_addresses", return_value=addresses or {}), \
                patch.object(recovery, "routed_networks", return_value=list(routes)), \
                patch.object(recovery, "defined_network", return_value=defined), \
                patch.object(recovery, "local_guests", return_value=guests or {}):
            recovery.check_networks(plan)
        return plan

    PRIVATE = config(APP, "net0: name=eth0,bridge=vmbr0,ip=dhcp\nnet1: name=eth1,bridge=vmbr11,ip=10.77.1.40/24\n")

    def test_a_missing_private_network_is_created_with_the_same_subnet(self):
        plan = self.check(self.PRIVATE)
        self.assertEqual(plan["blockers"], [])
        self.assertEqual(plan["bridges"], {"vmbr11": ipaddress.ip_network("10.77.1.0/24")})

    def test_a_private_network_already_here_is_left_as_it_is(self):
        plan = self.check(self.PRIVATE, links=("vmbr0", "vmbr11"),
                          addresses={"vmbr11": [ipaddress.ip_interface("10.77.1.1/24")]})
        self.assertEqual((plan["blockers"], plan["bridges"]), ([], {}))

    def test_the_subnet_in_use_on_this_host_cancels_the_recovery(self):
        plan = self.check(self.PRIVATE, links=("vmbr0", "vmbr20"),
                          addresses={"vmbr20": [ipaddress.ip_interface("10.77.1.1/24")]})
        self.assertEqual(len(plan["blockers"]), 1)
        self.assertIn("10.77.1.0/24", plan["blockers"][0])
        routed = self.check(self.PRIVATE, routes=[("vmbr0", ipaddress.ip_network("10.0.0.0/8"))])
        self.assertEqual(len(routed["blockers"]), 1)

    def test_the_bridge_name_used_for_another_network_cancels_the_recovery(self):
        plan = self.check(self.PRIVATE, links=("vmbr0", "vmbr11"),
                          addresses={"vmbr11": [ipaddress.ip_interface("192.168.5.1/24")]})
        self.assertEqual(len(plan["blockers"]), 1)
        defined = self.check(self.PRIVATE, defined=ipaddress.ip_network("192.168.5.0/24"))
        self.assertEqual(len(defined["blockers"]), 1)

    def test_an_address_taken_by_another_container_cancels_the_recovery(self):
        plan = self.check(self.PRIVATE, guests={200: "net0: name=eth0,bridge=vmbr30,ip=10.77.1.40/24\n"})
        self.assertTrue(any("10.77.1.40" in line for line in plan["blockers"]))

    def test_a_missing_bridge_of_the_local_network_is_not_invented(self):
        plan = self.check(config(APP, "net0: name=eth0,bridge=vmbr5,ip=dhcp\n"))
        self.assertEqual(len(plan["blockers"]), 1)
        self.assertEqual(plan["bridges"], {})


class RecordTests(unittest.TestCase):
    def test_what_a_restore_changes(self):
        related = recovery.restore_related
        self.assertTrue(related("rootfs", "local-lvm:vm-119-disk-0,size=8G", "tank:subvol-119-disk-0,size=8G"))
        self.assertTrue(related("mp0", "local-lvm:vm-119-disk-1,mp=/data,backup=1,size=2G",
                                "tank:subvol-119-disk-1,mp=/data,backup=1,size=2G"))
        self.assertFalse(related("mp0", "local-lvm:vm-119-disk-1,mp=/data,backup=1,size=2G",
                                 "local-lvm:vm-119-disk-1,mp=/other,backup=1,size=2G"))
        self.assertFalse(related("mp0", "/srv/a,mp=/data", "/srv/b,mp=/data"))
        self.assertTrue(related("net0", "name=eth0,bridge=vmbr0,hwaddr=AA:AA,ip=dhcp", "name=eth0,bridge=vmbr0,hwaddr=BB:BB,ip=dhcp"))
        self.assertFalse(related("net0", "name=eth0,bridge=vmbr0,ip=dhcp", "name=eth0,bridge=vmbr1,ip=dhcp"))
        self.assertTrue(related("hookscript", "local:snippets/a.sh", "nas:snippets/a.sh"))
        self.assertTrue(related("dev0", "path=/dev/dri/renderD128", None))
        self.assertTrue(related("mp1", "/srv/media,mp=/media", None))
        self.assertFalse(related("mp1", "local-lvm:vm-119-disk-1,mp=/data,backup=1,size=2G", None))
        self.assertFalse(related("memory", "2048", "4096"))
        self.assertFalse(related("mp2", None, "/etc,mp=/host"))

    def standalone(self, text, value=None):
        value = value or record(119, APP)
        observed = {"config": text, "config_sha256": "new", "api_config_sha256": "new"}
        with patch.object(instances, "observe", return_value=observed) as observe, \
                patch.object(recovery, "capture_sources", return_value={}), \
                patch.object(recovery, "capture_gpu_devices", return_value={}):
            return recovery.standalone_record(entry(119, APP, value, text)), observe

    def test_volumes_on_another_storage_become_the_reference(self):
        text = config(APP).replace("local-lvm:vm-119-disk-0", "tank:subvol-119-disk-0")
        result, observe = self.standalone(text)
        observe.assert_called_once()
        self.assertEqual(result["observed"]["config"], text)
        self.assertEqual(result["deployment"]["rootfs"]["storage"], "tank")

    def test_a_change_made_outside_stays_a_difference(self):
        text = config(APP).replace("local-lvm:vm-119-disk-0", "tank:subvol-119-disk-0").replace("memory: 2048", "memory: 4096")
        result, observe = self.standalone(text)
        observe.assert_not_called()
        self.assertIn("memory: 2048", result["observed"]["config"])
        self.assertIn("rootfs: tank:subvol-119-disk-0,size=8G", result["observed"]["config"])
        self.assertNotIn("api_config_sha256", result["observed"])
        self.assertEqual(result["deployment"]["rootfs"]["storage"], "tank")

    def test_a_single_container_restored_with_another_id_is_registered_under_it(self):
        value = record(119, APP)
        value["observed"]["config"] = config(APP, CONSOLE.format(119))
        found = entry(141, APP, value, config(APP, CONSOLE.format(141)).replace("vm-119-disk-0", "vm-141-disk-0"))
        with patch.object(recovery, "local_guests", return_value={141: saved(APP, "app")}), \
                patch.object(recovery, "registered_identities", return_value={}):
            plan = recovery.applications(Path("/nonexistent"), [found])[0]
        self.assertEqual((plan["blockers"], plan["renumbered"]), ([], {119: 141}))
        observed = {"config": found["config"], "config_sha256": "new"}
        with patch.object(instances, "observe", return_value=observed) as observe:
            result = recovery.standalone_record(plan["restored"][0])
        observe.assert_called_once()
        self.assertEqual((result["vmid"], result["deployment"]["vmid"]), (141, 141))

    def test_the_copy_cannot_add_a_host_directory_or_a_device(self):
        value = record(119, APP)
        value["deployment"]["mounts"] = [
            {"type": "host-bind", "source": "/etc", "container_path": "/host"},
            {"type": "host-bind", "source": "/srv/media", "container_path": "/media"},
            {"type": "managed-volume", "source": "local-lvm", "container_path": "/data"}]
        value["deployment"]["devices"] = [{"kind": "character-device", "host_path": "/dev/kvm"},
                                          {"kind": "character-device", "host_path": "/dev/dri/renderD128"}]
        extra = "mp0: /srv/media,mp=/media,backup=0\nmp1: tank:subvol-119-disk-1,mp=/data,backup=1,size=2G\ndev0: path=/dev/dri/renderD128,gid=104\n"
        value["observed"]["config"] = config(APP, extra.replace("tank:subvol", "local-lvm:vm"))
        result, _ = self.standalone(config(APP, extra), value)
        self.assertEqual([m["source"] for m in result["deployment"]["mounts"]], ["/srv/media", "tank"])
        self.assertEqual([d["host_path"] for d in result["deployment"]["devices"]], ["/dev/dri/renderD128"])

    def test_the_start_order_must_name_containers_of_the_application(self):
        contract = {"schema": 1, "stack": "tandoor", "dependencies": [
            {"vmid": 120, "label": "PostgreSQL",
             "healthcheck": {"type": "exec", "timeout_seconds": 120, "argv": ["pg_isready"]}}]}
        self.assertTrue(recovery.valid_contract(contract, {120}))
        self.assertFalse(recovery.valid_contract(contract, {121}))
        self.assertFalse(recovery.valid_contract(None, {120}))
        http = copy.deepcopy(contract)
        http["dependencies"][0]["healthcheck"] = {"type": "http", "timeout_seconds": 60, "url": "http://10.77.1.41:8080/health"}
        self.assertTrue(recovery.valid_contract(http, {120}))
        http["dependencies"][0]["healthcheck"]["url"] = "http://192.168.0.1/admin"
        self.assertFalse(recovery.valid_contract(http, {120}))


class RcloneMountTests(unittest.TestCase):
    MOUNT = {"mount_name": "drive", "shared_mount_root": "/mnt/oci-shared/remotes",
             "shared_mount_read_only_root": "/mnt/oci-shared/remotes-ro", "shared_mount_root_parent": "/mnt/oci-shared"}

    def test_a_mount_inside_its_common_root_is_published_again(self):
        self.assertEqual(recovery.rclone_mount(dict(self.MOUNT, extra="ignored")), self.MOUNT)

    def test_a_mount_the_host_cannot_publish_safely_is_left_to_the_user(self):
        for change in ({"mount_name": "../etc"}, {"mount_name": "a b"}, {"shared_mount_root": "/srv/other"},
                       {"shared_mount_root_parent": "/etc", "shared_mount_root": "/etc/remotes",
                        "shared_mount_read_only_root": "/etc/remotes-ro"},
                       {"shared_mount_root": "/mnt/oci-shared/../../etc"}, {"shared_mount_root_parent": "/"},
                       {"shared_mount_read_only_root": 5}):
            self.assertIsNone(recovery.rclone_mount({**self.MOUNT, **change}), change)
        self.assertIsNone(recovery.rclone_mount(None))

    def test_the_hookscript_of_the_mount_follows_the_new_id(self):
        text = "hookscript: local:snippets/proxmenux-rclone-119-fuse-hook.sh\nmemory: 119\n"
        self.assertEqual(recovery.renumbered_lines(text, 119, 143),
                         "hookscript: local:snippets/proxmenux-rclone-143-fuse-hook.sh\nmemory: 119\n")
        other = "hookscript: local:snippets/proxmenux-stack-dependencies.sh\n"
        self.assertEqual(recovery.renumbered_lines(other, 119, 143), other)

    def test_the_parameters_are_read_from_the_hookscript_of_the_host(self):
        hook = ("inside=/data/mounts/drive\npublished=/mnt/oci-shared/remotes/drive\n"
                "published_ro=/mnt/oci-shared/remotes-ro/drive\n    if ! mountpoint -q /mnt/oci-shared; then\n")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "proxmenux-rclone-119-fuse-hook.sh").write_text(hook)
        config = "arch: amd64\nhookscript: local:snippets/proxmenux-rclone-119-fuse-hook.sh\n"
        with patch.object(carried, "SNIPPETS", Path(tmp.name)):
            self.assertEqual(carried.rclone_mount(config), self.MOUNT)
            self.assertIsNone(carried.rclone_mount("arch: amd64\n"))
            self.assertIsNone(carried.rclone_mount(config.replace("119", "120")))


class NvidiaStaticTests(unittest.TestCase):
    """A privileged container names every file of the NVIDIA driver of its host."""

    @staticmethod
    def inventory(version, uuid):
        library = f"/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.{version}"
        return {"gpus": [f"Quadro P1000, {uuid}, {version}"], "toolkit_version": ["cli-version: 1", "lib-version: 1"],
                "devices": {"/dev/nvidia0": {"source": "/dev/nvidia0", "uid": 0, "gid": 0, "mode": 0o666,
                                             "major": 195, "minor": 0}},
                "files": {library: {"source": library, "uid": 0, "gid": 0, "mode": 0o644, "size": 1, "sha256": "x"}},
                "links": {}}

    def test_the_driver_files_are_named_again_for_the_host_the_container_is_on(self):
        import oci_nvidia_runtime as runtime
        old, new = self.inventory("550.1", "GPU-aaa"), self.inventory("560.2", "GPU-aaa")
        text = ("arch: amd64\ndev0: path=/dev/nvidia0,mode=0666,gid=0,deny-write=0\n"
                "lxc.mount.entry: /usr/lib/x86_64-linux-gnu/libnvidia-ml.so.550.1 "
                "usr/lib/x86_64-linux-gnu/libnvidia-ml.so.550.1 none ro,bind,create=file 0 0\n").encode()
        plan = runtime.refresh_plan(text, old, new)
        self.assertTrue(plan["changed"])
        self.assertIn(b"libnvidia-ml.so.560.2 usr/lib/x86_64-linux-gnu/libnvidia-ml.so.560.2", plan["config"])
        self.assertNotIn(b"550.1", plan["config"])
        other = self.inventory("560.2", "GPU-bbb")
        with self.assertRaises(ValueError):
            runtime.refresh_plan(text, old, other)
        self.assertTrue(runtime.refresh_plan(text, old, other, same_gpu=False)["changed"])
        self.assertFalse(runtime.refresh_plan(text, old, old)["changed"])


class ReturnedContainerTests(unittest.TestCase):
    """A container that came back from another node, an older backup or a
    snapshot carries the record that describes it."""

    def copy(self, value, generation):
        return {"schema_version": 1, "kind": carried.KIND, "node": "other", "vmid": 119,
                "generation": generation, "record": value}

    def test_a_copy_this_host_did_not_write_with_another_record_wins(self):
        host, older = record(119, APP), record(119, APP)
        older["deployment"]["hostname"] = "before-the-update"
        stamp = {"digest": "x", "generation": "ours"}
        self.assertTrue(carried.superseded(host, self.copy(older, "theirs"), stamp))
        # Written by this host: the record changed here afterwards.
        self.assertFalse(carried.superseded(host, self.copy(older, "ours"), stamp))
        # Came back without changes: the same record.
        self.assertFalse(carried.superseded(host, self.copy(record(119, APP), "theirs"), stamp))
        # Nothing was written by this host yet, or the copy is of another installation.
        self.assertFalse(carried.superseded(host, self.copy(older, "theirs"), {}))
        self.assertFalse(carried.superseded(host, self.copy(record(119, DB), "theirs"), stamp))

    def test_the_mark_of_the_last_copy_is_kept_on_the_host(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / carried.STAMP
        self.assertEqual(carried.read_stamp(path), {})
        path.write_text("abc\n")
        self.assertEqual(carried.read_stamp(path), {"digest": "abc"})
        path.write_text('{"digest": "abc", "generation": "g1"}\n')
        self.assertEqual(carried.read_stamp(path), {"digest": "abc", "generation": "g1"})


class ClusterCopyTests(unittest.TestCase):
    """Every node of a cluster reads the copy kept in /etc/pve."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        patcher = patch.object(carried, "CLUSTER", self.root / "cluster")
        patcher.start()
        self.addCleanup(patcher.stop)

    def copy(self, value, generation="g1", node="pve1", saved_at="2026-10-03T10:00:00+00:00"):
        return {"schema_version": 1, "kind": carried.KIND, "node": node, "vmid": value["vmid"],
                "generation": generation, "saved_at": saved_at, "record": value}

    def test_the_copy_is_written_and_read_back(self):
        self.assertIsNone(carried.read_cluster(119))
        self.assertTrue(carried.write_cluster(119, self.copy(record(119, APP))))
        self.assertEqual(carried.read_cluster(119)["record"]["installation_id"], APP)
        (carried.CLUSTER / "120.json").write_text("not json")
        self.assertIsNone(carried.read_cluster(120))
        carried.remove_cluster(119)
        self.assertIsNone(carried.read_cluster(119))

    def test_it_follows_the_copy_the_container_carries(self):
        value = self.copy(record(119, APP))
        carried.keep_cluster(119, value, "g1")
        written = (carried.CLUSTER / "119.json").stat().st_mtime_ns
        carried.keep_cluster(119, value, "g1")
        self.assertEqual((carried.CLUSTER / "119.json").stat().st_mtime_ns, written)
        carried.keep_cluster(119, value, "g2")
        self.assertEqual(carried.read_cluster(119)["generation"], "g2")

    def test_a_record_changed_on_another_node_replaces_the_one_of_this_host(self):
        path = self.root / "oci-compose.json"
        path.write_text("{}")
        os.utime(path, (1_000_000_000, 1_000_000_000))
        host, changed = record(119, APP), record(119, APP)
        changed["deployment"]["hostname"] = "updated-on-the-other-node"
        self.assertTrue(carried.replaced_elsewhere(host, path, self.copy(changed, node="pve2"), "pve1"))
        # Written by this node, the same record, another installation or an older copy.
        self.assertFalse(carried.replaced_elsewhere(host, path, self.copy(changed, node="pve1"), "pve1"))
        self.assertFalse(carried.replaced_elsewhere(host, path, self.copy(record(119, APP), node="pve2"), "pve1"))
        self.assertFalse(carried.replaced_elsewhere(host, path, self.copy(record(119, DB), node="pve2"), "pve1"))
        old = self.copy(changed, node="pve2", saved_at="1999-01-01T00:00:00+00:00")
        self.assertFalse(carried.replaced_elsewhere(host, path, old, "pve1"))
        self.assertFalse(carried.replaced_elsewhere(host, path, None, "pve1"))

    def examine(self, inside, shared):
        if shared is not None:
            carried.write_cluster(119, shared)
        done = type("Done", (), {"returncode": 0, "stdout": config(APP)})()

        class Root:
            def __enter__(self): return Path("/rootfs")
            def __exit__(self, *_): return False

        with patch.object(recovery, "run", return_value=done), \
                patch.object(carried, "container_root", return_value=Root()), \
                patch.object(carried, "read_copy", return_value=inside):
            return recovery.examine({"vmid": 119, "installation_id": APP, "hostname": "app"})

    def test_the_same_copy_in_the_cluster_is_taken_without_asking(self):
        value = self.copy(record(119, APP), "g1")
        result = self.examine(dict(value), value)
        self.assertTrue(result["trusted"])
        self.assertIsNone(result["problem"])

    def test_a_container_of_another_moment_is_described_by_its_own_copy(self):
        older = record(119, APP)
        older["deployment"]["hostname"] = "before"
        result = self.examine(self.copy(older, "g0"), self.copy(record(119, APP), "g1"))
        self.assertFalse(result["trusted"])
        self.assertEqual(result["copy"]["record"]["deployment"]["hostname"], "before")

    def test_a_container_without_its_copy_takes_the_one_of_the_cluster_and_asks(self):
        result = self.examine(None, self.copy(record(119, APP), "g1"))
        self.assertFalse(result["trusted"])
        self.assertIsNone(result["problem"])
        self.assertIsNotNone(result["copy"])
        carried.remove_cluster(119)
        nothing = self.examine(None, None)
        self.assertTrue(nothing["unrecoverable"])

    def test_the_copy_of_another_installation_is_not_used(self):
        carried.remove_cluster(119)
        result = self.examine(self.copy(record(119, APP), "g1"), self.copy(record(119, DB), "g1"))
        self.assertFalse(result["trusted"])
        self.assertEqual(result["copy"]["record"]["installation_id"], APP)

    def test_only_what_needs_no_question_is_registered_on_its_own(self):
        def plan(**extra):
            item = dict(entry(119, APP, record(119, APP)), trusted=True)
            item.update(extra.pop("entry", {}))
            return {"blockers": [], "bridges": {}, "renumbered": {}, "hold": False, "restored": [item], **extra}
        self.assertTrue(recovery.automatic(plan()))
        self.assertFalse(recovery.automatic(plan(entry={"trusted": False})))
        self.assertFalse(recovery.automatic(plan(bridges={"vmbr11": "10.77.1.0/24"})))
        self.assertFalse(recovery.automatic(plan(blockers=["missing"])))
        self.assertFalse(recovery.automatic(plan(renumbered={119: 140})))
        self.assertFalse(recovery.automatic(plan(entry={"firewall": {"port": 19999}})))
        self.assertFalse(recovery.automatic(plan(entry={"contract": {"schema": 1}})))


class RegistrationTests(unittest.TestCase):
    def test_no_record_is_left_when_the_application_cannot_be_registered_whole(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        database = record(120, DB, stack_member={"stack_id": APP, "primary_vmid": 119, "name": "database"})
        application = record(119, APP, stack_member={"stack_id": APP, "primary_vmid": 119, "name": "application"})
        plan = {"restored": [entry(119, APP, application), entry(120, DB, database)]}

        def refuse(_root, vmid):
            if vmid == 120:
                raise ValueError("cannot be updated")

        with patch.object(instances, "private_directory", lambda path: path.mkdir(parents=True, exist_ok=True)), \
                patch.object(recovery.oci_stack_modify, "register", side_effect=refuse):
            with self.assertRaises(ValueError):
                recovery.register(root, plan)
        self.assertFalse(instances.location(root, 119).exists())
        self.assertFalse(instances.location(root, 120).exists())


    def test_the_plan_each_container_was_installed_with_is_left_as_it_is_now(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        database = record(150, DB, stack_member={"stack_id": APP, "primary_vmid": 151, "name": "database"})
        database["deployment"]["mounts"] = [{"source": "local-lvm:vm-150-disk-1"}]
        application = record(151, APP, stack_member={"stack_id": APP, "primary_vmid": 151, "name": "application"})
        application["stack"] = {"id": APP, "members": [], "deployment": {"services": [
            {"name": "database", "vmid": 150, "deployment": {"mounts": [{"source": "local-lvm:vm-120-disk-1"}]}},
            {"name": "application", "vmid": 151, "deployment": {"create_arguments": ["119"]}},
            {"name": "check", "vmid": 150, "healthcheck": {"type": "running"}}]}}
        with patch.object(instances, "private_directory", lambda path: path.mkdir(parents=True, exist_ok=True)):
            instances.write(instances.location(root, 150), database)
            instances.write(instances.location(root, 151), application)
            recovery.refresh_service_plans(root, [151, 150])
        services = instances.read(root, 151)["stack"]["deployment"]["services"]
        self.assertEqual(services[0]["deployment"]["mounts"], [{"source": "local-lvm:vm-150-disk-1"}])
        self.assertEqual(services[1]["deployment"], application["deployment"])
        self.assertNotIn("deployment", services[2])


class FirewallConsentTests(unittest.TestCase):
    """A host firewall rule is added only for the container it was confirmed for."""

    def recover(self, confirmed):
        rule = lambda vmid, port: {"vmid": vmid, "port": port, "source": "192.0.2.0/24"}
        plan = {"bridges": {}, "renumbered": {}, "hold": False, "notes": [],
                "restored": [{"vmid": 120, "firewall": rule(120, 61208)}, {"vmid": 121, "firewall": rule(121, 19999)}]}
        added = []
        with patch.object(recovery, "restore_host_files"), patch.object(recovery, "clean_format_directories"), \
                patch.object(recovery, "register", return_value=[120, 121]), patch.object(recovery.carried, "carry"), \
                patch.object(recovery, "add_firewall_rule", side_effect=lambda rule: added.append(rule["vmid"]) or True), \
                patch.object(recovery, "msg_info"), patch.object(recovery, "msg_ok"):
            recovery.recover(Path("/nonexistent"), plan, host_firewall=confirmed)
        return added, plan["notes"]

    def test_one_confirmed_rule_does_not_add_the_others(self):
        added, notes = self.recover([121])
        self.assertEqual(added, [121])
        self.assertEqual([note[:7] for note in notes], ["CT 120:"])

    def test_without_an_answer_no_rule_is_added(self):
        added, notes = self.recover([])
        self.assertEqual(added, [])
        self.assertEqual(len(notes), 2)

    def test_the_menu_asks_for_each_rule_and_passes_only_the_confirmed_ones(self):
        sys.path.insert(0, str(ROOT / "src"))
        from proxmenux_oci import management
        rules = [{"vmid": 120, "port": 61208, "source": "192.0.2.0/24"},
                 {"vmid": 121, "port": 19999, "source": "192.0.2.0/24"}]
        answers = iter([True, False, True, False])  # recover, rule of 120, rule of 121, start

        class Ui:
            asked = []

            def confirm(self, text, default=False):
                self.asked.append(text)
                return next(answers)

        ui = Ui()
        with patch.object(management, "restored_applications", return_value=[{"vmid": 120, "hostname": "glances"},
                                                                             {"vmid": 121, "hostname": "netdata"}]), \
                patch.object(management, "_restored_firewall_rules", return_value=rules), \
                patch.object(management, "_run_lifecycle") as run:
            management.offer_recovery(ROOT, ui)
        command = run.call_args[0][0]
        self.assertEqual(len(ui.asked), 4)
        self.assertEqual(command[command.index("--host-firewall"):], ["--host-firewall", "121"])


if __name__ == "__main__":
    unittest.main()
