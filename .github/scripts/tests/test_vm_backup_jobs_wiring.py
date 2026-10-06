"""The VM/CT backup jobs feature is protected, shipped and translated."""
import json
from pathlib import Path
import re
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[3]
ROUTES = ROOT / 'AppImage/scripts/flask_vm_backup_routes.py'
SCRIPT = ROOT / 'scripts/backup_restore/vm_backup_jobs.sh'
LOCALES = ('en', 'es', 'de', 'fr', 'it', 'pt', 'sk', 'sv')


class VmBackupJobsWiring(TestCase):
    def test_every_route_is_protected_and_every_change_needs_an_administrator(self):
        source = ROUTES.read_text()
        routes = re.findall(r'@vm_backup_bp\.route\("([^"]+)", methods=\["(\w+)"\]\)\n@(\w+)\ndef (\w+)', source)
        self.assertEqual(len(routes), source.count('@vm_backup_bp.route('))
        self.assertEqual(len(routes), 8)
        for path, method, guard, name in routes:
            expected = 'require_auth' if method == 'GET' else 'require_admin_scope'
            self.assertEqual(guard, expected, f'{method} {path} ({name})')

    def test_proxmox_is_called_without_a_shell(self):
        source = ROUTES.read_text()
        self.assertNotIn('shell=True', source)
        self.assertNotIn('os.system', source)
        self.assertEqual(source.count('subprocess.run('), 1)
        self.assertIn('subprocess.run(["pvesh", *args]', source)

    def test_the_monitor_ships_and_registers_it(self):
        self.assertIn('flask_vm_backup_routes.py', (ROOT / 'AppImage/scripts/build_appimage.sh').read_text())
        server = (ROOT / 'AppImage/scripts/flask_server.py').read_text()
        self.assertIn('from flask_vm_backup_routes import vm_backup_bp', server)
        self.assertIn('app.register_blueprint(vm_backup_bp)', server)
        self.assertIn('<BackupTab ', (ROOT / 'AppImage/components/proxmox-dashboard.tsx').read_text())
        tab = (ROOT / 'AppImage/components/backup-tab.tsx').read_text()
        self.assertIn('<HostBackup />', tab)
        self.assertIn('<VmBackupJobs />', tab)
        # The backups of the host and those of the guests are separate views.
        self.assertNotIn('VmBackupJobs', (ROOT / 'AppImage/components/host-backup.tsx').read_text())

    def test_every_text_of_the_card_exists_in_the_eight_languages(self):
        component = (ROOT / 'AppImage/components/vm-backup-jobs.tsx').read_text()
        used = set(re.findall(r'backup\.vmJobs\.([A-Za-z]+)', component))
        english = json.loads((ROOT / 'AppImage/messages/en/common.json').read_text())['backup']['vmJobs']
        self.assertEqual(used - set(english), set())
        fields = lambda text: sorted(re.findall(r'\{(\w+)\}', text))
        for locale in LOCALES:
            texts = json.loads((ROOT / f'AppImage/messages/{locale}/common.json').read_text())['backup']['vmJobs']
            self.assertEqual(set(texts), set(english), locale)
            self.assertEqual(set(texts['presets']), set(english['presets']), locale)
            switch = json.loads((ROOT / f'AppImage/messages/{locale}/common.json').read_text())['backup']['viewSwitch']
            self.assertEqual(set(switch), {'ariaLabel', 'host', 'guests'}, locale)
            for key, value in english.items():
                if isinstance(value, str):
                    self.assertTrue(texts[key].strip(), f'{locale} {key}')
                    self.assertEqual(fields(texts[key]), fields(value), f'{locale} {key}')

    def test_the_edit_dialog_follows_the_edit_mode_contrast_rule(self):
        component = (ROOT / 'AppImage/components/vm-backup-jobs.tsx').read_text()
        self.assertIn('bg-accent [&_input]:bg-background [&_textarea]:bg-background [&_[role=combobox]]:bg-background', component)

    def test_the_menu_runs_a_job_as_a_proxmox_task_and_installs_nothing(self):
        source = SCRIPT.read_text()
        self.assertNotIn('apt-get', source)
        self.assertIn('pvesh create "/nodes/$node/vzdump"', source)
        self.assertEqual(re.findall(r'^\s*vzdump ', source, re.MULTILINE), [])
        menu = (ROOT / 'scripts/backup_restore/backup_host.sh').read_text()
        self.assertIn('bash "$LOCAL_SCRIPTS/backup_restore/vm_backup_jobs.sh"', menu)
