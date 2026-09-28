"""Inert, extracted consumers for Rclone guidance and HedgeDoc metadata."""
import ast
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[3]
INSTALLER = ROOT / 'oci/src/proxmenux_oci/installer.py'
RCLONE = ('Configure the remote in the Rclone Web UI first. Checking its name may start a '
          'stopped CT, even in a dry run. Applying the mount restarts the CT and attempts '
          'to publish two FUSE views on the host; a dry run does not publish them.')


def extract_function(path, name, **dependencies):
    node = next(n for n in ast.parse(path.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = dict(dependencies)
    future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future, node], type_ignores=[])),
                 str(path), 'exec'), scope)
    return scope[name]


class RcloneHedgeDocWording(TestCase):
    def test_i18n_workflow_runs_for_remote_shell_edits(self):
        workflow = (ROOT / '.github/workflows/test-i18n.yml').read_text()
        self.assertEqual(workflow.count("      - 'oci/remote/**/*.sh'"), 2)

    def test_remote_dry_run_messages_are_extracted_and_translate_with_fallback(self):
        import runpy
        extractor = runpy.run_path(str(ROOT / '.github/scripts/build_translation_cache.py'))
        shell = ROOT / 'oci/remote/configure_rclone_mount.sh'
        keys = [
            'Dry run completed; mount configuration was not applied. The CT was already running.',
            'Dry run completed; mount configuration was not applied. The CT was started for the remote check.',
        ]
        extracted = extractor['extract_translate_texts'](ROOT / 'oci/remote')
        self.assertTrue(set(keys).issubset(extracted))
        ui = (ROOT / 'oci/remote/oci_ui.sh').read_text()
        lookup = 'translate() {' + ui.split('translate() {', 1)[1].split('\n}', 1)[0] + '\n}\n'
        gate = shell.read_text().split('if [[ $DRY_RUN == 1 ]]; then', 1)[1].split('\nfi\n\nRC_USER=', 1)[0]
        gate = 'if [[ $DRY_RUN == 1 ]]; then' + gate + '\nfi\n'
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / 'locale.json'
            for status, expected_key in [('running', keys[0]), ('stopped', keys[1])]:
                for translations, expected in [({}, expected_key),
                                               ({expected_key: 'MESSAGGIO DI TEST'}, 'MESSAGGIO DI TEST')]:
                    with self.subTest(status=status, translations=translations):
                        cache.write_text(json.dumps(translations))
                        setup = (f'_OCI_LANGUAGE=it\n_OCI_LANG_FILE={cache}\n'
                                 f'STATUS={status}\nDRY_RUN=1\n' + lookup +
                                 'msg_ok() { printf "%s\\n" "$1"; }\n')
                        result = subprocess.run(['bash', '-c', setup + gate],
                                                text=True, capture_output=True, timeout=5)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stdout.strip(), expected)

    def test_remote_dry_run_reports_stopped_ct_start_and_no_mount_publication(self):
        script = (ROOT / 'oci/remote/configure_rclone_mount.sh').read_text()
        seam = script.split('msg_info "$(translate "Checking the remote...")"', 1)[1].split('\nfi\n\nRC_USER=', 1)[0]
        # This is the real status/listremotes/dry-run gate, not the root-guarded script.
        seam = 'msg_info "$(translate "Checking the remote...")"' + seam + '\nfi\n'
        for status, dry_run, starts, post_gate in (
            ('stopped', '1', 1, False), ('running', '1', 0, False),
            ('stopped', '0', 1, True), ('running', '0', 0, True)):
            with self.subTest(status=status, dry_run=dry_run):
                with tempfile.TemporaryDirectory() as directory:
                    trace = Path(directory) / 'pct.log'
                    harness = '''
set -Eeuo pipefail
VMID=101 REMOTE_NAME=notes DRY_RUN=%s
TRACE_FILE=%s
pct() {
  printf 'pct:%%s\\n' "$*" >>"$TRACE_FILE"
  case "$1" in
    status) printf 'status: %s\\n' ;;
    exec) if [[ "${5:-}" == version ]]; then return 0; else printf 'notes:\\n'; fi ;;
    start) return 0 ;;
    *) return 97 ;;
  esac
}
oci_quiet() { "$@"; }
oci_log() { :; }
sleep() { :; }
translate() { printf '%%s' "$1"; }
msg_info() { printf 'info:%%s\\n' "$1"; }
msg_ok() { printf 'ok:%%s\\n' "$1"; }
die() { printf 'error:%%s\\n' "$1"; exit 1; }
''' % (dry_run, str(trace), status)
                    result = subprocess.run(['bash', '-c', harness + seam + '\nprintf "POST_DRY_GATE\\n"\n'],
                                            text=True, capture_output=True, timeout=5)
                    calls = trace.read_text()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls.count('pct:start 101'), starts)
                self.assertIn('pct:exec 101 -- /usr/local/bin/rclone listremotes', calls)
                self.assertEqual('POST_DRY_GATE' in result.stdout, post_gate)
                if dry_run == '1':
                    self.assertIn('mount configuration was not applied', result.stdout)
                    if starts:
                        self.assertIn('CT was started for the remote check', result.stdout)
                    else:
                        self.assertIn('CT was already running', result.stdout)
                    self.assertNotIn('pct:stop', calls)

    def test_hedgedoc_overlay_survives_index_enrichment(self):
        sys.path.insert(0, str(ROOT / 'oci/src'))
        try:
            from proxmenux_oci.catalog import Catalog
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = Catalog(root, source=Mock())
            catalog.apps_dir.mkdir(parents=True)
            catalog.overlays_dir.mkdir(parents=True)
            template = json.loads((ROOT / 'oci/catalog/apps/hedgedoc.json').read_text())
            upstream = 'HedgeDoc gives you access to all your files wherever you are.'
            corrected = 'HedgeDoc is a self-hosted collaborative Markdown editor for notes.'
            template['catalog_ui']['description']['en_US'] = upstream
            template['catalog_ui']['tagline']['en_US'] = upstream
            overlay = json.loads((ROOT / 'oci/catalog/overlays/hedgedoc.json').read_text())
            self.assertTrue(overlay['catalog_ui']['hidden'])
            self.assertEqual(overlay['catalog_ui']['description']['en_US'], corrected)
            self.assertEqual(overlay['catalog_ui']['tagline']['en_US'], corrected)
            (catalog.overlays_dir / 'hedgedoc.json').write_text(json.dumps(overlay))
            catalog._apply_overlay('hedgedoc', template)
            self.assertEqual(template['catalog_ui']['description']['en_US'], corrected)
            self.assertEqual(template['catalog_ui']['tagline']['en_US'], corrected)
            (catalog.apps_dir / 'hedgedoc.json').write_text(json.dumps(template))
            payload = {'applications': [{'id': 'hedgedoc', 'description': upstream},
                                        {'id': 'unmodified', 'description': 'Original summary'}]}
            catalog._enrich_index_from_templates(payload)
            self.assertEqual(payload['applications'][0]['description'], corrected)
            self.assertEqual(payload['applications'][1]['description'], 'Original summary')

    def test_rclone_guidance_precedes_inputs_and_confirmation(self):
        events = []
        class UI:
            def message(self, text): events.append(('message', text))
            def ask(self, label, default=None, required=True):
                events.append(('ask', label))
                return {'VMID of the Rclone OCI container': '101',
                        'Exact name of the remote': 'notes',
                        'Mount name': 'notes'}.get(label, default or '')
            def choose(self, label, options, default):
                events.append(('choose', label))
                return default
            def confirm(self, label, default):
                events.append(('confirm', label))
                return True
        schema = {name: {'default': value} for name, value in (
            ('vfs_cache_mode', 'writes'), ('shared_mount_root_parent', '/mnt/rclone'),
            ('shared_mount_root', '/mnt/rclone/rw'),
            ('shared_mount_read_only_root', '/mnt/rclone/ro'))}
        schema['vfs_cache_mode']['options'] = ['writes']
        template = {'proxmox': {'laboratory_contract': {'configuration_schema': schema}}}
        fn = extract_function(INSTALLER, 'build_rclone_mount_deployment',
                              TerminalUI=UI, DialogUI=UI, translate=lambda text: text,
                              re=re, InstallError=ValueError, UserCancelled=ValueError)
        deployment = fn(template, UI())
        self.assertEqual(events[0], ('message', RCLONE))
        self.assertEqual(events[1][0], 'ask')
        self.assertEqual(events[-1][0], 'confirm')
        self.assertEqual(deployment['remote_name'], 'notes')

    def test_hedgedoc_detail_uses_corrected_template_and_index(self):
        key = 'HedgeDoc is a self-hosted collaborative Markdown editor for notes.'
        template = json.loads((ROOT / 'oci/catalog/apps/hedgedoc.json').read_text())
        item = next(item for item in json.loads((ROOT / 'oci/catalog/index.json').read_text())['applications']
                    if item['id'] == 'hedgedoc')
        self.assertEqual(template['catalog_ui']['tagline']['en_US'], key)
        self.assertEqual(template['catalog_ui']['description']['en_US'], key)
        self.assertEqual(item['description'], key)
        source = extract_function(ROOT / 'oci/src/proxmenux_oci/i18n.py', 'source_text',
                                  Any=object)
        fn = extract_function(ROOT / 'oci/src/proxmenux_oci/cli.py', '_app_detail_text',
                              source_text=source, translate=lambda text: text,
                              textwrap=__import__('textwrap'), DETAIL_WIDTH=92,
                              publisher=lambda _: 'LinuxServer.io',
                              is_tested=lambda _: False,
                              _display_architectures=lambda _: 'amd64',
                              _image_label=lambda text: text,
                              _recommended_storage=lambda _: 'Container volume')
        result = fn(SimpleNamespace(), item, template)
        self.assertIn(key, result)
        self.assertNotIn('gives you access to all your files', result)

    def test_missing_empty_and_synthetic_translation_on_real_consumers(self):
        from unittest.mock import Mock
        key = 'HedgeDoc is a self-hosted collaborative Markdown editor for notes.'
        scope = {'language': lambda: 'it', '_cache': {}}
        lookup = extract_function(ROOT / 'oci/src/proxmenux_oci/i18n.py', 'translate', **scope)
        cache = lookup.__globals__
        template = json.loads((ROOT / 'oci/catalog/apps/hedgedoc.json').read_text())
        item = next(x for x in json.loads((ROOT / 'oci/catalog/index.json').read_text())['applications']
                    if x['id'] == 'hedgedoc')
        source = extract_function(ROOT / 'oci/src/proxmenux_oci/i18n.py', 'source_text')
        detail = extract_function(ROOT / 'oci/src/proxmenux_oci/cli.py', '_app_detail_text',
                                  source_text=source, translate=lookup,
                                  textwrap=__import__('textwrap'), DETAIL_WIDTH=92,
                                  publisher=lambda _: 'LinuxServer.io', is_tested=lambda _: False,
                                  _display_architectures=lambda _: 'amd64',
                                  _image_label=lambda text: text,
                                  _recommended_storage=lambda _: 'Container volume')
        for values, expected_rclone, expected_hedgedoc in (
            ({}, RCLONE, key),
            ({RCLONE: '', key: ''}, RCLONE, key),
            ({RCLONE: 'GUIDA RCLONE', key: 'EDITOR COLLABORATIVO'},
             'GUIDA RCLONE', 'EDITOR COLLABORATIVO')):
            with self.subTest(values=values):
                cache['_cache'] = values
                ui = SimpleNamespace(message=Mock(), ask=Mock(side_effect=StopIteration))
                rclone = extract_function(INSTALLER, 'build_rclone_mount_deployment',
                                          TerminalUI=object, DialogUI=object, translate=lookup,
                                          re=re, InstallError=ValueError,
                                          UserCancelled=ValueError)
                # Stop at the first prompt: no operational path is entered.
                with self.assertRaises(StopIteration):
                    rclone(json.loads((ROOT / 'oci/catalog/apps/rclone.json').read_text()), ui)
                ui.message.assert_called_once_with(expected_rclone)
                self.assertIn(expected_hedgedoc, detail(SimpleNamespace(), item, template))

    def test_extractor_sees_both_new_sources(self):
        import runpy
        extractor = runpy.run_path(str(ROOT / '.github/scripts/build_translation_cache.py'))
        keys = extractor['extract_python_texts']([ROOT / 'oci/src'])
        self.assertIn(RCLONE, keys)
        keys = extractor['extract_catalog_texts']([ROOT / 'oci/catalog'])
        self.assertIn('HedgeDoc is a self-hosted collaborative Markdown editor for notes.', keys)
