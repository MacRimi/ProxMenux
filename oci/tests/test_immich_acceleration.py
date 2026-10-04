"""Immich asks in one menu, in both installation modes, what runs its video
transcoding and its recognition: the CPU, or each usable GPU of the host for
both or for only one of them."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from proxmenux_oci.catalog import Catalog
from proxmenux_oci.installer import ADVANCED_MODE, DEFAULT_MODE, build_deployment
from test_advanced_flow_order import RecordingUI, addresses, storages

PROMPT = "Hardware acceleration for Immich"
NODE = "/dev/dri/renderD128"
INTEL = {"intel": [NODE], "amd": [], "nvidia": False}
AMD = {"intel": [], "amd": [NODE], "nvidia": False}
BOTH = {"intel": [NODE], "amd": [], "nvidia": True}
NOTHING = {"intel": [], "amd": [], "nvidia": False}


class OptionsUI(RecordingUI):
    def __init__(self, answers=None):
        super().__init__(answers)
        self.options = {}
        self.defaults = {}
        self.messages = []

    def choose(self, text, options, default=None):
        self.options[text] = [tag for tag, _ in options]
        self.defaults[text] = default
        return super().choose(text, options, default)

    def message(self, text, title=None):
        self.messages.append(text)


@patch("proxmenux_oci.i18n.language", return_value="en")
@patch("proxmenux_oci.installer.host.storages", side_effect=storages)
@patch("proxmenux_oci.installer.host.bridges", return_value=[{"iface": "vmbr0", "cidr": "192.0.2.10/24"}])
@patch("proxmenux_oci.installer.host.timezone", return_value="Europe/Madrid")
@patch("proxmenux_oci.installer.host.rocm_blocker", return_value=None)
@patch("proxmenux_oci.installer.access.ask_addresses", side_effect=addresses)
class ImmichAccelerationTests(unittest.TestCase):
    template = Catalog(ROOT).compose("immich")

    def plan(self, gpus, mode, answer=None):
        ui = OptionsUI({PROMPT: answer} if answer else None)
        with patch("proxmenux_oci.installer.host.gpus", return_value=gpus):
            plan = build_deployment(self.template, ui, mode)
        return ui, (plan["video_transcoding"]["acceleration"], plan["machine_learning"]["acceleration"]), plan

    def test_the_menu_is_asked_in_both_modes_with_what_the_host_has(self, *_):
        for mode in (DEFAULT_MODE, ADVANCED_MODE):
            ui, _, _ = self.plan(INTEL, mode)
            self.assertEqual(ui.options[PROMPT], ["cpu", "intel", "intel-video", "intel-ml"], mode)
        ui, _, _ = self.plan(BOTH, DEFAULT_MODE)
        self.assertEqual(ui.options[PROMPT], ["cpu", "intel", "intel-video", "intel-ml",
                                              "nvidia", "nvidia-video", "nvidia-ml", "intel+nvidia"])

    def test_the_first_gpu_is_proposed_whole(self, *_):
        ui, result, _ = self.plan(BOTH, DEFAULT_MODE)
        self.assertEqual(ui.defaults[PROMPT], "intel")
        self.assertEqual(result, ("vaapi", "openvino"))

    def test_every_option_gives_the_gpu_to_what_it_names(self, *_):
        expected = {"cpu": ("cpu", "cpu"), "intel": ("vaapi", "openvino"), "intel-video": ("vaapi", "cpu"),
                    "intel-ml": ("cpu", "openvino"), "nvidia": ("nvenc", "cuda"), "nvidia-video": ("nvenc", "cpu"),
                    "nvidia-ml": ("cpu", "cuda"), "intel+nvidia": ("vaapi", "cuda")}
        for answer, result in expected.items():
            self.assertEqual(self.plan(BOTH, DEFAULT_MODE, answer)[1], result, answer)
        for answer, result in {"amd": ("vaapi", "rocm"), "amd-video": ("vaapi", "cpu"),
                               "amd-ml": ("cpu", "rocm")}.items():
            self.assertEqual(self.plan(AMD, DEFAULT_MODE, answer)[1], result, answer)

    def test_recognition_alone_still_gets_its_render_device(self, *_):
        for gpus, answer in ((INTEL, "intel-ml"), (AMD, "amd-ml")):
            _, _, plan = self.plan(gpus, DEFAULT_MODE, answer)
            self.assertEqual(plan["machine_learning"]["render_device"], NODE, answer)
            self.assertIsNone(plan["video_transcoding"]["render_device"], answer)

    def test_a_host_without_usable_gpu_says_so_and_installs_on_the_cpu(self, *_):
        for mode in (DEFAULT_MODE, ADVANCED_MODE):
            ui, result, _ = self.plan(NOTHING, mode)
            self.assertNotIn(PROMPT, ui.options, mode)
            self.assertEqual(len(ui.messages), 1, mode)
            self.assertIn("No usable GPU", ui.messages[0])
            self.assertEqual(result, ("cpu", "cpu"), mode)

    def test_an_amd_host_that_cannot_run_rocm_offers_video_only_and_says_why(self, *_):
        for blocker, text in (("kfd", "/dev/kfd"), ("space", "40 GB"), ("generation", "no support for the AMD GPU")):
            with patch("proxmenux_oci.installer.host.rocm_blocker", return_value=blocker), \
                    patch("proxmenux_oci.installer.host.amd_gpu_name", return_value="Lucienne (gfx90c)"):
                ui, result, _ = self.plan(AMD, DEFAULT_MODE)
            self.assertEqual(ui.options[PROMPT], ["cpu", "amd-video"], blocker)
            self.assertEqual(ui.defaults[PROMPT], "amd-video", blocker)
            self.assertEqual(result, ("vaapi", "cpu"), blocker)
            self.assertTrue(any(text in message and "Recognition is not offered" in message
                                for message in ui.messages), blocker)

    def test_a_gpu_rocm_supports_is_proposed_whole(self, *_):
        for target in (100300, 110501, None):
            ui, result, plan = self.plan(dict(AMD, amd_gfx_target=target), DEFAULT_MODE)
            self.assertEqual(ui.defaults[PROMPT], "amd", target)
            self.assertEqual(result, ("vaapi", "rocm"), target)
            self.assertIsNone(plan["machine_learning"]["gfx_override"], target)

    def test_a_gpu_rocm_does_not_support_officially_is_offered_as_experimental(self, *_):
        gpus = dict(AMD, amd_gfx_target=100305)
        with patch("proxmenux_oci.installer.host.amd_gpu_name", return_value="Radeon 680M (gfx1035)"):
            # Never the proposal: left alone, recognition stays on the CPU.
            ui, result, _ = self.plan(gpus, DEFAULT_MODE)
            self.assertEqual(ui.options[PROMPT], ["cpu", "amd", "amd-video", "amd-ml"])
            self.assertEqual(ui.defaults[PROMPT], "amd-video")
            self.assertEqual(result, ("vaapi", "cpu"))
            # Chosen and confirmed, it is installed with the generation of its family.
            ui = OptionsUI({PROMPT: "amd"})
            ui.confirm = lambda text, default=False: True if "ROCm does not support this GPU" in text else default
            with patch("proxmenux_oci.installer.host.gpus", return_value=gpus):
                plan = build_deployment(self.template, ui, DEFAULT_MODE)
            self.assertEqual(plan["machine_learning"]["acceleration"], "rocm")
            self.assertEqual(plan["machine_learning"]["gfx_override"], "10.3.0")
            # Declined, the menu is asked again.
            answers = iter(["amd", "amd-video"])
            ui = OptionsUI()
            ui.choose = lambda text, options, default=None: next(answers) if text == PROMPT else default
            with patch("proxmenux_oci.installer.host.gpus", return_value=gpus):
                plan = build_deployment(self.template, ui, DEFAULT_MODE)
            self.assertEqual(plan["machine_learning"]["acceleration"], "cpu")
            self.assertEqual(plan["video_transcoding"]["acceleration"], "vaapi")

    def test_the_780m_family_is_presented_as_its_generation(self, *_):
        gpus = dict(AMD, amd_gfx_target=110003)
        ui = OptionsUI({PROMPT: "amd-ml"})
        ui.confirm = lambda text, default=False: True if "ROCm does not support this GPU" in text else default
        with patch("proxmenux_oci.installer.host.gpus", return_value=gpus), \
                patch("proxmenux_oci.installer.host.amd_gpu_name", return_value="Radeon 780M (gfx1103)"):
            plan = build_deployment(self.template, ui, DEFAULT_MODE)
        self.assertEqual(plan["machine_learning"]["gfx_override"], "11.0.0")

    def test_machine_learning_gets_four_cores_and_at_least_four_gigabytes(self, *_):
        _, _, plan = self.plan(BOTH, DEFAULT_MODE, "cpu")
        self.assertEqual(plan["machine_learning"]["resources"]["cores"], 4)
        self.assertEqual(plan["machine_learning"]["resources"]["memory_mb"], 4096)
        for gpus, answer in ((BOTH, "nvidia"), (INTEL, "intel"), (AMD, "amd")):
            _, _, plan = self.plan(gpus, DEFAULT_MODE, answer)
            self.assertEqual(plan["machine_learning"]["resources"]["memory_mb"], 8192, answer)

    def test_the_installers_give_the_gpu_to_both_containers(self, *_):
        script = (ROOT / "remote/install_immich_stack.sh").read_text()
        helper = (ROOT / "remote/oci_immich_ml.sh").read_text()
        self.assertIn('configure_immich_nvidia "$SERVER_ID" "compute,video,utility"', script)
        self.assertIn('configure_immich_nvidia "$ML_ID" "compute,utility"', helper)
        self.assertIn('--dev1 "path=/dev/kfd', helper)
        self.assertIn("MIGraphXExecutionProvider", helper)
        self.assertIn("ML_ROOTFS_SIZE=40", helper)
        self.assertIn('--rootfs "${ROOTFS_STORAGE}:${ML_ROOTFS_SIZE}"', script)
        self.assertIn("'rocm')", (ROOT / "remote/oci_stack_replay.py").read_text())
        self.assertIn("MIGraphXExecutionProvider", (ROOT / "remote/oci_stack_native.py").read_text())

    def test_the_name_of_the_machine_learning_container_is_not_translated(self, *_):
        script = (ROOT / "remote/install_immich_stack.sh").read_text()
        self.assertNotIn('translate "Machine learning"', script)
        self.assertNotIn('translate("Machine learning")', (ROOT / "src/proxmenux_oci/cli.py").read_text())


if __name__ == "__main__":
    unittest.main()
