"""Proxmox's notification files are only written while /etc/pve is the
mounted cluster filesystem, and only when their content has to change."""
import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
SOURCE = SCRIPTS / 'flask_notification_routes.py'
NAMES = {'_pve_cluster_fs_mounted', '_pve_read_file', '_pve_backup_file', '_pve_prune_backups', '_pve_backup_prefix',
         '_pve_backups', '_pve_collect_legacy_backups', 'restore_pve_notification_cfg', '_pve_remove_our_blocks', '_pve_webhook_url',
         '_build_webhook_fallback', 'setup_pve_webhook_core', 'cleanup_pve_webhook_core', 'setup_pve_webhook_when_mounted'}
ASSIGNED = {'_PVE_ENDPOINT_ID', '_PVE_MATCHER_ID', '_PVE_OUR_HEADERS', '_PVE_NOT_MOUNTED', '_PVE_BACKUPS_KEPT',
            '_PVE_HEADER_RE', 'WEBHOOK_LOOPBACK_PORT', '_PVE_BACKUP_MARK'}


class FakeManager:
    def __init__(self):
        self.secret = 'c2VjcmV0LXRva2Vu'

    def get_webhook_secret(self):
        return self.secret

    def _save_setting(self, _key, value):
        self.secret = value


def load(directory):
    """The functions under test, pointed at a directory standing for /etc/pve."""
    body = []
    for node in ast.parse(SOURCE.read_text()).body:
        if isinstance(node, ast.FunctionDef) and node.name in NAMES:
            node.decorator_list = []
            body.append(node)
        elif isinstance(node, ast.Assign) and any(getattr(t, 'id', None) in ASSIGNED for t in node.targets):
            body.append(node)
        elif isinstance(node, ast.Import) and any(a.asname == '_re_pve_cfg' for a in node.names):
            body.append(node)
    import time
    scope = {'notification_manager': FakeManager(), 'time': time, 'jsonify': lambda value: value,
             '_PVE_NOTIFICATIONS_CFG': str(directory / 'notifications.cfg'),
             '_PVE_PRIV_CFG': str(directory / 'priv' / 'notifications.cfg'),
             '_PVE_BACKUP_DIR': str(directory.parent / 'proxmenux' / 'backups' / 'pve-notifications')}
    exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), str(SOURCE), 'exec'), scope)
    return scope


class PveNotificationWriteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.pve = Path(tmp.name) / 'pve'
        self.pve.mkdir()
        self.scope = load(self.pve)
        self.kept = Path(self.scope['_PVE_BACKUP_DIR'])
        self.mounted = True
        patcher = mock.patch('os.path.ismount', side_effect=lambda path: self.mounted and path == str(self.pve))
        patcher.start()
        self.addCleanup(patcher.stop)

    def files(self):
        return sorted(str(p.relative_to(self.pve)) for p in self.pve.rglob('*') if p.is_file())

    def test_nothing_is_written_while_the_cluster_filesystem_is_down(self):
        # The bare directory of the root disk: empty, and it has to stay so.
        self.mounted = False
        result = self.scope['setup_pve_webhook_core']()
        self.assertFalse(result['configured'])
        self.assertTrue(result['waiting'])
        self.assertEqual(self.scope['cleanup_pve_webhook_core']()['error'], self.scope['_PVE_NOT_MOUNTED'])
        self.assertEqual(list(self.pve.iterdir()), [])

    def test_the_webhook_is_written_once_and_not_again(self):
        (self.pve / 'priv').mkdir()
        existing = 'sendmail: mail-to-root\n\tcomment Send mails to root@pam\n\tmailto-user root@pam\n'
        (self.pve / 'notifications.cfg').write_text(existing)
        (self.pve / 'priv' / 'notifications.cfg').write_text('')
        self.assertTrue(self.scope['setup_pve_webhook_core']()['configured'])
        written = (self.pve / 'notifications.cfg').read_text()
        self.assertTrue(written.startswith(existing))
        self.assertIn('webhook: proxmenux-webhook\n', written)
        self.assertIn('matcher: proxmenux-default\n', written)
        first = {name: (self.pve / name).stat().st_mtime_ns for name in self.files()}
        # The copies taken before the change are kept with ProxMenux, not in /etc/pve.
        self.assertEqual(sorted(first), ['notifications.cfg', 'priv/notifications.cfg'])
        copies = sorted(p.name.split('.proxmenux_backup_')[0] for p in self.kept.iterdir())
        self.assertEqual(copies, ['notifications.cfg', 'priv-notifications.cfg'])
        self.assertEqual({oct(p.stat().st_mode & 0o777) for p in self.kept.iterdir()}, {'0o600'})
        self.assertEqual(oct(self.kept.stat().st_mode & 0o777), '0o700')
        # A second start finds both files as wanted: no write, no new backup.
        os.utime(self.pve / 'notifications.cfg', ns=(1, 1))
        os.utime(self.pve / 'priv' / 'notifications.cfg', ns=(1, 1))
        self.assertTrue(self.scope['setup_pve_webhook_core']()['configured'])
        self.assertEqual(self.files(), sorted(first))
        self.assertEqual((self.pve / 'notifications.cfg').stat().st_mtime_ns, 1)
        self.assertEqual((self.pve / 'priv' / 'notifications.cfg').stat().st_mtime_ns, 1)

    def test_copies_left_in_etc_pve_by_an_earlier_version_are_collected_without_a_write(self):
        (self.pve / 'priv').mkdir()
        (self.pve / 'priv' / 'notifications.cfg').write_text('')
        (self.pve / 'notifications.cfg').write_text('')
        self.scope['setup_pve_webhook_core']()
        for item in self.kept.iterdir():
            item.unlink()
        for index in range(40):
            for folder in (self.pve, self.pve / 'priv'):
                stale = folder / f'notifications.cfg.proxmenux_backup_20260101_{index:06d}'
                stale.write_text(f'old {index}')
                os.utime(stale, ns=(index * 10 ** 9, index * 10 ** 9))
        current = (self.pve / 'notifications.cfg').read_text()
        self.assertTrue(self.scope['setup_pve_webhook_core']()['configured'])
        self.assertEqual(self.files(), ['notifications.cfg', 'priv/notifications.cfg'])
        self.assertEqual((self.pve / 'notifications.cfg').read_text(), current)
        kept = sorted(p.name for p in self.kept.iterdir())
        self.assertEqual(kept, [f'notifications.cfg.proxmenux_backup_20260101_{i:06d}' for i in (37, 38, 39)]
                         + [f'priv-notifications.cfg.proxmenux_backup_20260101_{i:06d}' for i in (37, 38, 39)])
        self.assertEqual((self.kept / kept[2]).read_text(), 'old 39')

    def test_restore_takes_the_newest_copy_of_each_file(self):
        (self.pve / 'priv').mkdir()
        (self.pve / 'notifications.cfg').write_text('before\n')
        (self.pve / 'priv' / 'notifications.cfg').write_text('private before\n')
        self.scope['setup_pve_webhook_core']()
        answer, _status = self.scope['restore_pve_notification_cfg']()
        self.assertTrue(answer['success'])
        self.assertEqual((self.pve / 'notifications.cfg').read_text(), 'before\n')
        self.assertEqual((self.pve / 'priv' / 'notifications.cfg').read_text(), 'private before\n')
        self.mounted = False
        answer, _status = self.scope['restore_pve_notification_cfg']()
        self.assertFalse(answer['success'])

    def test_uninstalling_the_monitor_removes_its_target_from_proxmox(self):
        menu = (SCRIPTS.parents[1] / 'scripts/menus/config_menu.sh').read_text()
        body = menu[menu.index('remove_monitor_notification_target() {'):menu.index('uninstall_proxmenux_monitor() {')]
        self.assertIn('mountpoint -q /etc/pve || return 0', body)
        # The rule first: Proxmox does not delete a target that a rule still uses.
        self.assertLess(body.index('matchers/proxmenux-default'), body.index('endpoints/webhook/proxmenux-webhook'))
        self.assertIn('/etc/pve/priv/notifications.cfg.proxmenux_backup_*', body)
        uninstall = menu[menu.index('uninstall_proxmenux_monitor() {'):menu.index('check_monitor_status() {')]
        self.assertIn('remove_monitor_notification_target', uninstall)

    def test_a_start_during_a_restart_waits_for_the_mount(self):
        self.mounted = False
        (self.pve / 'priv').mkdir()

        def back(_seconds):
            self.mounted = True
        with mock.patch('time.sleep', side_effect=back):
            result = self.scope['setup_pve_webhook_when_mounted'](timeout=60, interval=1)
        self.assertTrue(result['configured'])
        self.assertIn('webhook: proxmenux-webhook', (self.pve / 'notifications.cfg').read_text())

    def test_the_wait_ends_without_writing(self):
        self.mounted = False
        result = self.scope['setup_pve_webhook_when_mounted'](timeout=0, interval=0)
        self.assertTrue(result['waiting'])
        self.assertEqual(list(self.pve.iterdir()), [])

    def test_the_monitor_starts_after_the_cluster_service(self):
        root = SCRIPTS.parents[1]
        for name in ('install_proxmenux.sh', 'install_proxmenux_beta.sh', 'scripts/menus/config_menu.sh'):
            text = (root / name).read_text()
            self.assertIn('After=network.target pve-cluster.service', text, name)
            self.assertNotIn('After=network.target\n\n[Service]\nType=simple\nUser=root\nWorkingDirectory=$MONITOR', text, name)


if __name__ == '__main__':
    unittest.main()
