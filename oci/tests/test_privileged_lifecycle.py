"""A privileged container, relaxed confinement, process limits, a monitor of
the host and a single mounted file are rebuilt like any other application."""
import json
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'remote'))
import oci_host_mounts as host_mounts
import oci_instance_transaction as transaction
import oci_runtime_settings as runtime_settings

INSTALLER = (ROOT / 'remote/install_oci.sh').read_text()
GLANCES = json.loads((ROOT / 'catalog/apps/glances.json').read_text())
MONITOR_CONFIG = (b'unprivileged: 0\n'
                  b'lxc.apparmor.profile: unconfined\n'
                  b'lxc.mount.entry: /etc/os-release etc/os-release none bind,create=file,ro 0 0\n'
                  b'lxc.mount.entry: /srv/app.conf etc/app.conf none bind,create=file 0 0\n'
                  b'lxc.mount.entry: tmpfs run/app tmpfs rw,size=64M,create=dir 0 0\n'
                  b'lxc.include: /etc/pve/proxmenux/host-monitor\n'
                  b'lxc.net.0.type: none\n')


def bind(source, target, read_only=True):
    return {'type': 'host-bind', 'container_path': target, 'source': source, 'backup': False, 'read_only': read_only}


class ProfileKeyTests(TestCase):
    def test_each_declared_setting_names_the_entries_the_installer_writes(self):
        deployment = {'security': {'options': {'apparmor_profile': 'unconfined', 'seccomp_profile': 'unconfined',
                                               'drop_all_capabilities': True, 'no_new_privileges': True}},
                      'resources': {'rlimits': [{'name': 'nofile', 'soft': '65536', 'hard': '65536'}]},
                      'host_monitor': 'glances'}
        self.assertEqual(transaction.profile_keys(deployment), {
            'lxc.apparmor.profile', 'lxc.seccomp.profile', 'lxc.cap.drop', 'lxc.cap.keep', 'lxc.include',
            'lxc.prlimit.nofile', 'lxc.net.0.type', 'lxc.hook.mount'})

    def test_a_plain_application_adds_none(self):
        self.assertEqual(transaction.profile_keys({'security': {'unprivileged': True, 'options': {}},
                                                   'resources': {'rlimits': []}}), set())

    def test_a_host_monitor_is_checked_like_any_other_application(self):
        self.assertEqual(transaction.effective_healthcheck(GLANCES)['port'], 61208)
        template = {'proxmox': {'installer_profile': {'host_monitor': 'netdata'}},
                    'first_run': {'endpoints': [{'scheme': 'http', 'port': 19999, 'path': '/'}]}}
        self.assertEqual(transaction.effective_healthcheck(template)['port'], 19999)


class FileBindTests(TestCase):
    def test_single_files_are_read_from_the_raw_entries(self):
        self.assertEqual(runtime_settings.file_binds(MONITOR_CONFIG), {'/etc/os-release': True, '/srv/app.conf': False})

    def test_declared_files_are_not_left_to_the_acceleration_check(self):
        deployment = {'mounts': [bind('/etc/os-release', '/etc/os-release')],
                      'tmpfs_mounts': [{'container_path': '/run/app', 'size_mb': 64, 'mount_options': ['rw']}]}
        left = runtime_settings.filter_config(MONITOR_CONFIG, deployment).decode()
        self.assertNotIn('/etc/os-release', left)
        self.assertNotIn('tmpfs', left)
        self.assertNotIn('lxc.include', left)
        # One the deployment does not declare stays, and is refused there.
        self.assertIn('/srv/app.conf', left)

    def test_a_file_is_told_apart_from_a_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'os-release'
            file.write_text('x')
            self.assertTrue(transaction.is_file_bind(bind(str(file), '/etc/os-release')))
            self.assertFalse(transaction.is_file_bind(bind(tmp, '/data')))
            self.assertTrue(transaction.is_file_bind(bind('/gone/file', '/x'), {'/gone/file': True}))
            self.assertFalse(transaction.is_file_bind({'type': 'managed-volume', 'source': 'local-lvm'}))

    def test_files_are_not_pinned_nor_ask_for_the_host_data_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'os-release'
            file.write_text('x')
            record = {'template': {}, 'observed': {},
                      'deployment': {'mounts': [bind(str(file), '/etc/os-release')]}}
            with patch.object(transaction, 'log'):
                self.assertEqual(transaction.freeze_host_sources(record, record, False), ({}, {}))


class DeclaredSourceTests(TestCase):
    def test_only_a_host_monitor_declares_sources(self):
        contract = {'template': GLANCES, 'deployment': {'host_monitor': 'glances'}}
        self.assertEqual(transaction.declared_sources(contract), {'/etc/os-release'})
        self.assertEqual(transaction.declared_sources({'template': GLANCES, 'deployment': {'host_monitor': None}}), set())

    def test_a_declared_system_directory_is_accepted_and_stays_declared(self):
        with self.assertRaises(ValueError):
            host_mounts.validate_source('/usr')
        value = host_mounts.validate_source('/usr', declared=True)
        self.assertTrue(value['declared'])
        host_mounts.verify_sources({'/usr': value})
        with self.assertRaises(ValueError):
            host_mounts.verify_sources({'/usr': {k: v for k, v in value.items() if k != 'declared'}})

    def test_the_system_mounts_of_a_monitor_need_no_notice_about_host_data(self):
        record = {'template': {'proxmox': {'installer_profile': {'host_monitor_mounts': [{'source': '/usr', 'target': '/host/usr'}]}}},
                  'observed': {}, 'deployment': {'host_monitor': 'netdata', 'mounts': [bind('/usr', '/host/usr')]}}
        with patch.object(transaction, 'log'):
            original, desired = transaction.freeze_host_sources(record, record, False)
        self.assertTrue(original['/usr']['declared'] and desired['/usr']['declared'])


class IncludeTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.include = Path(tmp.name) / 'host-monitor'
        patcher = patch.object(runtime_settings, 'HOST_MONITOR_INCLUDES', (self.include,))
        patcher.start()
        self.addCleanup(patcher.stop)

    def config(self):
        return f'lxc.include: {self.include}\n'.encode()

    def test_the_include_of_a_host_monitor_is_accepted_unchanged(self):
        self.include.write_text(runtime_settings.HOST_MONITOR_CONTENT)
        runtime_settings.check(self.config(), {'host_monitor': 'glances'}, 122)
        runtime_settings.check_recovery(self.config(), {'vmid': 122, 'record': {'deployment': {'host_monitor': 'glances'}}})

    def test_a_changed_include_or_one_nobody_declared_is_refused(self):
        self.include.write_text(runtime_settings.HOST_MONITOR_CONTENT + 'lxc.cap.drop =\n')
        with self.assertRaises(ValueError):
            runtime_settings.check(self.config(), {'host_monitor': 'glances'}, 122)
        self.include.write_text(runtime_settings.HOST_MONITOR_CONTENT)
        with self.assertRaises(ValueError):
            runtime_settings.check(self.config(), {}, 122)

    def test_no_new_privileges_goes_in_the_include_of_the_container(self):
        deployment = {'security': {'options': {'no_new_privileges': True},
                                   'sysctls': [{'name': 'net.ipv4.ip_forward', 'value': '1'}]}}
        self.assertEqual(runtime_settings.sysctl_content(deployment),
                         'lxc.sysctl.net.ipv4.ip_forward = 1\nlxc.no_new_privs = 1\n')
        self.assertEqual(runtime_settings.sysctl_content({'security': {'options': {}}}), '')


class RemovalTests(TestCase):
    def test_the_seccomp_profile_of_a_removed_container_is_deleted(self):
        import oci_remove
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / '126.proxmenux-seccomp'
            profile.write_text('2\ndenylist\n[all]\n')
            with patch.object(runtime_settings, 'seccomp_path', return_value=profile), \
                    patch.object(runtime_settings, 'include_path', return_value=Path(tmp) / 'none'), \
                    patch.object(runtime_settings, 'legacy_include_path', return_value=Path(tmp) / 'none'), \
                    patch.object(oci_remove, 'SNIPPETS', Path(tmp) / 'snippets'), \
                    patch.object(oci_remove, 'MONITOR_APPS', Path(tmp) / 'apps'), \
                    patch.object(oci_remove, 'CLUSTER_RECORDS', Path(tmp) / 'records'):
                self.assertTrue(oci_remove._leftovers(126))
                oci_remove.remove_host_state(126)
            self.assertFalse(profile.exists())


class InstallerTests(TestCase):
    def test_no_new_privileges_is_not_written_as_a_container_setting(self):
        self.assertNotIn('set_lxc_directive "lxc.no_new_privs"', INSTALLER)
        self.assertIn("printf 'lxc.no_new_privs = 1\\n' >>\"$SYSCTL_TEMP\"", INSTALLER)

    def test_a_startup_check_without_its_optional_fields_does_not_end_the_installation(self):
        self.assertIn(".request_timeout_seconds // 5", INSTALLER)
        self.assertIn(".verify_tls // false", INSTALLER)

    def test_seerr_can_write_its_configuration(self):
        for name in ('curated', 'apps'):
            profile = json.loads((ROOT / f'catalog/{name}/seerr.json').read_text())['proxmox']['installer_profile']
            self.assertEqual(profile['volume_owner'], {'uid': 1000, 'gid': 1000})
            self.assertEqual(profile['volume_preparations'][0]['container_path'], '/app/config')
            self.assertEqual(profile['startup_healthcheck']['request_timeout_seconds'], 5)


if __name__ == '__main__':
    import unittest
    unittest.main()
