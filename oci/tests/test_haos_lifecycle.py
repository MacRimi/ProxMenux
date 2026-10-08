"""Home Assistant OS is updated and modified like any other application."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'remote'))
import oci_instance_transaction as transaction

HAOS = json.loads((ROOT / 'catalog/curated/haos-one.json').read_text())
CONFIG = (b'net0: name=eth0,bridge=vmbr0,firewall=1,host-managed=1,hwaddr=BC:24:11:D5:0F:FD,ip=dhcp,type=veth\n'
          b'ostype: unmanaged\n')
ETH0 = b'2: eth0    inet 192.168.0.100/24 brd 192.168.0.255 scope global eth0\\       valid_lft forever\n'


class HaosCheckTests(TestCase):
    def test_the_recipe_has_a_check_so_the_operation_is_not_refused(self):
        check = transaction.effective_healthcheck(HAOS)
        self.assertEqual(check, {'type': 'haos', 'timeout_seconds': 1200})

    def test_the_check_is_left_to_the_installer_profile(self):
        contract = transaction.with_default_healthcheck({'template': json.loads(json.dumps(HAOS))})
        profile = contract['template']['proxmox']['installer_profile']
        self.assertNotIn('startup_healthcheck', profile)
        self.assertEqual(profile['haos_healthcheck'], {'timeout_seconds': 1200})

    def run_commands(self, *args):
        if args[:2] == ('pct', 'config'):
            return CONFIG
        if args[:2] == ('pct', 'status'):
            return b'status: running\n'
        if args[0] == 'lxc-attach':
            return ETH0
        raise AssertionError(args)

    def test_the_container_answers_on_its_own_interface(self):
        with patch.object(transaction, 'run', side_effect=self.run_commands):
            self.assertEqual(transaction.own_addresses(121), ['192.168.0.100'])

    def test_a_restored_container_passes_the_check_of_home_assistant(self):
        import haos_healthcheck
        urls = [{'label': 'Home Assistant', 'url': 'http://192.168.0.100:8123/'}]
        with patch.object(transaction, 'run', side_effect=self.run_commands), \
                patch.object(transaction, 'log'), \
                patch.object(haos_healthcheck, 'wait_ready', return_value=urls) as wait:
            self.assertEqual(transaction.healthcheck(121, HAOS), 'http://192.168.0.100:8123/')
        wait.assert_called_once_with(121, '192.168.0.100', 1200)

    def test_a_restored_container_that_does_not_pass_is_not_confirmed(self):
        import haos_healthcheck
        with patch.object(transaction, 'run', side_effect=self.run_commands), \
                patch.object(transaction, 'log'), \
                patch.object(haos_healthcheck, 'wait_ready', side_effect=RuntimeError('time is up')):
            with self.assertRaises(ValueError):
                transaction.healthcheck(121, HAOS)


class InstallerAddressTests(TestCase):
    """The installer takes the address of an interface of the container, not
    the one of a bridge Docker created inside it."""

    def address(self, listed, attach):
        script = (ROOT / 'remote/install_oci.sh').read_text()
        start = script.index('own_ipv4() {')
        function = script[start:script.index('\n}\n', start) + 3]
        with tempfile.TemporaryDirectory() as tmp:
            for name, body in (('lxc-info', f'printf "{listed}"'),
                               ('pct', 'echo "net0: name=eth0,bridge=vmbr0,ip=dhcp,type=veth"'),
                               ('lxc-attach', attach)):
                path = Path(tmp) / name
                path.write_text(f'#!/bin/bash\n{body}\n')
                path.chmod(0o755)
            result = subprocess.run(['bash', '-c', f'PATH={tmp}:$PATH; VMID=121; {function}\nown_ipv4; echo "rc=$?"'],
                                    capture_output=True, text=True)
        return result.stdout.split()

    def test_the_inner_bridges_are_skipped(self):
        attach = 'echo "2: eth0    inet 192.168.0.100/24 brd 192.168.0.255 scope global eth0"'
        self.assertEqual(self.address('172.30.232.1\\n172.30.32.1\\n192.168.0.100\\n', attach), ['192.168.0.100', 'rc=0'])

    def test_no_address_yet_is_waited_for(self):
        self.assertEqual(self.address('172.30.232.1\\n', 'true'), ['rc=0'])

    def test_interfaces_that_cannot_be_read_leave_it_to_the_caller(self):
        self.assertEqual(self.address('192.168.0.100\\n', 'exit 1'), ['rc=1'])
        self.assertEqual(self.address('', 'true'), ['rc=1'])


if __name__ == '__main__':
    import unittest
    unittest.main()
