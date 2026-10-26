"""Every path an image declares as a volume is mounted, or stated to hold no data,
so the installed container can be updated."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "remote"))

from proxmenux_oci.catalog import Catalog

# The VOLUME paths of each image, as `skopeo inspect --config` reports them.
DECLARED = {
    "postgresql": ["/var/lib/postgresql"],
    "threadfin": ["/home/threadfin/conf", "/tmp/threadfin"],
    "handbrake-jlesage": ["/config", "/output", "/storage", "/trash", "/watch"],
    "medusa-official": ["/anime", "/config", "/downloads", "/tv"],
    "cloudflared": ["/config", "/root/.cloudflared"],
    "archivebox": ["/data", "/out"],
    "flaresolverr": ["/config"],
    "openspeedtest": ["/var/log/letsencrypt"],
}


class ImageVolumeCoverageTests(unittest.TestCase):
    catalog = Catalog(ROOT)

    def test_declared_volumes_are_mounted_or_hold_no_data(self):
        for app, declared in DECLARED.items():
            template = self.catalog.compose(app)
            mounts = [v["container_path"] for v in template["container_contract"]["volumes"]]
            transient = set(template["proxmox"]["installer_profile"].get("non_persistent_image_volumes", []))
            uncovered = [p for p in declared if p not in transient
                         and not any(p == m or p.startswith(m.rstrip("/") + "/") for m in mounts)]
            self.assertEqual(uncovered, [], app)

    def test_postgresql_keeps_the_versioned_data_directory_on_the_volume(self):
        # PostgreSQL 18 stores PGDATA in /var/lib/postgresql/18/docker.
        template = self.catalog.compose("postgresql")
        self.assertEqual([v["container_path"] for v in template["container_contract"]["volumes"]],
                         ["/var/lib/postgresql"])

    def test_the_updater_leaves_paths_without_data_out(self):
        import oci_instance_transaction
        template = {"proxmox": {"installer_profile": {"non_persistent_image_volumes": ["/tmp/threadfin"]}}}
        self.assertEqual(oci_instance_transaction.non_persistent_image_volumes(template), {"/tmp/threadfin"})
        self.assertEqual(oci_instance_transaction.non_persistent_image_volumes({}), set())


if __name__ == "__main__":
    unittest.main()
