"""The Hardware page keeps its CPU and board blocks on ARM boards."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "AppImage/scripts"))
import system_board_info

ARM_LSCPU = """\
Architecture:             aarch64
  CPU op-mode(s):         32-bit, 64-bit
  Byte Order:             Little Endian
CPU(s):                   4
  On-line CPU(s) list:    0-3
Vendor ID:                ARM
  Model name:             Cortex-A76
    Model:                1
    Thread(s) per core:   1
    Core(s) per cluster:  4
    Socket(s):            -
    Cluster(s):           1
    Stepping:             r4p1
    CPU(s) scaling MHz:   62%
    CPU max MHz:          2400.0000
    CPU min MHz:          1500.0000
Caches (sum of all):
  L1d:                    256 KiB (4 instances)
  L1i:                    256 KiB (4 instances)
  L2:                     2 MiB (4 instances)
  L3:                     2 MiB (1 instance)
Vulnerabilities:
  Spectre v1:             Mitigation; __user pointer sanitization
"""

X86_LSCPU = """\
Architecture:                         x86_64
CPU(s):                               16
Model name:                           Intel(R) Core(TM) i7-10700 CPU @ 2.90GHz
Thread(s) per core:                   2
Core(s) per socket:                   8
Socket(s):                            1
CPU max MHz:                          4800.0000
CPU min MHz:                          800.0000
Virtualization:                       VT-x
L1d cache:                            256 KiB
L1i cache:                            256 KiB
L2 cache:                             2 MiB
L3 cache:                             16 MiB
"""


class LscpuTests(unittest.TestCase):
    def test_arm_dash_socket_count_keeps_the_rest_of_the_cpu_block(self):
        cpu = system_board_info.parse_lscpu(ARM_LSCPU)
        self.assertEqual(cpu["model"], "Cortex-A76")
        self.assertEqual(cpu["total_threads"], 4)
        self.assertEqual(cpu["max_mhz"], 2400.0)
        self.assertNotIn("sockets", cpu)
        self.assertNotIn("cores_per_socket", cpu)

    def test_x86_output_is_read_as_before(self):
        cpu = system_board_info.parse_lscpu(X86_LSCPU)
        self.assertEqual(cpu["sockets"], 1)
        self.assertEqual(cpu["cores_per_socket"], 8)
        self.assertEqual(cpu["total_threads"], 16)
        self.assertEqual(cpu["virtualization"], "VT-x")
        self.assertEqual(cpu["l3_cache"], "16 MiB")
        self.assertEqual(cpu["min_mhz"], 800.0)

    def test_a_comma_decimal_separator_is_read(self):
        cpu = system_board_info.parse_lscpu("CPU max MHz: 1800,0000\nCPU min MHz: 600,0000\n")
        self.assertEqual(cpu["max_mhz"], 1800.0)
        self.assertEqual(cpu["min_mhz"], 600.0)

    def test_garbage_never_raises(self):
        self.assertEqual(system_board_info.parse_lscpu(""), {})
        self.assertEqual(system_board_info.parse_lscpu("Socket(s): many\nCPU(s):\n"), {})


class DeviceTreeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def test_raspberry_pi_board_comes_from_the_device_tree(self):
        (self.root / "model").write_bytes(b"Raspberry Pi 5 Model B Rev 1.0\x00")
        (self.root / "serial-number").write_bytes(b"d83adde2e1b9f5c2\x00")
        (self.root / "compatible").write_bytes(b"raspberrypi,5-model-b\x00brcm,bcm2712\x00")
        board = system_board_info.read_device_tree_board(str(self.root))
        self.assertEqual(board, {
            "model": "Raspberry Pi 5 Model B Rev 1.0",
            "serial": "d83adde2e1b9f5c2",
            "manufacturer": "raspberrypi",
        })

    def test_x86_host_without_device_tree_gets_nothing(self):
        board = system_board_info.read_device_tree_board(str(self.root / "missing"))
        self.assertEqual(board, {})


if __name__ == "__main__":
    unittest.main()
