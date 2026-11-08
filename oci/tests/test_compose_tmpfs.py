"""Compose volatile paths use native mounts, not persistent storage."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'remote'))
from proxmenux_oci import custom
from proxmenux_oci.converter import _compose_tmpfs_mounts
from proxmenux_oci.installer import build_deployment
from proxmenux_oci.stack import DefaultsUI, ordered_services, service_template
import oci_runtime_settings as runtime


class ComposeTmpfs(unittest.TestCase):
    def single(self, **settings):
        return custom.template_from_compose(yaml.safe_dump({'services': {'app': {
            'image': 'nginx:alpine', 'ports': ['80:80'], **settings}}}))

    def test_string_list_and_long_syntax_map_without_persistent_disks(self):
        for settings in ({'tmpfs': '/tmp:size=64m'}, {'tmpfs': ['/tmp:size=64m']},
                         {'volumes': [{'type': 'tmpfs', 'target': '/tmp', 'tmpfs': {'size': 67108864}}]}):
            with self.subTest(settings=settings):
                template = self.single(**settings)
                self.assertTrue(template['compatibility']['automatic_install_candidate'])
                self.assertEqual(template['container_contract']['volumes'], [])
                mount = template['proxmox']['installer_profile']['tmpfs_mounts'][0]
                self.assertEqual((mount['container_path'], mount['default_size_mb'], mount['mode']),
                                 ('/tmp', 64, '01777'))
                self.assertNotIn('size_from_memory', mount)

    def test_modes_ids_and_supported_mount_flags_survive_render_and_json(self):
        template = self.single(tmpfs=['/run/app:ro,size=1.5m,mode=1770,uid=1001,gid=1002,noexec'])
        mount = template['proxmox']['installer_profile']['tmpfs_mounts'][0]
        self.assertEqual(mount['default_size_mb'], 2)
        self.assertEqual((mount['uid'], mount['gid'], mount['mode']), (1001, 1002, '01770'))
        plan = json.loads(json.dumps({'tmpfs_mounts': [{**mount, 'size_mb': mount['default_size_mb']}]}))
        rendered = runtime.tmpfs_lines(plan)[0]
        self.assertIn('run/app tmpfs ro,nosuid,nodev,noexec,uid=1001,gid=1002,mode=01770,size=2M', rendered)

    def test_long_permissions_are_octal_bits_and_read_only_is_preserved(self):
        for mode in ('1777', 0o1777):
            template = self.single(volumes=[{'type': 'tmpfs', 'target': '/run', 'read_only': True,
                                             'tmpfs': {'size': '8m', 'mode': mode}}])
            item = template['proxmox']['installer_profile']['tmpfs_mounts'][0]
            self.assertEqual(item['mode'], '01777')
            self.assertEqual(item['mount_options'], ['ro', 'nosuid', 'nodev'])
            self.assertEqual((item['uid'], item['gid']), (0, 0))

    def test_omitted_size_uses_half_the_selected_lxc_ram(self):
        template = self.single(tmpfs='/tmp', mem_limit='2g')
        with patch('proxmenux_oci.host.memory_total_mb', return_value=8192), \
             patch('proxmenux_oci.host.cpu_count', return_value=4), \
             patch('proxmenux_oci.installer.ask_storage', return_value='local-zfs'), \
             patch('proxmenux_oci.host.timezone', return_value='UTC'):
            plan = build_deployment(template, DefaultsUI())
        self.assertEqual(plan['tmpfs_mounts'][0]['size_mb'], 1024)
        self.assertEqual(plan['mounts'], [])
        self.assertIn('mode=01777', runtime.tmpfs_lines(plan)[0])

    def test_advanced_memory_choice_sets_the_implicit_capacity(self):
        class UI(DefaultsUI):
            def ask(self, text, default=None, required=True):
                return '4096' if text == 'Memory in MB' else super().ask(text, default, required)
        with patch('proxmenux_oci.host.memory_total_mb', return_value=8192), \
             patch('proxmenux_oci.host.cpu_count', return_value=4), \
             patch('proxmenux_oci.host.gpus', return_value={'intel': [], 'amd': [], 'nvidia': False}), \
             patch('proxmenux_oci.installer.ask_storage', return_value='local-zfs'), \
             patch('proxmenux_oci.installer.ask_bridge', return_value='vmbr0'), \
             patch('proxmenux_oci.installer.access.ask_ipv4', return_value=('dhcp', None)), \
             patch('proxmenux_oci.host.timezone', return_value='UTC'):
            plan = build_deployment(self.single(tmpfs='/tmp'), UI(), 'advanced')
        self.assertEqual(plan['resources']['memory_mb'], 4096)
        self.assertEqual(plan['tmpfs_mounts'][0]['size_mb'], 2048)

    def test_ipc_and_shm_size_keep_their_mount_alongside_other_tmpfs(self):
        for settings in ({'ipc': 'host'}, {'shm_size': '128m'}):
            template = self.single(tmpfs='/tmp:size=64m', **settings)
            mounts = template['proxmox']['installer_profile']['tmpfs_mounts']
            self.assertEqual({m['container_path'] for m in mounts}, {'/tmp', '/dev/shm'})

    def test_implicit_native_mount_collisions_are_rejected_before_installation(self):
        for target in ('/dev/shm', '/dev/shm/child'):
            if target == '/dev/shm':
                self.assertIsNotNone(_compose_tmpfs_mounts({'ipc': 'host', 'tmpfs': target}))
            else:
                self.assertIsNone(_compose_tmpfs_mounts({'ipc': 'host', 'tmpfs': target}))
        for target in ('/run/nginx', '/run/nginx/child', '/run'):
            self.assertIsNone(_compose_tmpfs_mounts({
                'image': 'lscr.io/linuxserver/libreoffice:latest', 'tmpfs': target}))

    def test_each_stack_member_keeps_its_own_tmpfs_including_long_syntax(self):
        document = {'services': {
            'app': {'image': 'nginx:alpine', 'ports': ['80:80'], 'tmpfs': ['/tmp:size=64m'],
                    'depends_on': ['worker']},
            'worker': {'image': 'nginx:alpine', 'tmpfs': '/run/worker:size=8m',
                       'volumes': [{'type': 'tmpfs', 'target': '/tmp', 'tmpfs': {'size': '32m'}}]}}}
        template = custom.template_from_compose(yaml.safe_dump(document, sort_keys=False))
        self.assertTrue(template['compatibility']['automatic_install_candidate'], template['compatibility'])
        for service in ordered_services(template):
            child = service_template(template, service, service['name'] == 'app')
            self.assertEqual(child['container_contract']['volumes'], [])
            mounts = child['proxmox']['installer_profile']['tmpfs_mounts']
            expected = {'/tmp': 64} if service['name'] == 'app' else {'/run/worker': 8, '/tmp': 32}
            self.assertEqual({m['container_path']: m['default_size_mb'] for m in mounts}, expected)
        again = custom.template_from_oci_compose(json.dumps(template))
        self.assertEqual(again['compose_stack']['services'], template['compose_stack']['services'])

    def test_invalid_inputs_are_blocked_rather_than_dropped(self):
        bad = [None, 1, {}, ['/tmp:size=0'], ['/tmp:size=-1'], ['/tmp:uid=-1'],
               ['/tmp:gid=root'], ['/tmp:uid=4294967295'], ['/tmp:mode=888'],
               ['/tmp:mode=755,mode=777'], ['/tmp:rw,ro'], ['/tmp:size=1m,size=2m'],
               ['/tmp:suid'], ['/tmp:uid=1=2'], ['/tmp:'], ['/tmp,else'],
               ['/tmp\nlxc.include=/etc/passwd'], ['/tmp/../etc'], ['/tmp/./dir'],
               ['/tmp//dir'], ['/tmp/'], ['/etc'], ['/dev'], ['/proc'], ['/data'],
               ['/tmp', '/tmp'], ['/tmp', '/tmp/child'], ['/tmp/child', '/tmp']]
        for value in bad:
            with self.subTest(value=value):
                self.assertIsNone(_compose_tmpfs_mounts({'tmpfs': value}))
        for mount in ({'type': 'tmpfs', 'target': '/tmp', 'source': '/host'},
                      {'type': 'tmpfs', 'target': '/tmp', 'tmpfs': {'unknown': True}},
                      {'type': 'tmpfs', 'target': '/tmp', 'read_only': 'false'},
                      {'type': 'tmpfs', 'target': '/tmp', 'tmpfs': {'mode': True}}):
            with self.subTest(mount=mount):
                self.assertIsNone(_compose_tmpfs_mounts({'volumes': [mount]}))

    def test_persistent_overlap_and_shm_collision_are_blocked(self):
        for volume in ['/tmp', 'data:/tmp', 'data:/tmp/nested', 'data:/run']:
            target = '/run/app' if volume.endswith('/run') else '/tmp'
            self.assertIsNone(_compose_tmpfs_mounts({'tmpfs': target, 'volumes': [volume]}))
        self.assertIsNone(_compose_tmpfs_mounts({'tmpfs': '/dev/shm', 'shm_size': '64m'}))
        self.assertIsNotNone(_compose_tmpfs_mounts({'tmpfs': '/tmp', 'volumes': ['data:/tmp-other']}))

    def test_persistent_path_aliases_cannot_hide_an_overlapping_mount(self):
        for target in ('/tmp//app', '/tmp/./app', '//tmp/app', '/tmp/other/../app'):
            self.assertIsNone(_compose_tmpfs_mounts({'tmpfs': '/tmp/app', 'volumes': ['data:' + target]}))
            plan = {'mounts': [{'container_path': target}], 'tmpfs_mounts': [{
                'container_path': '/tmp/app', 'size_mb': 64, 'mount_options': ['rw']}]}
            with self.assertRaisesRegex(ValueError, 'overlaps'):
                runtime.tmpfs_lines(plan)

    def test_unsupported_tmpfs_keeps_compatibility_blocker(self):
        template = self.single(tmpfs=['/tmp:unknown=yes'])
        self.assertFalse(template['compatibility']['automatic_install_candidate'])
        self.assertIn('tmpfs-format-options-or-overlap', template['compatibility']['untranslated_blockers'])

    def test_invalid_long_tmpfs_is_not_lost_while_compiling_stack_members(self):
        document = {'services': {
            'app': {'image': 'nginx:alpine', 'ports': ['80:80']},
            'worker': {'image': 'nginx:alpine', 'volumes': [
                {'type': 'tmpfs', 'target': '/tmp', 'source': '/etc'}]}}}
        template = custom.template_from_compose(yaml.safe_dump(document))
        self.assertFalse(template['compatibility']['automatic_install_candidate'])
        self.assertTrue(any('tmpfs' in error for error in template['compatibility']['untranslated_blockers']))

    def test_main_tmpfs_does_not_change_other_members_image_volume_policy(self):
        document = {'services': {
            'app': {'image': 'nginx:alpine', 'ports': ['80:80'], 'tmpfs': '/tmp'},
            'worker': {'image': 'nginx:alpine', 'tmpfs': '/run/worker'}}}
        template = custom.template_from_compose(yaml.safe_dump(document))
        for service in ordered_services(template):
            child = service_template(template, service)
            paths = child['proxmox']['installer_profile']['non_persistent_image_volumes']
            self.assertEqual(paths, ['/tmp'] if service['name'] == 'app' else ['/run/worker'])


if __name__ == '__main__':
    unittest.main()
