"""Parse NVIDIA device rows without confusing subsystem or legacy IDs."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


SOURCE = (Path(__file__).resolve().parents[1] / "scripts/gpu_tpu/nvidia_installer.sh").read_text()


def function(name):
    return re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", SOURCE, re.M | re.S).group(0)


class SupportedGpuIdsTests(unittest.TestCase):
    def parse(self, html):
        result = subprocess.run(
            ["bash", "-c", function("_nvidia_supported_ids_from_page")
             + "_nvidia_supported_ids_from_page"],
            input=html, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines()

    def test_subsystem_qualified_t400_and_t1000_are_supported(self):
        # NVIDIA 595.112.07 lists these devices only in qualified rows.
        self.assertEqual(self.parse('''
<tr id="devid1FF0_1028_1612"><td>NVIDIA T1000 8GB</td>
<td>1FF0 1028 1612</td></tr>
<tr id="devid1FF2_10DE_18FF"><td>NVIDIA T400 4GB</td>
<td>1FF2 10DE 18FF</td></tr>
'''), ["1ff0", "1ff2"])

    def test_unqualified_and_duplicate_rows_are_sorted_and_deduplicated(self):
        self.assertEqual(self.parse('''
<tr id="devid1E30"><td>Quadro RTX 6000</td><td>1E30</td></tr>
<tr id="devid1E30_1028_129E"><td>Quadro RTX 8000</td></tr>
<tr id="devid20B0"><td>A100</td><td>20B0</td></tr>
'''), ["1e30", "20b0"])

    def test_legacy_rows_and_unrelated_hex_cells_are_excluded(self):
        self.assertEqual(self.parse('''
<tr id="devid20B0"><td>A100</td><td>20B0</td></tr>
<td>1234</td>
<p>Below are the legacy GPUs that are no longer supported in the
current driver.</p>
<tr id="devid1CB1"><td>Quadro P1000</td><td>1CB1</td></tr>
'''), ["20b0"])

    def test_cache_refresh_does_not_reuse_fresh_v2_device_list(self):
        prefix = re.search(r'^NVIDIA_GPU_SUPPORT_CACHE_PREFIX="([^"]+)"', SOURCE, re.M).group(1)
        self.assertTrue(prefix.endswith("_v3_"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nvidia_gpu_support_v2_595.txt").write_text("1e30\n")
            script = '\n'.join([
                'NVIDIA_GPU_SUPPORT_CACHE_PREFIX="' + str(root / Path(prefix).name) + '"',
                'NVIDIA_BRANCHES_TTL_SECONDS=86400',
                'get_nvidia_branch_head() { echo 595.112.07; }',
                'curl() { echo \'<tr id="devid1FF2_10DE_18FF"><td>1FF2 10DE 18FF</td></tr>\'; }',
                function("_nvidia_supported_ids_from_page"),
                function("refresh_nvidia_gpu_support_for_major"),
                'refresh_nvidia_gpu_support_for_major 595',
            ])
            result = subprocess.run(["bash", "-c", script], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / "nvidia_gpu_support_v3_595.txt").read_text(), "1ff2\n")


if __name__ == "__main__":
    unittest.main()
