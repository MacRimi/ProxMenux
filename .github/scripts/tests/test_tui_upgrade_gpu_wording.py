"""Run the inert Node TUI consumer fixture in the existing offline i18n lane."""
import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[3]


class TuiUpgradeGpuWording(unittest.TestCase):
    def test_source_extracted_node_consumer(self):
        fixture = ROOT / 'tests/test_tui_upgrade_gpu_wording.cjs'
        self.assertTrue(fixture.is_file(), 'Node fixture must be packaged with the candidate')
        node = os.environ.get('NODE_BINARY') or 'node'
        result = subprocess.run([node, str(fixture)], cwd=ROOT, capture_output=True,
                                text=True, timeout=60, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertEqual(result.returncode, 0, result.stdout + '\n' + result.stderr)
        self.assertIn('PASS: extracted upgrade/GPU consumers', result.stdout)


if __name__ == '__main__':
    unittest.main()
