"""Simulate the native PVE replies at the transport boundary, with no host writes."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from copy import deepcopy
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
LXC = ROOT / "scripts/lxc"
sys.path.insert(0, str(LXC))
from plain_lxc import Operations, execute
from plain_lxc_pve import Proxmox
from plain_lxc_spec import GIB, LxcError, digest, strict_json

sys.path.remove(str(LXC))

WIZARD_SPEC = importlib.util.spec_from_file_location("plain_lxc_wizard", ROOT / "scripts/menus/plain_lxc_wizard.py")
wizard = importlib.util.module_from_spec(WIZARD_SPEC)
WIZARD_SPEC.loader.exec_module(wizard)

NAME = "debian-13-standard_13.1-2_amd64.tar.zst"
VOLUME = f"local:vztmpl/{NAME}"
NODE = "pve-test"
VMID = 240
BASE = f"/nodes/{NODE}"
PASSWORD = "simulated-input-!7"
REQUEST_ID = "1" * 32
NATIVE_EXPECTED = {'hostname': 'test-lxc', 'features': 'nesting=0', 'cores': 1,
                   'memory': 512, 'swap': 512, 'onboot': 0, 'storage': 'local-lvm', 'storage_type': 'lvmthin', 'net0': None}
ARCHIVE = b"simulated official archive"
CHECKSUM = hashlib.sha512(ARCHIVE).hexdigest()


def upid(kind, identity):
    return f"UPID:{NODE}:00001234:000000001:12345678:{kind}:{identity}:root@pam:"


def body(action, **payload):
    return {"schema_version": 1, "action": action, **payload}


class FakePVE(Proxmox):
    def __init__(self, directory):
        super().__init__()
        self.file = directory / NAME
        self.file.write_bytes(ARCHIVE)
        self.calls = []
        self.writes = []
        self.catalog = {
            "template": NAME, "section": "system", "type": "lxc", "architecture": "amd64",
            "source": "http://download.proxmox.com/images",
            "location": f"http://download.proxmox.com/images/system/{NAME}", "sha512sum": CHECKSUM,
        }
        self.storage = [
            {"storage": "local", "state": "available", "content": ["vztmpl"], "type": "dir", "avail": 50 * GIB},
            {"storage": "local-lvm", "state": "available", "content": ["rootdir"],
             "type": "lvmthin", "avail": 100 * GIB},
        ]
        self.network = [{"type": "bridge", "iface": "vmbr0", "active": 1, "bridge_vlan_aware": 1}]
        self.bridge_vlans = {"vmbr0": True}
        self.guests = []
        self.config = {}
        self.tasks = {}
        self.logs = {}
        self.present = True
        self.catalog_error = False
        self.nextid_error = False
        self.task_error = False
        self.create_exit = "OK"
        self.start_exit = "OK"
        self.prepare_exit = "OK"
        self.boot_attempts = 0
        self.task_running = False
        self.lost_reply = False
        self.missing_upid = False
        self.task_before_id = False
        self.reached_write = None
        self.finish_write = None
        self.prevent_marker = False
        self.capabilities = {'mount_points':16,'devices':16}
        self.hardware = {}

    def architecture(self):
        return "amd64"

    def hardware_inventory(self):
        return deepcopy(self.hardware)

    def device_assignments(self, paths, vmid):
        return {path:[] for path in paths}

    def run(self, command, body=None, timeout=12):
        self.calls.append(command)
        if command[0] == "/usr/bin/pvesh":
            assert command[1:3] == ["--noproxy", "get"] and command[4:6] == ["--output-format", "json"]
            data = self.get(command[3], dict(zip(command[6::2], command[7::2])))
        elif command[0] == "/usr/sbin/pvesm":
            assert command[1:] == ["path", VOLUME]
            if not self.present:
                raise LxcError("pve_unavailable")
            return os.fsencode(self.file) + b"\n"
        elif command[0] == "/usr/bin/sha512sum":
            assert command[1:] == ["--", str(self.file)]
            return super().run(command, timeout=timeout)
        else:
            assert command == ["/usr/bin/perl", str(LXC / "plain_lxc_pve.pl")]
            request = json.loads(body)
            assert request["node"] == NODE or request["action"] == "inspect"
            if request["action"] in ("inventory", "inspect"):
                assert request["params"].keys() <= {"vmid"}
                storages = deepcopy(self.storage)
                storages[0]["templates"] = [{"volid": VOLUME, "size": self.file.stat().st_size}] if self.present else []
                data = {"status": self.get(BASE + "/status", {}), "network": self.network,
                        'capabilities':self.capabilities,
                        "storages": storages, "bridge_vlans": self.bridge_vlans,
                        "catalog": None if self.catalog_error else self.get(BASE + "/aplinfo", {})}
                if "vmid" in request["params"]:
                    data.update(guests=self.guests, nextid=None if self.nextid_error else request["params"]["vmid"])
                if request["action"] == "inspect":
                    data = {"nodes": self.get("/cluster/status", {}), "inventory": data,
                            "nextid": None if self.nextid_error else VMID}
            else:
                data = self.mutate(request["action"], request["params"])
        return json.dumps(data).encode()

    def get(self, path, params):
        if path == "/cluster/status":
            return [{"type": "cluster", "quorate": 1}, {"type": "node", "name": NODE, "local": 1, "online": 1}]
        if path == "/cluster/nextid":
            return int(params.get("--vmid", VMID))
        if path == "/cluster/resources":
            assert params == {"--type": "vm"}
            return self.guests
        if path == BASE + "/status":
            return {"cpuinfo": {"cpus": 8}, "memory": {"total": 32 * GIB}}
        if path == BASE + "/network":
            return self.network
        if path == BASE + "/aplinfo":
            if self.catalog_error:
                raise LxcError("pve_unavailable")
            return [self.catalog] if self.catalog else []
        if path == BASE + f"/lxc/{VMID}/config":
            return self.config
        if path.startswith(BASE + "/tasks/"):
            if self.task_error:
                raise LxcError("pve_unavailable")
            _, _, _, _, task, resource = path.split("/")
            if resource == "log":
                offset, limit = int(params["--start"]), int(params["--limit"])
                return [{"n": index, "t": line} for index, line in
                        enumerate(self.logs[task][offset:offset + limit], offset + 1)]
            return self.tasks[task]
        raise AssertionError((path, params))

    def mutate(self, action, params):
        self.writes.append((action, params))
        if self.reached_write:
            self.reached_write.set()
            assert self.finish_write.wait(5)
        if action == "create":
            kind, identity, exit_status = "vzcreate", params["vmid"], self.create_exit
            if exit_status == "OK" or re.fullmatch(r"WARNINGS: [0-9]+", exit_status):
                self.guests.append({"type": "lxc", "vmid": params["vmid"], "node": NODE})
                if not self.prevent_marker:
                    # PVE::LXC::Config serializes description as comment lines;
                    # reading it back adds one final newline, including on PVE9.
                    self.config = {"description": params["description"] + "\n", "unprivileged": 1}
        elif action in ("start", "prepare"):
            assert self.config["description"] in (params["description"], params["description"] + "\n")
            assert set(params) == {'vmid', 'description', 'expected'}
            kind, identity, exit_status = ("vzstart" if action == "start" else "vzprepare"), params["vmid"], self.start_exit if action == "start" else self.prepare_exit
            if action == 'start' and not exit_status.startswith('ProxMenux preparation failed:'):
                self.boot_attempts += 1
        elif action == "download_template":
            assert params == {"storage": "local", "template": NAME, "architecture": "amd64", "sha512": CHECKSUM}
            kind, identity, exit_status = "download", params["template"], "OK"
            self.present = True
        else:
            raise AssertionError(action)
        task_id = upid(kind, identity)
        self.tasks[task_id] = {"upid": task_id, "status": "running"} if self.task_running else {
            "upid": task_id, "status": "stopped", "exitstatus": exit_status,
        }
        self.logs[task_id] = {
            "create": ["extracting template", "TASK OK"],
            "start": (["preparing first boot"] +
                      ([] if exit_status.startswith('ProxMenux preparation failed:') else
                       ["first-boot preparation completed", "starting CT"]) + [f"TASK {exit_status}"]),
            "prepare": ["preparing first boot", f"TASK {exit_status}"],
            "download_template": [],
        }[action]
        if self.lost_reply:
            raise LxcError("pve_unavailable")
        if self.missing_upid:
            return None
        if self.task_before_id:
            return "working...\n" + task_id
        return task_id


class EngineTests(unittest.TestCase):
    def test_no_start_choice_still_prepares_once_and_exposes_both_native_logs(self):
        payload = self.create_body(start_after_create=False)
        result = self.call('create', **payload)
        self.assertEqual((result['status'],result['phase'],result['created'],result['prepared']),
                         ('succeeded','prepare',True,True))
        self.assertEqual([name for name,_ in self.api.writes],['create','prepare'])
        self.assertEqual(self.api.boot_attempts,0)
        for phase in ('create','prepare'):
            self.assertIn('TASK OK',self.call('task_log',request_id=REQUEST_ID,phase=phase)['lines'])
        self.assertEqual(self.call('create',**payload),result)
        self.assertEqual(self.call('status',request_id=REQUEST_ID),result)
        self.assertEqual(len(self.api.writes),2)
        self.assertNotIn(PASSWORD,self.store.path.read_text(errors='replace'))

    def test_preparation_failure_is_terminal_partial_and_status_never_retries_it(self):
        for start in (False,True):
            with self.subTest(start=start),tempfile.TemporaryDirectory() as folder:
                self.api=FakePVE(Path(folder));self.store=Operations(Path(folder)/'state',os.getuid())
                self.api.prepare_exit=self.api.start_exit='ProxMenux preparation failed: simulated write failure'
                payload=self.create_body(start_after_create=start)
                result=self.call('create',**payload)
                self.assertEqual((result['status'],result['reason'],result['created']),
                                 ('partial','preparation_failed',True))
                self.assertNotIn('prepared',result)
                self.assertEqual(self.api.boot_attempts,0)
                saved=len(self.api.writes)
                self.assertEqual(self.call('status',request_id=REQUEST_ID),result)
                self.assertEqual(self.call('create',**payload),result)
                self.assertEqual(len(self.api.writes),saved)
                phase='start' if start else 'prepare'
                self.assertIn('ProxMenux preparation failed:',
                              ' '.join(self.call('task_log',request_id=REQUEST_ID,phase=phase)['lines']))

    def test_unknown_preparation_submission_retains_reservation_without_replay(self):
        original=self.api.mutate
        def lose_reply(action,params):
            result=original(action,params)
            if action=='prepare':raise LxcError('pve_unavailable')
            return result
        with patch.object(self.api,'mutate',side_effect=lose_reply):
            payload=self.create_body(start_after_create=False)
            result=self.call('create',**payload)
            self.assertEqual((result['status'],result['created']),('unknown',True))
            self.assertEqual(self.call('status',request_id=REQUEST_ID)['status'],'unknown')
            self.assertEqual(self.call('create',**payload)['status'],'unknown')
        self.assertEqual([a for a,_ in self.api.writes],['create','prepare'])
        self.assertEqual(self.api.boot_attempts,0)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.api = FakePVE(root)
        self.store = Operations(root / "state", os.getuid())
        self.spec = {
            # These original lifecycle tests exercise the opt-in preparation
            # path. Default-off behavior has independent maintainer regressions.
            "prepare_system": True,
            "node": NODE, "vmid": VMID, "hostname": "Debian-LXC", "template": {"volume_id": VOLUME},
            "access": {"mode": "password"}, "rootfs": {"storage": "local-lvm"},
            "network": {"bridge": "vmbr0", "vlan_tag": 200, "ipv4": {
                "mode": "static", "cidr": "192.0.2.10/24", "gateway": "192.0.2.1",
            }},
            "dns": {"nameservers": ["192.0.2.53"], "search_domains": ["LAN.Example."]},
        }

    def call(self, action, **payload):
        return execute(body(action, **payload), self.api, self.store, wait_seconds=0)

    def create_body(self, **spec):
        checked = self.call("plan", spec={**self.spec, **spec})
        return {"request_id": REQUEST_ID, **checked, "accepted_warnings": checked["plan"]["warnings"],
                "secret": {"password": PASSWORD}, "confirmed": True}

    def assert_rejected(self, error, action, **payload):
        with self.assertRaisesRegex(LxcError, f"^{error}$"):
            self.call(action, **payload)
        self.assertEqual(self.api.writes, [])
        self.assertFalse(self.store.path.exists())

    def test_context_and_plan_are_read_only_and_stable_for_json_clients(self):
        context = self.call("context")
        self.assertEqual(context["next_vmid"], VMID)
        self.assertIn(VOLUME, context["templates"])
        self.assertEqual(context["defaults"]["rootfs"]["size_gib"], 8)
        self.assertEqual([Path(command[0]).name for command in self.api.calls], ["perl"])
        self.api.calls.clear()
        response = self.call("plan", spec=self.spec)
        self.assertEqual([Path(command[0]).name for command in self.api.calls],
                         ["perl", "pvesm", "sha512sum"])
        wire = json.loads(json.dumps(body("plan", spec=self.spec), sort_keys=True))
        self.assertEqual(response, execute(wire, self.api, self.store))
        self.assertEqual(response["plan"]["spec"]["hostname"], "debian-lxc")
        self.assertFalse(self.store.directory.exists())
        self.assertEqual(self.api.writes, [])
        self.assertFalse(any("/storage" in part for command in self.api.calls for part in command))

    def test_create_rechecks_changed_template_storage_network_and_vmid_after_review(self):
        changes = {
            'template_checksum_mismatch': lambda api: api.file.write_bytes(b'corrupt after plan'),
            'template_unverified': lambda api: setattr(api, 'present', False),
            'disk_space_insufficient': lambda api: api.storage[1].update(avail=0),
            'bridge_unavailable': lambda api: setattr(api, 'network', []),
            'vmid_in_use': lambda api: api.guests.append({'vmid': VMID, 'type': 'lxc'}),
        }
        for error, change in changes.items():
            with self.subTest(error=error), tempfile.TemporaryDirectory() as folder:
                self.api = FakePVE(Path(folder))
                self.store = Operations(Path(folder)/'state', os.getuid())
                payload = self.create_body()
                change(self.api)
                self.assert_rejected(error, 'create', **payload)

    def test_inspection_rejects_invalid_discovery_before_checksum_or_write(self):
        for value, error in ((None, 'pve_output_invalid'), ([], 'node_unavailable'),
            ([{'type':'node','name':NODE,'local':1,'online':0}], 'node_unavailable'),
            ([{'type':'node','name':NODE,'local':2,'online':1}], 'pve_output_invalid')):
            with self.subTest(value=value):
                self.api.calls.clear()
                original = self.api.get
                with patch.object(self.api, 'get', side_effect=lambda path, params:
                                  value if path=='/cluster/status' else original(path, params)):
                    self.assert_rejected(error, 'plan', spec=self.spec)
                self.assertEqual([Path(command[0]).name for command in self.api.calls], ['perl'])

    def test_unsupported_architecture_does_not_start_inventory(self):
        with patch.object(self.api, 'architecture', return_value='unsupported'):
            self.assert_rejected('architecture_unsupported', 'context')
        self.assertEqual(self.api.calls, [])

    def test_inspect_transport_timeout_fails_closed_without_a_fallback_or_write(self):
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('perl', 24)) as runner:
            with self.assertRaisesRegex(LxcError, '^pve_unavailable$'):
                execute(body('context'), Proxmox(), self.store)
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(runner.call_args.kwargs['timeout'], 24)
        self.assertFalse(self.store.directory.exists())

    def test_create_then_start_and_both_boot_options(self):
        payload = self.create_body(onboot=True, start_after_create=True)
        result = self.call("create", **payload)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["create_upid"], upid("vzcreate", VMID))
        self.assertEqual(result["upid"], upid("vzstart", VMID))
        self.assertEqual([action for action, _ in self.api.writes], ["create", "start"])
        params = self.api.writes[0][1]
        self.assertEqual(params["net0"], "name=eth0,type=veth,bridge=vmbr0,ip=192.0.2.10/24,gw=192.0.2.1,tag=200")
        self.assertEqual((params["rootfs"], params["memory"], params["swap"]), ("local-lvm:8", 512, 512))
        self.assertEqual((params["onboot"], params["start"], params["unprivileged"], params["features"]),
                         (1, 0, 1, "nesting=1"))
        self.assertEqual((params["nameserver"], params["searchdomain"]), ("192.0.2.53", "lan.example"))
        self.assertEqual(params["password"], PASSWORD)
        self.assertNotIn(PASSWORD, repr(self.api.calls))
        self.assertNotIn(PASSWORD.encode(), self.store.path.read_bytes())
        self.assertNotIn(PASSWORD, json.dumps(result))
        self.assertEqual(self.call("create", **payload), result)
        self.assertEqual(self.call("status", request_id=REQUEST_ID), result)
        self.assertEqual(len(self.api.writes), 2)

    def test_a_task_that_warns_keeps_what_proxmox_wrote(self):
        self.api.task_running = True
        self.call("create", **self.create_body(start_after_create=True, prepare_system=False))
        create = upid("vzcreate", VMID)
        self.api.logs[create] = ["extracting archive", "WARN: Systemd 255 detected. You may need to enable nesting.",
                                 "  WARNING: thin pool notice", "WARN: Systemd 255 detected. You may need to enable nesting.",
                                 "TASK WARNINGS: 1"]
        self.api.tasks[create].update(status="stopped", exitstatus="WARNINGS: 1")
        result = self.call("status", request_id=REQUEST_ID)
        self.assertEqual(result["task_warning_messages"],
                         {"create": ["Systemd 255 detected. You may need to enable nesting."]})

    def test_nesting_is_on_unless_turned_off(self):
        self.assertTrue(self.call("context")["defaults"]["nesting"])
        spec = {key: value for key, value in self.spec.items() if key != "nesting"}
        self.assertTrue(self.call("plan", spec=spec)["plan"]["nesting"])
        self.assertFalse(self.call("plan", spec={**spec, "nesting": False})["plan"]["nesting"])

    def test_a_creation_lists_its_native_tasks_in_order(self):
        cases = (({"prepare_system": False}, ["create"], False),
                 ({"start_after_create": True, "prepare_system": False}, ["create", "start"], False),
                 ({"prepare_system": True}, ["create", "prepare"], True),
                 ({"start_after_create": True, "prepare_system": True}, ["create", "start"], True))
        for spec, steps, preparing in cases:
            with self.subTest(spec=spec):
                self.setUp()
                result = self.call("create", **self.create_body(**spec))
                self.assertEqual((result["steps"], result["preparing"]), (steps, preparing))
                self.assertEqual(self.call("status", request_id=REQUEST_ID)["steps"], steps)
                self.assertNotIn("start_after_create", result)

    def test_task_log_is_paginated_and_only_reads_the_recorded_task(self):
        self.call("create", **self.create_body(start_after_create=True))
        create, start = upid("vzcreate", VMID), upid("vzstart", VMID)
        self.api.logs[create] = ["\x1b[2J"] + ["extracting"] * 49 + ["TASK OK"]
        saved = self.store.path.read_bytes()
        self.api.calls.clear()
        first = self.call("task_log", request_id=REQUEST_ID, phase="create")
        self.assertEqual((first["upid"], first["next_offset"], len(first["lines"])), (create, 50, 50))
        self.assertEqual(first["lines"][0], " [2J")
        last = self.call("task_log", request_id=REQUEST_ID, phase="create", offset=50)
        self.assertEqual((last["lines"], last["next_offset"]), (["TASK OK"], None))
        self.assertEqual(self.call("task_log", request_id=REQUEST_ID, phase="start")["upid"], start)
        self.assertEqual([call[3] for call in self.api.calls],
                         [f"{BASE}/tasks/{create}/log", f"{BASE}/tasks/{create}/log", f"{BASE}/tasks/{start}/log"])
        self.api.calls.clear()
        for payload, error in (({"request_id": "2" * 32}, "request_not_found"),
                               ({"phase": "download"}, "invalid_field"),
                               ({"offset": -1}, "invalid_field"),
                               ({"upid": start}, "invalid_field")):
            with self.assertRaisesRegex(LxcError, error):
                self.call("task_log", **({"request_id": REQUEST_ID, "phase": "create"} | payload))
        foreign_store = Operations(self.store.directory, os.getuid() + 1)
        with self.assertRaisesRegex(LxcError, "request_conflict"):
            execute(body("task_log", request_id=REQUEST_ID, phase="create"), self.api, foreign_store)
        self.assertEqual(self.api.calls, [])
        self.assertEqual([action for action, _ in self.api.writes], ["create", "start"])
        self.assertEqual(self.store.path.read_bytes(), saved)

    def test_task_log_distinguishes_unknown_task_empty_log_and_unavailable_log(self):
        self.call("create", **self.create_body())
        create = upid("vzcreate", VMID)
        self.api.calls.clear()
        with self.assertRaisesRegex(LxcError, "task_log_unavailable"):
            self.call("task_log", request_id=REQUEST_ID, phase="start")
        self.assertEqual(self.api.calls, [])
        self.api.logs[create] = []
        self.assertEqual(self.call("task_log", request_id=REQUEST_ID, phase="create")["lines"], [])
        self.api.logs[create] = ["newly available"]
        self.assertEqual(self.call("task_log", request_id=REQUEST_ID, phase="create")["lines"], ["newly available"])
        for response in (None, [{"n": 3, "t": "partial"}], [{"n": 1, "t": 5}],
                         [{"n": 1, "t": "unable to open file - No such file or directory"}]):
            with patch.object(self.api, "read", return_value=response):
                with self.assertRaisesRegex(LxcError, "task_log_unavailable"):
                    self.call("task_log", request_id=REQUEST_ID, phase="create")
        self.api.task_error = True
        with self.assertRaisesRegex(LxcError, "task_log_unavailable"):
            self.call("task_log", request_id=REQUEST_ID, phase="create")
        self.assertEqual([action for action, _ in self.api.writes], ["create", "prepare"])

    def test_no_network_requires_acceptance_and_produces_no_interface(self):
        payload = self.create_body(network=None, dns={})
        self.assert_rejected("warnings_unaccepted", "create", **{**payload, "accepted_warnings": []})
        self.assertEqual(self.call("create", **payload)["status"], "succeeded")
        params = self.api.writes[0][1]
        self.assertEqual((params["onboot"], params["start"]), (0, 0))
        self.assertNotIn("net0", params)
        self.assertNotIn("nameserver", params)
        self.assertEqual([action for action, _ in self.api.writes], ["create", "prepare"])
        self.assertIsNone(self.api.writes[1][1]['expected']['net0'])

    def test_native_vlan_support_accepts_legacy_bridge_with_physical_port(self):
        self.api.network[0].pop("bridge_vlan_aware")
        checked = self.call("plan", spec=self.spec)
        self.assertTrue(checked["plan"]["resources"]["bridge"]["vlan_supported"])
        self.assertEqual(checked["plan"]["spec"]["network"]["vlan_tag"], 200)
        self.assertEqual(self.api.writes, [])
        self.assertFalse(self.store.path.exists())

    def test_vlan_without_native_support_is_refused_before_write(self):
        payload = self.create_body()
        self.api.bridge_vlans["vmbr0"] = False
        self.assert_rejected("bridge_unavailable", "create", **payload)
        plain_network = {"bridge": "vmbr0"}
        self.assertEqual(self.call("plan", spec={**self.spec, "network": plain_network})["plan"]
                         ["spec"]["network"]["ipv4"], {"mode": "dhcp"})

    def test_ovs_and_older_proxmox_keep_existing_vlan_support(self):
        self.api.network[0]["type"] = "OVSBridge"
        self.api.network[0].pop("bridge_vlan_aware")
        self.assertTrue(self.call("context")["bridges"]["vmbr0"]["vlan_supported"])
        self.api.network[0].update(type="bridge", bridge_vlan_aware=1)
        self.api.bridge_vlans = None
        self.assertTrue(self.call("context")["bridges"]["vmbr0"]["vlan_supported"])

    def test_collision_after_confirmation_and_plan_change_prevent_write(self):
        payload = self.create_body()
        self.api.guests.append({"type": "qemu", "vmid": VMID, "node": "pve-other"})
        self.assert_rejected("vmid_in_use", "create", **payload)
        self.api.guests.clear()
        self.api.storage[1]["type"] = "zfspool"
        self.assert_rejected("plan_changed", "create", **payload)
        self.api.storage[1]["avail"] = 7 * GIB
        # ZFS subvol can overcommit, but the newly required warning must be
        # reviewed; an old confirmation cannot silently accept it.
        self.assert_rejected("plan_changed", "create", **payload)

    def test_nextid_failure_blocks_planning_when_no_collision_is_observed(self):
        self.api.nextid_error = True
        self.assert_rejected("pve_unavailable", "plan", spec=self.spec)
        self.api.guests.append({"type": "lxc", "vmid": VMID, "node": NODE})
        self.assert_rejected("vmid_in_use", "plan", spec=self.spec)

    def test_unconfirmed_unknown_fields_and_remote_node_are_rejected(self):
        payload = self.create_body()
        self.assert_rejected("confirmation_required", "create", **{**payload, "confirmed": False})
        self.assert_rejected("invalid_field", "create", **{**payload, "force": True})
        self.assert_rejected("invalid_field", "plan", spec={**self.spec, "network": {"bridge": "vmbr0", "ipv6": "auto"}})
        self.assert_rejected("node_not_local", "plan", spec={**self.spec, "node": "remote"})
        self.assert_rejected("invalid_field", "plan", spec={**self.spec, "rootfs": {"storage": "local/../tmp"}})
        self.assert_rejected("storage_unavailable", "plan", spec={**self.spec, "rootfs": {"storage": "local"}})
        self.assert_rejected("invalid_field", "plan", spec={**self.spec, "vmid": True})
        with self.assertRaisesRegex(LxcError, "invalid_request"):
            strict_json(b'{"schema_version":1,"action":"plan","action":"create"}')

    def test_template_needs_official_source_architecture_and_archive_integrity(self):
        catalog = deepcopy(self.api.catalog)
        for key, value in (("architecture", "arm64"), ("section", "turnkeylinux"),
                           ("source", "https://example.com/images"), ("sha512sum", None)):
            self.api.catalog = {**catalog, key: value}
            self.assert_rejected("template_architecture_required", "plan", spec=self.spec)
        self.api.catalog = catalog
        self.api.file.write_bytes(b"same filename, modified archive")
        self.assert_rejected("template_checksum_mismatch", "plan", spec=self.spec)
        self.api.catalog_error = True
        self.assertEqual(self.call("context")["catalog_state"], "unavailable")
        self.assert_rejected("template_architecture_required", "plan", spec=self.spec)
        self.api.catalog_error = False
        self.api.catalog = None
        self.assertEqual(self.call("context")["catalog_state"], "empty")

    def test_download_is_separate_no_overwrite_and_catalog_selection_is_strict(self):
        payload = {"request_id": REQUEST_ID, "node": NODE, "catalog_id": NAME,
                   "template_storage": "local", "confirmed": True}
        self.assert_rejected("template_already_present", "download_template", **payload)
        self.api.present = False
        self.assert_rejected("confirmation_required", "download_template", **{**payload, "confirmed": False})
        self.assert_rejected("storage_unavailable", "download_template", **{**payload, "template_storage": "local-lvm"})
        self.assert_rejected("template_unverified", "download_template", **{**payload, "catalog_id": "foreign.tar.zst"})
        self.assert_rejected("invalid_field", "download_template", **{**payload, "catalog_id": "https://x/y.tar.zst"})
        result = self.call("download_template", **payload)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(self.call("download_template", **payload), result)
        self.assertIn(VOLUME, self.call("context")["templates"])
        self.assertEqual([action for action, _ in self.api.writes], ["download_template"])

    def test_simultaneous_confirmation_admits_one_write(self):
        payload = self.create_body()
        self.api.reached_write, self.api.finish_write = threading.Event(), threading.Event()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.call, "create", **payload)
            try:
                self.assertTrue(self.api.reached_write.wait(5))
                self.assertEqual(pool.submit(self.call, "create", **payload).result(5)["status"], "running")
                with self.assertRaisesRegex(LxcError, "target_operation_pending"):
                    self.call("create", **{**payload, "request_id": "2" * 32})
            finally:
                self.api.finish_write.set()
            self.assertEqual(first.result(5)["status"], "succeeded")
        self.assertEqual([action for action, _ in self.api.writes], ["create", "prepare"])
        changed = deepcopy(payload)
        changed["plan"]["spec"]["hostname"] = "another-name"
        changed["plan_hash"] = digest(changed["plan"])
        with self.assertRaisesRegex(LxcError, "request_conflict"):
            self.call("create", **changed)

    def test_known_start_error_is_partial_and_never_deletes_or_restarts(self):
        self.api.start_exit = "start error: " + PASSWORD
        result = self.call("create", **self.create_body(start_after_create=True))
        self.assertEqual((result["status"], result["reason"], result["created"]), ("partial", "start_failed", True))
        self.assertEqual(self.call("status", request_id=REQUEST_ID), result)
        self.assertEqual([action for action, _ in self.api.writes], ["create", "start"])
        self.assertNotIn(PASSWORD, json.dumps(result))

    def test_missing_task_or_lost_reply_is_unknown_and_replay_is_read_only(self):
        payload = self.create_body()
        self.api.lost_reply = True
        result = self.call("create", **payload)
        self.assertEqual((result["status"], result["container_observed"]), ("unknown", True))
        self.assertEqual(self.call("create", **payload), result)
        self.assertEqual(self.call("status", request_id=REQUEST_ID), result)
        self.assertEqual(len(self.api.writes), 1)

    def test_bad_task_identity_is_unknown(self):
        for bad_reply in (None, "working...\n" + upid("vzcreate", VMID), upid("vzrestore", VMID)):
            with self.subTest(bad_reply=bad_reply), patch.object(self.api, "mutate", return_value=bad_reply) as mutation:
                # Separate VMIDs and stores prevent the unknown reservation from
                # covering up a second malformed native response.
                with tempfile.TemporaryDirectory() as folder:
                    self.store = Operations(Path(folder) / "state", os.getuid())
                    payload = self.create_body()
                    self.assertEqual(self.call("create", **payload)["status"], "unknown")
                    self.assertEqual(self.call("create", **payload)["status"], "unknown")
                    mutation.assert_called_once()

    def test_status_recovers_delayed_task_but_does_not_start(self):
        self.api.task_running = True
        self.assertEqual(self.call("create", **self.create_body(start_after_create=True))["status"], "running")
        self.api.task_error = True
        self.assertEqual(self.call("status", request_id=REQUEST_ID)["status"], "unknown")
        self.api.task_error = False
        self.api.tasks[upid("vzcreate", VMID)].update(status="stopped")
        self.assertEqual(self.call("status", request_id=REQUEST_ID)["status"], "unknown")
        self.api.tasks[upid("vzcreate", VMID)].update(exitstatus="OK")
        result = self.call("status", request_id=REQUEST_ID)
        self.assertEqual((result["status"], result["reason"]), ("partial", "preparation_not_submitted"))
        self.assertEqual([action for action, _ in self.api.writes], ["create"])

    def test_unexpected_container_identity_blocks_start(self):
        self.api.prevent_marker = True
        result = self.call("create", **self.create_body(start_after_create=True))
        self.assertEqual((result["status"], result["reason"]), ("unknown", "container_identity_unknown"))
        self.assertEqual([action for action, _ in self.api.writes], ["create"])

    def test_native_create_warning_and_description_newline_allow_one_start(self):
        self.api.create_exit = "WARNINGS: 1"
        result = self.call("create", **self.create_body(start_after_create=True))
        self.assertEqual((result["status"], result["phase"], result["created"]), ("succeeded", "start", True))
        self.assertEqual([action for action, _ in self.api.writes], ["create", "start"])
        self.assertTrue(result["task_warnings"])
        self.assertEqual(result["task_warning_phases"], {"create": True, "start": False})
        self.assertEqual(self.call("status", request_id=REQUEST_ID)["task_warning_phases"],
                         {"create": True, "start": False})

    def test_create_warnings_survive_a_failed_start_and_both_logs_remain_readable(self):
        self.api.create_exit, self.api.start_exit = "WARNINGS: 1", "start failed"
        result = self.call("create", **self.create_body(start_after_create=True))
        self.assertEqual((result["status"], result["reason"]), ("partial", "start_failed"))
        self.assertTrue(result.get("task_warnings", False))
        self.assertEqual(result["task_warning_phases"], {"create": True, "start": False})
        for phase in ("create", "start"):
            self.assertIn("lines", self.call("task_log", request_id=REQUEST_ID, phase=phase))
        self.assertEqual([action for action, _ in self.api.writes], ["create", "start"])

    def test_nesting_is_explicit_boolean_and_requires_warning_acceptance(self):
        # On by default, as in the Proxmox interface; turning it off is a choice.
        default = self.call("plan", spec=self.spec)
        self.assertTrue(default["plan"]["nesting"])
        self.assertTrue(default["plan"]["spec"]["nesting"])
        self.assertNotIn("nesting_enabled", self.call("plan", spec={**self.spec, "nesting": False})["plan"]["warnings"])
        for invalid in (1, "true", None, [], {}):
            self.assert_rejected("invalid_field", "plan", spec={**self.spec, "nesting": invalid})
        payload = self.create_body(nesting=True, start_after_create=True)
        self.assertTrue(payload["plan"]["nesting"])
        self.assertEqual(payload["plan"]["warnings"], ["nesting_enabled"])
        self.assert_rejected("warnings_unaccepted", "create", **{**payload, "accepted_warnings": []})
        result = self.call("create", **payload)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual((self.api.writes[0][1]["unprivileged"], self.api.writes[0][1]["features"]),
                         (1, "nesting=1"))

    def test_description_identity_does_not_strip_additional_whitespace_or_text(self):
        original = self.api.mutate
        for suffix in ("\n\n", " ", "\r\n", "\nforeign text"):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as directory:
                self.store = Operations(Path(directory) / "state", os.getuid())
                self.api.guests.clear(); self.api.writes.clear()
                def mutate(action, params):
                    result = original(action, params)
                    if action == "create": self.api.config["description"] = params["description"] + suffix
                    return result
                with patch.object(self.api, "mutate", side_effect=mutate):
                    result = self.call("create", **self.create_body(start_after_create=True))
                self.assertEqual((result["status"], result["reason"]), ("unknown", "container_identity_unknown"))
                self.assertEqual([action for action, _ in self.api.writes], ["create"])

    def test_status_persists_a_resolved_pending_operation_without_starting_it(self):
        self.api.task_running = True
        self.call("create", **self.create_body(start_after_create=True))
        self.api.tasks[upid("vzcreate", VMID)].update(status="stopped", exitstatus="OK")
        result = self.call("status", request_id=REQUEST_ID)
        self.assertEqual((result["status"], result["reason"]), ("partial", "preparation_not_submitted"))
        self.assertEqual(self.store.get(REQUEST_ID)["status"], "partial")
        self.assertEqual([action for action, _ in self.api.writes], ["create"])
        with closing(self.store.connect()) as database:
            self.assertEqual(database.execute("SELECT pending FROM operations WHERE id=?", (REQUEST_ID,)).fetchone(), (0,))

    def test_late_status_observation_does_not_overwrite_a_concurrent_start(self):
        self.api.task_running = True
        self.call("create", **self.create_body(start_after_create=True))
        self.api.tasks[upid("vzcreate", VMID)].update(status="stopped", exitstatus="OK")
        observe = execute.__globals__["observe"]
        advanced = False

        def advance_after_observation(api, operation):
            nonlocal advanced
            result = observe(api, operation)
            if not advanced:
                advanced = True
                newer = self.store.get(REQUEST_ID)
                newer.update(phase="start", create_upid=newer["upid"], upid=upid("vzstart", VMID), created=True)
                self.api.tasks[newer["upid"]] = {"upid": newer["upid"], "status": "running"}
                self.store.save(newer)
            return result

        with patch("plain_lxc.observe", side_effect=advance_after_observation):
            result = self.call("status", request_id=REQUEST_ID)
        self.assertEqual((result["status"], result["phase"]), ("running", "start"))
        self.assertEqual(self.store.get(REQUEST_ID)["phase"], "start")
        with closing(self.store.connect()) as database:
            self.assertEqual(database.execute("SELECT pending FROM operations WHERE id=?", (REQUEST_ID,)).fetchone(), (1,))
        self.assertEqual([action for action, _ in self.api.writes], ["create"])

    def test_supported_ssh_access_and_dhcp_default(self):
        public_blob = "AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        payload = self.create_body(access={"mode": "ssh_key", "ssh_public_keys": ["ssh-ed25519 " + public_blob]},
                                   network={"bridge": "vmbr0"})
        del payload["secret"]
        result = self.call("create", **payload)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(self.api.writes[0][1]["net0"], "name=eth0,type=veth,bridge=vmbr0,ip=dhcp")
        self.assertNotIn("password", self.api.writes[0][1])
        self.assertEqual(self.api.writes[0][1]["ssh-public-keys"], "ssh-ed25519 " + public_blob)


class ScriptedDialog:
    def __init__(self, accept_create, download=False, accept_download=True, start=False, task_choices=(), prepare=False):
        self.accept_create = accept_create
        self.download = download
        self.accept_download = accept_download
        self.start = start
        self.prepare = prepare
        self.task_choices = iter(task_choices)
        self.steps = []
        self.review = ""
        self.messages = []
        self.logs = []

    def t(self, text):
        return text

    def number(self, step, prompt, default, optional=False):
        self.steps.append(step)
        return 200 if optional else default

    def input(self, step, prompt, default="", hidden=False):
        self.steps.append(step)
        if hidden:
            return PASSWORD
        return "debian-lxc" if step == 1 else ""

    def choose(self, step, prompt, choices, default=""):
        self.steps.append(step)
        if prompt.endswith("Choose what to do next."):
            self.review = prompt
            return "close"
        if choices[0][0] == "close":
            self.messages.append(prompt)
            selection = next(self.task_choices, "close")
            assert selection in dict(choices)
            return selection
        if prompt == "Select a system template" and self.download:
            self.download = False
            return "download"
        first = next(key for key, _ in choices if key not in ("download", ""))
        expected = {1: first, 2: "password", 3: "local-lvm",
                    4: "dhcp" if prompt == "Choose IPv4 configuration" else "bridge:vmbr0"}[step]
        assert expected in dict(choices)
        return expected

    def review_plan(self, step, text):
        self.steps.append(step)
        self.review = text
        return "create" if self.accept_create else "close"

    def confirm(self, step, text, *, default=False):
        self.steps.append(step)
        if text == "Start this container after creation?":
            return self.start
        if text.startswith('Prepare the system for its first boot?'):
            return self.prepare
        return self.accept_download and text.startswith("Download this template?")

    def message(self, step, text, widget="--msgbox"):
        self.messages.append(text)

    def task_log(self, step, text):
        self.logs.append(text)
        return True

    @contextmanager
    def progress(self, step, text, **options):
        self.messages.append(text)
        yield self.messages.append


class DownloadProgressTests(unittest.TestCase):
    """The share of a template download comes from wget's lines in the task log."""

    def progress(self, rows, error=False):
        import plain_lxc

        class API:
            def read(self, path, **params):
                if error:
                    raise LxcError("pve_output_invalid")
                return rows
        return plain_lxc.download_progress(API(), "pve", "UPID:pve:1:2:3:download:t:root@pam:")

    def test_the_last_reported_share_is_used(self):
        rows = [{"n": 1, "t": "Length: 145902106 (139M) [application/octet-stream]"},
                {"n": 2, "t": "     0K ........ ........ ........ ........ 22% 41.0M 3s"},
                {"n": 3, "t": " 32768K ........ ........ ........ ........ 45% 43.2M 2s"}]
        self.assertEqual(self.progress(rows), 45)

    def test_no_share_yet_or_an_unreadable_log_gives_none(self):
        self.assertIsNone(self.progress([{"n": 1, "t": "downloading http://download.proxmox.com/x.tar.zst"}]))
        self.assertIsNone(self.progress(None))
        self.assertIsNone(self.progress([], error=True))


class WizardTests(unittest.TestCase):
    def test_preparation_failure_ui_preserves_created_vmid_and_both_logs_without_start(self):
        for start in (False,True):
            with self.subTest(start=start),tempfile.TemporaryDirectory() as folder:
                path=Path(folder);api=FakePVE(path);store=Operations(path/'state',os.getuid())
                api.prepare_exit=api.start_exit='ProxMenux preparation failed: helper write failed'
                phase='start' if start else 'prepare'
                ui=ScriptedDialog(accept_create=True,start=start,task_choices=('create',phase),prepare=True)
                with self.simulate_engine(api,store) as calls:
                    wizard.wizard(ui)
                self.assertIn('The container was created, but first-boot preparation failed.',ui.messages[-1])
                self.assertIn('It was not started.',ui.messages[-1])
                self.assertIn('VMID: 240',ui.messages[-1])
                self.assertEqual([c['phase'] for c in calls if c['action']=='task_log'],['create',phase])
                self.assertIn('ProxMenux preparation failed:',ui.logs[-1])
                self.assertEqual(api.boot_attempts,0)

    def test_paint_profile_preserves_terminal_keys_and_colors_but_removes_bridge_optimizations(self):
        ui = wizard.Dialog('en')
        original = ('xterm-test|test terminal,\n\tbce,\n\tech=\\E[%p1%dX,\n'
                    '\trep=%p1%c\\E[%p2%db,\n\tel=\\E[K,\n\tel1=\\E[1K,\n\ted=\\E[J,\n'
                    '\tsmcup=\\E[?1049h,\n\trmcup=\\E[?1049l,\n'
                    '\tkcuu1=\\EOA,\n\tsetab=\\E[4%p1%dm,\n')
        with patch.dict(wizard.os.environ, {'TERM': 'xterm-test'}, clear=True), \
                patch.object(wizard.subprocess, 'run', side_effect=[
                    subprocess.CompletedProcess([], 0, stdout=original),
                    subprocess.CompletedProcess([], 0)]) as run:
            environment = ui.paint_environment()
            self.assertEqual(environment['TERM'], 'xterm-test')
            self.assertEqual(environment['NCURSES_NO_HARD_TABS'], '1')
            self.assertTrue(Path(environment['TERMINFO']).is_dir())
            compiled = run.call_args.kwargs['input']
            for capability in ('bce,', 'ech=', 'rep=', 'el=', 'el1=', 'ed=', 'smcup=', 'rmcup='):
                self.assertNotIn('\t' + capability, compiled)
            self.assertIn('\tkcuu1=\\EOA,', compiled)
            self.assertIn('\tsetab=\\E[4%p1%dm,', compiled)
            self.assertIs(ui.paint_environment(), environment)
            self.assertEqual(run.call_count, 2)
            self.assertNotIn('TERMINFO', wizard.os.environ)
        with patch.object(wizard.sys.stdout, 'isatty', return_value=False):
            ui.restore_terminal()
        self.assertFalse(Path(environment['TERMINFO']).exists())

    def test_paint_profile_failure_cleans_up_and_never_opens_a_dialog(self):
        ui = wizard.Dialog('en')
        with patch.dict(wizard.os.environ, {'TERM': 'xterm'}, clear=True), \
                patch.object(wizard.subprocess, 'run', side_effect=OSError('unavailable')) as run, \
                patch.object(wizard, 'TemporaryDirectory') as temporary:
            with self.assertRaises(wizard.WizardError):
                ui.input(1, 'Container ID (VMID)', '108')
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0][0], '/usr/bin/infocmp')
            temporary.return_value.cleanup.assert_called_once()
            self.assertIsNone(ui._paint_environment)

    def test_other_terminal_profiles_are_not_replaced(self):
        for terminal in ('linux', 'screen-256color', 'dumb'):
            with patch.dict(wizard.os.environ, {'TERM': terminal}, clear=True), \
                    patch.object(wizard.subprocess, 'run') as run:
                self.assertEqual(wizard.Dialog('en').paint_environment(), {'TERM': terminal})
                run.assert_not_called()

    def test_all_dialog_kinds_use_the_same_private_paint_environment(self):
        ui = wizard.Dialog('en'); environment = {'TERM': 'xterm', 'TERMINFO': '/private/test'}
        with patch.object(ui, 'paint_environment', return_value=environment), \
                patch.object(wizard.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, stderr='')) as run, \
                patch.object(wizard.subprocess, 'Popen') as launch:
            ui.message(5, 'message')
            self.assertIs(run.call_args.kwargs['env'], environment)
            self.assertFalse(ui.confirm(5, 'confirm'))
            self.assertIs(run.call_args.kwargs['env'], environment)
            with ui.progress(5, 'progress'):
                self.assertIs(launch.call_args.kwargs['env'], environment)
        for language, expected in (('en', ('OK', 'Cancel', 'Yes', 'No', 'Close')),
                                   ('sk', ('OK', 'Zrušiť', 'Áno', 'Nie', 'Zavrieť'))):
            with patch.object(wizard, 'SCRIPTS', ROOT/'scripts'):
                localized = wizard.Dialog(language)
            with patch.object(localized, 'paint_environment', return_value=environment), \
                    patch.object(wizard.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, stderr='')) as run, \
                    patch.object(wizard.subprocess, 'Popen') as launch:
                localized.message(5, 'message')
                commands = [run.call_args.args[0]]
                localized.task_log(5, 'log')
                commands.append(run.call_args.args[0])
                self.assertFalse(localized.confirm(5, 'confirm'))
                commands.append(run.call_args.args[0])
                with localized.progress(5, 'progress'):
                    commands.append(launch.call_args.args[0])
                for command in commands:
                    for option, label in zip(('--ok-label', '--cancel-label', '--yes-label', '--no-label', '--exit-label'), expected):
                        self.assertEqual(command[command.index(option)+1], label)

    def test_uniform_frame_clamps_to_actual_terminal_and_measures_unicode(self):
        ui = wizard.Dialog('en')
        for size, expected in (((144, 46), ('24', '75')), ((80, 24), ('22', '75')),
                               ((40, 24), ('22', '36')), ((40, 16), ('14', '36'))):
            with patch.object(wizard.os, 'get_terminal_size', return_value=os.terminal_size(size)):
                self.assertEqual(ui.dimensions('Short question?'), expected)
        with patch.object(wizard.os, 'get_terminal_size', return_value=os.terminal_size((40, 24))), \
                patch.dict(os.environ, {'COLUMNS': '144'}):
            self.assertEqual(ui.dimensions('Short question?'), ('22', '36'))
        self.assertEqual(ui.text_rows('界'*20, 36), 2)
        self.assertEqual(ui.text_rows('a\u0301'*20, 36), 1)

    def test_shared_dialog_frame_matches_main_menu_and_preserves_text_and_safe_defaults(self):
        ui = wizard.Dialog("en")
        prompt = "Start this container when the host boots?"
        with patch.object(wizard.os, 'get_terminal_size', return_value=os.terminal_size((144, 46))), \
                patch.object(wizard.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, stderr="")) as run, \
                patch.object(wizard.subprocess, "Popen") as launch:
            multiline = "First logical row\nSecond logical row"
            ui.message(5, multiline)
            self.assertEqual(run.call_args.args[0][-4:], ["--msgbox", multiline, "24", "75"])
            self.assertFalse(ui.confirm(5, prompt))
            self.assertIn("--defaultno", run.call_args.args[0])
            self.assertEqual(run.call_args.args[0][-4:], ["--yesno", prompt, "24", "75"])
            with ui.progress(5, prompt, height='10'):
                self.assertEqual(launch.call_args.args[0][-4:], ["--progressbox", prompt, "24", "75"])
            run.return_value=subprocess.CompletedProcess([],0,stderr='password')
            self.assertEqual(ui.choose(2,'Choose access',[('password','Root password')]),'password')
            command=run.call_args.args[0];index=command.index('--menu')
            self.assertEqual(command[index+2:index+5],['24','75','16'])
        # Native default button text does not use our translation catalog.
        # All cancellable widgets must explicitly receive the active label.
        for language, label in (('en', 'Cancel'), ('sk', 'Zrušiť')):
            with patch.object(wizard, 'SCRIPTS', ROOT/'scripts'):
                localized = wizard.Dialog(language)
            for widget, args in (('--inputbox', ('107',)), ('--passwordbox', ('',)),
                                 ('--menu', ('1', 'item', 'Item'))):
                with patch.object(localized, 'paint_environment', return_value={}), \
                        patch.object(wizard.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, stderr='')) as run:
                    self.assertEqual(localized.run(1, widget, 'Question', *args), (1, ''))
                    command = run.call_args.args[0]
                    self.assertEqual(command[command.index('--cancel-label')+1], label)
                    self.assertEqual(command[command.index('--extra-label')+1],
                                     'Späť' if language == 'sk' else 'Back')
        main_menu = (ROOT/'scripts/menus/main_menu.sh').read_text()
        self.assertIn('local height=24', main_menu)
        self.assertRegex(main_menu, r'--menu .*?75 .*?rows')

    def test_long_details_keep_width_and_grow_height_within_the_terminal(self):
        ui = wizard.Dialog('en')
        with patch.object(wizard.os, 'get_terminal_size', return_value=os.terminal_size((144, 46))):
            height, width = ui.dimensions('Detail row\n'*30, detail=True, menu_rows=7)
            self.assertEqual(width, '75')
            self.assertGreater(int(height), 24)
            self.assertLessEqual(int(height), 44)

    def test_identifier_only_and_labelled_choices_share_one_column_without_changing_values(self):
        ui=wizard.Dialog('en')
        choices=[(VOLUME,''),('download','Download an official template')]
        with patch.object(wizard.os,'get_terminal_size',return_value=os.terminal_size((144,46))), \
                patch.object(wizard.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stderr=VOLUME)) as run:
            self.assertEqual(ui.choose(1,'Select a system template',choices,default=VOLUME),VOLUME)
            command=run.call_args.args[0]
            self.assertIn('--no-tags',command)
            self.assertEqual(command[-4:],[VOLUME,VOLUME,'download','Download an official template'])
            self.assertEqual(choices,[(VOLUME,''),('download','Download an official template')])

    def test_low_terminal_review_is_scrollable_before_the_same_actions_and_esc_cancels(self):
        ui = wizard.Dialog('en'); text='Complete review row\n'*30
        choices=[('create','Create'),('resources','Resources'),('close','Close')]
        with patch.object(wizard.os, 'get_terminal_size', return_value=os.terminal_size((80, 24))), \
                patch.object(ui, 'task_log', return_value=True) as page, \
                patch.object(ui, 'run', return_value=(0, 'resources')) as run:
            self.assertEqual(ui.choose(5,text,choices,default='create'),'resources')
            page.assert_called_once_with(5,text)
            self.assertEqual(run.call_args.args[2],'Choose what to do next.')
            self.assertEqual(run.call_args.kwargs['default_item'],'create')
        with patch.object(wizard.os, 'get_terminal_size', return_value=os.terminal_size((80, 24))), \
                patch.object(ui, 'task_log', return_value=False), patch.object(ui, 'run') as run:
            with self.assertRaises(wizard.Cancelled):ui.choose(5,text,choices)
            run.assert_not_called()

    def test_restore_terminal_resets_only_a_terminal_and_keeps_scrollback(self):
        ui = wizard.Dialog("en")
        with patch.object(wizard.sys.stdout, "isatty", side_effect=[False, True]), \
                patch.object(wizard.subprocess, "run") as run:
            ui.restore_terminal()
            run.assert_not_called()
            ui.restore_terminal()
            run.assert_called_once_with(["/usr/bin/tput", "-x", "-S"], input="sgr0\nclear\n",
                                        text=True, stderr=subprocess.DEVNULL)

    def test_password_dialog_masks_both_inputs_without_passing_the_password_as_an_argument(self):
        ui = wizard.Dialog("en")
        result = subprocess.CompletedProcess([], 0, stderr=PASSWORD)
        with patch.object(wizard.subprocess, "run", return_value=result) as run:
            for prompt in ("Enter the root password", "Repeat the root password"):
                self.assertEqual(ui.input(2, prompt, hidden=True), PASSWORD)
                command = run.call_args.args[0]
                self.assertLess(command.index("--insecure"), command.index("--passwordbox"))
                self.assertNotIn(PASSWORD, command)
            ui.input(2, "Hostname")
            self.assertNotIn("--insecure", run.call_args.args[0])

    def test_progress_window_closes_when_plan_fails(self):
        with patch.object(wizard.subprocess, "Popen") as launch:
            display = launch.return_value.__enter__.return_value
            with self.assertRaises(wizard.WizardError), wizard.Dialog("en").progress(5, "Checking…"):
                raise wizard.WizardError("pve_unavailable")
            self.assertIn("--progressbox", launch.call_args.args[0])
            display.stdin.close.assert_called_once_with()
            display.wait.assert_called_once_with(timeout=2)

    @contextmanager
    def simulate_engine(self, api, store, before_plan=None):
        calls = []

        def run_request(raw, on_phase=None):
            request = json.loads(raw)
            calls.append(request)
            if request["action"] == "plan" and before_plan is not None:
                before_plan()
            try:
                response = execute(request, api, store, wait_seconds=0, on_phase=on_phase)
            except LxcError as error:
                return {"ok": False, "error": error.code, "field": error.field}
            return {"ok": True, "data": response}

        def run(command, *, input, **options):
            self.assertEqual(command, ["/usr/bin/python3", "-I", "-B", str(wizard.ENGINE)])
            self.assertNotIn(PASSWORD, repr(command) + repr(options))
            return subprocess.CompletedProcess(command, 0, json.dumps(run_request(input)).encode())

        def stream(command, raw, on_phase):
            self.assertEqual(command, ["/usr/bin/python3", "-I", "-B", str(wizard.ENGINE)])
            self.assertNotIn(PASSWORD, repr(command))
            return run_request(raw, on_phase)

        real_run = subprocess.run
        with patch.object(wizard.subprocess, "run",
                          side_effect=lambda cmd, **kw: run(cmd, **kw) if cmd[-1] == str(wizard.ENGINE)
                          else real_run(cmd, **kw)), patch.object(wizard, "stream_response", side_effect=stream):
            yield calls

    def test_confirmed_create_reports_both_phases_and_separate_logs_even_if_start_fails(self):
        for start_exit in ("OK", "ERROR: simulated start failure"):
            with self.subTest(start_exit=start_exit), tempfile.TemporaryDirectory() as folder:
                path = Path(folder)
                api, store = FakePVE(path), Operations(path / "state", os.getuid())
                api.start_exit = start_exit
                api.create_exit = "WARNINGS: 1"
                mutate = api.mutate

                def append_redaction_fixture(action, params):
                    task = mutate(action, params)
                    if action == "start":
                        api.logs[task].append(f"test input {PASSWORD}")
                    return task

                ui = ScriptedDialog(accept_create=True, start=True, task_choices=("create", "start"))
                with patch.object(api, "mutate", side_effect=append_redaction_fixture), \
                        self.simulate_engine(api, store) as calls:
                    wizard.wizard(ui)
                self.assertEqual([request["action"] for request in calls],
                                 ["context", "plan", "create", "task_log", "task_log"])
                self.assertEqual([request["phase"] for request in calls[-2:]], ["create", "start"])
                self.assertTrue(all(request["request_id"] == calls[2]["request_id"] for request in calls[3:]))
                creating = ui.messages.index("Creating the container...")
                starting = ui.messages.index("Starting the container...")
                self.assertLess(creating, starting)
                self.assertIn("VMID: 240", ui.messages[-1])
                self.assertIn("Proxmox reported task warnings.", ui.messages[-1])
                self.assertIn("OS health was not checked.", ui.messages[-1])
                self.assertIn("Warnings during creation.", ui.messages[-1])
                if start_exit == "OK":
                    self.assertIn("Operation completed.", ui.messages[-1])
                else:
                    self.assertIn("The container was created. Its start task failed.", ui.messages[-1])
                self.assertIn("extracting template", ui.logs[0])
                self.assertIn(f"TASK {start_exit}", ui.logs[1])
                self.assertIn("test input […]", ui.logs[1])
                self.assertNotIn(PASSWORD, "".join(ui.messages + ui.logs))
                self.assertEqual([action for action, _ in api.writes], ["create", "start"])
                self.assertEqual(api.guests, [{"type": "lxc", "vmid": VMID, "node": NODE}])

    def test_unavailable_log_then_status_recheck_does_not_resubmit_create(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            api, store = FakePVE(path), Operations(path / "state", os.getuid())
            api.task_running = True
            ui = ScriptedDialog(accept_create=True, task_choices=("create", "status", "close"), prepare=True)
            handle_get = api.get

            def disappear_then_complete(resource, params):
                if resource.endswith("/log"):
                    task = upid("vzcreate", VMID)
                    api.tasks[task] = {"upid": task, "status": "stopped", "exitstatus": "OK"}
                    raise LxcError("pve_unavailable")
                return handle_get(resource, params)

            with patch.object(api, "get", side_effect=disappear_then_complete), \
                    self.simulate_engine(api, store) as calls:
                wizard.wizard(ui)
            self.assertEqual([request["action"] for request in calls],
                             ["context", "plan", "create", "task_log", "status"])
            self.assertEqual(calls[2]["request_id"], calls[3]["request_id"])
            self.assertEqual(calls[2]["request_id"], calls[4]["request_id"])
            self.assertTrue(any("The Proxmox task is still running." in text for text in ui.messages))
            self.assertIn("The Proxmox task log could not be read.", ui.messages)
            self.assertIn("first-boot preparation was not submitted", ui.messages[-1])
            self.assertNotIn("Preparing and starting the container...", ui.messages)
            self.assertEqual([action for action, _ in api.writes], ["create"])

    def test_progress_stream_without_final_result_preserves_the_observed_phase(self):
        events = []
        code = 'import sys; sys.stdin.buffer.read(); print(\'{"schema_version":1,"event":"phase","phase":"create"}\')'
        with self.assertRaisesRegex(ValueError, "Missing operation result"):
            wizard.stream_response([sys.executable, "-I", "-B", "-c", code], b"{}", events.append)
        self.assertEqual(events, ["create"])

    def test_cancel_confirmation_leaves_no_operation_or_secret_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            api, store = FakePVE(path), Operations(path / "state", os.getuid())
            api.network[0].pop("bridge_vlan_aware")
            ui = ScriptedDialog(accept_create=False)
            with self.simulate_engine(api, store, lambda: self.assertIn("Checking container configuration…",
                                                                         ui.messages)) as calls:
                wizard.wizard(ui)
            self.assertEqual([request["action"] for request in calls], ["context", "plan"])
            self.assertEqual(ui.steps, sorted(ui.steps))
            self.assertEqual(api.writes, [])
            self.assertFalse(store.directory.exists())
            self.assertNotIn(PASSWORD, ui.review)
            self.assertIn("VLAN tag: 200", ui.review)

    def test_download_refreshes_choices_then_creates_with_the_same_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            api, store = FakePVE(path), Operations(path / "state", os.getuid())
            api.present = False
            ui = ScriptedDialog(accept_create=True, download=True)
            with self.simulate_engine(api, store) as calls:
                wizard.wizard(ui)
            self.assertEqual([request["action"] for request in calls],
                             ["context", "download_template", "context", "plan", "create"])
            self.assertEqual(calls[-1]["plan"]["spec"], calls[-2]["spec"] | {
                "access": {"mode": "password", "ssh_public_keys": []},
            })
            self.assertEqual(calls[-1]["secret"], {"password": PASSWORD})
            self.assertNotIn(PASSWORD, ui.review + "".join(ui.messages))
            self.assertIn("VLAN tag: 200", ui.review)
            self.assertIn("VMID: 240", ui.messages[-1])

    def test_declining_the_download_keeps_existing_template_choices(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            api, store = FakePVE(path), Operations(path / "state", os.getuid())
            ui = ScriptedDialog(accept_create=False, download=True, accept_download=False)
            with self.simulate_engine(api, store) as calls:
                wizard.wizard(ui)
            self.assertEqual([request["action"] for request in calls], ["context", "plan"])
            self.assertEqual(api.writes, [])
            self.assertFalse(store.directory.exists())


class EditingDialog(ScriptedDialog):
    def __init__(self, edits, accept_create=False):
        super().__init__(accept_create=accept_create)
        self.edits = iter(edits)
        self.editing = None
        self.changes = {}
        self.summaries = []
        self.defaults = []

    def review_plan(self, step, text):
        self.summaries.append((text, {"create": "", "modify": ""}))
        self.editing, self.changes = next(self.edits, ("close", {}))
        return self.editing if self.editing in ("create", "close") else "modify"

    def choose(self, step, prompt, choices, default=""):
        if prompt.endswith("Choose what to do next."):
            self.summaries.append((prompt, dict(choices)))
            action = next(self.edits, ("close", {}))
            self.editing, self.changes = action
            self.assert_valid_choice = self.editing in dict(choices)
            assert self.assert_valid_choice
            return self.editing
        if prompt == "Choose what to modify":
            assert self.editing in dict(choices)
            return self.editing
        if self.editing:
            self.defaults.append((prompt, default))
            return self.changes.get(prompt, default if default in dict(choices) else choices[0][0])
        return super().choose(step, prompt, choices, default)

    def number(self, step, prompt, default, optional=False):
        if self.editing:
            self.defaults.append((prompt, default))
            if self.changes.get("cancel_at") == prompt:
                raise wizard.Cancelled()
            return self.changes.get(prompt, default if default != "" else None)
        return super().number(step, prompt, default, optional)

    def input(self, step, prompt, default="", hidden=False):
        if self.editing:
            self.defaults.append((prompt, default))
            return self.changes.get(prompt, PASSWORD if hidden else default)
        return super().input(step, prompt, default, hidden)

    def confirm(self, step, text, *, default=False):
        if self.editing:
            return self.changes.get(text, default)
        return super().confirm(step, text, default=default)


class ReviewEditingTests(unittest.TestCase):
    simulate_engine = WizardTests.simulate_engine

    def test_nesting_compatibility_notice_precedes_access_and_esc_has_no_effects(self):
        for language in ('en', 'sk'):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as folder:
                api, store = FakePVE(Path(folder)), Operations(Path(folder)/'state', os.getuid())
                with patch.object(wizard, 'SCRIPTS', ROOT/'scripts'):
                    translated = wizard.Dialog(language)
                class EarlyExit(ScriptedDialog):
                    t = staticmethod(translated.t)
                    def confirm(self, step, text, *, default=False):
                        if step == 1:
                            self.notice, self.default = text, default
                            raise wizard.Cancelled()
                        raise AssertionError('Access or execution must not be reached')
                    def input(self, step, prompt, default='', hidden=False):
                        if hidden: raise AssertionError('No password before the nesting choice')
                        return super().input(step, prompt, default, hidden)
                ui = EarlyExit(accept_create=False)
                with self.simulate_engine(api, store) as calls, self.assertRaises(wizard.Cancelled):
                    wizard.wizard(ui)
                self.assertIn('Debian 13', ui.notice)
                self.assertIn('systemd 257', ui.notice)
                for path in ('/tmp', '/run/lock', '/dev/mqueue', '/proc', '/sys'):
                    self.assertIn(path, ui.notice)
                self.assertIn('Niektoré šablóny' if language=='sk' else 'Some templates', ui.notice)
                self.assertTrue(ui.default)
                self.assertEqual([r['action'] for r in calls], ['context'])
                self.assertEqual(api.writes, [])
                self.assertFalse(store.directory.exists())

    def test_nesting_notice_tracks_the_choice_without_changing_other_plan_values(self):
        class ChoiceDialog(EditingDialog):
            def confirm(self, step, text, *, default=False):
                if self.editing == 'system' and text.startswith('Enable nesting?'):
                    return self.changes['nesting']
                return super().confirm(step, text, default=default)
        with tempfile.TemporaryDirectory() as folder:
            api, store = FakePVE(Path(folder)), Operations(Path(folder)/'state', os.getuid())
            ui = ChoiceDialog([('system', {'nesting': True}), ('system', {'nesting': False}), ('close', {})])
            with self.simulate_engine(api, store) as calls:
                wizard.wizard(ui)
            summaries = [text for text, _ in ui.summaries]
            for index in (0, 2):
                self.assertIn('Some templates, such as Debian 13 with systemd 257', summaries[index])
                self.assertIn('To change nesting, open System.', summaries[index])
            self.assertNotIn('Some templates, such as Debian 13 with systemd 257', summaries[1])
            self.assertIn(wizard.NESTING_NOTICE, summaries[1])
            plans = [r['spec'] for r in calls if r['action']=='plan']
            self.assertEqual(plans[1], {**plans[0], 'nesting': True})
            self.assertEqual(plans[2], plans[0])
            self.assertEqual(api.writes, [])
            self.assertFalse(store.directory.exists())

    def test_back_from_nesting_notice_keeps_hostname_and_default_yes(self):
        class BackOnce(ScriptedDialog):
            def __init__(self):
                super().__init__(accept_create=False)
                self.defaults, self.names, self.back = [], [], True
            def input(self, step, prompt, default='', hidden=False):
                if prompt=='Container hostname':
                    self.names.append(default)
                    return 'retained-name'
                return super().input(step, prompt, default, hidden)
            def confirm(self, step, text, *, default=False):
                if step==1:
                    self.defaults.append(default)
                    if self.back:
                        self.back = False
                        raise wizard.Back()
                return super().confirm(step, text, default=default)
        with tempfile.TemporaryDirectory() as folder:
            api, store = FakePVE(Path(folder)), Operations(Path(folder)/'state', os.getuid())
            ui = BackOnce()
            with self.simulate_engine(api, store) as calls:
                wizard.wizard(ui)
            self.assertEqual(ui.names[-1], 'retained-name')
            self.assertEqual(ui.defaults, [True, True])
            self.assertEqual([r['action'] for r in calls], ['context', 'plan'])
            self.assertEqual(calls[-1]['spec']['hostname'], 'retained-name')
            # Offered on; this dialog answers no.
            self.assertFalse(calls[-1]['spec']['nesting'])
            self.assertEqual(api.writes, [])
            self.assertFalse(store.directory.exists())

    def test_small_terminal_review_wraps_the_notice_without_losing_choices_or_values(self):
        choices = [('create', 'Continue'), ('system', 'System'), ('close', 'Cancel')]
        for language in ('en', 'sk'):
            with self.subTest(language=language), patch.object(wizard, 'SCRIPTS', ROOT/'scripts'):
                ui = wizard.Dialog(language)
                text = 'Hostname: retained-name\n'*18 + '\n' + ui.t(wizard.NESTING_COMPATIBILITY_NOTICE)
                with patch.object(ui, 'terminal_size', return_value=os.terminal_size((80, 24))), \
                        patch.object(ui, 'task_log', return_value=True) as page, \
                        patch.object(ui, 'run', return_value=(0, 'system')) as run:
                    self.assertEqual(ui.choose(5, text, choices, default='create'), 'system')
                wrapped = page.call_args.args[1]
                self.assertEqual(' '.join(wrapped.split()), ' '.join(text.split()))
                self.assertLessEqual(max(map(len, wrapped.splitlines())), 67)
                for path in ('/tmp', '/run/lock', '/dev/mqueue'):
                    self.assertIn(path, wrapped)
                self.assertEqual(run.call_args.kwargs['default_item'], 'create')
                self.assertEqual(run.call_args.args[3:], ('0', 'create', 'Continue', 'system', 'System', 'close', 'Cancel'))

    def test_validation_error_keeps_its_field_on_the_same_logical_line(self):
        for language in ('en', 'sk'):
            ui = wizard.Dialog(language)
            for code in (*wizard.ERRORS, 'unrecognized_code'):
                with self.subTest(language=language, code=code):
                    error = wizard.WizardError(code, 'hostname')
                    text = wizard.error_text(ui, error)
                    self.assertNotIn('\n', text)
                    self.assertTrue(text.endswith(' (hostname)'))
                    self.assertIn(ui.t(wizard.ERRORS.get(code, 'The wizard could not complete the operation.')), text)

    def test_invalid_hostname_message_and_review_share_the_complete_inline_error(self):
        with tempfile.TemporaryDirectory() as folder:
            api, store = FakePVE(Path(folder)), Operations(Path(folder)/'state', os.getuid())
            ui = EditingDialog([('system', {'Container hostname': 'bad hostname'}), ('close', {})])
            with self.simulate_engine(api, store):
                wizard.wizard(ui)
            expected = 'Check the value in the indicated field. (hostname)'
            self.assertIn(expected, ui.messages)
            self.assertTrue(ui.summaries[-1][0].startswith(expected+'\n\n'))
            self.assertEqual(api.writes, [])

    def test_system_nesting_edit_and_cancel_preserve_the_rest_of_the_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            api, store = FakePVE(Path(folder)), Operations(Path(folder)/'state', os.getuid())
            prompt = "Enable nesting?\n\n" + wizard.NESTING_NOTICE + '\n\n' + wizard.NESTING_COMPATIBILITY_NOTICE
            ui = EditingDialog([('system', {prompt: True}),
                                ('resources', {'RAM (MiB)': 2048, 'cancel_at': 'Swap (MiB)'}), ('close', {})])
            with self.simulate_engine(api, store) as calls:
                wizard.wizard(ui)
            plans = [r['spec'] for r in calls if r['action'] == 'plan']
            self.assertEqual(len(plans), 3)
            self.assertFalse(plans[0]['nesting'])
            self.assertTrue(plans[1]['nesting'])
            self.assertEqual(plans[1], {**plans[0], 'nesting': True})
            self.assertEqual(plans[2], plans[1])
            self.assertEqual(api.writes, [])

    def test_editor_uses_one_context_but_replans_after_every_edit_and_cancel(self):
        with tempfile.TemporaryDirectory() as folder:
            api, store = FakePVE(Path(folder)), Operations(Path(folder)/'state', os.getuid())
            ui = EditingDialog([('resources', {'RAM (MiB)': 1024}),
                ('network', {'VLAN tag (optional)': 201}),
                ('resources', {'RAM (MiB)': 2048, 'cancel_at': 'Swap (MiB)'}), ('close', {})])
            with self.simulate_engine(api, store) as calls:
                wizard.wizard(ui)
            self.assertEqual([x['action'] for x in calls], ['context', 'plan', 'plan', 'plan', 'plan'])
            self.assertEqual(calls[-1]['spec']['memory']['ram_mib'], 1024)
            self.assertEqual(calls[-1]['spec']['network']['vlan_tag'], 201)
            self.assertEqual(api.writes, []); self.assertFalse(store.directory.exists())
            self.assertIn('Loading Proxmox configuration…', ui.messages)

    def test_fresh_plan_rejects_changes_to_all_live_dependencies_after_edit(self):
        changes = {
            'checksum': lambda api: api.file.write_bytes(b'changed archive'),
            'missing_template': lambda api: setattr(api, 'present', False),
            'capacity': lambda api: api.storage[1].update(avail=0),
            'storage': lambda api: api.storage.pop(),
            'bridge': lambda api: setattr(api, 'network', []),
            'vmid': lambda api: api.guests.append({'vmid': VMID, 'type': 'lxc'}),
            'catalog': lambda api: setattr(api, 'catalog_error', True),
            'nextid': lambda api: setattr(api, 'nextid_error', True),
        }
        for kind, change in changes.items():
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                api, store = FakePVE(Path(folder)), Operations(Path(folder)/'state', os.getuid())
                ui = EditingDialog([('resources', {'RAM (MiB)': 1024}), ('close', {})])
                count = 0
                def before_plan():
                    nonlocal count
                    count += 1
                    if count == 2: change(api)
                with self.simulate_engine(api, store, before_plan) as calls:
                    wizard.wizard(ui)
                self.assertEqual([x['action'] for x in calls], ['context', 'plan', 'plan'])
                self.assertNotIn('create', ui.summaries[-1][1])
                self.assertEqual(api.writes, []); self.assertFalse(store.directory.exists())

    def test_retry_refreshes_the_form_inventory_without_reusing_an_invalid_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            api, store = FakePVE(Path(folder)), Operations(Path(folder)/'state', os.getuid())
            ui = EditingDialog([('resources', {'RAM (MiB)': 0}), ('retry', {}),
                                ('resources', {'RAM (MiB)': 1024}), ('close', {})])
            with self.simulate_engine(api, store) as calls:
                wizard.wizard(ui)
            self.assertEqual(sum(x['action']=='plan' for x in calls), 4)
            self.assertGreaterEqual(sum(x['action']=='context' for x in calls), 2)
            self.assertEqual(calls[-1]['spec']['memory']['ram_mib'], 1024)
            self.assertEqual(api.writes, [])
    def test_review_edits_resources_and_network_without_resetting_other_groups(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder); api, store = FakePVE(path), Operations(path / "state", os.getuid())
            ui = EditingDialog([("resources", {"RAM (MiB)": 1024}), ("network", {"VLAN tag (optional)": 201}), ("close", {})])
            with self.simulate_engine(api, store) as calls:
                wizard.wizard(ui)
            plans = [x["spec"] for x in calls if x["action"] == "plan"]
            self.assertEqual(len(plans), 3)
            expected = deepcopy(plans[0]); expected["memory"]["ram_mib"] = 1024
            self.assertEqual(plans[1], expected)
            expected["network"]["vlan_tag"] = 201
            self.assertEqual(plans[2], expected)
            self.assertIn(("RAM (MiB)", 512), ui.defaults)
            self.assertIn(("VLAN tag (optional)", 200), ui.defaults)
            self.assertIn("RAM / swap: 1024 / 512 MiB", ui.summaries[-1][0])
            self.assertIn("VLAN tag: 201", ui.summaries[-1][0])
            self.assertEqual(api.writes, []); self.assertFalse(store.directory.exists())
            self.assertNotIn(PASSWORD, json.dumps(calls)); self.assertNotIn(PASSWORD, repr(ui.summaries))

    def test_cancel_mid_group_discards_all_partial_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder); api, store = FakePVE(path), Operations(path / "state", os.getuid())
            ui = EditingDialog([("resources", {"Root disk size (GiB)": 20, "CPU cores": 4, "cancel_at": "RAM (MiB)"}), ("close", {})])
            with self.simulate_engine(api, store) as calls:
                wizard.wizard(ui)
            plans = [x["spec"] for x in calls if x["action"] == "plan"]
            self.assertEqual(plans[0], plans[1]); self.assertEqual(api.writes, [])
            self.assertFalse(store.directory.exists())

    def test_invalid_edit_cannot_use_previous_plan_and_can_be_corrected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder); api, store = FakePVE(path), Operations(path / "state", os.getuid())
            ui = EditingDialog([("resources", {"RAM (MiB)": 0}), ("resources", {"RAM (MiB)": 1024}), ("create", {})], True)
            with self.simulate_engine(api, store) as calls:
                wizard.wizard(ui)
            self.assertNotIn("create", ui.summaries[1][1])
            creates = [x for x in calls if x["action"] == "create"]
            self.assertEqual(len(creates), 1)
            self.assertEqual(creates[0]["plan"]["spec"]["memory"]["ram_mib"], 1024)
            self.assertEqual(creates[0]["plan_hash"], digest(creates[0]["plan"]))
            self.assertEqual(creates[0]["secret"], {"password": PASSWORD})
            self.assertEqual([a for a, _ in api.writes], ["create"])

    def test_system_and_start_options_preserve_resource_and_network_choices(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder); api, store = FakePVE(path), Operations(path / "state", os.getuid())
            ui = EditingDialog([("system", {"Container hostname": "edited-host"}),
                                ("startup", {"Start this container when the host boots?": True}), ("close", {})])
            with self.simulate_engine(api, store) as calls:
                wizard.wizard(ui)
            plans = [x["spec"] for x in calls if x["action"] == "plan"]
            expected = deepcopy(plans[0]); expected["hostname"] = "edited-host"
            self.assertEqual(plans[1], expected); expected["onboot"] = True
            self.assertEqual(plans[2], expected); self.assertEqual(api.writes, [])

    def test_access_edit_keeps_password_in_memory_then_switching_to_key_discards_it(self):
        for mode in ("password", "ssh_key"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                path = Path(folder); api, store = FakePVE(path), Operations(path / "state", os.getuid())
                key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                changes = {"Choose how to access the container": mode, "Paste an OpenSSH public key": key}
                ui = EditingDialog([("access", changes), ("create", {})], True)
                with self.simulate_engine(api, store) as calls:
                    wizard.wizard(ui)
                create = next(x for x in calls if x["action"] == "create")
                self.assertEqual(create["plan"]["spec"]["access"]["mode"], mode)
                self.assertEqual(create.get("secret"), {"password": PASSWORD} if mode == "password" else None)
                self.assertNotIn(PASSWORD, json.dumps([x for x in calls if x["action"] != "create"]))
                self.assertNotIn(PASSWORD, repr(ui.summaries) + repr(ui.defaults))

    def test_collision_or_read_error_after_edit_never_submits_a_create(self):
        for failure in ("collision", "read"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                path = Path(folder); api, store = FakePVE(path), Operations(path / "state", os.getuid())
                ui = EditingDialog([("resources", {"RAM (MiB)": 1024}), ("close", {})])
                count = 0
                def before_plan():
                    nonlocal count
                    count += 1
                    if count == 2:
                        if failure == "collision": api.guests = [{"vmid": VMID, "node": NODE, "type": "qemu"}]
                        else: api.nextid_error = True
                with self.simulate_engine(api, store, before_plan) as calls:
                    wizard.wizard(ui)
                self.assertNotIn("create", ui.summaries[-1][1]); self.assertEqual(api.writes, [])
                self.assertNotIn("create", [x["action"] for x in calls]); self.assertFalse(store.directory.exists())


class MenuTests(unittest.TestCase):
    def test_main_menu_create_routing_and_direct_vm_preset(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            scripts, commands = path / "scripts", path / "bin"
            menus = scripts / "menus"
            for directory in (commands, menus, scripts / "global", scripts / "oci"):
                directory.mkdir(parents=True)
            main = (ROOT / "scripts/menus/main_menu.sh").read_text().replace("/usr/local/share/proxmenux", str(path))
            (menus / "main_menu.sh").write_text(main)
            utils = 'load_language() { LANGUAGE=en; }\ninitialize_cache() { :; }\ntranslate() { echo "$1"; }\nmsg_ok() { :; }\n'
            (path / "utils.sh").write_text(utils)
            (scripts / "utils.sh").write_text(utils)
            (scripts / "global/platform-functions.sh").write_text('pmx_is_pbs() { test "$TEST_PLATFORM" = pbs; }\n')
            (menus / "create_vm_menu.sh").write_text('printf "VM %s\\n" "$*"\n')
            (menus / "plain_lxc_wizard.py").write_text('print("plain LXC wizard")\n')
            (menus / "pbs_menu.sh").write_text('echo PBS\n')
            (menus / "menu_Helper_Scripts.sh").write_text('echo Community\n')
            (scripts / "oci/oci_manager_apps.sh").write_text('echo OCI\n')
            (menus / "search_menu.py").write_text(
                f'import sys\nfrom pathlib import Path\nPath(sys.argv[-1]).write_text({str(menus / "create_vm_menu.sh")!r} + "\\n4\\n")\n')
            dialog = commands / "dialog"
            dialog.write_text('#!/bin/bash\nread -r choice < "$TEST_DIALOG_QUEUE" || exit 1\n'
                              'sed -i "1d" "$TEST_DIALOG_QUEUE"\nprintf "%s" "$choice" >&2\n')
            dialog.chmod(0o755)
            queue = path / "queue"
            for product, choices, expected in (
                ("pve", "3\n", "VM"),
                ("pve", "6\n", "Community"),
                ("pve", "o\n", "OCI"),
                ("pve", "search\n", "VM 4"),
                ("pbs", "3\n2\n", "PBS"),
            ):
                with self.subTest(product=product, choices=choices):
                    queue.write_text(choices)
                    result = subprocess.run(["bash", str(menus / "main_menu.sh")], text=True,
                                            capture_output=True, timeout=10, env={
                                                **os.environ, "PATH": str(commands) + ":" + os.environ["PATH"],
                                                "TEST_DIALOG_QUEUE": str(queue), "TEST_PLATFORM": product,
                                            })
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), expected)

    def test_the_installed_tree_contains_the_engine_and_slovak_translations(self):
        for installer in ("install_proxmenux.sh", "install_proxmenux_beta.sh"):
            self.assertIn('cp -r "./scripts/"* "$BASE_DIR/scripts/"', (ROOT / installer).read_text())
        with tempfile.TemporaryDirectory() as folder:
            engine = Path(folder) / "scripts/lxc"
            shutil.copytree(LXC, engine)
            shutil.copytree(ROOT / 'oci/remote', Path(folder) / 'oci/engine/remote')
            result = subprocess.run(["/usr/bin/python3", "-I", "-B", str(engine / "plain_lxc.py")],
                                    input=b"", capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn(json.loads(result.stdout)["error"], {"root_required", "invalid_request"})
            self.assertEqual(result.stderr, b"")
        language = json.loads((ROOT / "lang/sk.json").read_text())
        parsed = ast.parse(Path(wizard.__file__).read_text())
        texts = {
            call.args[0].value for call in ast.walk(parsed)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "N_"
        }
        texts.update(("Create VM and LXC", "Create VM", "Create LXC from template",
                      "Create VM and LXC from template or script"))
        self.assertEqual([key for key in sorted(texts) if not language.get(key)], [])


# Run the real Perl entry point with fake PVE modules. Mapped root grants the
# test only its normal filesystem rights and never touches an actual PVE host.
PERL_DRIVER = r"""
BEGIN {
    $INC{$_} = 1 for qw(PVE/INotify.pm PVE/RPCEnvironment.pm PVE/API2.pm
        PVE/Storage.pm PVE/HA/Config.pm PVE/APLInfo.pm PVE/IPRoute2.pm
        PVE/LXC.pm PVE/LXC/Config.pm PVE/Tools.pm PVE/ProcFSTools.pm);
}
sub record_call {
    return unless $ENV{TEST_CALL_LOG};
    open(my $log, '>>', $ENV{TEST_CALL_LOG}) or die; print {$log} "$_[0]\n"; close($log);
}
sub PVE::RPCEnvironment::fork_worker {
    my ($self, $kind, $vmid, $user, $code) = @_;
    die unless $vmid == 240 && $user eq 'root@pam';
    my $ok = eval { $code->(); 1 };
    if (!$ok) {
        my $error = $@;
        if ($ENV{TEST_ASYNC}) { record_call('TASK ERROR ' . $error); }
        else { die $error; }
    }
    return "UPID:pve-test:00001234:000000001:12345678:$kind:$vmid:root\@pam:";
}
sub PVE::LXC::Config::lock_config {
    my ($class, $vmid, $code) = @_;
    die 'lock busy' if $ENV{TEST_LOCK_BUSY};
    die if $main::locked; local $main::locked = 1; record_call('LOCK');
    my $result = $code->(); record_call('UNLOCK'); return $result;
}
sub PVE::LXC::Config::load_config {
    die unless $main::locked;
    my $conf = {description => $ENV{TEST_MARKER}, unprivileged => $ENV{TEST_PRIVILEGED} ? 0 : 1,
        hostname => $ENV{TEST_CHANGED} ? 'changed' : 'test-lxc', features => 'nesting=0',
        cores => 1, memory => 512, swap => 512, onboot => 0, lxc => [], pending => {},
        rootfs => 'local-lvm:vm-240-disk-0', arch => 'amd64'};
    if ($ENV{TEST_EXTRA_CONFIG}) {
        my $extra = JSON::PP::decode_json($ENV{TEST_EXTRA_CONFIG});
        @$conf{keys %$extra} = values %$extra;
    }
    $conf->{lock} = 'backup' if $ENV{TEST_LOCK};
    $conf->{template} = 1 if $ENV{TEST_CT_TEMPLATE};
    $conf->{pending} = {memory => 1024} if $ENV{TEST_PENDING};
    $conf->{mp0} = '/etc,mp=/host' if $ENV{TEST_MP};
    $conf->{hookscript} = 'local:snippets/untrusted' if $ENV{TEST_HOOK};
    $conf->{net0} = $ENV{TEST_NET0} if $ENV{TEST_NET0};
    return $conf;
}
sub PVE::LXC::Config::json_config_properties {
    return {map {$_=>{}} qw(mp0 mp1 mp2 dev0 dev1 dev2)};
}
sub PVE::LXC::Config::parse_volume {
    my ($class,$key,$text) = @_;
    my ($volume,@options) = split(',', $text);
    my $value = {volume=>$volume,type=>$volume =~ m{\A/} ? 'bind' : 'volume',ro=>0};
    for my $option (@options) { my ($k,$v) = split('=',$option,2); $value->{$k}=$v; }
    $value->{size} = $1*1073741824 if ($value->{size}//'') =~ /\A([0-9]+)G\z/;
    if ($key eq 'rootfs') { $value->{ro}=$ENV{TEST_RO}; $value->{quota}=0; }
    return $value;
}
sub PVE::LXC::Config::parse_device {
    return {map {split('=',$_,2)} split(',',$_[1])};
}
sub PVE::LXC::Config::parse_lxc_network {
    return {hwaddr => 'AA:BB:CC:DD:EE:FF', map {split(/=/, $_, 2)} split(/,/, $_[1])};
}
sub PVE::Storage::parse_volume_id { return split(/:/, $_[0], 2); }
sub PVE::Storage::parse_volname { return ('images', 'disk', $ENV{TEST_OWNER} // 240); }
sub PVE::LXC::parse_id_maps { return ([], 100000, 100000); }
sub PVE::LXC::check_running { $ENV{TEST_RUNNING} }
sub PVE::ProcFSTools::is_mounted {
    return $main::stage_leftover if $_[0] =~ /pve-staged-mounts/;
    return $main::mounted || $ENV{TEST_MOUNTED};
}
sub PVE::LXC::mount_all {
    die unless $main::locked; record_call('MOUNT'); $main::mounted = 1;
    record_call('MOUNT_INCLUDES_DATA') if grep { /\A(?:mp|dev)[0-9]+\z/ } keys %{$_[2]};
    $main::stage_leftover = 1 if $ENV{TEST_STAGE_LEFTOVER};
    die 'mount failure' if $ENV{TEST_MOUNT_FAIL};
    return '/var/lib/lxc/240/rootfs';
}
sub PVE::LXC::umount_all {
    die unless $main::locked; record_call('UNMOUNT');
    record_call('UNMOUNT_INCLUDES_DATA') if grep { /\A(?:mp|dev)[0-9]+\z/ } keys %{$_[2]};
    die 'unmount failure' if $ENV{TEST_UNMOUNT_FAIL};
    return 0 if $ENV{TEST_UNMOUNT_FALSE};
    $main::mounted = 0; return 1;
}
sub PVE::LXC::vm_start {
    die unless $main::locked && !$main::mounted;
    record_call('START'); die 'native start failure' if $ENV{TEST_START_FAIL};
    record_call('START_FULL_CONFIG') if grep { /\A(?:mp|dev)[0-9]+\z/ } keys %{$_[1]};
}
sub PVE::LXC::Config::write_config {
    die unless $main::locked;
    record_call('WRITE_HARDWARE');
}
sub PVE::Tools::run_command {
    my ($cmd, %options) = @_;
    if ($cmd->[3] =~ m{/plain_lxc_resources.py$}) {
        if ($cmd->[4] eq '--check-hardware' || $cmd->[4] eq '--prepare-hardware') {
            die unless $options{timeout} == 180 && $cmd->[5] eq '--json' && $cmd->[6] eq '240';
            my $input = JSON::PP::decode_json($options{input});
            die unless ref($input->{hardware}) eq 'ARRAY' && ref($input->{devices}) eq 'ARRAY';
            record_call($cmd->[4] eq '--prepare-hardware' ? 'PREPARE_HARDWARE' : 'CHECK_HARDWARE');
            die 'hardware policy conflict' if $ENV{TEST_HARDWARE_FAIL};
            die 'hardware preparation failed' if $cmd->[4] eq '--prepare-hardware' && $ENV{TEST_HARDWARE_PREPARE_FAIL};
            my $wanted = JSON::PP::decode_json($ENV{TEST_HARDWARE_LXC} // '[]');
            die 'unexpected lxc directives' if @{$input->{lxc}} && JSON::PP::encode_json($input->{lxc}) ne JSON::PP::encode_json($wanted);
            $options{outfunc}->(JSON::PP::encode_json($wanted));
            return;
        }
        die unless $options{timeout} == 180 && $cmd->[4] eq '--check-device' && $cmd->[6] eq '240';
        record_call('CHECK_DEVICE'); die 'device policy conflict' if $ENV{TEST_DEVICE_POLICY_FAIL};
        return;
    }
    die unless $main::locked && $main::mounted && $options{timeout} == 30
        && $cmd->[0] eq '/usr/bin/python3' && $cmd->[3] =~ m{/plain_lxc_prepare.py$}
        && $cmd->[4] eq '/var/lib/lxc/240/rootfs' && $cmd->[5] eq '100000' && $cmd->[6] eq '100000';
    record_call('PREPARE'); die 'helper failure' if $ENV{TEST_PREPARE_FAIL};
    die 'missing preparation helper' if $ENV{TEST_HELPER_MISSING};
    die 'preparation helper timeout' if $ENV{TEST_HELPER_TIMEOUT};
    if ($ENV{TEST_ROOTFS}) {
        require File::Basename;
        my $code = 'import sys,os;sys.path.insert(0,sys.argv[1]);from plain_lxc_prepare import prepare;prepare(sys.argv[2],os.getuid(),os.getgid(),sys.argv[3]=="1")';
        system('/usr/bin/python3', '-I', '-B', '-c', $code, File::Basename::dirname($cmd->[3]), $ENV{TEST_ROOTFS}, $cmd->[7]) == 0 or die 'rootfs helper failed';
    }
}
sub PVE::INotify::nodename { 'pve-test' }
sub PVE::INotify::inotify_init {}
sub PVE::IPRoute2::ip_link_details {
    return { vmbr0 => { bridge => 1, port => 1 }, vmbr10 => { bridge => 1 },
        vmbr20 => { bridge => 1, vlan_aware => 1 }, nic1 => {} };
}
sub PVE::IPRoute2::ip_link_is_bridge { $_[0]->{bridge} }
sub PVE::IPRoute2::bridge_is_vlan_aware { $_[0]->{vlan_aware} }
sub PVE::IPRoute2::get_physical_bridge_ports {
    my ($bridge, $links) = @_;
    my @ports = $links->{$bridge}->{port} ? ('nic1') : ();
    return @ports;
}
sub PVE::RPCEnvironment::init {
    my ($class, $type, %options) = @_;
    die unless $type eq 'priv';
    $main::atfork = $options{atfork};
    return bless {}, $class;
}
sub PVE::RPCEnvironment::init_request {}
sub PVE::RPCEnvironment::active_workers {
    record_call('TASKS');
    return [{upid=>'UPID:pve-test:00001234:000000001:12345678:vzcreate:240:root@pam:',pid=>1234}]
        if $ENV{TEST_ACTIVE_TASK};
    return [{bad=>'partial'}] if $ENV{TEST_BAD_TASKS};
    return [];
}
sub PVE::RPCEnvironment::set_user { die unless $_[1] eq 'root@pam'; }
sub PVE::Storage::config {
    my $ids = {map { $_ => {} } qw(local offline custom disabled)};
    $ids->{'local-lvm'} = {type => $ENV{TEST_STORAGE_CHANGED} ? 'external' : 'lvmthin'} if $ENV{TEST_MARKER};
    return {ids => $ids};
}
sub PVE::Storage::storage_check_enabled {
    my ($cfg, $storage, $node) = @_;
    die unless $node eq 'pve-test';
    return undef if $storage eq 'disabled';
    return {type => ($storage eq 'custom' ? 'external' : 'dir'), content => {vztmpl => 1}};
}
sub PVE::Storage::Plugin::lookup { die unless $_[1] eq 'dir'; 'MockPlugin' }
sub PVE::Storage::path { $ENV{TEST_ARCHIVE} }
sub PVE::APLInfo::load_data {
    my $name = $ENV{TEST_TEMPLATE};
    return {all => {$name => {
        type => 'lxc', section => 'system', architecture => 'amd64', sha512sum => $ENV{TEST_SHA},
        source => $ENV{TEST_SOURCE}, location => $ENV{TEST_LOCATION} // "http://download.proxmox.com/images/system/$name",
    }}};
}
sub MockPlugin::status { return $_[1] eq 'local' ? (200, 100, 100, 1) : (); }
sub MockPlugin::activate_storage { die 'must never activate storage'; }
sub MockPlugin::list_volumes {
    die unless $_[1] eq 'local' && $_[4][0] eq 'vztmpl';
    return [{volid => 'local:vztmpl/system.tar.zst', size => 50}];
}
sub PVE::HA::Config::vm_is_ha_managed { $ENV{TEST_HA} }
sub PVE::API2::find_handler {
    my ($class, $method, $path, $uri) = @_;
    $uri->{node} = 'pve-test';
    $uri->{vmid} = 240 if $path =~ m{/240/};
    return ('MockAPI', [$method, $path]);
}
sub MockAPI::handle {
    my ($class, $info, $params) = @_;
    my ($method, $path) = @$info;
    if ($ENV{TEST_CALL_LOG}) {
        open(my $log, '>>', $ENV{TEST_CALL_LOG}) or die;
        print {$log} "$method $path\n";
        close($log);
    }
    if ($method eq 'GET') {
        return [{type => 'node', name => 'pve-test', local => 1, online => ($ENV{TEST_OFFLINE} ? 0 : 1)}]
            if $path eq '/cluster/status';
        return {description => $ENV{TEST_MARKER}} if $path eq '/nodes/pve-test/lxc/240/config';
        return {cpuinfo => {cpus => 2}} if $path eq '/nodes/pve-test/status';
        return [] if $path eq '/nodes/pve-test/aplinfo';
        return [{type => 'bridge', active => 1}] if $path eq '/nodes/pve-test/network';
        return [] if $path eq '/cluster/resources' && $params->{type} eq 'vm';
        return $params->{vmid} // 240 if $path eq '/cluster/nextid';
        die;
    }
    if ($path eq '/nodes/pve-test/lxc') {
        print $params->{password};
        warn $params->{password};
        die unless $params->{vmid} == 240 && $params->{node} eq 'pve-test';
        my $pid = fork();
        die unless defined $pid;
        if (!$pid) {
            $main::atfork->();
            sleep 3;
            exit 0;
        }
        return 'UPID:pve-test:00001234:000000001:12345678:vzcreate:240:root@pam:';
    }
    if ($path eq '/nodes/pve-test/aplinfo') {
        die unless $params->{storage} eq 'local' && $params->{template} eq $ENV{TEST_TEMPLATE};
        return "UPID:pve-test:00001234:000000001:12345678:download:$params->{template}:root\@pam:";
    }
    die unless $path eq '/nodes/pve-test/lxc/240/status/start';
    return 'UPID:pve-test:00001234:000000001:12345678:vzstart:240:root@pam:';
}
do $ARGV[0];
die $@ if $@;
"""


class PerlBridgeTests(unittest.TestCase):
    def test_preparation_mount_helper_unmount_and_start_share_one_native_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);log=root/'calls';marker='ProxMenux request '+REQUEST_ID
            for action,expected in (('prepare',['LOCK','MOUNT','PREPARE','UNMOUNT','UNLOCK']),
                                    ('start',['LOCK','MOUNT','PREPARE','UNMOUNT','START','UNLOCK'])):
                result=self.call(action,vmid=VMID,description=marker,expected=NATIVE_EXPECTED,
                                 environment={'TEST_MARKER':marker,'TEST_CALL_LOG':str(log)})
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(json.loads(result.stdout),upid('vzprepare' if action=='prepare' else 'vzstart',VMID))
                self.assertEqual(log.read_text().splitlines(),expected)
                log.unlink()

    def test_all_preparation_failures_have_zero_native_start_and_cleanup_mounts(self):
        cases={'TEST_MOUNT_FAIL':['LOCK','MOUNT','UNMOUNT'],
               'TEST_PREPARE_FAIL':['LOCK','MOUNT','PREPARE','UNMOUNT'],
               'TEST_HELPER_MISSING':['LOCK','MOUNT','PREPARE','UNMOUNT'],
               'TEST_HELPER_TIMEOUT':['LOCK','MOUNT','PREPARE','UNMOUNT'],
               'TEST_UNMOUNT_FAIL':['LOCK','MOUNT','PREPARE','UNMOUNT'],
               'TEST_UNMOUNT_FALSE':['LOCK','MOUNT','PREPARE','UNMOUNT'],
               'TEST_STAGE_LEFTOVER':['LOCK','MOUNT','PREPARE','UNMOUNT']}
        with tempfile.TemporaryDirectory() as folder:
            log=Path(folder)/'calls';marker='ProxMenux request '+REQUEST_ID
            for failure,calls in cases.items():
                with self.subTest(failure=failure):
                    result=self.call('start',vmid=VMID,description=marker,expected=NATIVE_EXPECTED,
                        environment={'TEST_MARKER':marker,'TEST_CALL_LOG':str(log),'TEST_ASYNC':'1',failure:'1'})
                    self.assertEqual(json.loads(result.stdout),upid('vzstart',VMID))
                    rows=log.read_text().splitlines()
                    self.assertEqual(rows[:len(calls)],calls)
                    self.assertNotIn('START',rows)
                    self.assertTrue(any(row.startswith('TASK ERROR ProxMenux preparation failed:') for row in rows))
                    log.unlink()

    def test_conflicting_or_unsafe_container_is_rejected_before_mount_or_start(self):
        with tempfile.TemporaryDirectory() as folder:
            log=Path(folder)/'calls';marker='ProxMenux request '+REQUEST_ID
            for flag,value in (('TEST_MARKER','foreign'),('TEST_PRIVILEGED','1'),('TEST_LOCK','1'),
                ('TEST_HA','1'),('TEST_PENDING','1'),('TEST_RUNNING','1'),('TEST_CHANGED','1'),
                ('TEST_MP','1'),('TEST_HOOK','1'),('TEST_OWNER','999'),('TEST_RO','1'),
                ('TEST_CT_TEMPLATE','1'),('TEST_NET0','name=eth0,bridge=vmbr0'),('TEST_MOUNTED','1'),
                ('TEST_LOCK_BUSY','1'),('TEST_STORAGE_CHANGED','1')):
                with self.subTest(flag=flag):
                    env={'TEST_MARKER':marker,'TEST_CALL_LOG':str(log),flag:value}
                    self.assertEqual(self.call('start',vmid=VMID,description=marker,expected=NATIVE_EXPECTED,environment=env).returncode,1)
                    if log.exists():
                        self.assertEqual(log.read_text().splitlines(),['LOCK'])
                        log.unlink()

    def test_real_filesystem_helper_runs_inside_native_sequence_without_boot_on_conflict(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);guest=root/'guest';guest.mkdir();log=root/'calls'
            path=guest/'usr/lib/systemd/system/systemd-networkd-wait-online.service'
            path.parent.mkdir(parents=True);path.write_text('[Service]\nType=oneshot\nExecStart=/usr/lib/systemd/systemd-networkd-wait-online\n')
            marker='ProxMenux request '+REQUEST_ID
            env={'TEST_MARKER':marker,'TEST_CALL_LOG':str(log),'TEST_ROOTFS':str(guest)}
            result=self.call('start',vmid=VMID,description=marker,expected=NATIVE_EXPECTED,environment=env)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue((guest/'usr/local/libexec/proxmenux-has-network-interface').is_file())
            self.assertIn('START',log.read_text().splitlines());log.unlink()
            target=guest/'etc/systemd/system/systemd-networkd-wait-online.service.d/90-proxmenux-firstboot.conf'
            target.write_text('custom file')
            result=self.call('start',vmid=VMID,description=marker,expected=NATIVE_EXPECTED,environment=env)
            self.assertEqual(result.returncode,1)
            self.assertEqual(target.read_text(),'custom file')
            self.assertNotIn('START',log.read_text().splitlines())

    @classmethod
    def setUpClass(cls):
        cls.prefix = []
        if os.geteuid() != 0:
            if not shutil.which("unshare"):
                raise unittest.SkipTest("user namespace tool unavailable")
            cls.prefix = ["unshare", "--map-root-user", "--"]
            if subprocess.run([*cls.prefix, "true"], capture_output=True).returncode:
                raise unittest.SkipTest("user namespace unavailable")

    def call(self, action, node=NODE, environment=None, **params):
        command = [*self.prefix, "/usr/bin/perl", "-e", PERL_DRIVER, str(LXC / "plain_lxc_pve.pl")]
        request = json.dumps({"action": action, "node": node, "params": params}).encode()
        return subprocess.run(command, input=request, capture_output=True, timeout=2,
                              env={**os.environ, **(environment or {})})

    def test_read_inventory_filters_before_probing_and_never_activates_storage(self):
        result = self.call("inventory")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["storages"], [
            {"storage": "local", "state": "available", "type": "dir", "content": ["vztmpl"],
             "avail": 100, "templates": [{"volid": "local:vztmpl/system.tar.zst", "size": 50}]},
            {"storage": "offline", "state": "unavailable"},
        ])
        self.assertEqual(self.call("inventory", node="other").returncode, 1)

    def test_inspect_batches_discovery_inventory_nextid_and_gates_bad_targets(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder)/'calls'
            env = {'TEST_CALL_LOG': str(log)}
            result = self.call('inspect', node='localhost', environment=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(value['nodes'][0]['name'], NODE)
            self.assertEqual(value['nextid'], VMID)
            self.assertIn('storages', value['inventory'])
            self.assertTrue(all(line.startswith('GET ') for line in log.read_text().splitlines()))
            for target, extra in (('other', {}), ('localhost', {'TEST_OFFLINE': '1'})):
                log.unlink()
                result = self.call('inspect', node=target, environment={**env, **extra})
                self.assertEqual(result.returncode, 0)
                self.assertEqual(set(json.loads(result.stdout)), {'nodes'})
                self.assertEqual(log.read_text().splitlines(), ['GET /cluster/status'])
            log.unlink()
            self.assertEqual(self.call('inspect', node='localhost', environment=env, unexpected='x').returncode, 1)
            self.assertFalse(log.exists())
            result = self.call('inspect', node=NODE, vmid=VMID)
            self.assertEqual(result.returncode, 0)
            value = json.loads(result.stdout)
            self.assertEqual(value['inventory']['nextid'], VMID)
            self.assertEqual(value['inventory']['guests'], [])
            self.assertNotIn('nextid', value)

    def test_native_vlan_detection_uses_kernel_filtering_and_eligible_ports(self):
        result = self.call("inventory", vmid=VMID)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["bridge_vlans"], {"vmbr0": 1, "vmbr10": 0, "vmbr20": 1})
        self.assertEqual((data["guests"], data["nextid"]), ([], VMID))
        self.assertEqual(self.call("inventory", bridge="vmbr0").returncode, 1)

    def test_create_keeps_the_reply_pipe_private_and_rejects_out_of_scope_payloads(self):
        params = {
            "vmid": VMID, "ostemplate": VOLUME, "storage": "local-lvm", "rootfs": "local-lvm:8",
            "description": "ProxMenux request " + REQUEST_ID, "unprivileged": 1, "features": "nesting=0",
            "start": 0, "password": PASSWORD,
        }
        for feature in ("nesting=0", "nesting=1"):
            result = self.call("create", **{**params, "features": feature})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), upid("vzcreate", VMID))
            self.assertEqual(result.stderr, b"")
        for change in ({"force": 1}, {"start": 1}, {"unprivileged": 0}, {"ostemplate": "/tmp/other.tar.zst"},
                       {"rootfs": "local-lvm:vm-240-disk-0"}, {"features": "nesting=2"},
                       {"features": "nesting=1,keyctl=1"}, {"features": "nesting=1\n"}):
            with self.subTest(change=change):
                rejected = self.call("create", **{**params, **change})
                self.assertEqual((rejected.returncode, rejected.stdout, rejected.stderr), (1, b"", b""))

    def test_start_requires_the_same_unlocked_container_and_excludes_ha(self):
        marker = "ProxMenux request " + REQUEST_ID
        for env in ({}, {"TEST_MARKER": marker, "TEST_HA": "1"}):
            self.assertEqual(self.call("start", environment=env, vmid=VMID, description=marker, expected=NATIVE_EXPECTED).returncode, 1)
        result = self.call("start", environment={"TEST_MARKER": marker, "TEST_HA": ""}, vmid=VMID, description=marker, expected=NATIVE_EXPECTED)
        self.assertEqual(json.loads(result.stdout), upid("vzstart", VMID))
        result = self.call("start", environment={"TEST_MARKER": marker + "\n", "TEST_HA": ""}, vmid=VMID, description=marker, expected=NATIVE_EXPECTED)
        self.assertEqual(json.loads(result.stdout), upid("vzstart", VMID))
        for suffix in ("\n\n", " ", "\r\n", "\nforeign text"):
            self.assertEqual(self.call("start", environment={"TEST_MARKER": marker + suffix, "TEST_HA": ""},
                                       vmid=VMID, description=marker, expected=NATIVE_EXPECTED).returncode, 1)

    def test_native_download_checks_index_and_refuses_existing_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / NAME
            env = {"TEST_ARCHIVE": str(archive), "TEST_TEMPLATE": NAME, "TEST_SHA": CHECKSUM,
                   "TEST_SOURCE": "http://download.proxmox.com/images"}
            params = {"storage": "local", "template": NAME, "sha512": CHECKSUM, "architecture": "amd64"}
            result = self.call("download_template", environment=env, **params)
            self.assertEqual(json.loads(result.stdout), upid("download", NAME))
            result = self.call("download_template", environment={**env, "TEST_SOURCE": "https://example.org"}, **params)
            self.assertEqual((result.returncode, result.stdout), (1, b""))
            archive.write_bytes(b"existing file")
            result = self.call("download_template", environment=env, **params)
            self.assertEqual((result.returncode, result.stdout), (1, b""))
            self.assertEqual(archive.read_bytes(), b"existing file")
