"""The advanced installer asks for each data path's storage next to its size."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci.catalog import Catalog
from proxmenux_oci.installer import ADVANCED_MODE, DEFAULT_MODE, build_deployment

STORAGES = [{"storage": "Public", "type": "nfs", "avail": 9 * 2**40},
            {"storage": "local-lvm", "type": "lvmthin", "avail": 700 * 2**30}]


class RecordingUI:
    """Answers every question with its default, or with a scripted answer."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.asked = []

    def _answer(self, text, default):
        self.asked.append(text)
        return self.answers.get(text, default)

    def ask(self, text, default=None, required=True):
        return self._answer(text, default if default is not None else "")

    def password(self, text, required=True):
        return self._answer(text, "secret")

    def choose(self, text, options, default=None):
        return self._answer(text, default)

    def confirm(self, text, default=False):
        return self._answer(text, default)

    def checklist(self, text, options, default=None):
        return self._answer(text, default)

    def info(self, text):
        pass

    def message(self, text):
        pass


def storages(content):
    return STORAGES if content == "rootdir" else [{"storage": "local", "type": "dir", "avail": 2**35}]


def addresses(ui, bridge, names, *args):
    return {name: "dhcp" for name in names}, None


@patch("proxmenux_oci.i18n.language", return_value="en")
@patch("proxmenux_oci.installer.host.storages", side_effect=storages)
@patch("proxmenux_oci.installer.host.bridges", return_value=[{"iface": "vmbr0", "cidr": "192.0.2.10/24"}])
@patch("proxmenux_oci.installer.host.timezone", return_value="Europe/Madrid")
@patch("proxmenux_oci.installer.access.ask_ipv4", return_value=("dhcp", None))
@patch("proxmenux_oci.installer.access.ask_addresses", side_effect=addresses)
class AdvancedFlowOrderTests(unittest.TestCase):
    catalog = Catalog(ROOT)

    def build(self, app, ui, mode=ADVANCED_MODE):
        return build_deployment(self.catalog.compose(app), ui, mode)

    def test_each_volume_asks_its_storage_and_then_its_size(self, *_):
        ui = RecordingUI({"Storage for /data/movies": "Public"})
        plan = self.build("jellyfin", ui)
        volumes = {m["container_path"]: m["source"] for m in plan["mounts"]}
        self.assertEqual(volumes, {"/config": "local-lvm", "/data/tvshows": "local-lvm",
                                   "/data/movies": "Public"})
        asked = ui.asked
        self.assertEqual(asked.index("Size in GB of /config"), asked.index("Storage for /config") + 1)
        self.assertNotIn("Storage for persistent data", asked)
        self.assertNotIn("Where to store /config", asked)

    def test_volumes_are_proposed_on_the_rootfs_storage(self, *_):
        ui = RecordingUI({"Storage for rootfs": "Public"})
        plan = self.build("jellyfin", ui)
        self.assertEqual({m["source"] for m in plan["mounts"]}, {"Public"})

    def test_system_resources_then_data_then_network_then_start(self, *_):
        ui = RecordingUI()
        self.build("jellyfin", ui)
        asked = ui.asked
        order = ["Memory in MB", "Storage for rootfs", "Rootfs size in GB", "Storage for /config",
                 "Where to store /data/movies", "Network bridge", "Value for TZ",
                 "Start with Proxmox", "Start when finished"]
        self.assertEqual([asked.index(text) for text in order], sorted(asked.index(text) for text in order))
        self.assertEqual(asked[-2:], ["Start with Proxmox", "Start when finished"])

    def test_single_option_and_system_paths_are_not_asked(self, *_):
        ui = RecordingUI()
        plan = self.build("frigate", ui)
        self.assertNotIn("Where to store /etc/localtime", ui.asked)
        self.assertNotIn("Host path for /etc/localtime", ui.asked)
        self.assertIn("Where to store /media/frigate", ui.asked)
        localtime = next(m for m in plan["mounts"] if m["container_path"] == "/etc/localtime")
        self.assertEqual((localtime["type"], localtime["source"]), ("host-bind", "/etc/localtime"))

    def test_default_mode_asks_one_storage_the_address_and_the_start(self, *_):
        ui = RecordingUI({"Storage for the container and its data": "Public"})
        plan = self.build("jellyfin", ui, DEFAULT_MODE)
        self.assertEqual(ui.asked[0], "Storage for the container and its data")
        self.assertEqual(ui.asked[-2:], ["Start with Proxmox", "Start when finished"])
        self.assertFalse([text for text in ui.asked if text.startswith("Storage for /")])
        self.assertEqual(plan["rootfs"]["storage"], "Public")
        self.assertEqual({m["source"] for m in plan["mounts"]}, {"Public"})
        plan = self.build("jellyfin", RecordingUI(), DEFAULT_MODE)
        self.assertEqual({plan["rootfs"]["storage"]} | {m["source"] for m in plan["mounts"]}, {"local-lvm"})

    def assert_follows(self, asked, *texts):
        positions = [asked.index(text) for text in texts]
        self.assertEqual(positions, list(range(positions[0], positions[0] + len(texts))), texts)

    def test_stack_asks_each_member_path_with_its_storage_and_size(self, *_):
        ui = RecordingUI({"Storage for linkwarden-postgres: /var/lib/postgresql": "Public"})
        plan = self.build("linkwarden", ui)
        asked = ui.asked
        self.assertNotIn("Storage for persistent data", asked)
        self.assert_follows(asked, "Where to store linkwarden-postgres: /var/lib/postgresql",
                            "Storage for linkwarden-postgres: /var/lib/postgresql",
                            "Size in GB of linkwarden-postgres: /var/lib/postgresql")
        self.assertLess(asked.index("Add extra paths to this stack"), asked.index("Access bridge"))
        self.assertLess(asked.index("Access bridge"), asked.index("Timezone"))
        self.assertEqual(asked[-1], "Start the stack with Proxmox")
        sources = {(s["name"], m["container_path"]): m["source"]
                   for s in plan["services"] for m in s["deployment"]["mounts"]}
        self.assertEqual(sources[("linkwarden-postgres", "/var/lib/postgresql")], "Public")
        self.assertTrue(all(s["deployment"]["onboot"] is False for s in plan["services"]))

    def test_arr_suite_asks_data_first_and_start_last(self, *_):
        ui = RecordingUI()
        plan = self.build("suite-arr", ui)
        asked = ui.asked
        self.assertLess(asked.index("Shared host media directory"), asked.index("Access bridge"))
        self.assertLess(asked.index("Add extra paths to this stack"), asked.index("Access bridge"))
        self.assertEqual(asked[-1], "Start each LXC with Proxmox (no coordinated startup)")
        self.assertTrue(all("onboot" in s["deployment"] for s in plan["services"]))

    def test_special_stacks_ask_each_storage_next_to_its_size(self, *_):
        ui = RecordingUI()
        self.build("immich", ui)
        self.assert_follows(ui.asked, "Where to store the Immich library", "Storage for the Immich library",
                            "Library size in GB", "Local storage for PostgreSQL", "PostgreSQL volume size in GB")
        ui = RecordingUI()
        self.build("paperless-ngx", ui)
        self.assert_follows(ui.asked, "Storage for Paperless data and documents", "Data volume size in GB",
                            "Documents volume size in GB", "Local storage for PostgreSQL",
                            "PostgreSQL volume size in GB")
        ui = RecordingUI()
        self.build("tandoor", ui)
        self.assert_follows(ui.asked, "Storage for staticfiles", "staticfiles volume size in GB",
                            "Local storage for PostgreSQL", "PostgreSQL volume size in GB")
        self.assertEqual(ui.asked[-2:], ["Start the stack with Proxmox", "Start when finished"])


if __name__ == "__main__":
    unittest.main()
