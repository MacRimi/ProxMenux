"""The LinuxServer/MariaDB variant keeps its complete private stack and safe bootstrap."""
import json
import base64
import re
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(Path(__file__).parent)]
from proxmenux_oci.catalog import Catalog
from proxmenux_oci.custom import template_from_oci_compose
from proxmenux_oci.installer import ADVANCED_MODE, DEFAULT_MODE, build_deployment
from proxmenux_oci.stack import assess
from test_advanced_flow_order import RecordingUI, storages, addresses


class NextcloudMariaDBTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog(ROOT)
        self.template = self.catalog.compose('nextcloud-mariadb')

    def test_catalog_roundtrip_preserves_the_original_image_families_and_tls(self):
        t = template_from_oci_compose(json.dumps(self.template))
        self.catalog.validate(t)
        self.assertEqual(assess(t), [])
        services = {s['name']: s for s in t['compose_stack']['services']}
        self.assertEqual({k: v['image'] for k, v in services.items()}, {
            'nextcloud': 'lscr.io/linuxserver/nextcloud:latest',
            'db': 'mariadb:10.11', 'redis': 'redis:7-alpine'})
        self.assertEqual(t['first_run']['endpoints'][0]['scheme'], 'https')
        self.assertEqual(t['first_run']['endpoints'][0]['port'], 443)
        self.assertTrue(t['catalog_ui']['icon'].startswith('https://'))
        self.assertEqual(set(services['nextcloud']['depends_on']), {'db', 'redis'})
        for name in ('db', 'redis'):
            self.assertFalse(services[name]['compose'].get('ports'))
            self.assertFalse(services[name]['frontend_network'])

    def plan(self, mode, answers=None):
        with ExitStack() as stack:
            for target, value in [
                ('proxmenux_oci.installer.host.storages', storages),
                ('proxmenux_oci.installer.access.ask_addresses', addresses)]:
                stack.enter_context(patch(target, side_effect=value))
            for target, value in [
                ('proxmenux_oci.i18n.language', 'en'),
                ('proxmenux_oci.installer.host.bridges', [{'iface': 'vmbr0', 'cidr': '192.0.2.1/24'}]),
                ('proxmenux_oci.installer.host.timezone', 'Europe/Madrid')]:
                stack.enter_context(patch(target, return_value=value))
            return build_deployment(self.template, RecordingUI(answers), mode)

    def test_default_and_advanced_plans_keep_shared_secrets_private_dependencies_and_persistence(self):
        for mode in (DEFAULT_MODE, ADVANCED_MODE):
            with self.subTest(mode=mode):
                plan = self.plan(mode)
                services = {s['name']: s for s in plan['services']}
                env = {name: {e['name']: e['value'] for e in s['deployment']['environment']}
                       for name, s in services.items()}
                self.assertEqual(env['nextcloud']['MYSQL_PASSWORD'], env['db']['MYSQL_PASSWORD'])
                self.assertNotEqual(env['db']['MYSQL_PASSWORD'], env['db']['MYSQL_ROOT_PASSWORD'])
                self.assertEqual(env['nextcloud']['MYSQL_HOST'], 'db')
                self.assertEqual([s['name'] for s in plan['services']], ['db', 'redis', 'nextcloud'])
                self.assertEqual([s['name'] for s in plan['services'] if s.get('frontend')], ['nextcloud'])
                self.assertEqual(services['db']['healthcheck']['argv'][0], 'healthcheck.sh')
                self.assertEqual(services['nextcloud']['healthcheck']['endpoint']['scheme'], 'https')
                self.assertEqual({k: s['deployment']['hostname'] for k, s in services.items()},
                                 {'nextcloud': 'nextcloud', 'db': 'nextcloud-db', 'redis': 'nextcloud-redis'})
                for service in services.values():
                    self.assertTrue(service['deployment']['security']['unprivileged'])
                    self.assertTrue(all(m['backup'] for m in service['deployment']['mounts']))
                self.assertEqual({k: v['deployment']['resources']['memory_mb'] for k, v in services.items()},
                                 {'nextcloud': 2048, 'db': 1024, 'redis': 512})
                runtime = services['nextcloud']['template']['proxmox']['installer_profile']['runtime']
                self.assertIn('exec /init', runtime['compose_entrypoint'][2])
                self.assertNotIn('\n', runtime['compose_entrypoint'][2])
                self.assertNotIn('\r', runtime['compose_entrypoint'][2])

    def test_nas_mount_is_separate_from_configuration_database_and_cache(self):
        plan = self.plan(DEFAULT_MODE, {'Where to store nextcloud: /data': 'host-bind',
                                      'Host path for nextcloud: /data': '/mnt/pve/media/Nextcloud'})
        services = {s['name']: s for s in plan['services']}
        mounts = {m['container_path']: m for m in services['nextcloud']['deployment']['mounts']}
        self.assertEqual(mounts['/data']['source'], '/mnt/pve/media/Nextcloud')
        self.assertEqual(mounts['/data']['type'], 'host-bind')
        self.assertFalse(mounts['/data']['backup'])
        self.assertEqual(mounts['/config']['type'], 'managed-volume')
        for name in ('db', 'redis'):
            self.assertTrue(all(m['type'] == 'managed-volume' and m['backup']
                                for m in services[name]['deployment']['mounts']))

    @unittest.skipUnless(shutil.which('php'), 'PHP CLI is needed to execute the bootstrap contract')
    def test_bootstrap_prefills_mysql_with_escaped_secrets_and_preserves_existing_files(self):
        entry = next(s for s in self.template['compose_stack']['services'] if s['name'] == 'nextcloud')['compose']['entrypoint']
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'config'
            image_config = Path(temp) / 'image-config'
            image_config.mkdir()
            defaults = {'CAN_INSTALL': '', '.htaccess': 'deny all', 'config.sample.php': '<?php // sample'}
            for name, content in defaults.items(): (image_config / name).write_text(content)
            payload = re.search(r'printf %s ([A-Za-z0-9+/=]+) \| base64 -d \| php', entry[2]).group(1)
            source = base64.b64decode(payload).decode()
            self.assertEqual(source, (ROOT / 'examples/nextcloud-mariadb-bootstrap.php').read_text())
            test_source = source.replace('/config/www/nextcloud/config', str(folder)).replace('/app/www/src/config', str(image_config))
            script = entry[2].replace(payload, base64.b64encode(test_source.encode()).decode()).replace('exec /init', 'exit 0')
            password = "test-'quote\\backslash$not-a-real-secret\nline"
            env = dict(os.environ, MYSQL_HOST='db', MYSQL_DATABASE='nextcloud', MYSQL_USER='nextcloud', MYSQL_PASSWORD=password)
            subprocess.run(['/bin/sh', '-ec', script], env=env, check=True, capture_output=True)
            for name, content in defaults.items(): self.assertEqual((folder / name).read_text(), content)
            autoconfig = folder / 'autoconfig.php'
            redis = folder / 'proxmenux-redis.config.php'
            for path in (autoconfig, redis):
                subprocess.run(['php', '-l', str(path)], check=True, capture_output=True)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            code = 'require $argv[1]; echo json_encode($AUTOCONFIG);'
            values = json.loads(subprocess.check_output(['php', '-r', code, str(autoconfig)], env=env))
            self.assertEqual(values['dbpass'], password)
            self.assertEqual(values['dbhost'], 'db')
            self.assertEqual(values['directory'], '/data')
            self.assertNotIn('adminpass', values)
            cache = json.loads(subprocess.check_output(['php', '-r', 'require $argv[1]; echo json_encode($CONFIG);', str(redis)]))
            self.assertEqual(cache['redis']['host'], 'redis')
            self.assertEqual(cache['memcache.locking'], '\\OC\\Memcache\\Redis')
            # A retry/update must not replace user edits or a completed installation.
            saved = {p: p.read_bytes() for p in (autoconfig, redis)}
            subprocess.run(['/bin/sh', '-ec', script], env=dict(env, MYSQL_PASSWORD='changed'), check=True, capture_output=True)
            for path, content in saved.items(): self.assertEqual(path.read_bytes(), content)
            autoconfig.unlink()
            (folder / 'CAN_INSTALL').unlink()
            (folder / 'config.php').write_text('<?php $CONFIG = ["installed" => true];')
            subprocess.run(['/bin/sh', '-ec', script], env=env, check=True, capture_output=True)
            self.assertFalse(autoconfig.exists())
            self.assertFalse((folder / 'CAN_INSTALL').exists())

    @unittest.skipUnless(sys.platform.startswith('linux') and os.geteuid() == 0 and shutil.which('php'),
                         'Linux root is needed to reproduce existing-volume ownership')
    def test_existing_config_volume_can_read_new_redis_configuration_as_its_app_user(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o755)
            folder = root / 'config'
            folder.mkdir(mode=0o755)
            os.chown(folder, 1001, 1001)
            installed = folder / 'autoconfig.php'
            installed.write_text('<?php $CONFIG = ["installed" => true];')
            installed.chmod(0o640)
            os.chown(installed, 1001, 1001)
            source = (ROOT / 'examples/nextcloud-mariadb-bootstrap.php').read_text()
            source = source.replace('/config/www/nextcloud/config', str(folder))
            subprocess.run(['php'], input=source.encode(), check=True, capture_output=True)
            redis = folder / 'proxmenux-redis.config.php'
            self.assertEqual((redis.stat().st_uid, redis.stat().st_gid), (1001, 1001))
            self.assertEqual(redis.stat().st_mode & 0o777, 0o600)
            def app_user():
                os.setgroups([])
                os.setgid(1001)
                os.setuid(1001)
            result = subprocess.check_output(['php', '-r',
                'require $argv[1]; echo json_encode($CONFIG);', str(redis)], preexec_fn=app_user)
            self.assertEqual(json.loads(result)['redis']['host'], 'redis')
            self.assertEqual(installed.read_text(), '<?php $CONFIG = ["installed" => true];')
            self.assertFalse((folder / 'config.php').exists())

    @unittest.skipUnless(shutil.which('php'), 'PHP CLI needed for the installed-instance contract')
    def test_existing_installation_does_not_override_user_cache_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'config'
            folder.mkdir()
            config = folder / 'config.php'
            content = '<?php $CONFIG = ["installed" => true, "redis" => ["host" => "user-cache", "timeout" => 3]];'
            config.write_text(content)
            source = (ROOT / 'examples/nextcloud-mariadb-bootstrap.php').read_text()
            source = source.replace('/config/www/nextcloud/config', str(folder))
            subprocess.run(['php'], input=source.encode(), check=True, capture_output=True)
            self.assertEqual(config.read_text(), content)
            self.assertFalse((folder / 'proxmenux-redis.config.php').exists())
            self.assertFalse((folder / 'autoconfig.php').exists())

if __name__ == '__main__':
    unittest.main()
