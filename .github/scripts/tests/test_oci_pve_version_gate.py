"""OCI manager Apps opens only on Proxmox VE 9.1 or later, the first release
that runs OCI images as LXC containers."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = ROOT / 'scripts/oci/oci_manager_apps.sh'


class OciPveVersionGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = LAUNCHER.read_text(encoding='utf-8')
        cls.function = ''.join(re.search(rf'^{name}\(\) \{{\n.*?^\}}\n', text, re.M | re.S).group(0)
                               for name in ('pve_manager_version', 'pve_supports_oci'))
        cls.text = text

    def supported(self, version):
        with tempfile.TemporaryDirectory() as folder:
            fake = Path(folder, 'dpkg-query')
            # Without Proxmox the package is not installed: dpkg-query fails.
            fake.write_text('#!/bin/sh\nexit 1\n' if version is None else
                            f'#!/bin/sh\nprintf %s "{version}"\n')
            fake.chmod(0o755)
            result = subprocess.run(['bash', '-c', f'PATH={folder}:/usr/bin:/bin\n{self.function}pve_supports_oci'],
                                    capture_output=True, text=True)
        return result.returncode == 0

    def test_versions_from_9_1_open_it(self):
        for version in ('9.1.0', '9.1.4', '9.2.2', '10.0.1'):
            with self.subTest(version=version):
                self.assertTrue(self.supported(version))

    def test_older_versions_and_hosts_without_proxmox_do_not(self):
        for version in ('8.4.1', '9.0.11', None):
            with self.subTest(version=version):
                self.assertFalse(self.supported(version))

    def test_the_version_is_read_without_the_slow_pveversion(self):
        self.assertNotIn('pveversion', self.function)

    def test_it_is_checked_before_anything_is_installed(self):
        self.assertLess(self.text.index('if ! pve_supports_oci; then'), self.text.index('ensure_oci_dependencies || exit 1'))


if __name__ == '__main__':
    unittest.main()
