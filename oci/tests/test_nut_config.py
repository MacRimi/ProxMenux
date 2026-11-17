"""A NUT server watches every UPS passed to its container, each with the
driver its vendor needs, and two UPS of one model are told apart."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))
sys.path.insert(0, str(ROOT / "src"))

import oci_nut_config as nut  # noqa: E402

ENVIRONMENT = [{'name': 'NAME', 'value': 'ups'}, {'name': 'DESCRIPTION', 'value': 'UPS'},
               {'name': 'API_USER', 'value': 'upsmon'}, {'name': 'API_PASSWORD', 'value': '5e6ceb1633bd569b'}]


def ups(port, vendor='06da', product='0003', serial=None, **extra):
    identity = {'vendor': vendor, 'product': product, 'port': port}
    if serial:
        identity['serial'] = serial
    return {'id': f'ups-{port}', 'kind': 'usb', 'container_path': '/dev/bus/usb', 'usb': identity, **extra}


def render(*devices, environment=ENVIRONMENT):
    return nut.render({'devices': list(devices), 'environment': environment})


class RenderTests(unittest.TestCase):
    def test_one_ups_gets_the_driver_of_its_vendor(self):
        files = render(ups('3-3', '0463', 'ffff'))
        self.assertIn('[ups]\n        driver = usbhid-ups\n        port = auto\n        vendorid = 0463\n'
                      '        productid = ffff\n        desc = "UPS"', files['/etc/nut/ups.conf'])
        self.assertNotIn('busport', files['/etc/nut/ups.conf'])
        self.assertIn('MONITOR ups@localhost 1 upsmon 5e6ceb1633bd569b primary', files['/etc/nut/upsmon.conf'])
        self.assertIn('[upsmon]\n        password = 5e6ceb1633bd569b\n        upsmon primary', files['/etc/nut/upsd.users'])
        self.assertIn('LISTEN 0.0.0.0 3493', files['/etc/nut/upsd.conf'])
        # The image does not add its own section of one UPS on top.
        self.assertEqual(files['/etc/nut/.setup'], '')

    def test_two_ups_of_one_model_without_serial_are_told_apart_by_their_port(self):
        files = render(ups('1-3'), ups('1-4'))
        conf = files['/etc/nut/ups.conf']
        self.assertIn('[ups]\n        driver = nutdrv_qx', conf)
        self.assertIn('[ups2]\n        driver = nutdrv_qx', conf)
        self.assertIn('busport = "003"', conf)
        self.assertIn('busport = "004"', conf)
        self.assertIn('desc = "UPS 1"', conf)
        monitors = [line for line in files['/etc/nut/upsmon.conf'].splitlines() if line.startswith('MONITOR')]
        self.assertEqual([line.split()[1] for line in monitors], ['ups@localhost', 'ups2@localhost'])

    def test_a_real_serial_number_tells_them_apart_instead(self):
        conf = render(ups('1-3', serial='AB12'), ups('1-4', serial='CD34'))['/etc/nut/ups.conf']
        self.assertIn('serial = "AB12"', conf)
        self.assertNotIn('busport', conf)

    def test_the_driver_chosen_at_install_is_kept(self):
        conf = render(ups('3-3', '0463', 'ffff', nut_driver='blazer_usb'))['/etc/nut/ups.conf']
        self.assertIn('driver = blazer_usb', conf)
        with self.assertRaises(ValueError):
            render(ups('3-3', nut_driver='rm -rf'))

    def test_vendors(self):
        self.assertEqual(nut.driver_for({'vendor': '06da', 'product': '0003'}), 'nutdrv_qx')
        self.assertEqual(nut.driver_for({'vendor': '06da', 'product': 'ffff'}), 'usbhid-ups')
        self.assertEqual(nut.driver_for({'vendor': '051d', 'product': '0002'}), 'usbhid-ups')
        self.assertEqual(nut.driver_for({'vendor': '0665', 'product': '5161'}), 'nutdrv_qx')

    def test_ups_on_ports_with_the_same_number_are_reported(self):
        same = [ups('1-3'), ups('1-4.3')]
        self.assertEqual(len(nut.ambiguous(same)), 1)
        self.assertEqual(nut.ambiguous([ups('1-3'), ups('1-4')]), [])
        self.assertEqual(nut.ambiguous([ups('1-3', serial='A1'), ups('1-4.3', serial='B2')]), [])

    def test_a_password_nut_cannot_read_is_refused(self):
        for password in ('', 'with space', 'quote"d', 'line\nbreak'):
            environment = [*ENVIRONMENT[:3], {'name': 'API_PASSWORD', 'value': password}]
            with self.subTest(password=password), self.assertRaises(ValueError):
                render(ups('3-3'), environment=environment)

    def test_nothing_is_written_without_a_ups(self):
        self.assertEqual(render(), {})
        serial = {'id': 'z', 'kind': 'usb', 'serial_link': '/dev/serial/by-id/x', 'container_path': '/dev/ttyACM0',
                  'major': 166, 'usb': {'vendor': '1cf1', 'product': '0030', 'port': '3-9'}}
        self.assertEqual(render(serial), {})


class WriteTests(unittest.TestCase):
    def test_the_files_are_written_for_the_root_of_the_container(self):
        with tempfile.TemporaryDirectory() as temp:
            rootfs = Path(temp)
            (rootfs / 'etc/nut').mkdir(parents=True)
            (rootfs / 'etc/nut/ups.conf').write_text('# example of the image\n')
            with mock.patch.object(nut.os, 'chown') as chown:
                written = nut.write(rootfs, {'devices': [ups('3-3', '0463', 'ffff')], 'environment': ENVIRONMENT},
                                    100000, 100000)
            self.assertEqual(written, ['/etc/nut/.setup', '/etc/nut/ups.conf', '/etc/nut/upsd.conf',
                                       '/etc/nut/upsd.users', '/etc/nut/upsmon.conf'])
            self.assertIn('driver = usbhid-ups', (rootfs / 'etc/nut/ups.conf').read_text())
            self.assertEqual(oct((rootfs / 'etc/nut/upsd.users').stat().st_mode & 0o777), '0o640')
            self.assertTrue(all(call.args[1:] == (100000, 100000) for call in chown.call_args_list))
            self.assertFalse(list((rootfs / 'etc/nut').glob('.*.proxmenux')))

    def test_a_link_in_the_container_is_not_followed(self):
        with tempfile.TemporaryDirectory() as temp:
            rootfs = Path(temp)
            (rootfs / 'etc/nut').mkdir(parents=True)
            (rootfs / 'etc/nut/ups.conf').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):
                nut.write(rootfs, {'devices': [ups('3-3')], 'environment': ENVIRONMENT}, 0, 0)


class InstallerTests(unittest.TestCase):
    ROWS = [{'path': '/dev/bus/usb/001/004', 'name': 'Phoenixtec 1300VA UPS', 'kind': 'UPS'},
            {'path': '/dev/bus/usb/001/005', 'name': 'Phoenixtec 1300VA UPS', 'kind': 'UPS'},
            {'path': '/dev/ttyACM0', 'name': 'ConBee II', 'kind': 'Serial'}]

    def test_the_default_installation_watches_every_ups(self):
        from proxmenux_oci import installer
        with mock.patch.object(installer.host, 'usb_devices', return_value=self.ROWS):
            self.assertEqual(installer.ups_paths({'host_path_default': ''}, False, None, set()),
                             ['/dev/bus/usb/001/004', '/dev/bus/usb/001/005'])

    def test_the_advanced_installation_chooses_among_them(self):
        from proxmenux_oci import installer
        ui = mock.Mock()
        ui.checklist.return_value = ['/dev/bus/usb/001/005']
        with mock.patch.object(installer.host, 'usb_devices', return_value=self.ROWS):
            self.assertEqual(installer.ups_paths({'host_path_default': ''}, True, ui, set()), ['/dev/bus/usb/001/005'])
        self.assertEqual(ui.checklist.call_args.args[2], ['/dev/bus/usb/001/004', '/dev/bus/usb/001/005'])

    def test_the_driver_variable_shows_the_driver_of_the_first_ups(self):
        from proxmenux_oci import installer
        devices = [ups('1-3', nut_driver='nutdrv_qx')]
        environment = installer.ups_environment(devices, [{'name': 'DRIVER', 'value': 'usbhid-ups'}], mock.Mock())
        self.assertEqual(environment, [{'name': 'DRIVER', 'value': 'nutdrv_qx', 'sensitive': False}])

    def test_the_recipe_writes_the_configuration_and_proposes_no_root_hub(self):
        for folder in ('apps', 'curated'):
            recipe = json.loads((ROOT / 'catalog' / folder / 'nut-server.json').read_text())
            profile = recipe['proxmox']['installer_profile']
            self.assertIs(profile.get('nut_configuration'), True)
            self.assertNotIn('/001/001', profile['device_requests'][0]['host_path_default'])


if __name__ == "__main__":
    unittest.main()
