"""The AI applications whose image depends on the GPU take the image and the
devices of the profile that is chosen."""

from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from proxmenux_oci.catalog import Catalog
from proxmenux_oci.installer import DEFAULT_MODE, build_deployment
from test_advanced_flow_order import RecordingUI, storages

RENDER, KFD = "/dev/dri/renderD128", "/dev/kfd"
EXPECTED = {
    "ollama": {"cpu": (":latest", []), "nvidia": (":latest", ["nvidia-runtime"]), "rocm": (":rocm", [RENDER, KFD])},
    "llamacpp": {"cpu": (":server", []), "nvidia": (":server-cuda", ["nvidia-runtime"]),
                 "rocm": (":server-rocm", [RENDER, KFD]), "intel": (":server-intel", [RENDER])},
    "faster-whisper": {"cpu": (":latest", []), "nvidia": (":gpu", ["nvidia-runtime"])},
    "piper": {"cpu": (":latest", []), "nvidia": (":gpu", ["nvidia-runtime"])},
}
SOURCES = {"ollama": "overlays", "llamacpp": "curated", "faster-whisper": "overlays", "piper": "overlays"}


# Every profile is offered: what the host has is checked in its own test.
@patch("proxmenux_oci.installer.host.gpus", return_value={"intel": ["/dev/dri/renderD128"], "amd": ["/dev/dri/renderD128"], "nvidia": True})
@patch("proxmenux_oci.installer._profile_usable", return_value=True)
@patch("proxmenux_oci.i18n.language", return_value="en")
@patch("proxmenux_oci.installer.host.storages", side_effect=storages)
@patch("proxmenux_oci.installer.host.bridges", return_value=[{"iface": "vmbr0", "cidr": "192.0.2.10/24"}])
@patch("proxmenux_oci.installer.host.timezone", return_value="Europe/Madrid")
class AiGpuProfileTests(unittest.TestCase):
    catalog = Catalog(ROOT)

    def test_each_profile_installs_its_image_with_its_devices(self, *_):
        for app, profiles in EXPECTED.items():
            hardware = self.catalog.compose(app)["proxmox"]["installer_profile"]["hardware_acceleration"]
            self.assertEqual([profile["id"] for profile in hardware["profiles"]], list(profiles), app)
            self.assertEqual(hardware["default"], "cpu", app)
            for profile, (tag, devices) in profiles.items():
                template = self.catalog.compose(app)
                plan = build_deployment(template, RecordingUI({hardware["prompt"]: profile}), DEFAULT_MODE)
                self.assertTrue(template["container_contract"]["image"]["reference"].endswith(tag), (app, profile))
                self.assertEqual([device.get("host_path") or device["kind"] for device in plan["devices"]],
                                 devices, (app, profile))

    def test_the_shipped_copy_matches_its_source(self, *_):
        read = lambda place, app: json.loads((ROOT / f"catalog/{place}/{app}.json").read_text())[
            "proxmox"]["installer_profile"]["hardware_acceleration"]
        for app, source in SOURCES.items():
            self.assertEqual(read(source, app), read("apps", app), app)


if __name__ == "__main__":
    unittest.main()
