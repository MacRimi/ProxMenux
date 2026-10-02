"""Frigate's AMD profile takes the image built for ROCm and the two devices
it needs, and says what is left for the user to set."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from proxmenux_oci.catalog import Catalog
from proxmenux_oci.installer import DEFAULT_MODE, build_deployment
from test_advanced_flow_order import RecordingUI, storages

PROMPT = "Hardware acceleration for Frigate"


# Every profile is offered: what the host has is checked in its own test.
@patch("proxmenux_oci.installer.host.gpus", return_value={"intel": ["/dev/dri/renderD128"], "amd": ["/dev/dri/renderD128"], "nvidia": True})
@patch("proxmenux_oci.installer._profile_usable", return_value=True)
@patch("proxmenux_oci.i18n.language", return_value="en")
@patch("proxmenux_oci.installer.host.storages", side_effect=storages)
@patch("proxmenux_oci.installer.host.bridges", return_value=[{"iface": "vmbr0", "cidr": "192.0.2.10/24"}])
@patch("proxmenux_oci.installer.host.timezone", return_value="Europe/Madrid")
class FrigateAmdProfileTests(unittest.TestCase):
    def build(self, profile):
        template = Catalog(ROOT).compose("frigate")
        plan = build_deployment(template, RecordingUI({PROMPT: profile}), DEFAULT_MODE)
        return template, plan

    def test_the_amd_profile_uses_the_rocm_image_with_both_devices(self, *_):
        template, plan = self.build("rocm")
        self.assertEqual(template["container_contract"]["image"]["reference"],
                         "ghcr.io/blakeblackshear/frigate:stable-rocm")
        self.assertEqual([device["host_path"] for device in plan["devices"]], ["/dev/dri/renderD128", "/dev/kfd"])
        self.assertEqual(plan["devices"][0]["drm_vendor_ids"], ["0x1002"])
        self.assertTrue(any("type: onnx" in note for note in plan["completion_notes"]))

    def test_the_other_profiles_keep_their_image(self, *_):
        for profile, tag in (("none", "stable"), ("vaapi", "stable"), ("nvidia", "stable-tensorrt")):
            template, plan = self.build(profile)
            self.assertTrue(template["container_contract"]["image"]["reference"].endswith(":" + tag), profile)
            self.assertFalse(plan.get("completion_notes"), profile)

    def test_the_shipped_copy_matches_the_curated_profile(self, *_):
        import json
        read = lambda name: json.loads((ROOT / f"catalog/{name}/frigate.json").read_text())[
            "proxmox"]["installer_profile"]["hardware_acceleration"]
        self.assertEqual(read("curated"), read("apps"))


if __name__ == "__main__":
    unittest.main()
