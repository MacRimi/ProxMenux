"""Scratch images need runtime DNS without changing image/user network files."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'remote'))
import oci_network_files as network

CONFIG = 'ostype: unmanaged\nunprivileged: 1\nhostname: scratch-app\n'
HOST = 'nameserver 192.0.2.53\nnameserver 2001:db8::53\nsearch home.example\noptions ndots:2\n'


class NetworkFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'root'
        self.root.mkdir()
        self.owner = patch.object(network, 'mapped_root', return_value=(os.getuid(), os.getgid()))
        self.owner.start()
        self.addCleanup(self.owner.stop)

    def prepare(self, config=CONFIG, deployment=None, host=HOST, upstream=''):
        return network.prepare(self.root, config, deployment or {}, host, upstream)

    def test_scratch_gets_resolvers_search_options_and_localhost_before_boot(self):
        previous = os.umask(0o077)
        try:
            self.assertEqual(self.prepare(), ['resolv.conf', 'hosts'])
        finally:
            os.umask(previous)
        self.assertEqual((self.root / 'etc/resolv.conf').read_text(), HOST)
        hosts = (self.root / 'etc/hosts').read_text()
        self.assertIn('127.0.0.1 localhost\n', hosts)
        self.assertIn('::1 localhost ip6-localhost ip6-loopback\n', hosts)
        self.assertIn('127.0.1.1 scratch-app.home.example scratch-app\n', hosts)
        self.assertEqual((self.root / 'etc').stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.root / 'etc/resolv.conf').stat().st_mode & 0o777, 0o644)

    def test_existing_files_and_later_user_edits_are_never_overwritten(self):
        self.prepare()
        resolver = self.root / 'etc/resolv.conf'
        resolver.write_text('nameserver 198.51.100.53\n')
        self.assertEqual(self.prepare(host=''), [])
        self.assertEqual(resolver.read_text(), 'nameserver 198.51.100.53\n')

    def test_proxmox_dns_and_kept_update_settings_take_precedence(self):
        config = CONFIG + 'nameserver: 198.51.100.1\nsearchdomain: old.example\n'
        self.prepare(config, {'kept_proxmox_settings': {
            'nameserver': '198.51.100.2 2001:db8::2', 'searchdomain': 'new.example'}})
        resolver = (self.root / 'etc/resolv.conf').read_text()
        self.assertIn('nameserver 198.51.100.2\nnameserver 2001:db8::2\n', resolver)
        self.assertIn('search new.example\n', resolver)
        self.assertNotIn('198.51.100.1', resolver)

    def test_host_stub_uses_resolved_upstreams_in_a_dedicated_namespace(self):
        self.prepare(host='nameserver 127.0.0.53\n', upstream='nameserver 192.0.2.54\n')
        self.assertEqual((self.root / 'etc/resolv.conf').read_text(), 'nameserver 192.0.2.54\n')

    def test_shared_host_network_can_use_host_loopback(self):
        self.prepare(CONFIG + 'lxc.net.0.type: none\n', host='nameserver 127.0.0.1\n')
        self.assertIn('nameserver 127.0.0.1\n', (self.root / 'etc/resolv.conf').read_text())

    def test_explicit_container_loopback_is_not_replaced_with_public_dns(self):
        self.prepare(CONFIG + 'nameserver: 127.0.0.1\n')
        self.assertIn('nameserver 127.0.0.1\n', (self.root / 'etc/resolv.conf').read_text())

    def test_no_usable_resolver_fails_before_writing_network_files(self):
        with self.assertRaisesRegex(ValueError, 'No usable DNS server'):
            self.prepare(host='nameserver 127.0.0.53\n')
        self.assertFalse((self.root / 'etc/resolv.conf').exists())
        self.assertFalse((self.root / 'etc/hosts').exists())

    def test_managed_operating_systems_keep_proxmox_native_setup(self):
        self.assertEqual(self.prepare(CONFIG.replace('unmanaged', 'debian')), [])
        self.assertFalse((self.root / 'etc').exists())

    def test_explicit_etc_mount_is_not_populated(self):
        self.assertEqual(self.prepare(deployment={'mounts': [{'container_path': '/etc'}]}), [])
        self.assertFalse((self.root / 'etc').exists())

    def test_explicit_resolver_mount_keeps_that_file_for_the_mount(self):
        self.assertEqual(self.prepare(deployment={'mounts': [{'container_path': '/etc/resolv.conf'}]}), ['hosts'])
        self.assertFalse((self.root / 'etc/resolv.conf').exists())

    def test_ignore_markers_and_dangling_image_links_are_preserved(self):
        etc = self.root / 'etc'
        etc.mkdir()
        (etc / 'resolv.conf').symlink_to('/run/image-resolver/resolv.conf')
        (etc / '.pve-ignore.hosts').touch()
        self.assertEqual(self.prepare(host=''), [])
        self.assertTrue((etc / 'resolv.conf').is_symlink())
        self.assertFalse((etc / 'hosts').exists())

    def test_etc_symlink_cannot_redirect_host_writes(self):
        outside = Path(self.tmp.name) / 'outside'
        outside.mkdir()
        (self.root / 'etc').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            self.prepare()
        self.assertEqual(list(outside.iterdir()), [])

    def test_invalid_hostname_cannot_inject_hosts_entries(self):
        with self.assertRaisesRegex(ValueError, 'Invalid container hostname'):
            self.prepare(CONFIG.replace('scratch-app', 'bad name'))
        self.assertFalse((self.root / 'etc/resolv.conf').exists())

    def test_invalid_nameserver_is_rejected(self):
        with self.assertRaises(ValueError):
            self.prepare(CONFIG + 'nameserver: not-an-address\n')

    def test_fully_qualified_hostname_does_not_get_another_domain(self):
        self.prepare(CONFIG.replace('scratch-app', 'scratch-app.example'))
        self.assertIn('127.0.1.1 scratch-app.example\n', (self.root / 'etc/hosts').read_text())

    def test_installer_transfers_helper_for_local_and_ssh_before_extra_hosts(self):
        launcher = (ROOT / 'src/proxmenux_oci/installer.py').read_text()
        self.assertEqual(launcher.count("'oci_network_files.py'"), 2)
        script = (ROOT / 'remote/install_oci.sh').read_text()
        self.assertLess(script.rindex('\nprepare_unmanaged_network_files\n'),
                        script.rindex('\napply_extra_hosts\n'))


if __name__ == '__main__':
    unittest.main()
