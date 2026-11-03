"""A Compose volume that binds a host device node, such as /dev/net/tun for
Tailscale, is passed to the LXC as a device: a mount there hides the device."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from proxmenux_oci import converter


class DeviceNodeBindTests(unittest.TestCase):
    service = {"image": "tailscale/tailscale:latest", "volumes": [
        {"type": "bind", "source": "/DATA/AppData/tailscale", "target": "/var/lib/tailscale"},
        {"type": "bind", "source": "/dev/net/tun", "target": "/dev/net/tun"},
        "/dev/fuse:/dev/fuse"]}

    def test_device_nodes_are_not_volumes(self):
        mounts = converter._mount_contract(self.service["volumes"], set())
        self.assertEqual([m["container_path"] for m in mounts], ["/var/lib/tailscale"])

    def test_device_nodes_become_device_requests(self):
        profile, blockers = converter._device_installer_profile(self.service)
        self.assertEqual(blockers, [])
        self.assertEqual([(r["id"], r["container_path"]) for r in profile["device_requests"]],
                         [("dev-net-tun", "/dev/net/tun"), ("dev-fuse", "/dev/fuse")])

    def test_a_device_directory_is_left_to_its_own_handling(self):
        self.assertIsNone(converter._device_bind("/dev/dri:/dev/dri"))
        self.assertIsNone(converter._device_bind({"type": "volume", "source": "/dev/net/tun", "target": "/dev/net/tun"}))

    def test_the_tailscale_recipe_passes_the_tun_device(self):
        import json
        recipe = json.loads((Path(__file__).resolve().parents[1] / "catalog/apps/tailscale.json").read_text())
        self.assertNotIn("/dev/net/tun", [v["container_path"] for v in recipe["container_contract"]["volumes"]])
        self.assertIn("dev-net-tun", [r["id"] for r in recipe["proxmox"]["installer_profile"]["device_requests"]])


if __name__ == "__main__":
    unittest.main()
