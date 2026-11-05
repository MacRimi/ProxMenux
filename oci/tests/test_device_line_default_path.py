"""A device added from the Proxmox interface is written with its path as the
first value, without `path=`. Every reader of the container configuration
accepts both forms."""
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'remote'))

import oci_gpu_devices as devices  # noqa: E402
import oci_instance_reconcile as reconcile  # noqa: E402


class DeviceFieldsTests(unittest.TestCase):
    def test_both_forms_give_the_same_fields(self):
        expected = {'path': '/dev/dri/renderD128', 'gid': '993'}
        self.assertEqual(devices.device_fields('/dev/dri/renderD128,gid=993'), expected)
        self.assertEqual(devices.device_fields('path=/dev/dri/renderD128,gid=993'), expected)
        self.assertEqual(devices.device_fields('/dev/apex_0'), {'path': '/dev/apex_0'})

    def test_a_value_without_name_after_the_first_is_refused(self):
        for value in ('/dev/dri/renderD128,993', 'gid=993,/dev/dri/renderD128', ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                devices.device_fields(value)

    def test_actual_devices_reads_a_line_written_by_proxmox(self):
        config = (b'arch: amd64\n'
                  b'dev0: /dev/dri/renderD128,gid=993\n'
                  b'dev1: path=/dev/apex_0,mode=0660\n')
        self.assertEqual(devices.actual_devices(config), {
            '/dev/dri/renderD128': {'path': '/dev/dri/renderD128', 'gid': '993'},
            '/dev/apex_0': {'path': '/dev/apex_0', 'mode': '0660'},
        })

    def test_the_same_device_in_both_forms_is_a_duplicate(self):
        config = b'dev0: /dev/dri/renderD128\ndev1: path=/dev/dri/renderD128\n'
        with self.assertRaises(ValueError):
            devices.actual_devices(config)

    def test_adoption_names_the_line_it_cannot_read(self):
        with self.assertRaisesRegex(ValueError, '^dev2: '):
            reconcile._device('dev2', '/dev/dri/renderD128,993')


class NoPairParsingLeftTests(unittest.TestCase):
    def test_no_reader_builds_the_fields_from_pairs_alone(self):
        pattern = re.compile(r"dict\(\s*\w+\.split\('=', 1\) for \w+ in .*split\(','\)")
        for path in sorted((ROOT / 'remote').glob('*.py')):
            source = path.read_text()
            for line in source.splitlines():
                if 'dev' in line or 'properties' in line:
                    with self.subTest(file=path.name):
                        self.assertIsNone(pattern.search(line), line)


class ShellDuplicateCheckTests(unittest.TestCase):
    def check(self, config, path):
        script = ('pct() { printf "%s" "$CONFIG"; }\n'
                  f'pct config 1 | grep -Eq "^dev[0-9]+: ((.*,)?path=)?{path}(,|$)"')
        return subprocess.run(['bash', '-c', script], env={'CONFIG': config, 'PATH': '/usr/bin:/bin'}).returncode

    def test_the_installer_sees_a_device_already_added_in_either_form(self):
        self.assertEqual(self.check('dev0: /dev/ttyUSB0,gid=20\n', '/dev/ttyUSB0'), 0)
        self.assertEqual(self.check('dev0: mode=0660,path=/dev/ttyUSB0\n', '/dev/ttyUSB0'), 0)
        self.assertEqual(self.check('dev0: /dev/ttyUSB1\n', '/dev/ttyUSB0'), 1)
        self.assertEqual(self.check('dev0: /dev/ttyUSB01\n', '/dev/ttyUSB0'), 1)

    def test_the_installer_uses_that_check(self):
        source = (ROOT / 'remote/oci_ui.sh').read_text()
        self.assertIn('grep -Eq "^dev[0-9]+: ((.*,)?path=)?${path}(,|$)"', source)


if __name__ == '__main__':
    unittest.main()
