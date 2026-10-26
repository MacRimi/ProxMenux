"""rqlite uses its image default command and persists the default data directory."""

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RqliteProfileTests(unittest.TestCase):
    def test_default_startup_persists_default_data_directory(self):
        curated = json.loads((ROOT / "catalog/curated/rqlite.json").read_text())
        app = json.loads((ROOT / "catalog/apps/rqlite.json").read_text())
        self.assertEqual(curated, app)

        # The official image's default `run` entrypoint starts rqlited and
        # uses DATA_DIR=/rqlite/file/data. Avoid an override: positional
        # non-flag arguments are executed literally by its entrypoint.
        compose_service = curated["compose_stack"]["services"][0]["compose"]
        original_compose = json.loads(curated["container_contract"]["original_compose"])
        self.assertNotIn("runtime", curated["proxmox"]["installer_profile"])
        image_policy = curated["proxmox"]["image_metadata_policy"]
        self.assertEqual(image_policy["entrypoint"], "import-from-oci-image")
        self.assertEqual(image_policy["cmd"], "import-from-oci-image")
        for config in (compose_service, original_compose["services"]["rqlite"]):
            self.assertNotIn("command", config)

        image = curated["container_contract"]["image"]
        self.assertEqual(image["reference"], "ghcr.io/rqlite/rqlite:latest")
        self.assertEqual(image["registry"], "ghcr.io")
        self.assertEqual(image["repository"], "ghcr.io/rqlite/rqlite")
        self.assertEqual(original_compose["services"]["rqlite"]["image"], image["reference"])

        mounts = [
            volume["container_path"]
            for volume in curated["container_contract"]["volumes"]
        ]
        self.assertIn("/rqlite/file", mounts)
        self.assertTrue(
            any(
                path == "/rqlite/file/data"
                or "/rqlite/file/data".startswith(path.rstrip("/") + "/")
                for path in mounts
            )
        )


if __name__ == "__main__":
    unittest.main()
