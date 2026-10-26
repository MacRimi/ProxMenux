"""A path that holds content of the user is offered as a container volume or
as a host directory. Either way it belongs to the user the application writes
with: a volume left to root is one the application cannot write to."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci.catalog import Catalog


def owners(template):
    profile = template["proxmox"]["installer_profile"]
    return {item["container_path"]: item["owner_strategy"] for item in profile["volume_preparations"]}


class ContentVolumeOwnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog(ROOT)

    def test_the_content_of_the_user_belongs_to_the_application(self):
        found = owners(self.catalog.compose("duplicati"))
        self.assertEqual(found["/backups"], "mapped-application-user")
        self.assertEqual(found["/source"], "mapped-application-user")

    def test_the_state_of_the_application_stays_as_the_recipe_says(self):
        self.assertEqual(owners(self.catalog.compose("duplicati"))["/config"], "mapped-root")

    def test_it_follows_the_choice_the_installation_offers(self):
        contract = {"volumes": [
            {"container_path": "/downloads", "installation_choice": ["managed-volume", "host-bind", "skip"]},
            {"container_path": "/config", "installation_choice": ["managed-volume", "host-bind"],
             "managed_volume": {"default_size_gb": 4}}]}
        profile = {"volume_preparations": [
            {"container_path": "/downloads", "owner_strategy": "mapped-root"},
            {"container_path": "/config", "owner_strategy": "mapped-root"}]}
        self.catalog._apply_volume_policy("an-application", contract, profile)
        self.assertEqual({item["container_path"]: item["owner_strategy"] for item in profile["volume_preparations"]},
                         {"/downloads": "mapped-application-user", "/config": "mapped-root"})
        self.assertEqual(contract["volumes"][1]["installation_choice"], ["managed-volume"])

    def test_the_content_of_the_user_is_always_mounted(self):
        contract = {"volumes": [
            {"container_path": "/downloads", "installation_choice": ["managed-volume", "host-bind", "skip"],
             "default": "skip"},
            {"container_path": "/var/run/docker.sock", "installation_choice": ["host-bind", "skip"], "default": "skip"}]}
        self.catalog._apply_volume_policy("an-application", contract, {})
        self.assertEqual(contract["volumes"][0]["installation_choice"], ["managed-volume", "host-bind"])
        self.assertEqual(contract["volumes"][0]["default"], "managed-volume")
        # What is not content of the user, as a socket of the host, can still be left out.
        self.assertEqual(contract["volumes"][1]["installation_choice"], ["host-bind", "skip"])
        for app, path in (("sonarr", "/downloads"), ("manyfold", "/libraries"), ("qbittorrent", "/downloads")):
            volume = next(item for item in self.catalog.compose(app)["container_contract"]["volumes"]
                          if item["container_path"] == path)
            self.assertNotIn("skip", volume["installation_choice"], app)
            self.assertEqual(volume["default"], "managed-volume", app)

    def test_a_container_volume_is_never_read_only(self):
        source = (ROOT / "src" / "proxmenux_oci" / "installer.py").read_text()
        self.assertIn('"read_only": item["read_only"] and volume_mode != "managed-volume"', source)

    def test_the_time_files_of_the_host_are_not_mounted(self):
        for app in ("openhab", "lyrionmusicserver"):
            template = self.catalog.compose(app)
            paths = [volume["container_path"] for volume in template["container_contract"]["volumes"]]
            self.assertNotIn("/etc/localtime", paths, app)
            self.assertNotIn("/etc/timezone", paths, app)
            self.assertNotIn("/etc/localtime", owners(template), app)

    def test_a_new_volume_is_filled_from_the_image_as_docker_does(self):
        # Declared or not: an image that runs as a user of its own, as Node-RED
        # or Grafana, finds its data directory with its own owner.
        installer = (ROOT / "remote" / "install_oci.sh").read_text()
        capture = installer[installer.index("capture_volume_seeds() {"):installer.index("apply_volume_seeds() {")]
        self.assertIn('select(.type == "managed-volume") | .container_path\' "$DEPLOYMENT_FILE")', capture)
        self.assertIn('is_reused_managed_mount "$target" && continue', capture)
        self.assertIn('cp -a -- "${source}/." "${stage}/"', capture)
        self.assertIn("[[ -n $target && -z ${declared_seeds[$target]:-} ]] || continue", capture)

    def test_a_recipe_without_preparations_is_left_alone(self):
        contract = {"volumes": [{"container_path": "/downloads", "installation_choice": ["managed-volume", "host-bind"]}]}
        self.catalog._apply_volume_policy("an-application", contract, None)
        self.catalog._apply_volume_policy("an-application", contract, {})


if __name__ == "__main__":
    unittest.main()
