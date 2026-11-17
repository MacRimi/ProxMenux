"""A USB device is passed to a container by what it is, not by the number the
kernel gives it: the container keeps it after a reboot or a reconnection, and
the engine checks, keeps and removes what that takes like its other lines."""

from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_usb_passthrough as usb  # noqa: E402

UPS = {'id': 'ups-usb', 'kind': 'usb', 'container_path': '/dev/bus/usb',
       'usb': {'vendor': '0463', 'product': 'ffff', 'port': '3-3'}}
ZIGBEE = {'id': 'zigbee', 'kind': 'usb', 'container_path': '/dev/ttyACM0', 'major': 166,
          'serial_link': '/dev/serial/by-id/usb-dresden_elektronik_ConBee_II_DE2141544-if00',
          'usb': {'vendor': '1cf1', 'product': '0030', 'serial': 'DE2141544', 'port': '3-9'}}
BASE = b'arch: amd64\nhostname: nut\n'


def device_dir(root, port, vendor, product, serial='', busnum=3, devnum=10):
    directory = root / 'bus/usb/devices' / port
    directory.mkdir(parents=True)
    for name, value in (('idVendor', vendor), ('idProduct', product), ('serial', serial),
                        ('busnum', str(busnum)), ('devnum', str(devnum))):
        (directory / name).write_text(value + '\n')
    return directory


class LinesTests(unittest.TestCase):
    def test_a_usb_device_gets_the_usb_tree_and_the_right_to_open_it(self):
        self.assertEqual(usb.lines({'devices': [UPS]}), [usb.USB_ALLOW, usb.USB_MOUNT])

    def test_a_serial_adapter_is_mounted_by_its_stable_name_where_the_app_looks(self):
        self.assertEqual(usb.lines({'devices': [ZIGBEE]}), [
            'lxc.cgroup2.devices.allow: c 166:* rwm',
            'lxc.mount.entry: /dev/serial/by-id/usb-dresden_elektronik_ConBee_II_DE2141544-if00 dev/ttyACM0 '
            'none bind,optional,create=file'])

    def test_two_devices_of_one_kind_share_their_lines(self):
        second = dict(UPS, id='ups-2', usb={'vendor': '0463', 'product': 'ffff', 'port': '3-4'})
        self.assertEqual(usb.lines({'devices': [UPS, second]}), [usb.USB_ALLOW, usb.USB_MOUNT])

    def test_two_adapters_cannot_take_the_same_path(self):
        with self.assertRaises(ValueError):
            usb.lines({'devices': [ZIGBEE, dict(ZIGBEE, id='other')]})

    def test_other_devices_are_not_touched(self):
        gpu = {'id': 'gpu', 'kind': 'character-device', 'host_path': '/dev/dri/renderD128'}
        self.assertEqual(usb.lines({'devices': [gpu]}), [])

    def test_a_forged_record_is_refused(self):
        for broken in (dict(UPS, usb={'vendor': '0463"', 'product': 'ffff', 'port': '3-3'}),
                       dict(UPS, container_path='/'),
                       dict(ZIGBEE, container_path='/dev/../etc/passwd'),
                       dict(ZIGBEE, serial_link='/etc/shadow')):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                usb.lines({'devices': [broken]})


class ConfigurationTests(unittest.TestCase):
    def config(self, *devices):
        return BASE + ''.join(f'{line}\n' for line in usb.lines({'devices': list(devices)})).encode()

    def test_the_lines_written_here_are_recognized_and_left_out(self):
        config = self.config(UPS, ZIGBEE)
        self.assertEqual(usb.without(config), BASE)
        self.assertTrue(all(usb.own(line) for line in usb.lines({'devices': [UPS, ZIGBEE]})))
        self.assertFalse(usb.own('lxc.mount.entry: /mnt/data mnt/data none bind,create=dir 0 0'))
        self.assertFalse(usb.own('lxc.cgroup2.devices.allow: c 226:* rwm'))

    def test_check_accepts_exactly_the_recorded_devices(self):
        usb.check(self.config(UPS), {'devices': [UPS]})
        for config, devices in ((BASE, [UPS]), (self.config(UPS), []), (self.config(UPS, ZIGBEE), [UPS])):
            with self.subTest(devices=devices), self.assertRaises(ValueError):
                usb.check(config, {'devices': devices})

    def test_a_snapshot_section_is_not_counted(self):
        config = self.config(UPS) + b'\n[before]\n' + usb.USB_ALLOW.encode() + b'\n'
        usb.check(config, {'devices': [UPS]})

    def test_apply_writes_the_lines_and_the_rule_and_keeps_the_rest(self):
        with tempfile.TemporaryDirectory() as temp:
            conf_dir, rules = Path(temp) / 'lxc', Path(temp) / 'rules'
            conf_dir.mkdir(), rules.mkdir()
            conf = conf_dir / '120.conf'
            conf.write_text('arch: amd64\nlxc.mount.entry: /dev/bus/usb dev/bus/usb none bind,optional,create=dir\n'
                            '\n[snap]\narch: amd64\n')
            with mock.patch.object(usb, 'CONF_DIR', conf_dir), mock.patch.object(usb, 'RULES', rules), \
                    mock.patch.object(usb.subprocess, 'run') as run:
                usb.apply(120, {'devices': [UPS, ZIGBEE]})
                text = conf.read_text()
                self.assertEqual(text.split('\n[', 1)[0].splitlines(),
                                 ['arch: amd64', *usb.lines({'devices': [UPS, ZIGBEE]})])
                self.assertIn('\n[snap]\narch: amd64\n', text)
                rule = (rules / '99-proxmenux-oci-120.rules').read_text()
                self.assertIn('SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="0463", '
                              'ATTR{idProduct}=="ffff", MODE="0666"', rule)
                self.assertIn('SUBSYSTEM=="tty", ATTRS{idVendor}=="1cf1", ATTRS{idProduct}=="0030", '
                              'ATTRS{serial}=="DE2141544", MODE="0666"', rule)
                self.assertTrue(run.called)
                # Taking the devices away leaves no line and no rule.
                usb.apply(120, {'devices': []})
                self.assertEqual(conf.read_text().split('\n[', 1)[0], 'arch: amd64\n')
                self.assertFalse((rules / '99-proxmenux-oci-120.rules').exists())

    def test_a_device_left_out_gets_its_default_permission_back(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(usb, 'RULES', Path(temp)), \
                mock.patch.object(usb.subprocess, 'run') as run:
            usb.write_rules(121, {'devices': [UPS, ZIGBEE]})
            calls = [call.args[0] for call in run.call_args_list]
            self.assertIn(['udevadm', 'trigger', '--action=change', '--subsystem-match=usb',
                           '--attr-match=idVendor=0463', '--attr-match=idProduct=ffff'], calls)
            self.assertIn(['udevadm', 'trigger', '--action=change', '--subsystem-match=tty',
                           '--property-match=ID_VENDOR_ID=1cf1'], calls)
            run.reset_mock()
            # Modify takes the UPS away: only it gets an add event.
            usb.write_rules(121, {'devices': [ZIGBEE]})
            calls = [call.args[0] for call in run.call_args_list]
            self.assertIn(['udevadm', 'trigger', '--action=add', '--subsystem-match=usb',
                           '--attr-match=idVendor=0463', '--attr-match=idProduct=ffff'], calls)
            self.assertNotIn(['udevadm', 'trigger', '--action=add', '--subsystem-match=tty',
                              '--property-match=ID_VENDOR_ID=1cf1'], calls)
            run.reset_mock()
            usb.remove(121)
            calls = [call.args[0] for call in run.call_args_list]
            self.assertIn(['udevadm', 'trigger', '--action=add', '--subsystem-match=tty',
                           '--property-match=ID_VENDOR_ID=1cf1'], calls)
            self.assertFalse(usb.rule_path(121).exists())

    def test_a_device_that_comes_back_restarts_its_container(self):
        rule = usb.rules(122, {'devices': [UPS, ZIGBEE]})
        run = ('RUN+="/usr/bin/systemd-run --no-block --quiet --collect --unit=proxmenux-usb-reconnect-122 '
               f'/usr/bin/python3 {usb.ENGINE_SCRIPT} reconnect 122"')
        self.assertIn('ACTION=="add", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="0463", '
                      f'ATTR{{idProduct}}=="ffff", {run}', rule)
        self.assertIn('ACTION=="add", SUBSYSTEM=="tty", ATTRS{idVendor}=="1cf1", ATTRS{idProduct}=="0030", '
                      f'ATTRS{{serial}}=="DE2141544", {run}', rule)
        self.assertEqual(usb._pairs(rule), {('usb', '0463', 'ffff'), ('tty', '1cf1', '0030')})

    def test_the_whole_usb_tree_has_no_rule(self):
        tree = usb.tree_entry('usb')
        self.assertEqual(usb.lines({'devices': [tree]}), [usb.USB_ALLOW, usb.USB_MOUNT])
        self.assertEqual(usb.rules(120, {'devices': [tree]}), '')


class IdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.sys = Path(temp.name) / 'sys'
        patch = mock.patch.object(usb, 'SYS', self.sys)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_placeholder_serial_number_identifies_nothing(self):
        directory = device_dir(self.sys, '3-3', '0463', 'ffff', serial='000000000')
        self.assertEqual(usb._identity(directory), {'vendor': '0463', 'product': 'ffff', 'port': '3-3'})
        real = device_dir(self.sys, '3-9', '1cf1', '0030', serial='DE2141544')
        self.assertEqual(usb._identity(real)['serial'], 'DE2141544')

    def test_a_usb_node_is_recorded_by_its_identity(self):
        directory = device_dir(self.sys, '3-3', '0463', 'ffff', serial='000000000')
        (self.sys / 'dev/char').mkdir(parents=True)
        (self.sys / 'dev/char/189:265').symlink_to(directory)
        with mock.patch.object(usb, '_device_number', return_value=(189, 265)):
            value = usb.converted({'id': 'ups-usb', 'kind': 'character-device', 'host_path': '/dev/bus/usb/003/010',
                                   'container_path': '/dev/bus/usb/003/010', 'mode': '0666'})
        self.assertEqual(value, UPS)

    def test_a_gpu_and_a_device_tied_to_a_uid_stay_as_they_are(self):
        for device in ({'id': 'gpu', 'kind': 'character-device', 'host_path': '/dev/dri/renderD128'},
                       {'id': 'u', 'kind': 'character-device', 'host_path': '/dev/ttyUSB0', 'uid': 1000}):
            self.assertIs(usb.converted(device), device)

    def test_the_usb_tree_of_a_recipe_becomes_the_tree_entry(self):
        self.assertEqual(usb.converted({'id': 'usb', 'kind': 'character-device-tree', 'host_path': '/dev/bus/usb'}),
                         usb.tree_entry('usb'))

    def test_an_installation_keeps_a_device_that_is_not_plugged_in(self):
        old = {'id': 'ups-usb', 'kind': 'character-device', 'host_path': '/dev/bus/usb/003/010'}
        with mock.patch.object(usb, '_device_number', side_effect=FileNotFoundError):
            self.assertEqual(usb.migrated([old]), [old])

    def test_the_device_is_found_again_after_the_kernel_numbers_it_again(self):
        device_dir(self.sys, '3-3', '0463', 'ffff', serial='000000000', devnum=12)
        self.assertEqual(usb.present(UPS), '/dev/bus/usb/003/012')
        self.assertIsNone(usb.present(dict(UPS, usb=dict(UPS['usb'], port='3-4'))))


class ReconnectTests(unittest.TestCase):
    """A device that comes back while its container runs restarts it once;
    a stopped or busy container is left alone."""

    def setUp(self):
        import oci_watchdog
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.watchdog = oci_watchdog
        for patch in (mock.patch.object(usb, 'RUN_DIR', Path(temp.name)),
                      mock.patch.object(oci_watchdog, 'is_running', return_value=True),
                      mock.patch.object(oci_watchdog, 'is_busy', return_value=False)):
            patch.start()
            self.addCleanup(patch.stop)
        self.run = mock.patch.object(usb.subprocess, 'run', return_value=mock.Mock(returncode=0)).start()
        self.addCleanup(mock.patch.stopall)

    def reconnect(self, now=1000.0):
        return usb.reconnect(122, sleep=lambda seconds: None, now=now)

    def test_a_running_container_is_restarted_once(self):
        self.assertEqual(self.reconnect(), 'restarted')
        commands = [call.args[0] for call in self.run.call_args_list]
        self.assertEqual(commands, [['pct', 'shutdown', '122', '--timeout', '20', '--forceStop', '1'],
                                    ['systemd-run', '--scope', '--quiet', '--collect', 'pct', 'start', '122']])
        # Another device of the same moment does not restart it again.
        stamp = usb.RUN_DIR / 'proxmenux-usb-reconnect-122'
        os.utime(stamp, (1000.0, 1000.0))
        self.assertEqual(self.reconnect(now=1010.0), 'recent')
        self.assertEqual(self.reconnect(now=1000.0 + usb.QUIET_SECONDS + 1), 'restarted')

    def test_a_stopped_or_busy_container_is_left_alone(self):
        with mock.patch.object(self.watchdog, 'is_running', return_value=False):
            self.assertEqual(self.reconnect(), 'stopped')
        with mock.patch.object(self.watchdog, 'is_busy', return_value=True):
            self.assertEqual(self.reconnect(), 'busy')
        self.run.assert_not_called()


class EngineTests(unittest.TestCase):
    """The rest of the engine leaves these lines to this module."""

    def test_device_checks_skip_identity_devices(self):
        import oci_gpu_devices as gpu_devices
        self.assertEqual(gpu_devices.planned({'devices': [UPS, ZIGBEE]}), {})
        self.assertEqual(gpu_devices.check(BASE, {'devices': [UPS]}), {})

    def test_the_acceleration_filter_and_the_nvidia_mounts_ignore_them(self):
        import oci_nvidia_runtime as nvidia
        import oci_runtime_settings as runtime_settings
        config = BASE + ''.join(f'{line}\n' for line in usb.lines({'devices': [UPS, ZIGBEE]})).encode()
        self.assertEqual(runtime_settings.filter_config(config, {}), BASE)
        self.assertEqual(nvidia.mount_lines(config), [])

    def test_they_are_not_taken_for_lines_the_user_added(self):
        import oci_instance_transaction as transaction
        config = BASE + ''.join(f'{line}\n' for line in usb.lines({'devices': [UPS]})).encode()
        record = {'observed': {'config': BASE.decode()}, 'deployment': {'devices': [UPS]}}
        self.assertEqual(transaction.custom_lxc(record, config), [])
        self.assertNotIn('lxc.cgroup2.devices.allow', transaction.settings(config))

    def test_an_installation_rebuilt_gets_its_usb_devices_by_identity(self):
        import oci_instance_transaction as transaction
        old = {'id': 'ups-usb', 'kind': 'character-device', 'host_path': '/dev/bus/usb/003/010'}
        with mock.patch.object(usb, 'converted', return_value=UPS):
            candidate = transaction.with_usb_identity({'deployment': {'devices': [old]}})
        self.assertEqual(candidate['deployment']['devices'], [UPS])

    def test_removing_the_container_removes_its_rule(self):
        import oci_remove
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(usb, 'RULES', Path(temp)), \
                mock.patch.object(usb.subprocess, 'run'):
            rule = usb.rule_path(130)
            rule.write_text('# rule\n')
            self.assertTrue(oci_remove._leftovers(130))
            usb.remove(130)
            self.assertFalse(rule.exists())


if __name__ == "__main__":
    unittest.main()
