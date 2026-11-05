"""Ownership and mode are preserved on volatile native OCI-LXC mounts."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'remote'))
sys.path.insert(0, str(ROOT / 'src'))

import oci_runtime_settings as runtime_settings


class TmpfsOwnershipTests(unittest.TestCase):
    def test_image_user_is_taken_from_the_effective_lxc_init_identity(self):
        plan = {'tmpfs_mounts': [{
            'container_path': '/run', 'size_mb': 64, 'mount_options': ['rw', 'nosuid', 'nodev'],
            'owner_strategy': 'image-user', 'mode': '0755',
        }]}
        config = b'lxc.init.uid: 65534\nlxc.init.gid: 65534\n'
        self.assertEqual(runtime_settings.tmpfs_lines(plan, config), [
            'tmpfs run tmpfs rw,nosuid,nodev,uid=65534,gid=65534,mode=0755,size=64M,create=dir 0 0'
        ])

    def test_mapped_root_and_application_user_strategies(self):
        root = {'tmpfs_mounts': [{'container_path': '/run/app', 'size_mb': 32,
                                  'mount_options': ['rw'], 'owner_strategy': 'mapped-root'}]}
        app = {'environment': [{'name': 'PUID', 'value': '1001'}, {'name': 'PGID', 'value': '1002'}],
               'tmpfs_mounts': [{'container_path': '/run/app', 'size_mb': 32,
                                 'mount_options': ['rw'], 'owner_strategy': 'mapped-application-user'}]}
        overridden = {'environment': [{'name': 'PUID', 'value': '1001'}, {'name': 'PGID', 'value': '1002'}],
                      'tmpfs_mounts': [{'container_path': '/run/app', 'size_mb': 32,
                                        'mount_options': ['rw'], 'owner_strategy': 'mapped-application-user',
                                        'uid': 2001, 'gid': 2002}]}
        self.assertIn('uid=0,gid=0', runtime_settings.tmpfs_lines(root)[0])
        self.assertIn('uid=1001,gid=1002', runtime_settings.tmpfs_lines(app)[0])
        self.assertIn('uid=2001,gid=2002', runtime_settings.tmpfs_lines(overridden)[0])

    def test_plain_run_mount_is_rejected_without_an_owner_strategy(self):
        plan = {'tmpfs_mounts': [{'container_path': '/run', 'size_mb': 64,
                                  'mount_options': ['rw', 'nosuid', 'nodev']}]}
        with self.assertRaises(ValueError):
            runtime_settings.tmpfs_lines(plan)

    def test_invalid_owner_ids_modes_and_duplicate_init_identity_are_rejected(self):
        app = {'tmpfs_mounts': [{'container_path': '/run/app', 'size_mb': 32,
                                 'mount_options': ['rw'], 'owner_strategy': 'mapped-application-user',
                                 'uid': 'root', 'gid': 10}]}
        mode = {'tmpfs_mounts': [{'container_path': '/run/app', 'size_mb': 32,
                                  'mount_options': ['rw'], 'owner_strategy': 'mapped-root', 'mode': '777'}]}
        image = {'tmpfs_mounts': [{'container_path': '/run/app', 'size_mb': 32,
                                   'mount_options': ['rw'], 'owner_strategy': 'image-user'}]}
        with self.assertRaises(ValueError):
            runtime_settings.tmpfs_lines(app)
        with self.assertRaises(ValueError):
            runtime_settings.tmpfs_lines(mode)
        with self.assertRaises(ValueError):
            runtime_settings.tmpfs_lines(image, b'lxc.init.uid: 1000\nlxc.init.uid: 1001\n')

    def test_runtime_validation_requires_the_exact_rendered_owner_and_mode(self):
        plan = {'vmid': 120, 'tmpfs_mounts': [{
            'container_path': '/run', 'size_mb': 64, 'mount_options': ['rw'],
            'owner_strategy': 'image-user', 'mode': '0755',
        }]}
        entry = 'tmpfs run tmpfs rw,uid=1000,gid=1001,mode=0755,size=64M,create=dir 0 0'
        runtime_settings.check(
            f'lxc.init.uid: 1000\nlxc.init.gid: 1001\nlxc.mount.entry: {entry}\n'.encode(), plan, 120
        )
        with self.assertRaises(ValueError):
            runtime_settings.check(
                f'lxc.init.uid: 1000\nlxc.init.gid: 1001\n'
                'lxc.mount.entry: tmpfs run tmpfs rw,uid=0,gid=0,mode=0755,size=64M,create=dir 0 0\n'.encode(),
                plan, 120,
            )

    def test_acceleration_filter_recognises_image_owned_tmpfs_entry(self):
        plan = {'tmpfs_mounts': [{'container_path': '/run', 'size_mb': 64, 'mount_options': ['rw'],
                                  'owner_strategy': 'image-user', 'mode': '0755'}]}
        line = ('lxc.mount.entry: tmpfs run tmpfs rw,uid=1000,gid=1001,mode=0755,'
                'size=64M,create=dir 0 0\n')
        config = ('lxc.init.uid: 1000\nlxc.init.gid: 1001\n' + line).encode()
        filtered = runtime_settings.filter_config(config, plan).decode()
        self.assertNotIn('tmpfs', filtered)
        self.assertIn('lxc.init.uid: 1000', filtered)

    def test_recovery_accepts_only_journalled_image_user_tmpfs_entries(self):
        plan = {'tmpfs_mounts': [{'container_path': '/run', 'size_mb': 64, 'mount_options': ['rw'],
                                  'owner_strategy': 'image-user', 'mode': '0755'}]}
        old = b'lxc.init.uid: 1000\nlxc.init.gid: 1001\n'
        current_line = ('lxc.mount.entry: tmpfs run tmpfs rw,uid=2000,gid=2001,mode=0755,'
                        'size=64M,create=dir 0 0\n')
        current = ('lxc.init.uid: 2000\nlxc.init.gid: 2001\n' + current_line).encode()
        state = {'vmid': 120, 'before_config': old.decode(), 'record': {'deployment': plan},
                 'candidate_contract': {'deployment': plan}}
        runtime_settings.check_recovery(current, state)
        unknown = current.replace(b'uid=2000,gid=2001', b'uid=2000,gid=3001')
        with self.assertRaises(ValueError):
            runtime_settings.check_recovery(unknown, state)

    def test_input_is_visible_installable_and_uses_its_image_user_for_run(self):
        template = json.loads((ROOT / 'catalog/curated/input.json').read_text())
        profile = template['proxmox']['installer_profile']
        entry = next(item for item in profile['tmpfs_mounts'] if item['container_path'] == '/run')
        index = json.loads((ROOT / 'catalog/index.json').read_text())['applications']
        index_item = next(item for item in index if item['id'] == 'input')
        self.assertEqual(entry['owner_strategy'], 'image-user')
        self.assertEqual(entry['mode'], '0755')
        self.assertTrue(template['compatibility']['automatic_install_candidate'])
        self.assertTrue(index_item['automatic_install_candidate'])
        self.assertFalse(index_item['hidden'])
        self.assertFalse(template['compatibility']['validated'])

    def test_installer_renders_tmpfs_after_the_profile_sets_the_image_identity(self):
        script = (ROOT / 'remote/install_oci.sh').read_text()
        profile = script.index('apply_installer_profile\n', script.index('prepare_managed_format_directories "/var/lib'))
        render = script.index('--render-tmpfs "$DEPLOYMENT_FILE" "$CONF"')
        self.assertLess(profile, render)

    def test_recipe_renderer_uses_the_same_lines_as_runtime_validation(self):
        plan = {'tmpfs_mounts': [{'container_path': '/run', 'size_mb': 64, 'mount_options': ['rw'],
                                  'owner_strategy': 'image-user', 'mode': '0755'}]}
        config = b'lxc.init.uid: 65534\nlxc.init.gid: 65534\n'
        with tempfile.TemporaryDirectory() as temporary:
            deployment_path = Path(temporary) / 'deployment.json'
            config_path = Path(temporary) / 'container.conf'
            deployment_path.write_text(json.dumps(plan))
            config_path.write_bytes(config)
            self.assertEqual(runtime_settings.render_tmpfs(deployment_path, config_path),
                             'lxc.mount.entry: ' + runtime_settings.tmpfs_lines(plan, config)[0] + '\n')


if __name__ == '__main__':
    unittest.main()
