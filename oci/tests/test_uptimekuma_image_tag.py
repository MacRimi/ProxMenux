"""Uptime Kuma must use the current v2 image line, not the frozen latest tag."""

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci.catalog import Catalog


class UptimeKumaImageTagTests(unittest.TestCase):
    def test_catalog_and_composed_template_use_v2(self):
        entry = json.loads((ROOT / "catalog" / "apps" / "uptimekuma.json").read_text())
        template = Catalog(ROOT).compose("uptimekuma")

        self.assertEqual(
            entry["container_contract"]["image"]["reference"],
            "louislam/uptime-kuma:2",
        )
        self.assertEqual(entry["container_contract"]["image"]["tag"], "2")
        self.assertNotIn("louislam/uptime-kuma:latest", entry["container_contract"]["original_compose"])

        self.assertEqual(
            template["container_contract"]["image"]["reference"],
            "louislam/uptime-kuma:2",
        )
        service = template["compose_stack"]["services"][0]
        self.assertEqual(service["image"], "louislam/uptime-kuma:2")
        self.assertEqual(service["compose"]["image"], "louislam/uptime-kuma:2")


if __name__ == "__main__":
    unittest.main()
