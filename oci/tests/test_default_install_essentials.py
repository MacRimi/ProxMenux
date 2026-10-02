"""A default installation of a multi-container application still asks its
storage, its address and how it starts; everything else comes from the recipe."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from proxmenux_oci.catalog import Catalog
from proxmenux_oci.installer import DEFAULT_MODE, build_deployment
from test_advanced_flow_order import RecordingUI, addresses, storages

STORAGE = "Storage for the containers and their data"
ADDRESS = "<address>"


def asked_addresses(ui, bridge, names, *args):
    # The address belongs to the questions asked through the real interface.
    ui.asked.append(ADDRESS)
    return addresses(ui, bridge, names)


def storages_used(plan):
    used = {value for key, value in plan.items()
            if key.endswith("storage") and key != "template_storage" and isinstance(value, str)}
    used |= {plan[key]["storage"] for key in ("media", "application", "transfer")
             if isinstance(plan.get(key), dict) and plan[key].get("storage")}
    for service in plan.get("services", []):
        used.add(service["deployment"]["rootfs"]["storage"])
        used |= {m["source"] for m in service["deployment"]["mounts"] if m["type"] == "managed-volume"}
    return used


# The GPUs of the host the tests run on are not part of what they check.
@patch("proxmenux_oci.installer.host.gpus", return_value={"intel": ["/dev/dri/renderD128"], "amd": [], "nvidia": False})
@patch("proxmenux_oci.i18n.language", return_value="en")
@patch("proxmenux_oci.installer.host.storages", side_effect=storages)
@patch("proxmenux_oci.installer.host.bridges", return_value=[{"iface": "vmbr0", "cidr": "192.0.2.10/24"}])
@patch("proxmenux_oci.installer.host.timezone", return_value="Europe/Madrid")
@patch("proxmenux_oci.installer.access.ask_addresses", side_effect=asked_addresses)
class DefaultInstallEssentialsTests(unittest.TestCase):
    catalog = Catalog(ROOT)

    def build(self, app, answers=None):
        ui = RecordingUI(answers)
        return ui, build_deployment(self.catalog.compose(app), ui, DEFAULT_MODE)

    def test_every_stack_asks_storage_address_and_start(self, *_):
        for app in ("nextcloud-stack", "paperless-ngx", "tandoor", "immich", "linkwarden", "suite-arr"):
            ui, _plan = self.build(app)
            self.assertIn(STORAGE, ui.asked, app)
            self.assertIn(ADDRESS, ui.asked, app)
            self.assertTrue(any("with Proxmox" in text for text in ui.asked), app)
            self.assertLess(ui.asked.index(STORAGE), ui.asked.index(ADDRESS), app)

    def test_the_users_data_is_placed_by_the_user_and_the_rest_comes_from_the_recipe(self, *_):
        expected = {
            "nextcloud-stack": [STORAGE, "Where to store the Nextcloud files, configuration and data",
                                "Nextcloud volume size in GB", ADDRESS, "Start the stack with Proxmox",
                                "Start when finished"],
            "immich": [STORAGE, "Where to store the Immich library", "Library size in GB", ADDRESS,
                       "Hardware acceleration for Immich", "Start the stack with Proxmox", "Start when finished"],
            "tandoor": [STORAGE, "Where to store the recipe images and files", "Files volume size in GB", ADDRESS,
                        "Start the stack with Proxmox"],
            "paperless-ngx": [STORAGE, "Documents volume size in GB", "Where to store the consume and export folders",
                              "Shared directory for consume and export", ADDRESS, "Start the stack with Proxmox",
                              "Start when finished"],
            "linkwarden": [STORAGE, "Where to store linkwarden: /data/data", "Size in GB of linkwarden: /data/data",
                           ADDRESS, "Start the stack with Proxmox"],
        }
        for app, asked in expected.items():
            self.assertEqual(self.build(app)[0].asked, asked, app)
        for text in ("Stack name", "Base VMID (empty = next free block)", "Timezone"):
            self.assertNotIn(text, self.build("suite-arr")[0].asked)

    def test_a_host_directory_can_be_chosen_for_the_data(self, *_):
        _ui, plan = self.build("nextcloud-stack", {
            "Where to store the Nextcloud files, configuration and data": "host-bind",
            "Shared host directory": "/mnt/tank/nextcloud"})
        self.assertEqual((plan["application"]["mode"], plan["application"]["host_path"], plan["application"]["backup"]),
                         ("host-bind", "/mnt/tank/nextcloud", False))
        _ui, plan = self.build("nextcloud-stack", {"Nextcloud volume size in GB": "200"})
        self.assertEqual((plan["application"]["mode"], plan["application"]["size_gb"]), ("managed-volume", 200))

    def test_the_chosen_storage_holds_the_containers_and_their_data(self, *_):
        for app in ("nextcloud-stack", "paperless-ngx", "tandoor", "immich", "linkwarden", "suite-arr"):
            _ui, plan = self.build(app, {STORAGE: "Public"})
            self.assertEqual(storages_used(plan), {"Public"}, app)
            _ui, plan = self.build(app)
            self.assertEqual(storages_used(plan), {"local-lvm"}, app)

    def test_a_single_image_application_asks_the_same_essentials(self, *_):
        single = "Storage for the container and its data"
        for app in ("jellyfin", "frigate", "uptimekuma"):
            ui, plan = self.build(app, {single: "Public"})
            self.assertEqual(ui.asked[0], single, app)
            self.assertIn(ADDRESS, ui.asked, app)
            self.assertEqual(ui.asked[-2:], ["Start with Proxmox", "Start when finished"], app)
            self.assertEqual(plan["rootfs"]["storage"], "Public", app)
            self.assertEqual({m["source"] for m in plan["mounts"] if m["type"] == "managed-volume"} - {"Public"},
                             set(), app)

    def test_the_members_of_a_stack_ask_nothing_of_their_own(self, *_):
        for app in ("linkwarden", "suite-arr"):
            ui, _plan = self.build(app)
            self.assertEqual(ui.asked.count(ADDRESS), 1, app)
            self.assertNotIn("Storage for the container and its data", ui.asked, app)
            self.assertNotIn("Start with Proxmox", ui.asked, app)
            self.assertNotIn("Start when finished", ui.asked, app)

    def test_the_start_answers_are_the_users(self, *_):
        _ui, plan = self.build("nextcloud-stack", {"Start the stack with Proxmox": True, "Start when finished": False})
        self.assertEqual((plan["onboot"], plan["start_after_create"]), (True, False))


if __name__ == "__main__":
    unittest.main()
