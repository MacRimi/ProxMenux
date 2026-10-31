"""The VLAN tag of the access interface is a setting of the installation."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "remote"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import oci_installation_state as state
import oci_instance_transaction as transaction
from proxmenux_oci import network


class Answer:
    def __init__(self, value):
        self.value = value

    def ask(self, text, default=None, required=True):
        return self.value if self.value is not None else default


def record(net0):
    config = f"arch: amd64\nmemory: 1024\nnet0: {net0}\n"
    return {"observed": {"config": config, "config_sha256": transaction.sha(config.encode())},
            "installation_id": "x"}, config.encode()


class Question(unittest.TestCase):
    def test_empty_means_no_tag_and_the_current_one_is_offered(self):
        self.assertIsNone(network.ask_vlan_tag(Answer("")))
        self.assertEqual(network.ask_vlan_tag(Answer(None), 40), 40)
        self.assertEqual(network.ask_vlan_tag(Answer(" 4 ")), 4)

    def test_only_a_valid_vlan_is_accepted(self):
        for value in ("0", "4095", "abc", "1,2", "-1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                network.ask_vlan_tag(Answer(value))


class TagSetInProxmox(unittest.TestCase):
    NET = "name=eth0,bridge=vmbr0,firewall=1,hwaddr=BC:24:11:98:91:D2,ip=dhcp,type=veth"

    def changes(self, before, after, adopt=True):
        saved, _ = record(before)
        return transaction.external_changes(saved, record(after)[1], adopt=adopt)

    def test_an_application_takes_the_tag_into_its_record(self):
        self.assertEqual(self.changes(self.NET, self.NET + ",tag=4"), {"vlan_tag": 4})

    def test_a_tag_removed_in_proxmox_is_taken_as_well(self):
        self.assertEqual(self.changes(self.NET + ",tag=4", self.NET), {"vlan_tag": None})

    def test_a_stack_member_keeps_the_line_as_it_is(self):
        self.assertEqual(self.changes(self.NET, self.NET + ",tag=4", adopt=False), {})

    def test_the_rest_of_the_network_line_is_taken_as_well(self):
        self.assertEqual(self.changes(self.NET, self.NET.replace("vmbr0", "vmbr1") + ",tag=4"),
                         {"bridge": "vmbr1", "vlan_tag": 4})


class Kept(unittest.TestCase):
    def test_the_update_names_the_tag_it_keeps(self):
        import oci_update_current as update
        with patch.object(update, "translate", side_effect=str):
            self.assertEqual(update.kept_settings({"vlan_tag": 4}, {"network": {"vlan_tag": 4}}), ["VLAN tag"])


class Carried(unittest.TestCase):
    CONFIG = b"memory: 512\nnameserver: 9.9.9.9\nnet0: name=eth0,mtu=1400,bridge=vmbr0\nprotection: 1\nfeatures: keyctl=1\n"

    def kept(self, candidate_network=None):
        saved = {"deployment": {"network": {"bridge": "vmbr0"}, "security": {}}}
        new = {"deployment": {"network": candidate_network or {"bridge": "vmbr0"}, "security": {}}}
        return transaction.kept_settings(saved, new, state.parse_config(self.CONFIG))

    def test_what_the_user_set_goes_back_to_the_rebuilt_container(self):
        kept = self.kept()
        self.assertEqual(kept["nameserver"], "9.9.9.9")
        self.assertEqual(kept["features"], "keyctl=1")
        self.assertEqual(kept["net0"], "name=eth0,mtu=1400,bridge=vmbr0")

    def test_protection_comes_back_only_at_the_end(self):
        self.assertNotIn("protection", self.kept())

    def test_only_a_command_of_the_user_goes_back(self):
        config = state.parse_config(b"entrypoint: /usr/bin/app --flag\n")
        same = {"deployment": {}}
        self.assertNotIn("entrypoint", transaction.kept_settings(same, same, config))
        custom = {"deployment": {"custom_entrypoint": "/usr/bin/app --flag"}}
        self.assertEqual(transaction.kept_settings(custom, custom, config)["entrypoint"], "/usr/bin/app --flag")

    def test_a_network_edited_in_modify_is_not_overwritten(self):
        self.assertNotIn("net0", self.kept({"bridge": "vmbr1"}))

    def test_a_start_command_set_in_proxmox_is_taken(self):
        saved, config = record("name=eth0,bridge=vmbr0")
        self.assertEqual(transaction.external_changes(saved, config + b"entrypoint: /bin/app\n"),
                         {"entrypoint": "/bin/app"})

    def test_the_snapshot_a_backup_leaves_is_not_a_change(self):
        saved, config = record("name=eth0,bridge=vmbr0")
        self.assertEqual(transaction.external_changes(saved, config + b"parent: vzdump\n"), {})

    def test_a_snapshot_of_the_user_is_not_discarded(self):
        saved, config = record("name=eth0,bridge=vmbr0")
        with self.assertRaises(ValueError):
            transaction.external_changes(saved, config + b"parent: before-upgrade\n")

    def test_raw_lines_of_the_user_are_told_from_those_of_the_engine(self):
        before = "lxc.init.cwd: /\nlxc.cgroup2.devices.allow: c 1:1 rwm\n"
        saved = {"observed": {"config": before}, "deployment": {"custom_lxc": ["lxc.cgroup2.devices.allow: c 1:1 rwm"]}}
        config = (before + "lxc.mount.entry: /a b none bind 0 0\nlxc.environment.runtime: A=1\n").encode()
        self.assertEqual(transaction.custom_lxc(saved, config),
                         ["lxc.cgroup2.devices.allow: c 1:1 rwm", "lxc.mount.entry: /a b none bind 0 0"])


class Probe(unittest.TestCase):
    def curl(self, net):
        def run(*args):
            return b"1234\n" if args[0] == "lxc-info" else f"memory: 512\n{net}\n".encode()
        return state.container_curl(108, run)

    def test_the_host_looks_at_an_untagged_container(self):
        self.assertEqual(self.curl("net0: name=eth0,bridge=vmbr0,ip=dhcp"), ["curl"])

    def test_a_tagged_interface_is_looked_at_from_inside(self):
        expected = ["nsenter", "--net=/proc/1234/ns/net", "curl"]
        self.assertEqual(self.curl("net0: name=eth0,bridge=vmbr0,tag=4,ip=dhcp"), expected)
        self.assertEqual(self.curl("net1: name=lan,bridge=vmbr0,tag=4"), expected)

    def test_every_web_check_goes_through_it(self):
        for name in ("install_oci.sh", "install_paperless_stack.sh", "install_tandoor_stack.sh",
                     "install_nextcloud_stack.sh"):
            self.assertIn("oci_curl", (ROOT / "remote" / name).read_text(), name)
        for name in ("oci_instance_transaction.py", "oci_stack_native.py", "install_generic_stack.py",
                     "haos_healthcheck.py"):
            self.assertIn("container_curl", (ROOT / "remote" / name).read_text(), name)


class Creation(unittest.TestCase):
    def option(self, network_values):
        with tempfile.TemporaryDirectory() as directory:
            deployment = Path(directory) / "deployment.json"
            deployment.write_text(json.dumps({"network": network_values}))
            text = (ROOT / "remote/oci_ui.sh").read_text()
            start = text.index("oci_vlan_option() {")
            function = text[start:text.index("\n}", start) + 2]
            return subprocess.run(
                ["/bin/bash", "-c", f'DEPLOYMENT_FILE={deployment}\n{function}\n'
                 'oci_vlan_option vlan_tag; code=$?; echo "$code:$OCI_VLAN_OPTION"'],
                capture_output=True, text=True, check=True).stdout.strip()

    def test_the_option_of_the_interface(self):
        self.assertEqual(self.option({"vlan_tag": 4}), "0:,tag=4")
        self.assertEqual(self.option({}), "0:")

    def test_an_invalid_tag_stops_the_installation(self):
        self.assertEqual(self.option({"vlan_tag": 5000}), "1:")
        self.assertEqual(self.option({"vlan_tag": "4,trunks=1"}), "1:")

    def test_every_installer_applies_it(self):
        for name in ("install_oci.sh", "install_immich_stack.sh", "install_paperless_stack.sh",
                     "install_nextcloud_stack.sh", "install_tandoor_stack.sh"):
            self.assertIn("oci_vlan_option", (ROOT / "remote" / name).read_text(), name)
        self.assertIn("frontend_vlan_tag", (ROOT / "remote/install_generic_stack.py").read_text())


if __name__ == "__main__":
    unittest.main()
