"""Glances' Web UI is the only listener used by the native ``-w`` profile."""

from pathlib import Path
import unittest

from proxmenux_oci.catalog import Catalog


class GlancesPortContractTests(unittest.TestCase):
    def test_web_profile_exposes_only_the_web_ui_port(self):
        root = Path(__file__).resolve().parents[1]
        template = Catalog(root).compose("glances")

        ports = template["container_contract"]["ports"]
        self.assertEqual([item["container_port"] for item in ports], [61208])
        self.assertEqual(template["first_run"]["endpoints"], [{
            "label": "Web UI",
            "scheme": "http",
            "port": 61208,
            "path": "/",
            "source": "compose-metadata",
        }])
        self.assertEqual(template["proxmox"]["installer_profile"]["startup_healthcheck"]["port"], 61208)
