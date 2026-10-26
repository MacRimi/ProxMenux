"""The rqlite data directory is a positional argument to rqlited."""

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RqliteProfileTests(unittest.TestCase):
    def test_persistent_data_directory_is_passed_positionally(self):
        curated = json.loads((ROOT / "catalog/curated/rqlite.json").read_text())
        app = json.loads((ROOT / "catalog/apps/rqlite.json").read_text())
        self.assertEqual(curated, app)

        data_dir = "/rqlite/file"
        self.assertEqual(curated["proxmox"]["installer_profile"]["runtime"]["command"], [data_dir])
        self.assertEqual(curated["compose_stack"]["services"][0]["compose"]["command"], [data_dir])
        original_compose = json.loads(curated["container_contract"]["original_compose"])
        self.assertEqual(original_compose["services"]["rqlite"]["command"], [data_dir])
        image = curated["container_contract"]["image"]
        self.assertEqual(image["reference"], "ghcr.io/rqlite/rqlite:latest")
        self.assertEqual(image["registry"], "ghcr.io")
        self.assertEqual(image["repository"], "ghcr.io/rqlite/rqlite")
        self.assertEqual(original_compose["services"]["rqlite"]["image"], image["reference"])

        mounted_paths = [volume["container_path"] for volume in curated["container_contract"]["volumes"]]
        self.assertIn(data_dir, mounted_paths)


if __name__ == "__main__":
    unittest.main()
