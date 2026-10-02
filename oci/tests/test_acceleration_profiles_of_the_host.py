"""An application offers the acceleration profiles the host can run."""

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

NODE = "/dev/dri/renderD128"


class OptionsUI(RecordingUI):
    def __init__(self, answers=None):
        super().__init__(answers)
        self.options, self.messages = {}, []

    def choose(self, text, options, default=None):
        self.options[text] = [tag for tag, _ in options]
        return super().choose(text, options, default)

    def message(self, text, title=None):
        self.messages.append(text)


@patch("proxmenux_oci.i18n.language", return_value="en")
@patch("proxmenux_oci.installer.host.storages", side_effect=storages)
@patch("proxmenux_oci.installer.host.bridges", return_value=[{"iface": "vmbr0", "cidr": "192.0.2.10/24"}])
@patch("proxmenux_oci.installer.host.timezone", return_value="Europe/Madrid")
class HostProfileTests(unittest.TestCase):
    catalog = Catalog(ROOT)

    def offered(self, app, gpus, kfd=False, answer=None):
        template = self.catalog.compose(app)
        prompt = template["proxmox"]["installer_profile"]["hardware_acceleration"]["prompt"]
        ui = OptionsUI({prompt: answer} if answer else None)
        with patch("proxmenux_oci.installer.host.gpus", return_value=gpus), \
                patch("pathlib.Path.is_char_device", return_value=kfd):
            plan = build_deployment(template, ui, DEFAULT_MODE)
        return ui.options.get(prompt), ui, plan

    def test_an_amd_host_is_not_offered_nvidia(self, *_):
        amd = {"intel": [], "amd": [NODE], "nvidia": False}
        self.assertEqual(self.offered("frigate", amd, kfd=True)[0], ["none", "vaapi", "rocm"])
        self.assertEqual(self.offered("ollama", amd, kfd=True)[0], ["cpu", "rocm"])
        self.assertEqual(self.offered("llamacpp", amd, kfd=True)[0], ["cpu", "rocm"])

    def test_rocm_is_not_offered_without_its_compute_device(self, *_):
        amd = {"intel": [], "amd": [NODE], "nvidia": False}
        self.assertEqual(self.offered("frigate", amd, kfd=False)[0], ["none", "vaapi"])

    def test_an_intel_and_nvidia_host_is_not_offered_amd(self, *_):
        both = {"intel": [NODE], "amd": [], "nvidia": True}
        self.assertEqual(self.offered("frigate", both)[0], ["none", "vaapi", "nvidia"])
        self.assertEqual(self.offered("llamacpp", both)[0], ["cpu", "nvidia", "intel"])

    def test_a_host_without_gpu_is_told_and_not_asked(self, *_):
        nothing = {"intel": [], "amd": [], "nvidia": False}
        for app in ("faster-whisper", "ollama", "frigate"):
            options, ui, plan = self.offered(app, nothing)
            self.assertIsNone(options, app)
            self.assertTrue(any("No usable GPU" in message for message in ui.messages), app)
            self.assertEqual(plan["devices"], [], app)

    def test_the_render_node_proposed_belongs_to_the_gpu_of_the_profile(self, *_):
        # The first render node of this host is the NVIDIA one; Intel's is the second.
        gpus = {"intel": ["/dev/dri/renderD129"], "amd": [], "nvidia": True}
        _, _, plan = self.offered("llamacpp", gpus, answer="intel")
        self.assertEqual([device["host_path"] for device in plan["devices"]], ["/dev/dri/renderD129"])


if __name__ == "__main__":
    unittest.main()
