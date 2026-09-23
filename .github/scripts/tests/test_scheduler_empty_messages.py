"""Offline actual scheduler gates; never source the administrative script."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
SCHEDULER = ROOT / 'scripts/backup_restore/backup_scheduler.sh'
MESSAGES = {
    'pbs': 'No matching PVE vzdump jobs were found for the PBS backend.',
    'local': 'No matching PVE vzdump jobs were found for the local archive backend.',
}
HINT = 'Create one first in Datacenter → Backup, then return here to attach.'


def function(text, name):
    start = text.index(name + '() {')
    return text[start:text.index('\n}', start) + 2] + '\n'


def consumers():
    text = SCHEDULER.read_text()
    attached = function(text, '_create_job_attached').split('  local pve_prune\n')[0] + '}\n'
    # Only the backend/attach selection gate, not ID/config writes or scheduling.
    new = function(text, '_create_job')
    new = '_create_job() {\n  local id=fixture backend on_calendar\n' + new[new.index('  backend=$(dialog'):new.index('  on_calendar=$(dialog')]
    new += '  return 42\n}\n'
    return attached + new


def fixture(directory, backend='pbs', consumer='attached', rows='', second=None,
            locale='en', catalog=None, real_dialog=None):
    directory = Path(directory)
    if catalog is not None:
        (directory / f'{locale}.json').write_text(json.dumps(catalog), encoding='utf-8')
    (directory / 'rows').write_text(rows)
    (directory / 'second').write_text(rows if second is None else second)
    bindir = directory / 'bin'
    bindir.mkdir(exist_ok=True)
    # Only jq is executable via PATH; wrapper validates all lookup arguments.
    (bindir / 'jq').symlink_to('/usr/bin/jq') if not (bindir / 'jq').exists() else None
    translation = function((ROOT / 'scripts/utils.sh').read_text(), 'translate')
    filter_code = function((ROOT / 'scripts/backup_restore/lib_host_backup_common.sh').read_text(), 'hb_pve_list_vzdump_jobs_for_backend')
    preamble = f'''PATH={shlex.quote(str(bindir))}
LANG_DIR={shlex.quote(str(directory))}
LANGUAGE={shlex.quote(locale)}
FIXTURE={shlex.quote(str(directory))}
BACKEND={backend}
HB_UI_MENU_H=20 HB_UI_MENU_W=84 HB_UI_MENU_LIST=10
command_not_found_handle() {{ printf 'FORBIDDEN:%s\\n' "$*" >> "$FIXTURE/errors"; return 99; }}
jq() {{ [[ "$#" == 6 && "$1" == -r && "$2" == --arg && "$3" == text && "$5" == '.[$text] // empty' && "$6" == "$FIXTURE/$LANGUAGE.json" ]] || {{ printf 'bad jq' >> "$FIXTURE/errors"; return 99; }}; command jq "$@"; }}
head() {{ [[ "$*" == '-1' ]] || return 99; local first; IFS= read -r first; printf '%s\\n' "$first"; while IFS= read -r first; do :; done; }}
hb_pve_list_vzdump_jobs() {{
  local file="$FIXTURE/rows" line
  [[ -f "$FIXTURE/read" ]] && file="$FIXTURE/second"
  printf read >> "$FIXTURE/read"
  while IFS= read -r line; do printf '%s\\n' "$line"; done < "$file"
}}
dialog() {{
  printf '%s\\0' "$@" >> "$FIXTURE/dialogs"
  local title='' kind='' message='' previous='' arg
  for arg in "$@"; do
    [[ "$previous" == --title ]] && title="$arg"
    [[ "$previous" == --msgbox || "$previous" == --menu ]] && message="$arg"
    [[ "$arg" == --msgbox || "$arg" == --menu ]] && kind="$arg"
    previous="$arg"
  done
  if [[ "$kind" == --msgbox ]]; then
    printf '%s' "$message" > "$FIXTURE/message"
    {'command ' + shlex.quote(real_dialog) + ' "$@"' if real_dialog else ':'}
    return 0
  fi
  case "$title" in
    "$(translate 'Backend')") printf '%s' "$BACKEND" >&2 ;;
    "$(translate 'How to schedule')") printf attach >&2 ;;
    "$(translate 'Pick PVE vzdump job')") return 1 ;;
    *) printf 'unexpected dialog:%s' "$title" >> "$FIXTURE/errors"; return 99 ;;
  esac
}}
'''
    return preamble + translation + filter_code + consumers() + f'\nif _create_job{"_attached fixture " + backend if consumer == "attached" else ""}; then rc=0; else rc=$?; fi\nprintf "%s" "$rc" > "$FIXTURE/status"\n'


def run_case(**kwargs):
    with tempfile.TemporaryDirectory(prefix='scheduler-') as directory:
        code = fixture(directory, **kwargs)
        result = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', code],
                                env={'PATH': '/nonexistent', 'LC_ALL': 'C.UTF-8'}, capture_output=True, text=True)
        if result.returncode or result.stderr:
            raise AssertionError((result.returncode, result.stderr))
        p = Path(directory)
        if (p / 'errors').exists():
            raise AssertionError((p / 'errors').read_text())
        return {name: (p / name).read_text() if (p / name).exists() else ''
                for name in ('message', 'status', 'dialogs', 'read')}


class SchedulerMessages(unittest.TestCase):
    def test_new_whole_message_and_separate_hint(self):
        for backend in MESSAGES:
            with self.subTest(backend=backend):
                result = run_case(backend=backend, consumer='new')
                self.assertEqual(result['message'], MESSAGES[backend] + '\n\n' + HINT)
                self.assertEqual(result['status'], '1')

    def test_lookup_cache_modes_at_both_consumers(self):
        # Unconditional synthetic coverage, independent of cache completeness.
        for backend, message in MESSAGES.items():
            for consumer in ('attached', 'new'):
                for mode, locale, catalog, expected, hint in (
                    ('english', 'en', {message: 'ignored', HINT: 'ignored'}, message, HINT),
                    ('missing-file', 'missing', None, message, HINT),
                    ('missing-key', 'xx', {'unrelated': 'unrelated'}, message, HINT),
                    ('translated', 'xx', {message: 'SYNTHETIC reordered backend: ' + backend,
                                          HINT: 'SYNTHETIC hint'},
                     'SYNTHETIC reordered backend: ' + backend, 'SYNTHETIC hint'),
                ):
                    with self.subTest(backend=backend, consumer=consumer, mode=mode):
                        result = run_case(backend=backend, consumer=consumer, locale=locale, catalog=catalog)
                        suffix = '\n\n' + hint if consumer == 'new' else ''
                        self.assertEqual(result['message'], expected + suffix)
                        self.assertEqual(result['status'], '1')

    def test_all_shipped_caches_at_both_consumers(self):
        catalogs = sorted((ROOT / 'lang').glob('*.json'))
        self.assertTrue(catalogs, 'No shipped locale catalogs discovered')
        for path in catalogs:
            catalog = json.loads(path.read_text(encoding='utf-8'))
            self.assertIsInstance(catalog, dict, path.name)
            for backend, message in MESSAGES.items():
                for consumer in ('attached', 'new'):
                    with self.subTest(locale=path.stem, backend=backend, consumer=consumer):
                        # Exercise the real translate function with the actual locale
                        # filename, not just a comparison of JSON values. Missing or
                        # empty translations are valid: runtime falls back to English.
                        result = run_case(backend=backend, consumer=consumer,
                                          locale=path.stem, catalog=catalog)
                        expected = message if path.stem == 'en' else catalog.get(message) or message
                        hint = HINT if path.stem == 'en' else catalog.get(HINT) or HINT
                        suffix = '\n\n' + hint if consumer == 'new' else ''
                        self.assertEqual(result['message'], expected + suffix)
                        self.assertEqual(result['status'], '1')

    def test_nonempty_menus_disabled_and_second_read_empty(self):
        for backend, storage in (('pbs', 'pbs'), ('local', 'nfs')):
            for count in (1, 3):
                rows = ''.join(f'job{i}\tstore{i}\t{storage}\tdaily\t-\t0\n' for i in range(count))
                for consumer in ('attached', 'new'):
                    with self.subTest(backend=backend, count=count, consumer=consumer):
                        result = run_case(backend=backend, consumer=consumer, rows=rows)
                        self.assertEqual(result['message'], '')
                        self.assertEqual(result['status'], '1')  # cancel at actual parent picker
                        for i in range(count):
                            self.assertIn(f'job{i}  ·  store{i}  ·  daily  (disabled)', result['dialogs'])
                result = run_case(backend=backend, consumer='new', rows=rows, second='')
                self.assertEqual(result['message'], MESSAGES[backend])
                self.assertEqual(result['read'], 'readread')
                self.assertEqual(result['status'], '1')

    def test_actual_filter_types_and_enabled_states(self):
        for backend in MESSAGES:
            for storage in ('pbs', 'dir', 'nfs', 'cifs', 'zfspool', 'lvmthin', 'btrfs', 'rbd', '-'):
                for enabled in ('0', '1'):
                    with self.subTest(backend=backend, storage=storage, enabled=enabled):
                        result = run_case(backend=backend, rows=f'job\tstore\t{storage}\tdaily\t-\t{enabled}\n')
                        matches = storage == 'pbs' if backend == 'pbs' else storage in ('dir', 'nfs', 'cifs', 'zfspool', 'lvmthin', 'btrfs')
                        self.assertEqual(result['message'], '' if matches else MESSAGES[backend])
                        if matches:
                            self.assertEqual('(disabled)' in result['dialogs'], enabled == '0')

    def test_borg_excludes_attach_gate(self):
        result = run_case(backend='borg', consumer='new')
        self.assertEqual(result['status'], '42')  # stopped before real schedule/config work
        self.assertEqual(result['message'], '')
        self.assertEqual(result['read'], '')
        self.assertNotIn('How to schedule', result['dialogs'])

    def test_actual_offline_extractor_discovers_whole_messages(self):
        spec = importlib.util.spec_from_file_location('scheduler_cache_builder', ROOT / '.github/scripts/build_translation_cache.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        discovered = module.extract_translate_texts(ROOT / 'scripts')
        for message in MESSAGES.values():
            self.assertIn(message, discovered)

    def test_attached_whole_message(self):
        for backend in MESSAGES:
            with self.subTest(backend=backend):
                result = run_case(backend=backend)
                self.assertEqual(result['message'], MESSAGES[backend])
                self.assertEqual(result['status'], '1')


if __name__ == '__main__':
    unittest.main()
