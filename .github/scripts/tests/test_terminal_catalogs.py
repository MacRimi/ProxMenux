"""Offline regressions for copyable commands and runtime format fields."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parents[1]
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location('check_terminal_catalogs', SCRIPTS / 'check_terminal_catalogs.py')
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class TerminalCatalogsTests(unittest.TestCase):
    def test_extractor_includes_launchers_remote_scripts_and_catalog_text(self):
        fixtures = {
            'menu': 'translate "Main launcher"',
            'install_proxmenux.sh': 'translate "Stable installer"',
            'install_proxmenux_beta.sh': 'translate "Beta installer"',
            'scripts/check.sh': 'translate "Host shell script"',
            'scripts/check.py': 'translate("Host Python script")',
            'oci/src/check.py': 'N_("OCI Python script")',
            'oci/remote/check.py': 'translate("Remote Python script")',
            'oci/remote/check.sh': 'translate "Remote shell script"',
            'oci/catalog/app.json': json.dumps({'catalog_ui': {'tagline': {'en_US': 'Application tagline'}}}),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, content in fixtures.items():
                file = root / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(content, encoding='utf-8')
            self.assertEqual(set(MODULE.active_sources(root)), {
                'Main launcher', 'Stable installer', 'Beta installer',
                'Host shell script', 'Host Python script', 'OCI Python script',
                'Remote Python script', 'Remote shell script', 'Application tagline',
            })

    def test_runtime_format_field_cannot_be_translated(self):
        source = 'Kimai has no default account. Enter the container with: pct enter {main_vmid}'
        with self.assertRaisesRegex(ValueError, 'placeholder'):
            MODULE.validate_message(source, 'Kimai nemá účet: pct enter {main vmid}')
        MODULE.validate_message(source, 'Kimai nemá účet: pct enter {main_vmid}')

    def test_copyable_command_and_environment_variable_are_literal(self):
        examples = [
            ('Example: pct config 110 | grep unprivileged', 'Ejemplo: configuración pct 110 | grep sin privilegios'),
            ("Use 'pct restore' to recover the disks.", "Verwenden Sie 'pct restart', um die Datenträger wiederherzustellen."),
            ('Invalid ALLOWED_HOSTS value', 'Valeur HÔTES INDÉSIRABLES'),
        ]
        for source, target in examples:
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, 'literal command or identifier'):
                    MODULE.validate_message(source, target)
        MODULE.validate_message('Example: pct config 110 | grep unprivileged',
                                'Ejemplo: pct config 110 | grep unprivileged')

    def test_dns_capitalization_does_not_relax_file_path_case(self):
        MODULE.validate_message('Cannot reach download.proxmox.com.',
                                'Download.proxmox.com ist nicht erreichbar.')
        with self.assertRaisesRegex(ValueError, 'literal command or identifier'):
            MODULE.validate_message('Check /etc/pve/storage.cfg', 'Prüfen Sie /etc/PVE/storage.cfg')

    def test_shipped_active_catalogs_keep_literal_contracts(self):
        result = subprocess.run(
            [sys.executable, '-B', str(SCRIPTS / 'check_terminal_catalogs.py'),
             '--root', str(ROOT)],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for locale in MODULE.DEFAULT_LANGUAGES:
            self.assertIn(f'[{locale}] active=', result.stdout)
        # New hand-reviewed Slovak keys ship with their source changes;
        # other locales may use the runtime English fallback until translated.
        result = subprocess.run(
            [sys.executable, '-B', str(SCRIPTS / 'check_terminal_catalogs.py'),
             '--root', str(ROOT), '--languages', 'sk', '--require-complete'],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('missing=0', result.stdout)


    def test_optional_completeness_still_rejects_invalid_present_translations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'scripts').mkdir()
            (root / 'lang').mkdir()
            (root / 'scripts/check.sh').write_text('translate "Check /etc/pve/storage.cfg"')
            (root / 'lang/sk.json').write_text(json.dumps({'Check /etc/pve/storage.cfg': 'Skontrolujte /etc/pve/storage.cfg'}))
            (root / 'lang/es.json').write_text('{}')

            def check(languages, *flags):
                return subprocess.run(
                    [sys.executable, '-B', str(SCRIPTS / 'check_terminal_catalogs.py'),
                     '--root', str(root), '--languages', languages, *flags],
                    capture_output=True, text=True, timeout=60,
                )

            self.assertEqual(check('es,sk').returncode, 0)
            self.assertEqual(check('sk', '--require-complete').returncode, 0)
            self.assertNotEqual(check('es', '--require-complete').returncode, 0)
            (root / 'lang/es.json').write_text(json.dumps({'Check /etc/pve/storage.cfg': 'Compruebe /etc/PVE/storage.cfg'}))
            self.assertNotEqual(check('es,sk').returncode, 0)


if __name__ == '__main__':
    unittest.main()
