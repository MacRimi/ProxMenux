"""The actual Flask route and Monitor guard, with the native PVE boundary simulated."""

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
import urllib.parse
from unittest.mock import Mock, patch

from flask import Flask, g, jsonify, request

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import jwt_middleware
import permissions
import guest_firewall_reads
import pve_mirror


class GuestFirewallReadTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.testing = True
        self.client = self.app.test_client()
        self.inventory = {"105": {"type": "qemu", "node": "test-node"},
                          "106": {"type": "lxc", "node": "test-node"}}
        self.read_inventory = Mock(return_value=self.inventory)
        self.read_config = Mock(side_effect=lambda node, vm_type, vmid:
                                "hostname: test-ct\n" if vm_type == "lxc" else "name: test-vm\n")
        self.stat = Mock(return_value=SimpleNamespace(st_ino=40, st_mtime_ns=500, st_size=200))
        self.process = Mock(side_effect=self.run_pvesh)
        self.ticket = "PVE:fixture@pve:00000000::fixture"
        self.pve = Mock(side_effect=self.pve_request)
        self.pve_create = Mock(side_effect=self.native_create)
        self.grants = {"VM.Audit": 0, "VM.Console": 0}
        self.profile = "admin"
        self.start = "/nodes/test-node"
        self.maps = {"/cluster/firewall/options": {"enable": 1},
                     self.start + "/network": [{"type": "bridge", "iface": "vmbr0"},
                                              {"type": "eth", "iface": "eth0"}],
                     self.start + "/firewall/options": {"enable": 0},
                     self.start + "/services/pve-firewall/state": {
                         "service": "pve-firewall", "state": "running", "active-state": "active"}}
        for guest in ("qemu/105", "lxc/106"):
            base = f"{self.start}/{guest}"
            self.maps.update({
                base + "/firewall/options": {"enable": 1, "digest": "a" * 40},
                base + "/config": {"digest": "b" * 40},
                base + "/pending": [{"key": "net1", "value": "bridge=vmbr0,firewall=1"},
                                    {"key": "net0", "value": "bridge=vmbr0,firewall=1"}],
                base + "/firewall/rules": [],
                base + "/firewall/log": [{"n": 1, "t": "no content"}],
            })
        source = SCRIPTS / "flask_server.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        nodes = [item for item in tree.body if getattr(item, "name", "").startswith("_firewall_")
                 or getattr(item, "name", "") in ("_GuestFirewallError", "api_vm_firewall", "api_write_vm_firewall_rule",
                                                  "api_vm_firewall_settings")
                 or isinstance(item, ast.Assign) and isinstance(item.targets[0], ast.Name)
                 and item.targets[0].id in ("_FIREWALL_WRITE_LOCKS", "_FIREWALL_LOG_LEVELS")]
        scope = dict(app=self.app, require_auth=jwt_middleware.require_auth, jsonify=jsonify,
                     request=request, g=g, re=re, json=json, urllib=urllib,
                     time=SimpleNamespace(time=lambda: 1000),
                     os=SimpleNamespace(stat=self.stat, path=os.path), sys=sys, __file__=str(source),
                     hashlib=hashlib, threading=threading, guest_firewall_reads=guest_firewall_reads,
                     pve_mirror=SimpleNamespace(read_vmlist=self.read_inventory,
                                                guest_config_path=lambda *parts: parts,
                                                read_guest_config=self.read_config,
                                                config_properties=pve_mirror.config_properties),
                     pve_auth=SimpleNamespace(_request=self.pve, write_firewall_rule=self.pve_create,
                                              is_ticket=lambda value: value == self.ticket),
                     subprocess=SimpleNamespace(run=self.process, TimeoutExpired=subprocess.TimeoutExpired,
                                                CalledProcessError=subprocess.CalledProcessError))
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), scope)
        config = patch.object(jwt_middleware, "load_auth_config", return_value={"enabled": True})
        verify = patch.object(jwt_middleware, "verify_token_full", side_effect=lambda token:
                              ("fixture@pve", "full_admin") if token in (self.ticket, "local") else (None, None))
        profile = patch.object(jwt_middleware, "profile_for", side_effect=lambda *args: self.profile)
        refused = patch("access_log.refused")
        for replacement in (config, verify, profile, refused):
            replacement.start()
            self.addCleanup(replacement.stop)

    def native_data(self, path):
        value = self.maps[path]
        if isinstance(value, Exception):
            raise value
        return value

    def run_pvesh(self, command, **kwargs):
        if command[0] == "perl":
            node, guest_type, vmid, mode = command[-4:]
            base = f"/nodes/{node}/{guest_type}/{vmid}"
            return SimpleNamespace(stdout=json.dumps({
                "options": self.native_data(base + "/firewall/options"),
                "config": self.native_data(base + "/config"),
                "pending": self.native_data(base + "/pending"),
                "bridges": self.native_data(f"/nodes/{node}/network") if mode == "settings-network" else [],
            }))
        if command[0] == sys.executable:
            self.assertEqual(command[1:3], ["-I", "-B"])
            node, guest_type, vmid = command[-3:]
            node_path = f"/nodes/{node}"
            with patch.object(guest_firewall_reads, "subprocess", SimpleNamespace(
                    run=self.process, SubprocessError=subprocess.SubprocessError)):
                result = guest_firewall_reads.collect(f"{node_path}/{guest_type}/{vmid}", node_path,
                                                       guest_firewall_reads._pvesh_read)
            return SimpleNamespace(stdout=json.dumps(result))
        if command[0] == "pvesh" and command[1] in ("create", "set", "delete"):
            options = dict(item[2:].split("=", 1) for item in command[3:])
            if "enable" in options:
                options["enable"] = int(options["enable"])
            self.native_create(command[2], options, None, method={"create": "POST", "set": "PUT", "delete": "DELETE"}[command[1]])
            return SimpleNamespace(stdout="")
        self.assertEqual(command[:2], ["pvesh", "get"])
        self.assertEqual(command[3:5], ["--output-format", "json"])
        self.assertTrue(kwargs["check"])
        return SimpleNamespace(stdout=json.dumps(self.native_data(command[2])))

    def pve_request(self, method, url, ticket=None):
        self.assertEqual((method, ticket), ("GET", self.ticket))
        path = urlsplit(url).path
        if path == "/access/permissions":
            guest_path, = parse_qs(urlsplit(url).query)["path"]
            return 200, {guest_path: self.grants}
        return 200, self.native_data(path)

    def native_create(self, path, parameters, ticket, *, method="POST"):
        if method == "PUT" and path.endswith("/firewall/options"):
            self.assertEqual(parameters["digest"], self.maps[path]["digest"])
            self.maps[path].update({**parameters, "digest": "c" * 40})
            return 200
        if method == "PUT" and path.endswith("/config"):
            self.assertEqual(parameters["digest"], self.maps[path]["digest"])
            pending = self.maps[path.rsplit("/", 1)[0] + "/pending"]
            for name, value in parameters.items():
                if name == "digest":
                    continue
                previous = next((row for row in pending if row["key"] == name), None)
                if previous is None:
                    pending.append({"key": name, "pending": value.replace("virtio,", "virtio=AA:BB:CC:DD:EE:FF,")})
                else:
                    previous["value"] = value
            self.maps[path]["digest"] = "e" * 40
            return 200
        if method in ("PUT", "DELETE"):
            parent, _, position = path.rpartition("/")
            row = self.maps[parent][int(position)]
            self.assertEqual(parameters["digest"], row["digest"])
            if "moveto" in parameters:
                self.assertEqual(set(parameters), {"digest", "moveto"})
                slot = int(parameters["moveto"])
                ordered = self.maps[parent]
                reordered = ordered[:slot] + [row] + ordered[slot:]
                del reordered[int(position) + int(slot <= int(position))]
                self.maps[parent] = [dict(rule, pos=i) for i, rule in enumerate(reordered)]
                return 200
            if method == "DELETE":
                del self.maps[parent][int(position)]
                for pos, remaining in enumerate(self.maps[parent]):
                    remaining["pos"] = pos
                return 200
            for field in filter(None, parameters.get("delete", "").split(",")):
                row.pop(field, None)
            row.update({key: value for key, value in parameters.items() if key not in ("delete", "digest")})
            return 200
        self.maps[path] = [{"pos": 0, **parameters}, *[
            dict(row, pos=row["pos"] + 1) for row in self.maps[path]
        ]]
        return 200

    def read(self, section, vmid=105, vm_type="qemu", node="test-node", token="local"):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = self.client.get(f"/api/vms/{vmid}/firewall/{section}",
                                   query_string={"type": vm_type, "node": node}, headers=headers)
        return response.status_code, response.get_json()

    def settings(self, vmid, guest_type, token="local", *, network=False):
        response = self.client.get(f"/api/vms/{vmid}/firewall/settings", query_string={
            "node": "test-node", "type": guest_type, **({"network": "1"} if network else {}),
        }, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def save_settings(self, snapshot, token="local", **changes):
        return self.client.put(f"/api/vms/{snapshot['vmid']}/firewall/settings", json={
            **{key: snapshot[key] for key in ("node", "type", "revision")}, **changes,
        }, headers={"Authorization": f"Bearer {token}"} if token else {})

    def test_settings_preserve_rules_and_other_properties_and_disable_before_nic_change(self):
        self.grants["VM.Config.Network"] = 0
        base = self.start + "/qemu/105"
        self.maps[base + "/pending"] = [
            {"key": "net0", "value": "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,firewall=1,tag=8,mtu=1500"},
            {"key": "net1", "value": "e1000=AA:BB:CC:DD:EE:00,bridge=vmbr0,firewall=1"},
        ]
        self.maps[base + "/firewall/options"]["dhcp"] = 1
        self.maps[base + "/firewall/rules"] = [{"pos": 0, "type": "in", "action": "ACCEPT", "enable": 1}]
        view = self.settings(105, "qemu", self.ticket)
        self.assertEqual(view["settings"]["policy_in"], "DROP")
        self.assertNotIn("digest", view)
        response = self.save_settings(view, self.ticket, options={"enabled": False, "log_level_in": "info"},
                                      interfaces={"net0": False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["applied"], ["settings", "interfaces"])
        self.assertEqual(self.maps[base + "/pending"][0]["value"],
                         "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,tag=8,mtu=1500,firewall=0")
        self.assertTrue(self.maps[base + "/pending"][1]["value"].endswith("firewall=1"))
        self.assertEqual(self.maps[base + "/firewall/rules"][0]["enable"], 1)
        self.assertEqual(self.maps[base + "/firewall/options"]["dhcp"], 1)
        repeated = self.save_settings(view, self.ticket, options={"enabled": False}, interfaces={})
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(self.pve_create.call_count, 2)

    def test_attach_lxc_static_and_qemu_pending_with_explicit_bridge_and_digest(self):
        for vmid, kind in ((106, "lxc"), (105, "qemu")):
            base = self.start + f"/{kind}/{vmid}"
            self.maps[base + "/firewall/options"].pop("enable")
            self.maps[base + "/pending"] = [{"key": "net1", "pending": "name=eth0,bridge=vmbr0,firewall=0"}]
            snapshot = self.settings(vmid, kind, network=True)
            self.assertEqual(snapshot["bridges"], ["vmbr0"])
            detail = {"bridge": "vmbr0", "vlan": 42, "firewall": True}
            detail.update({"mode": "static", "ip": "192.0.2.2/24", "gateway": "192.0.2.1"} if kind == "lxc"
                          else {"model": "virtio"})
            response = self.save_settings(snapshot, options={"enabled": True}, network=detail)
            self.assertEqual(response.status_code, 200)
            result = response.get_json()
            self.assertEqual((result["applied"], result["pending"], result["interface"]),
                             (["settings", "interfaces"], ["net0"], "net0"))
            definition = self.maps[base + "/pending"][1]["pending"]
            self.assertIn("tag=42", definition)
            self.assertIn("name=eth1" if kind == "lxc" else "virtio=AA:BB", definition)
            if kind == "lxc":
                self.assertIn("ip=192.0.2.2/24", definition)
                self.assertIn("gw=192.0.2.1", definition)

    def test_settings_refuse_unapproved_targets_and_partial_write_is_reported(self):
        view = self.settings(106, "lxc", network=True)
        self.assertEqual(self.save_settings(view, None, options={}, interfaces={}).status_code, 401)
        self.assertEqual(self.save_settings(view, self.ticket, options={}, interfaces={}).status_code, 403)
        self.grants["VM.Config.Network"] = 0
        base = self.start + "/lxc/106"
        self.maps[base + "/pending"][0]["pending"] = "name=eth0,bridge=vmbr0,firewall=0"
        view = self.settings(106, "lxc", self.ticket, network=True)
        self.assertEqual(self.save_settings(view, self.ticket, options={}, interfaces={"net1": False}).status_code, 400)
        self.assertEqual(self.save_settings(view, self.ticket, options={}, network={
            "bridge": "eth0", "vlan": None, "firewall": True, "mode": "dhcp", "ip": "", "gateway": "",
        }).status_code, 400)
        self.pve_create.assert_not_called()
        self.pve_create.side_effect = lambda path, *args, **kw: self.native_create(path, *args, **kw) \
            if path.endswith("/options") else 503
        result = self.save_settings(view, self.ticket, options={"enabled": False}, interfaces={"net0": False})
        self.assertEqual(result.status_code, 502)
        self.assertEqual(result.get_json(), {"applied": ["settings"], "error": "firewall_settings_uncertain"})
        self.assertEqual(self.maps[base + "/firewall/options"]["enable"], 0)
        self.assertTrue(self.maps[base + "/pending"][1]["value"].endswith("firewall=1"))

    def add_rule(self, vmid=105, guest_type="qemu", token="local", revision=None, *, enabled=None, position=None, **draft):
        if revision is None:
            revision = self.read("rules", vmid, guest_type, token=token)[1].get("add_rule_revision")
        return self.client.open(f"/api/vms/{vmid}/firewall/rules", method="PUT" if position is not None else "POST", json={
            "node": "test-node", "type": guest_type, "revision": revision,
            "rule": {"direction": "IN", "action": "ACCEPT", "protocol": "tcp", "dport": "22", **draft},
            **({"enabled": enabled} if enabled is not None else {}),
            **({"pos": position} if position is not None else {}),
        }, headers={"Authorization": f"Bearer {token}"})

    def test_add_disabled_to_both_guest_types_and_preserve_rule_order(self):
        self.grants["VM.Config.Network"] = 0
        for vmid, guest_type, token in ((105, "qemu", "local"), (106, "lxc", self.ticket)):
            with self.subTest(guest_type=guest_type):
                path = f"{self.start}/{guest_type}/{vmid}/firewall/rules"
                self.maps[path] = [{"pos": 0, "type": "out", "action": "DROP", "enable": 1, "comment": "existing"}]
                response = self.add_rule(vmid, guest_type, token, iface="net1", comment="draft")
                self.assertEqual(response.status_code, 201, response.get_json())
                rules = self.read("rules", vmid, guest_type, token=token)[1]["rules"]
                self.assertEqual([(row["pos"], row["enabled"], row["comment"]) for row in rules],
                                 [(0, False, "draft"), (1, True, "existing")])
        self.pve_create.assert_called_once_with(f"{self.start}/lxc/106/firewall/rules",
                                              {"type": "in", "action": "ACCEPT", "proto": "tcp", "enable": 0,
                                               "dport": "22", "iface": "net1", "comment": "draft"}, self.ticket,
                                              method="POST")

    def test_explicit_enabled_add_and_position_preserving_edit_for_vm_and_lxc(self):
        self.grants["VM.Config.Network"] = 0
        for vmid, guest_type, token, enable in ((105, "qemu", "local", 1), (106, "lxc", self.ticket, 0)):
            with self.subTest(guest_type=guest_type):
                path = f"{self.start}/{guest_type}/{vmid}/firewall/rules"
                self.maps[path] = [
                    {"pos": 0, "type": "group", "action": "keep", "enable": 1, "digest": "a" * 40},
                    {"pos": 1, "type": "in", "action": "ACCEPT", "proto": "tcp", "dport": "80",
                     "enable": enable, "source": "192.0.2.0/24", "comment": "old", "digest": "a" * 40},
                ]
                before = self.read("rules", vmid, guest_type, token=token)[1]
                self.assertEqual(before["editable_rule_positions"], [1])
                self.assertEqual(self.add_rule(vmid, guest_type, token, position=1, enabled=True).status_code, 400)
                self.assertEqual(self.add_rule(vmid, guest_type, token, position=0).status_code, 409)
                response = self.add_rule(vmid, guest_type, token, position=1, dport="443")
                self.assertEqual(response.status_code, 200, response.get_json())
                self.assertEqual(self.add_rule(vmid, guest_type, token, revision=before["add_rule_revision"],
                                               position=1).status_code, 409)
                row = self.maps[path][1]
                self.assertEqual((row["pos"], row["enable"], row["dport"]), (1, enable, "443"))
                self.assertNotIn("comment", row)
                self.assertNotIn("source", row)
                self.assertEqual(self.maps[path][0]["action"], "keep")
                self.assertEqual(self.add_rule(vmid, guest_type, token, enabled=True).status_code, 201)
                self.assertEqual(self.maps[path][0]["enable"], 1)
                self.assertEqual(self.maps[path][2]["enable"], enable)

    def test_rule_log_level_can_be_set_preserved_and_cleared(self):
        self.grants["VM.Config.Network"] = 0
        path = self.start + "/lxc/106/firewall/rules"
        args = (106, "lxc", self.ticket)
        for invalid in ("verbose", "", 6, ["info", "warning"]):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.add_rule(*args, log=invalid).status_code, 400)
        self.pve_create.assert_not_called()
        self.assertEqual(self.add_rule(*args, log="warning").status_code, 201)
        self.maps[path][0]["digest"] = "a" * 40
        self.assertEqual(self.add_rule(*args, position=0, comment="legacy client").status_code, 200)
        self.assertEqual(self.maps[path][0]["log"], "warning")
        self.assertEqual(self.add_rule(*args, position=0, log="info").status_code, 200)
        self.assertEqual(self.read("rules", *args[:2], token=self.ticket)[1]["rules"][0]["log"], "info")
        self.assertEqual(self.add_rule(*args, position=0, log="nolog").status_code, 200)
        self.assertEqual(self.pve_create.call_args.args[1]["delete"], "log")
        self.assertNotIn("log", self.maps[path][0])
        self.assertFalse(self.read("rules", *args[:2], token=self.ticket)[1]["rules"][0]["enabled"])

    def test_state_change_and_delete_use_digest_and_preserve_other_rules(self):
        self.grants["VM.Config.Network"] = 0
        path = self.start + "/lxc/106/firewall/rules"
        self.maps[path] = [
            {"pos": 0, "type": "in", "action": "ACCEPT", "proto": "tcp", "dport": "443", "enable": 0, "digest": "a" * 40},
            {"pos": 1, "type": "in", "action": "DROP", "proto": "tcp", "dport": "22", "enable": 1, "digest": "a" * 40},
        ]
        start = self.read("rules", 106, "lxc", token=self.ticket)[1]
        self.assertEqual(start["writable_rule_positions"], [0, 1])
        payload = {"node": "test-node", "type": "lxc", "revision": start["add_rule_revision"], "pos": 0}
        headers = {"Authorization": f"Bearer {self.ticket}"}
        self.assertEqual(self.client.patch("/api/vms/106/firewall/rules", json={**payload, "enabled": 1},
                                           headers=headers).status_code, 400)
        self.assertEqual(self.client.patch("/api/vms/106/firewall/rules", json={**payload, "enabled": True},
                                           headers=headers).status_code, 200)
        self.assertEqual(self.client.delete("/api/vms/106/firewall/rules", json=payload, headers=headers).status_code, 409)
        self.assertEqual(self.pve_create.call_count, 1)
        self.assertEqual(self.pve_create.call_args.kwargs["method"], "PUT")
        self.assertEqual(self.pve_create.call_args.args[1], {"enable": 1, "digest": "a" * 40})
        payload["revision"] = self.read("rules", 106, "lxc", token=self.ticket)[1]["add_rule_revision"]
        self.assertEqual(self.client.delete("/api/vms/106/firewall/rules", json=payload, headers=headers).status_code, 200)
        self.assertEqual(self.pve_create.call_args.kwargs["method"], "DELETE")
        self.assertEqual(self.pve_create.call_args.args[1], {"digest": "a" * 40})
        self.assertEqual([(row["pos"], row["action"], row["enable"]) for row in self.maps[path]], [(0, "DROP", 1)])

    def test_rule_move_uses_native_slots_and_preserves_rule_fields(self):
        self.grants["VM.Config.Network"] = 0
        for vmid, guest_type, token in ((105, "qemu", "local"), (106, "lxc", self.ticket)):
            with self.subTest(guest_type=guest_type):
                path = f"{self.start}/{guest_type}/{vmid}/firewall/rules"
                original = [
                    {"pos": 0, "type": "in", "action": "DROP", "proto": "tcp", "source": "0.0.0.0/0", "enable": 1},
                    {"pos": 1, "type": "in", "action": "ACCEPT", "proto": "tcp", "dport": "22", "enable": 1},
                    {"pos": 2, "type": "group", "action": "web", "enable": 0},
                    {"pos": 3, "type": "in", "action": "ACCEPT", "proto": "tcp", "dport": "443", "enable": 1},
                ]
                self.maps[path] = [dict(row, digest="a" * 40) for row in original]
                for source, target, slot, expected in ((0, 3, 4, [1, 2, 3, 0]), (3, 0, 0, [0, 1, 2, 3]), (0, 1, 2, [1, 0, 2, 3])):
                    revision = self.read("rules", vmid, guest_type, token=token)[1]["add_rule_revision"]
                    response = self.client.patch(f"/api/vms/{vmid}/firewall/rules", headers={"Authorization": f"Bearer {token}"},
                                                 json={"node": "test-node", "type": guest_type, "revision": revision,
                                                       "pos": source, "to": target})
                    self.assertEqual(response.status_code, 200)
                    result = response.get_json()
                    self.assertTrue(result["moved"])
                    self.assertNotEqual(result["rules_snapshot"]["add_rule_revision"], revision)
                    readback = self.read("rules", vmid, guest_type, token=token)[1]
                    self.assertEqual(result["rules_snapshot"], {key: value for key, value in readback.items()
                                                               if key not in ("vmid", "node", "type")})
                    self.assertEqual(self.maps[path], [dict(original[i], pos=pos, digest="a" * 40)
                                                       for pos, i in enumerate(expected)])
                    if token == self.ticket:
                        self.pve_create.assert_called_with(f"{path}/{source}", {"digest": "a" * 40, "moveto": slot},
                                                           self.ticket, method="PUT")
                    else:
                        self.assertTrue(any(call.args[0] == ["pvesh", "set", f"{path}/{source}",
                                                             "--digest=" + "a" * 40, f"--moveto={slot}"]
                                            for call in self.process.call_args_list))

    def test_rule_move_rejects_mixed_stale_or_missing_confirmation_results(self):
        self.grants["VM.Config.Network"] = 0
        path = f"{self.start}/lxc/106/firewall/rules"
        self.maps[path] = [
            {"pos": 0, "type": "in", "action": "DROP", "enable": 1, "digest": "a" * 40},
            {"pos": 1, "type": "in", "action": "ACCEPT", "enable": 1, "digest": "a" * 40},
        ]
        headers = {"Authorization": f"Bearer {self.ticket}"}
        revision = self.read("rules", 106, "lxc", token=self.ticket)[1]["add_rule_revision"]
        payload = {"node": "test-node", "type": "lxc", "revision": revision, "pos": 0, "to": 1}
        endpoint = "/api/vms/106/firewall/rules"
        for values in ({"to": True}, {"to": 0}, {"to": 2}, {"enabled": False}):
            self.assertEqual(self.client.patch(endpoint, headers=headers, json={**payload, **values}).status_code, 400)
        self.maps[path] = [dict(row, digest="b" * 40) for row in self.maps[path]]
        self.assertEqual(self.client.patch(endpoint, headers=headers, json=payload).status_code, 409)
        self.pve_create.assert_not_called()
        self.pve_create.side_effect = None
        self.pve_create.return_value = 200
        payload["revision"] = self.read("rules", 106, "lxc", token=self.ticket)[1]["add_rule_revision"]
        uncertain = self.client.patch(endpoint, headers=headers, json=payload)
        self.assertEqual(uncertain.status_code, 502)
        self.assertNotIn("rules_snapshot", uncertain.get_json())
        self.pve_create.assert_called_once()

    def test_native_overview_batch_and_older_installation_fallback(self):
        result = {"guest": {}, "host": {}, "cluster": None, "config": [], "service": None}
        with patch.object(guest_firewall_reads.socket, "gethostname", return_value="test-node.example"), \
             patch.object(guest_firewall_reads.subprocess, "run") as run, \
             patch.object(guest_firewall_reads, "collect") as fallback:
            run.return_value.stdout = json.dumps(result)
            self.assertEqual(guest_firewall_reads.read_overview("test-node", "lxc", "106"), result)
            self.assertEqual(run.call_args.args[0][-3:], ["test-node", "lxc", "106"])
            fallback.assert_not_called()
            run.return_value.stdout = "unsupported"
            self.assertIs(guest_firewall_reads.read_overview("test-node", "lxc", "106"), fallback.return_value)
            run.reset_mock()
            self.assertIs(guest_firewall_reads.read_overview("other-node", "lxc", "106"), fallback.return_value)
            run.assert_not_called()

    def test_write_refuses_permissions_identity_invalid_and_stale_forms(self):
        revision = self.read("rules")[1]["add_rule_revision"]
        self.assertEqual(self.add_rule(token=self.ticket, revision=revision).status_code, 403)
        self.assertEqual(self.add_rule(guest_type="lxc", revision=revision).status_code, 409)
        self.assertEqual(self.add_rule(revision=revision, iface="eth0").status_code, 400)
        self.assertEqual(self.add_rule(revision=revision, iface="net44").status_code, 400)
        self.assertEqual(self.add_rule(revision=revision, enable=1).status_code, 400)
        self.assertEqual(self.add_rule(revision=revision, dport="100:22").status_code, 400)
        self.assertEqual(self.add_rule(revision="old").status_code, 409)
        self.profile = "observer"
        self.assertIsNone(self.read("rules")[1]["add_rule_revision"])
        self.assertEqual(self.add_rule(revision=revision).status_code, 403)
        self.pve_create.assert_not_called()
        self.assertFalse(any(call.args[0][1] == "create" for call in self.process.call_args_list))

    def test_uncertain_rule_readback_never_retries_write(self):
        self.grants["VM.Config.Network"] = 0
        self.pve_create.side_effect = None
        self.pve_create.return_value = 200
        response = self.add_rule(token=self.ticket)
        self.assertEqual((response.status_code, response.get_json()["error"]), (502, "firewall_rule_uncertain"))
        self.assertEqual(self.pve_create.call_count, 1)

    def test_both_guest_types_use_current_interface_flags_and_ignore_host_enable(self):
        for vmid, vm_type in ((105, "qemu"), (106, "lxc")):
            with self.subTest(vm_type=vm_type):
                code, status = self.read("status", vmid, vm_type)
                self.assertEqual((code, status["status"], status["service"]), (200, "configured", "running"))
                self.assertEqual([item["name"] for item in status["interfaces"]], ["net0", "net1"])
                self.assertEqual((status["vmid"], status["type"], status["node"]), (vmid, vm_type, "test-node"))
        self.assertFalse(any("firewall/log" in call.args[0][2] for call in self.process.call_args_list))

    def test_overview_overlaps_independent_reads_and_selects_service_from_node_settings(self):
        host_path = self.start + "/firewall/options"
        cluster_path = "/cluster/firewall/options"
        guest_path = self.start + "/qemu/105/firewall/options"
        service_path = self.start + "/services/proxmox-firewall/state"
        self.maps[host_path] = {"nftables": 1}
        self.maps[service_path] = {"service": "proxmox-firewall", "active-state": "active"}
        rendezvous = threading.Barrier(3)
        host_ready = threading.Event()

        def overlapping_read(command, **kwargs):
            path = command[2]
            if path in (host_path, cluster_path, guest_path):
                rendezvous.wait(timeout=2)
            if path == service_path:
                self.assertTrue(host_ready.is_set())
            data = self.run_pvesh(command, **kwargs)
            if path == host_path:
                host_ready.set()
            return data

        self.process.side_effect = overlapping_read
        code, status = self.read("status")
        self.assertEqual((code, status["backend"], status["service"]), (200, "nftables", "running"))
        paths = [call.args[0][2] for call in self.process.call_args_list if call.args[0][:2] == ["pvesh", "get"]]
        self.assertCountEqual(paths, [host_path, cluster_path, guest_path, service_path,
                                      self.start + "/qemu/105/pending"])

    def test_partial_coverage_and_pending_add_change_remove(self):
        self.maps[self.start + "/lxc/106/pending"] = [
            {"key": "net0", "value": "bridge=vmbr0,firewall=1", "delete": 2},
            {"key": "net1", "value": "bridge=vmbr1", "pending": "bridge=vmbr1,firewall=1"},
            {"key": "net2", "pending": "bridge=vmbr0,firewall=1"},
            {"key": "irrelevant", "value": "do not transmit"},
        ]
        code, data = self.read("status", 106, "lxc")
        self.assertEqual((code, data["status"]), (200, "partial"))
        self.assertEqual([(row["coverage"], row["pending"], row["pending_flag"]) for row in data["interfaces"]],
                         [("configured", "remove", None), ("disabled", "change", True), ("absent", "add", True)])
        self.assertNotIn("do not transmit", str(data))

    def test_disabled_unknown_and_no_network_are_distinct(self):
        cluster = "/cluster/firewall/options"
        self.maps[cluster] = {"enable": 0}
        self.assertEqual(self.read("status")[1]["status"], "disabled")
        self.maps[cluster] = subprocess.TimeoutExpired([], 6)
        self.assertEqual(self.read("status")[1]["status"], "unknown")
        self.maps[cluster] = {"enable": 1}
        self.maps[self.start + "/qemu/105/pending"] = [{"key": "net0", "value": False}]
        self.assertEqual(self.read("status")[1]["status"], "unknown")
        self.maps[self.start + "/qemu/105/pending"] = []
        self.assertEqual(self.read("status")[1]["status"], "noInterfaces")
        self.maps[self.start + "/qemu/105/pending"] = [{"key": "net0", "value": "bridge=vmbr0,firewall=1"}]
        self.maps[self.start + "/firewall/options"] = {"nftables": 1}
        service = self.start + "/services/proxmox-firewall/state"
        self.maps[service] = {"service": "proxmox-firewall", "unit-state": "not-found"}
        self.assertEqual(self.read("status")[1]["status"], "unknown")
        self.maps[service] = {"service": "proxmox-firewall", "active-state": "inactive"}
        self.assertEqual(self.read("status")[1]["status"], "disabled")

    def test_native_timed_cluster_enable_boundary(self):
        for timestamp, enabled in ((941, True), (940, True), (939, False)):
            with self.subTest(timestamp=timestamp):
                self.maps["/cluster/firewall/options"] = {"enable": timestamp}
                self.assertIs(self.read("status")[1]["cluster_enabled"], enabled)

    def test_native_order_and_disabled_group_are_preserved(self):
        self.maps[self.start + "/qemu/105/firewall/rules"] = [
            {"pos": 0, "type": "in", "action": "ACCEPT", "enable": 1, "dport": "443", "digest": "private"},
            {"pos": 1, "type": "group", "action": "web-access", "enable": 0, "iface": "net1"},
            {"pos": 2, "type": "out", "action": "DROP", "enable": 1},
        ]
        code, data = self.read("rules")
        self.assertEqual(code, 200)
        self.assertEqual([(rule["pos"], rule["action"], rule["enabled"]) for rule in data["rules"]],
                         [(0, "ACCEPT", True), (1, "web-access", False), (2, "DROP", True)])
        self.assertNotIn("digest", data["rules"][0])

    def test_native_empty_log_file_error_and_foreign_line_are_distinct(self):
        log_path = self.start + "/qemu/105/firewall/log"
        self.assertEqual(self.read("log")[1]["logs"], [])
        for value in ([{"n": 1, "t": "unable to open file - No such file or directory"}],
                      [{"n": 1, "t": "106 IN ACCEPT"}], {"logs": []},
                      subprocess.CalledProcessError(404, [])):
            with self.subTest(value=value):
                self.maps[log_path] = value
                self.assertEqual(self.read("log"), (502, {"error": "firewall_read_failed"}))
        self.maps[log_path] = [{"n": 3, "t": "105 IN ACCEPT"}]
        self.assertEqual(self.read("log")[1], {"node": "test-node", "type": "qemu", "vmid": 105,
                                              "logs": self.maps[log_path], "log_lines": 1})
        self.read_config.assert_not_called()
        legacy = self.client.get("/api/vms/105/firewall/log?start=2&limit=5",
                                 headers={"Authorization": "Bearer local"})
        self.assertEqual(legacy.get_json(), {"node": "test-node", "type": "qemu", "vmid": 105,
                                             "logs": self.maps[log_path], "log_lines": 1,
                                             "name": "test-vm", "firewall_enabled": True})
        self.read_config.assert_called_once_with("test-node", "qemu", 105)
        self.assertEqual(self.process.call_args.args[0][-4:], ["--start", "2", "--limit", "5"])

    def test_monitor_guard_precedes_all_pve_reads_and_methods_are_read_only(self):
        self.assertEqual(self.read("status", token=None)[0], 401)
        self.profile = permissions.custom_profile(["node"], [])
        self.assertEqual(self.read("rules")[0], 403)
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertEqual(self.client.open("/api/vms/105/firewall/log", method=method).status_code, 405)
        self.pve.assert_not_called()
        self.stat.assert_not_called()
        self.read_inventory.assert_not_called()
        self.process.assert_not_called()

    def test_native_audit_and_console_are_independent_and_precede_lookup(self):
        self.grants = {"VM.Audit": 0}
        self.assertEqual(self.read("log", token=self.ticket)[0], 403)
        self.read_inventory.assert_not_called()
        self.assertEqual(self.read("status", token=self.ticket)[0], 200)
        self.assertEqual(self.read("rules", token=self.ticket)[0], 200)
        self.grants = {"VM.Console": 0}
        self.read_inventory.reset_mock()
        self.assertEqual(self.read("status", token=self.ticket)[0], 403)
        self.assertEqual(self.read("rules", token=self.ticket)[0], 403)
        self.read_inventory.assert_not_called()
        self.assertEqual(self.read("log", token=self.ticket)[0], 200)
        self.process.assert_not_called()

    def test_wrong_target_and_concurrent_move_are_rejected(self):
        self.assertEqual(self.read("status", vm_type="lxc")[0], 409)
        self.assertEqual(self.read("rules", node="other-node")[0], 409)
        self.process.assert_not_called()
        self.read_inventory.side_effect = [
            self.inventory, {"105": {"type": "qemu", "node": "other-node"}},
        ]
        self.assertEqual(self.read("log"), (409, {"error": "guest_changed"}))

    def test_changed_configuration_signature_discards_result(self):
        self.stat.side_effect = [
            SimpleNamespace(st_ino=40, st_mtime_ns=500, st_size=200),
            SimpleNamespace(st_ino=41, st_mtime_ns=500, st_size=200),
        ]
        self.assertEqual(self.read("rules"), (409, {"error": "guest_changed"}))


if __name__ == "__main__":
    unittest.main()
