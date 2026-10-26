"""The passthrough entries of a VM that belong to a GPU are the GPU, the audio
at its slot and the devices of its IOMMU group. Another function at the same
slot is a device of its own: on an AMD APU the USB controllers share the slot
of the integrated graphics, and a VM that only has one of them does not use
the GPU."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
HELPERS = ROOT / "scripts/global/pci_passthrough_helpers.sh"
SCRIPTS = [ROOT / "scripts/gpu_tpu" / name
           for name in ("switch_gpu_mode.sh", "switch_gpu_mode_direct.sh", "add_gpu_vm.sh")]
IGPU = "0000:05:00.0"
# The functions of the slot of an AMD APU, and a discrete card.
CLASSES = {"0000:05:00.0": "0x030000", "0000:05:00.1": "0x040300", "0000:05:00.3": "0x0c0330",
           "0000:05:00.4": "0x0c0330", "0000:05:00.6": "0x040300",
           "0000:01:00.0": "0x030000", "0000:01:00.1": "0x040300"}


@unittest.skipUnless(shutil.which("bash"), "bash is needed")
class GpuEntriesTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        for bdf, value in CLASSES.items():
            (self.folder / "sys" / bdf).mkdir(parents=True)
            (self.folder / "sys" / bdf / "class").write_text(value + "\n")

    def entries(self, config, *group, gpu=IGPU):
        conf = self.folder / "vm.conf"
        conf.write_text(config)
        script = f'source "{HELPERS}"; _vm_gpu_hostpci_indexes "$1" "$2" "${{@:3}}"'
        done = subprocess.run(["bash", "-c", script, "bash", str(conf), gpu, *group], capture_output=True, text=True,
                              env={"PMX_PCI_SYSFS": str(self.folder / "sys"), "PATH": "/usr/bin:/bin"}, check=False)
        self.assertEqual(done.stderr, "")
        return done.stdout.split()

    def test_a_vm_with_only_a_usb_controller_of_that_slot_does_not_have_the_gpu(self):
        self.assertEqual(self.entries("hostpci0: 0000:01:00.0,pcie=1,x-vga=1\nhostpci1: 0000:01:00.1,pcie=1\n"
                                      "hostpci2: 0000:05:00.4,pcie=1\n"), [])

    def test_the_gpu_goes_with_the_audio_of_its_slot_and_the_usb_stays(self):
        self.assertEqual(self.entries("hostpci0: 0000:05:00.0,pcie=1,x-vga=1\nhostpci1: 0000:05:00.1,pcie=1\n"
                                      "hostpci2: 0000:05:00.4,pcie=1\nhostpci3: 0000:05:00.6\n"), ["0", "1", "3"])

    def test_a_device_of_the_same_iommu_group_goes_with_the_gpu(self):
        self.assertEqual(self.entries("hostpci0: 0000:05:00.0\nhostpci1: 0000:05:00.4\n", "0000:05:00.4"), ["0", "1"])

    def test_the_whole_slot_carries_the_gpu(self):
        self.assertEqual(self.entries("hostpci0: 05:00,pcie=1\nhostpci1: 0000:01:00.0\n"), ["0"])

    def test_several_devices_in_one_entry(self):
        self.assertEqual(self.entries("hostpci4: 0000:05:00.0;0000:05:00.1,pcie=1\n"), ["4"])

    def test_addresses_are_read_with_or_without_domain_and_in_any_case(self):
        self.assertEqual(self.entries("hostpci0: 05:00.0,pcie=1\n", gpu="05:00.0"), ["0"])
        self.assertEqual(self.entries("hostpci0: 0000:0A:00.0\n", gpu="0000:0a:00.0"), ["0"])

    def test_another_gpu_and_a_slot_that_only_looks_alike_are_left(self):
        # 00:02 inside 0000:02:00.0 is not the same device.
        self.assertEqual(self.entries("hostpci0: 0000:02:00.0\n", gpu="0000:00:02.0"), [])
        self.assertEqual(self.entries("hostpci0: 0000:01:00.0\nhostpci1: 0000:05:00.0\n", gpu="0000:01:00.0"), ["0"])

    def test_snapshots_and_resource_mappings_are_not_read(self):
        self.assertEqual(self.entries("hostpci0: 0000:01:00.0\n[snap1]\nhostpci0: 0000:05:00.0\n"), [])
        self.assertEqual(self.entries("hostpci0: mapping=gpu1,pcie=1\nhostpci1: 0000:05:00.1\n"), [])

    def test_the_gpu_scripts_decide_through_it(self):
        for script in SCRIPTS:
            with self.subTest(script=script.name):
                source = script.read_text()
                self.assertIn("_vm_gpu_hostpci_indexes", source)
                # No entry is deleted, or taken for the GPU, by its slot alone.
                self.assertNotIn("sed -E -i \"/^hostpci", source)
                self.assertNotRegex(source, r'grep -qE "hostpci\[0-9\]\+:\.\*\$\{pci_slot\}"')
                self.assertNotRegex(source, r"\$\{slot\}\(\\\\\.\[0-7\]\)\?")

    def test_the_device_check_does_not_match_a_neighbour(self):
        script = (f'qm() {{ printf "hostpci0: 0000:05:00.4,pcie=1\\n"; }}; source "{HELPERS}"; '
                  '_pci_slot_assigned_to_vm 0000:05:00.0 100 && echo gpu; '
                  '_pci_slot_assigned_to_vm 0000:05:00.4 100 && echo usb; true')
        done = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
        self.assertEqual(done.stdout.split(), ["usb"])


if __name__ == "__main__":
    unittest.main()
