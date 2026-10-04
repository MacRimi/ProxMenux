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


class FrigateAmdGenerationTests(unittest.TestCase):
    """The ROCm image of Frigate carries the kernels of RDNA2 and newer GPUs:
    on an older one, such as the integrated Vega of a Ryzen 5000U, its
    detector aborts, so the profile is not offered there."""

    def profile(self):
        profiles = Catalog(ROOT).compose("frigate")["proxmox"]["installer_profile"]["hardware_acceleration"]["profiles"]
        return next(item for item in profiles if item["id"] == "rocm")

    def usable(self, target):
        from proxmenux_oci.installer import _profile_usable
        found = {"intel": [], "amd": ["/dev/dri/renderD128"], "nvidia": False, "amd_gfx_target": target}
        with patch("proxmenux_oci.installer.Path.is_char_device", return_value=True):
            return _profile_usable(self.profile(), found)

    def test_the_profile_is_offered_on_the_generations_the_image_supports(self):
        self.assertIn(100300, self.profile()["amd_gfx_targets"])
        self.assertTrue(self.usable(100300))
        self.assertTrue(self.usable(110501))
        self.assertFalse(self.usable(90012))
        self.assertFalse(self.usable(100100))
        # The other GPUs of a family it supports are offered as experimental.
        self.assertTrue(self.usable(100305))
        self.assertTrue(self.usable(110003))
        # A driver that does not say the generation does not hide the profile.
        self.assertTrue(self.usable(None))

    def test_the_generation_is_read_from_the_compute_driver(self):
        import tempfile
        from proxmenux_oci import host
        with tempfile.TemporaryDirectory() as directory:
            nodes = Path(directory) / "sys/class/kfd/kfd/topology/nodes"
            for index, value in enumerate((0, 90012)):
                (nodes / str(index)).mkdir(parents=True)
                (nodes / str(index) / "properties").write_text(f"simd_count 32\ngfx_target_version {value}\ndevice_id 5708\n")
            self.assertEqual(host.amd_gfx_target(Path(directory)), 90012)
            self.assertIsNone(host.amd_gfx_target(Path(directory) / "none"))
        self.assertEqual([host.gfx_name(value) for value in (90012, 100300, 110501, 90010, 90402)],
                         ["gfx90c", "gfx1030", "gfx1151", "gfx90a", "gfx942"])

    def test_recognition_with_rocm_needs_a_supported_generation(self):
        from proxmenux_oci import host
        with patch("proxmenux_oci.host.Path.is_char_device", return_value=True), \
                patch("proxmenux_oci.host.storages", return_value=[]):
            for target, expected in ((90012, "generation"), (100100, "generation"), (100305, None),
                                     (110003, None), (110501, None), (90010, None), (None, None)):
                with patch("proxmenux_oci.host.amd_gfx_target", return_value=target):
                    self.assertEqual(host.rocm_blocker("local-lvm"), expected, target)

    def test_how_each_generation_runs_rocm(self):
        from proxmenux_oci import host
        expected = {100300: ("native", None), 110501: ("native", None), 90010: ("native", None),
                    100305: ("experimental", "10.3.0"), 100302: ("experimental", "10.3.0"),
                    110003: ("experimental", "11.0.0"), 90012: (None, None), 100100: (None, None),
                    110502: (None, None), None: ("native", None)}
        for target, (support, override) in expected.items():
            self.assertEqual((host.rocm_support(target), host.rocm_override(target)), (support, override), target)
        # An image with fewer kernels supports fewer generations.
        self.assertIsNone(host.rocm_support(110003, (100300,)))

    def test_the_gpu_is_named_as_its_owner_knows_it(self):
        from proxmenux_oci import host
        from types import SimpleNamespace
        listed = ("35:00.0 VGA compatible controller [0300]: Advanced Micro Devices, Inc. [AMD/ATI] "
                  "Rembrandt [Radeon 680M] [1002:1681] (rev c7)\n")
        plain = "04:00.0 VGA compatible controller [0300]: Advanced Micro Devices, Inc. [AMD/ATI] Lucienne [1002:164c] (rev c1)\n"
        for output, target, name in ((listed, 100305, "Radeon 680M (gfx1035)"), (plain, 90012, "Lucienne (gfx90c)"),
                                     ("", 100300, "AMD GPU (gfx1030)"), ("", None, "AMD GPU")):
            with patch("proxmenux_oci.host.subprocess.run", return_value=SimpleNamespace(stdout=output)), \
                    patch("proxmenux_oci.host.amd_gfx_target", return_value=target):
                self.assertEqual(host.amd_gpu_name(), name)


@patch("proxmenux_oci.i18n.language", return_value="en")
@patch("proxmenux_oci.installer.host.storages", side_effect=storages)
@patch("proxmenux_oci.installer.host.bridges", return_value=[{"iface": "vmbr0", "cidr": "192.0.2.10/24"}])
@patch("proxmenux_oci.installer.host.timezone", return_value="Europe/Madrid")
@patch("proxmenux_oci.installer.Path.is_char_device", return_value=True)
@patch("proxmenux_oci.installer.host.amd_gpu_name", return_value="Radeon 680M (gfx1035)")
class FrigateExperimentalRocmTests(unittest.TestCase):
    """On a GPU ROCm does not support officially the profile is offered as
    experimental, explained before the larger image is downloaded, and never
    taken without a yes."""

    WARNING = "ROCm does not support this GPU"

    class UI(RecordingUI):
        def __init__(self, answers, accept):
            super().__init__(answers)
            self.labels, self.messages, self.accept, self.asked_warning = {}, [], accept, 0

        def choose(self, text, options, default=None):
            self.labels[text] = dict(options)
            return super().choose(text, options, default)

        def confirm(self, text, default=False):
            if FrigateExperimentalRocmTests.WARNING in text:
                self.asked_warning += 1
                return self.accept
            return default

        def message(self, text, title=None):
            self.messages.append(text)

    def build(self, target, answers, accept=True):
        found = {"intel": [], "amd": ["/dev/dri/renderD128"], "nvidia": False, "amd_gfx_target": target}
        ui = self.UI(answers, accept)
        with patch("proxmenux_oci.installer.host.gpus", return_value=found):
            plan = build_deployment(Catalog(ROOT).compose("frigate"), ui, DEFAULT_MODE)
        return ui, plan

    def override(self, plan):
        return [item["value"] for item in plan["environment"] if item["name"] == "HSA_OVERRIDE_GFX_VERSION"]

    def test_the_profile_is_marked_and_confirmed_and_sets_the_generation(self, *_):
        ui, plan = self.build(100305, {PROMPT: "rocm"})
        self.assertIn("experimental on this GPU", ui.labels[PROMPT]["rocm"])
        self.assertEqual(ui.asked_warning, 1)
        self.assertEqual(plan["hardware_profile"], "rocm")
        self.assertEqual(self.override(plan), ["10.3.0"])

    def test_a_supported_gpu_has_no_mark_and_no_question(self, *_):
        ui, plan = self.build(100300, {PROMPT: "rocm"})
        self.assertNotIn("experimental", ui.labels[PROMPT]["rocm"])
        self.assertEqual((ui.asked_warning, self.override(plan)), (0, []))

    def test_without_a_yes_the_menu_is_asked_again(self, *_):
        answers = iter(["rocm", "vaapi"])
        found = {"intel": [], "amd": ["/dev/dri/renderD128"], "nvidia": False, "amd_gfx_target": 100305}
        ui = self.UI({}, False)
        ui.choose = lambda text, options, default=None: next(answers) if text == PROMPT else default
        with patch("proxmenux_oci.installer.host.gpus", return_value=found):
            plan = build_deployment(Catalog(ROOT).compose("frigate"), ui, DEFAULT_MODE)
        self.assertEqual(plan["hardware_profile"], "vaapi")
        self.assertEqual(self.override(plan), [])

    def test_a_gpu_the_image_cannot_use_is_not_offered_and_the_reason_is_said(self, *_):
        with patch("proxmenux_oci.installer.host.amd_gpu_name", return_value="Lucienne (gfx90c)"):
            ui, plan = self.build(90012, {})
        self.assertNotIn("rocm", ui.labels[PROMPT])
        self.assertTrue(any("Lucienne (gfx90c)" in message and "not offered" in message for message in ui.messages))
