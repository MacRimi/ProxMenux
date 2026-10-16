"""USB/IP ownership, device identity, SSH policy and service regression tests.

No physical USB devices, live systemd units or host configuration are changed.
The optional Linux integration lane exercises actual SSH, socat and namespaces.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "scripts/devices/usbip_manager.py"
EXPORT = "abcdef123456"
CLIENT = "fedcba654321"


def load():
    spec = importlib.util.spec_from_file_location("usbip_manager", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class USBIPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.m = load()
        for attr, path in (("CONFIG_DIR", "config"), ("RUN_DIR", "client-run"),
                           ("SERVER_RUN_DIR", "server-run"), ("UNIT_DIR", "units"), ("SYSFS", "sysfs")):
            setattr(self.m, attr, self.root / path)
            getattr(self.m, attr).mkdir()
        self.calls = []
        self.key = self.root / "id_ed25519"
        self.key.write_text("test-key")
        self.key.chmod(0o600)
        self.remote = {"host": "usb.example.test", "ssh_port": 2222, "key": str(self.key)}

    def config(self, exports=None, imports=None, server=True):
        value = {"server": server, "exports": exports or [], "imports": imports or []}
        self.m.atomic_json(self.m.CONFIG_DIR / "config.json", value)
        return value

    def device(self, busid="1-2", serial="zigbee-123", device_class="00", interface="03", driver="usb"):
        path = self.m.SYSFS / busid
        path.mkdir()
        values = {"idVendor": "10c4", "idProduct": "ea60", "serial": serial,
                  "product": "Test Zigbee adapter", "bDeviceClass": device_class}
        for key, value in values.items():
            (path / key).write_text(value)
        child = path / f"{busid}:1.0"
        child.mkdir()
        (child / "bInterfaceClass").write_text(interface)
        self.set_driver(busid, driver)
        return next(d for d in self.m.inventory() if d["busid"] == busid)

    def set_driver(self, busid, driver):
        target = self.root / "drivers" / driver
        target.mkdir(parents=True, exist_ok=True)
        path = self.m.SYSFS / busid / "driver"
        path.unlink(missing_ok=True)
        path.symlink_to(target, target_is_directory=True)

    def selected(self, device):
        return {k: device[k] for k in ("busid", "vendor", "product", "serial", "name")} | {"id": EXPORT}

    def usb(self, args, timeout=20):
        self.calls.append(args)
        if args[:2] == ["usbip", "bind"]:
            self.set_driver(args[-1], "usbip-host")
        elif args[:2] == ["usbip", "unbind"]:
            self.set_driver(args[-1], "usb")
        return ""

    def test_storage_composite_interfaces_and_hubs_are_never_exported(self):
        for index, (base, interface) in enumerate((("08", "06"), ("09", "00"), ("00", "08"), ("", "03"))):
            device = self.device(busid=f"1-{index + 1}", device_class=base, interface=interface)
            self.assertTrue(device["blocked"])
            self.config()
            with self.assertRaises(self.m.USBIPError), patch.object(self.m, "run") as command:
                self.m.add_export(device["busid"])
            command.assert_not_called()
        self.assertEqual(self.m.load_config()["exports"], [])

    def test_export_intent_is_private_and_bind_is_idempotent(self):
        device = self.device()
        self.config()
        selected = self.m.add_export(device["busid"])
        owned = {}
        with patch.object(self.m, "run", side_effect=self.usb):
            self.assertEqual(self.m.reconcile_exports(self.m.load_config(), owned), {})
            self.assertEqual(self.m.reconcile_exports(self.m.load_config(), owned), {})
        self.assertEqual(self.calls, [["usbip", "bind", "--busid", "1-2"]])
        self.assertEqual(self.m.catalog()[0]["id"], selected["id"])
        self.assertEqual(self.m.catalog()[0]["status"], "exported")
        for path in (self.m.CONFIG_DIR / "config.json", self.m.state_path()):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotEqual(self.m.RUN_DIR, self.m.SERVER_RUN_DIR)

    def test_serial_moves_to_another_port_without_unbinding_a_replacement(self):
        selected = self.selected(self.device())
        config = self.config([selected])
        owned = {}
        with patch.object(self.m, "run", side_effect=self.usb):
            self.m.reconcile_exports(config, owned)
            shutil.rmtree(self.m.SYSFS / "1-2")
            self.device(serial="other-device", driver="usbip-host")
            self.device(busid="2-4")
            self.m.reconcile_exports(config, owned)
        self.assertEqual(owned[EXPORT]["busid"], "2-4")
        self.assertEqual(self.calls, [["usbip", "bind", "--busid", "1-2"], ["usbip", "bind", "--busid", "2-4"]])
        self.assertEqual(self.m.catalog()[0]["busid"], "2-4")

    def test_no_serial_requires_same_busid_and_ambiguous_serial_is_rejected(self):
        selected = self.selected(self.device(serial=""))
        shutil.rmtree(self.m.SYSFS / "1-2")
        self.device(busid="2-4", serial="")
        with self.assertRaises(self.m.USBIPError):
            self.m.resolve_device(selected, self.m.inventory())
        self.device(busid="1-3", serial="duplicate")
        first = self.device(busid="1-4", serial="duplicate")
        with self.assertRaises(self.m.USBIPError):
            self.m.resolve_device(first, self.m.inventory())

    def test_foreign_exports_are_not_adopted_and_disable_only_releases_owned_devices(self):
        own = self.selected(self.device())
        foreign = self.device(busid="1-3", serial="foreign", driver="usbip-host")
        config = self.config([own, self.selected(foreign) | {"id": CLIENT}])
        owned = {}
        with patch.object(self.m, "run", side_effect=self.usb):
            errors = self.m.reconcile_exports(config, owned)
            self.assertIn("outside ProxMenux", errors[CLIENT])
            config["server"] = False
            self.m.reconcile_exports(config, owned)
        self.assertEqual(self.calls, [["usbip", "bind", "--busid", "1-2"], ["usbip", "unbind", "--busid", "1-2"]])
        self.assertEqual(owned, {})
        self.assertEqual(next(d for d in self.m.inventory() if d["busid"] == "1-3")["driver"], "usbip-host")

    def test_recover_bind_intent_and_remove_selected_export(self):
        selected = self.selected(self.device(driver="usbip-host"))
        self.config([selected])
        owned = {EXPORT: selected}
        self.m.atomic_json(self.m.state_path(), owned)
        with patch.object(self.m, "run", side_effect=self.usb):
            self.m.reconcile_exports(self.m.load_config(), owned)
            self.assertEqual(self.calls, [])
            self.m.remove_export(EXPORT)
            self.m.reconcile_exports(self.m.load_config(), owned)
        self.assertEqual(self.calls, [["usbip", "unbind", "--busid", "1-2"]])

    def test_failed_bind_is_reported_and_retains_recoverable_intent(self):
        selected = self.selected(self.device())
        config = self.config([selected])
        owned = {}
        with patch.object(self.m, "run", side_effect=self.m.USBIPError("bind failed")):
            self.assertEqual(self.m.reconcile_exports(config, owned), {EXPORT: "bind failed"})
        self.assertIn(EXPORT, self.m.read_json(self.m.state_path(), {}))
        self.assertEqual(self.m.status()["server_status"]["errors"], {EXPORT: "bind failed"})
        self.assertEqual(self.m.catalog()[0]["status"], "waiting")

    def test_namespace_guard_fails_before_spawning_a_listener(self):
        with patch.object(self.m.os, "readlink", return_value="net:[1]"), patch.object(self.m.subprocess, "Popen") as process:
            with self.assertRaisesRegex(self.m.USBIPError, "PrivateNetwork"):
                self.m.serve()
        process.assert_not_called()

    def test_generated_units_are_isolated_quoted_and_owned(self):
        self.m.SCRIPT = self.root / 'with space/%and$dollar"quote.py'
        with patch("shutil.which", return_value="/usr/sbin/modprobe"):
            server = self.m.unit_text("server")
            client = self.m.unit_text("client", CLIENT)
        self.assertIn("PrivateNetwork=yes", server)
        self.assertIn("RuntimeDirectory=proxmenux-usbip-server", server)
        self.assertIn("RuntimeDirectoryPreserve=yes", server)
        self.assertIn('%%and$$dollar\\"quote.py" serve', server)
        self.assertNotIn("PrivateNetwork=yes", client)
        self.assertNotIn("RuntimeDirectory=", client)
        self.assertIn("vhci-hcd", client)
        self.assertIn("Restart=on-failure", client)
        unit = self.m.UNIT_DIR / self.m.SERVER_UNIT
        unit.write_text("[Unit]\nDescription=Someone else's service\n")
        with self.assertRaises(self.m.USBIPError), patch.object(self.m, "run") as command:
            self.m.update_server(True)
        command.assert_not_called()
        self.assertFalse((self.m.CONFIG_DIR / "config.json").exists())

    def test_failed_server_start_restores_configuration_and_removes_new_unit(self):
        previous = self.config(server=False)
        def fail_start(args, timeout=20):
            self.calls.append(args)
            if args[:3] == ["systemctl", "enable", "--now"]:
                raise self.m.USBIPError("start failed")
            return ""
        with patch.object(self.m, "run", side_effect=fail_start), patch("shutil.which", return_value="/sbin/modprobe"):
            with self.assertRaisesRegex(self.m.USBIPError, "start failed"):
                self.m.update_server(True)
        self.assertEqual(self.m.load_config(), previous)
        self.assertFalse((self.m.UNIT_DIR / self.m.SERVER_UNIT).exists())
        self.assertIn(["systemctl", "disable", "--now", self.m.SERVER_UNIT], self.calls)

    def test_ssh_policy_and_argument_boundaries(self):
        remote = self.m.validate_remote(self.remote["host"], 2222, str(self.key))
        args = self.m.tunnel_args(remote | {"local_port": 33240})
        for required in ("BatchMode=yes", "StrictHostKeyChecking=yes", "IdentitiesOnly=yes", "ForwardAgent=no",
                         "PasswordAuthentication=no", "ExitOnForwardFailure=yes"):
            self.assertIn(required, args)
        self.assertIn("127.0.0.1:33240:/run/proxmenux-usbip-server/usbip.sock", args)
        self.assertNotIn("StrictHostKeyChecking=no", args)
        self.assertEqual(args[-2:], ["--", "usb.example.test"])
        for host in ("-oProxyCommand=touch /tmp/no", "root@host", "host;id", "host\nother", "$(id)"):
            with self.assertRaises(self.m.USBIPError):
                self.m.validate_remote(host, 22, str(self.key))
        self.key.chmod(0o644)
        with self.assertRaisesRegex(self.m.USBIPError, "permissions"):
            self.m.validate_remote("192.0.2.1", 22, str(self.key))

    def test_ssh_credential_or_catalog_failure_never_saves_a_connection(self):
        for failure in (self.m.USBIPError("Permission denied"), self.m.USBIPError("Connection timed out")):
            with patch.object(self.m, "run", side_effect=failure):
                with self.assertRaises(self.m.USBIPError):
                    self.m.add_import(self.remote, EXPORT, 33240)
            self.assertFalse((self.m.CONFIG_DIR / "config.json").exists())
        with patch.object(self.m, "run", return_value='[{"id":"--bad","busid":"1-2"}]'):
            with self.assertRaisesRegex(self.m.USBIPError, "valid"):
                self.m.remote_catalog(self.remote)

    def test_import_service_failure_rolls_back_and_occupied_port_is_rejected(self):
        exports = [{"id": EXPORT, "status": "exported", "busid": "1-2"}]
        previous = self.config()
        with patch.object(self.m, "remote_catalog", return_value=exports):
            with socket.socket() as busy:
                busy.bind(("127.0.0.1", 0))
                with self.assertRaisesRegex(self.m.USBIPError, "in use"):
                    self.m.add_import(self.remote, EXPORT, busy.getsockname()[1])
            with socket.socket() as unused:
                unused.bind(("127.0.0.1", 0))
                port = unused.getsockname()[1]
            with patch("shutil.which", return_value="/sbin/modprobe"), patch.object(self.m, "enable_unit", side_effect=self.m.USBIPError("failed")):
                with self.assertRaises(self.m.USBIPError):
                    self.m.add_import(self.remote, EXPORT, port)
        self.assertEqual(self.m.load_config(), previous)

    def port(self, **overrides):
        return {"port": 2, "status": "Port in Use", "local_busid": "3-1", "host": "127.0.0.1", "tcp_port": 33240,
                "busid": "1-2"} | overrides

    def test_real_upstream_port_output_and_unowned_port_cleanup(self):
        output = """Imported USB devices
====================
Port 02: <Port in Use> at High Speed(480Mbps)
       Test Zigbee adapter (10c4:ea60)
       3-1 -> usbip://127.0.0.1:33240/1-2
           -> remote bus/dev 001/002
Port 03: <Port Error> at Full Speed(12Mbps)
       Another adapter
       3-2 -> usbip://192.0.2.1:3240/1-3
"""
        ports = self.m.parse_ports(output)
        self.assertEqual(ports[0], self.port())
        self.assertEqual(ports[1]["status"], "Port Error")
        owner = self.m.RUN_DIR / f"client-{CLIENT}.json"
        self.m.atomic_json(owner, ports[0])
        reused = self.port(local_busid="3-7")
        with patch.object(self.m, "imported_ports", return_value=[reused, ports[1]]), patch.object(self.m, "run") as command:
            self.m.release_import(owner)
        command.assert_not_called()
        self.assertFalse(owner.exists())
        self.m.atomic_json(owner, ports[0])
        with patch.object(self.m, "imported_ports", return_value=ports), patch.object(self.m, "run") as command:
            self.m.release_import(owner)
        command.assert_called_once_with(["usbip", "detach", "--port", "2"])

    def test_attach_reuses_live_port_and_recovers_error_with_new_remote_busid(self):
        selected = self.remote | {"id": CLIENT, "local_port": 33240, "export_id": EXPORT}
        owner = self.m.RUN_DIR / f"client-{CLIENT}.json"
        self.m.atomic_json(owner, self.port())
        with patch.object(self.m, "imported_ports", return_value=[self.port()]), patch.object(self.m, "remote_catalog") as remote:
            self.assertEqual(self.m.attach_once(selected, owner)["port"], 2)
        remote.assert_not_called()
        ports = [self.port(status="Port Error")]
        def usb(args, timeout=20):
            self.calls.append(args)
            if "detach" in args:
                ports.clear()
            elif "attach" in args:
                ports.append(self.port(busid="2-4", local_busid="3-5"))
            return ""
        with patch.object(self.m, "imported_ports", side_effect=lambda: copy.deepcopy(ports)), patch.object(
            self.m, "remote_catalog", return_value=[{"id": EXPORT, "status": "exported", "busid": "2-4"}]
        ), patch.object(self.m, "run", side_effect=usb):
            attached = self.m.attach_once(selected, owner)
        self.assertEqual(attached["busid"], "2-4")
        self.assertEqual(self.calls, [["usbip", "detach", "--port", "2"],
            ["usbip", "--tcp-port", "33240", "attach", "--remote", "127.0.0.1", "--busid", "2-4"]])
        self.assertEqual(self.m.read_json(owner, None), attached)

    def test_missing_remote_or_unowned_import_is_never_detached(self):
        selected = self.remote | {"id": CLIENT, "local_port": 33240, "export_id": EXPORT}
        owner = self.m.RUN_DIR / f"client-{CLIENT}.json"
        with patch.object(self.m, "remote_catalog", return_value=[]), patch.object(self.m, "run") as command:
            with self.assertRaisesRegex(self.m.USBIPError, "unplugged"):
                self.m.attach_once(selected, owner)
        command.assert_not_called()
        with patch.object(self.m, "remote_catalog", return_value=[{"id": EXPORT, "status": "exported", "busid": "1-2"}]), patch.object(
            self.m, "imported_ports", return_value=[self.port()]
        ), patch.object(self.m, "run") as command:
            with self.assertRaisesRegex(self.m.USBIPError, "unowned"):
                self.m.attach_once(selected, owner)
        command.assert_not_called()

    @unittest.skipUnless(sys.platform == "linux" and shutil.which("systemd-analyze"), "systemd verifier requires Linux")
    def test_systemd_accepts_both_generated_service_files(self):
        with patch("shutil.which", return_value="/bin/true"):
            for name, content in ((self.m.SERVER_UNIT, self.m.unit_text("server")),
                                  (self.m.unit_name(CLIENT), self.m.unit_text("client", CLIENT))):
                path = self.m.UNIT_DIR / name
                path.write_text(content)
                result = subprocess.run(["systemd-analyze", "verify", str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_menu_and_search_expose_server_and_client_actions(self):
        menu = (ROOT / "scripts/menus/hw_grafics_menu.sh").read_text()
        self.assertIn('bash "$LOCAL_SCRIPTS/devices/usbip_menu.sh"', menu)
        index = json.loads((ROOT / "scripts/menus/search_index.json").read_text())
        self.assertTrue(any(i["script"] == "devices/usbip_menu.sh" and "usbip" in i["keywords"] for i in index))
        for script in (ROOT / "scripts/devices/usbip_menu.sh", ROOT / "scripts/menus/hw_grafics_menu.sh"):
            subprocess.run(["bash", "-n", str(script)], check=True)


if __name__ == "__main__":
    unittest.main()
