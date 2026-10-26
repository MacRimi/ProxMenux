"""Regression coverage for PocketBase's native OCI data mount."""
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
INSTALLER = ROOT / "remote" / "install_oci.sh"

from proxmenux_oci.catalog import Catalog


class PocketBasePersistenceTests(unittest.TestCase):
    def test_data_volume_uses_the_image_working_directory(self):
        template = Catalog(ROOT).compose("pocketbase")
        volumes = template["container_contract"]["volumes"]

        self.assertEqual(len(volumes), 1)
        self.assertEqual(volumes[0]["container_path"], "/pocketbase/pb_data")
        self.assertTrue(volumes[0]["required"])
        self.assertTrue(volumes[0]["managed_volume"]["backup"])

    def test_first_install_seeds_only_the_new_managed_data_volume(self):
        template = Catalog(ROOT).compose("pocketbase")
        seeds = template["proxmox"]["installer_profile"]["volume_seeds"]

        self.assertEqual(seeds, [{
            "container_path": "/pocketbase/pb_data",
            "source_path": "/pocketbase/pb_data",
            "mount_types": ["managed-volume", "host-bind"],
        }])

    def test_seed_mechanism_is_opt_in_and_never_overwrites_existing_data(self):
        installer = INSTALLER.read_text(encoding="utf-8")

        self.assertIn('and all(.[]; . == "managed-volume" or . == "host-bind")', installer)
        self.assertIn('[[ $selected_mount_type == managed-volume ]] && is_reused_managed_mount "$target";', installer)
        self.assertIn('Refusing to seed a persistent volume that already contains data:', installer)
        self.assertIn('Keeping existing host data without seeding it:', installer)
        self.assertIn('mktemp -d "/var/tmp/proxmenux-oci-seed-${VMID}.XXXXXX"', installer)
        self.assertIn('cleanup_volume_seed_staging || true', installer)
        self.assertLess(installer.index('capture_volume_seeds\nMOUNT_INDEX=0'),
                        installer.index('while IFS=$\'\\t\' read -r TYPE TARGET'))


if __name__ == "__main__":
    unittest.main()
