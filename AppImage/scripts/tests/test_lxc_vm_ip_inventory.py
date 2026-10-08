"""Contracts for LXC IP inventory returned by the compact `/api/vms` list."""

import ast
import threading
import unittest
from pathlib import Path


SERVER_SOURCE = Path(__file__).resolve().parents[1] / "flask_server.py"


def load_server_functions(*names):
    """Compile selected production functions without importing host-bound Flask state."""
    tree = ast.parse(SERVER_SOURCE.read_text())
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    }
    missing = set(names) - functions.keys()
    if missing:
        raise AssertionError(f"Missing production functions: {sorted(missing)}")
    module = ast.Module(body=[functions[name] for name in names], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {}
    exec(compile(module, str(SERVER_SOURCE), "exec"), namespace)
    return namespace


class LxcVmIpInventoryTests(unittest.TestCase):
    def setUp(self):
        self.server = load_server_functions("_normalise_lxc_ips", "get_proxmox_vms")
        self.server.update({
            "_get_lxc_update_status_map": lambda: {},
            "_get_lxc_app_watch_map": lambda: {},
            "_get_lxc_docker_inventory_map": lambda: {},
            "get_proxmox_node_name": lambda: "pve",
            "_get_cached_vm_list_search_notes": lambda _resources, _node: {},
            "get_cached_vm_disk": lambda _vmid: None,
            "_guest_lifecycle_lock": threading.RLock(),
            "_guest_modal_cache_revision": {},
            "_guest_modal_cache_epoch": 1,
        })

    def list_rows(self, resources, ip_info_by_vmid):
        self.server["get_cached_pvesh_cluster_resources_vm"] = lambda: resources
        self.server["_get_lxc_ip_info_cached"] = lambda vmid: ip_info_by_vmid.get(vmid)
        return self.server["get_proxmox_vms"]()

    @staticmethod
    def running_lxc(vmid):
        return {
            "type": "lxc", "node": "pve", "status": "running", "vmid": vmid,
            "name": f"ct-{vmid}", "cpu": 0, "mem": 0, "maxmem": 0,
            "disk": 0, "maxdisk": 0, "uptime": 0,
        }

    def test_unregistered_lxc_keeps_its_primary_ip_in_the_list(self):
        rows = self.list_rows([self.running_lxc(300)], {
            300: {
                "all_ips": ["10.100.100.218"],
                "real_ips": ["10.100.100.218"],
                "docker_ips": [],
                "primary_ip": "10.100.100.218",
            },
        })

        self.assertEqual(rows[0]["ip"], "10.100.100.218")
        self.assertEqual(rows[0]["ips"], ["10.100.100.218"])
        self.assertNotIn("app_watches", rows[0])

    def test_lxc_with_multiple_ips_preserves_order_and_docker_classification_output(self):
        rows = self.list_rows([self.running_lxc(301)], {
            301: {
                "all_ips": ["10.100.100.219", "10.100.100.220", "172.17.0.1"],
                "real_ips": ["10.100.100.219", "10.100.100.220"],
                "docker_ips": ["172.17.0.1"],
                "primary_ip": "10.100.100.219",
            },
        })

        self.assertEqual(rows[0]["ip"], "10.100.100.219")
        self.assertEqual(rows[0]["ips"], ["10.100.100.219", "10.100.100.220", "172.17.0.1"])

    def test_lxc_without_an_ip_returns_an_empty_ips_list(self):
        rows = self.list_rows([self.running_lxc(302)], {302: None})

        self.assertEqual(rows[0]["ips"], [])
        self.assertNotIn("ip", rows[0])


class LxcPrimaryAddressTests(unittest.TestCase):
    """A container that rebooted from inside shows the addresses of its inner
    bridges until it has its own again."""

    def setUp(self):
        self.server = load_server_functions(
            "_get_lxc_ip_info_cached", "_remember_lxc_ip", "get_lxc_ip_from_lxc_info")
        self.listed = ""

        class Result:
            returncode = 0

        def run(_command, **_options):
            result = Result()
            result.stdout = self.listed
            return result

        import types
        self.server.update({
            "_lxc_ip_cache": {},
            "subprocess": types.SimpleNamespace(run=run),
            "_lxc_isolated_ips": lambda _vmid: set(),
            "_lxc_shares_host_network": lambda _vmid: False,
        })

    def read(self, listed):
        self.listed = listed
        return self.server["_get_lxc_ip_info_cached"](121)

    def test_ipv4_is_the_primary_address_wherever_it_is_listed(self):
        info = self.read("fd0c:ac1e:2100::1\n172.30.32.1\n192.168.0.100\n")
        self.assertEqual(info["primary_ip"], "192.168.0.100")
        self.assertEqual(info["real_ips"], ["192.168.0.100", "fd0c:ac1e:2100::1"])
        self.assertIn(121, self.server["_lxc_ip_cache"])

    def test_an_answer_without_ipv4_of_its_own_is_read_again(self):
        self.read("172.30.232.1\n172.30.32.1\nfd0c:ac1e:2100::1\n")
        self.assertNotIn(121, self.server["_lxc_ip_cache"])
        self.assertEqual(self.read("192.168.0.100\n172.30.32.1\n")["primary_ip"], "192.168.0.100")
        self.assertIn(121, self.server["_lxc_ip_cache"])


if __name__ == "__main__":
    unittest.main()
