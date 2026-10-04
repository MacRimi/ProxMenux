"""A container volume is always part of the backups: an update restores its
application from one, and refuses a volume that would be left out."""

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def volumes_without_backup(value, found=None):
    """Container paths a template would create as a container volume left out of the backups."""
    found = [] if found is None else found
    if isinstance(value, dict):
        managed = value.get("managed_volume")
        if (isinstance(managed, dict) and managed.get("backup") is not True
                and "managed-volume" in (value.get("installation_choice") or [])):
            found.append(value.get("container_path"))
        if value.get("mode") == "managed-volume" and value.get("backup") is False:
            found.append(value.get("container_path"))
        for item in value.values():
            volumes_without_backup(item, found)
    elif isinstance(value, list):
        for item in value:
            volumes_without_backup(item, found)
    return found


class ContainerVolumeBackupTests(unittest.TestCase):
    def test_no_application_of_the_catalog_creates_a_volume_left_out_of_the_backups(self):
        for folder in ("apps", "curated"):
            for path in sorted((ROOT / "catalog" / folder).glob("*.json")):
                template = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(volumes_without_backup(template), [], f"{folder}/{path.name}")

    def test_a_converted_compose_backs_up_every_volume_it_creates(self):
        from proxmenux_oci import converter
        contract = converter._mount_contract(["/srv/app/config:/config", "/srv/app/cache:/cache",
                                              "/srv/app/transcode:/transcode", "/srv/app/tmp:/tmp"], set())
        self.assertEqual([item["container_path"] for item in contract], ["/config", "/cache", "/transcode", "/tmp"])
        self.assertTrue(all(item["managed_volume"]["backup"] is True for item in contract))


if __name__ == "__main__":
    unittest.main()
