"""Offline, bounded real Bash consumers: no administrative entrypoints are sourced."""
import importlib.util
import json

from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / 'scripts'
NETWORK = {
    'share/iscsi_host.sh': 1,
    'share/nfs_client.sh': 1,
    'share/nfs_host.sh': 2,
    'share/samba_client.sh': 1,
    'share/samba_host.sh': 2,
}
MOUNT = 'Mounting existing filesystem ({filesystem})...'
RAID = 'If you are sure you want to use it, remove the RAID metadata or format it manually using external tools.'


def function(text, name):
    start = text.index(name + '() {')
    return text[start:text.index('\n}', start) + 2] + '\n'


def network_blocks(path):
    lines = path.read_text().splitlines()
    blocks = []
    for i, line in enumerate(lines):
        if re.search(r'^\s*if (?:pct exec .* -- )?nc -z -w 2 ', line):
            depth = len(line) - len(line.lstrip())
            end = next(j for j in range(i + 1, len(lines))
                       if lines[j].strip() == 'fi' and len(lines[j]) - len(lines[j].lstrip()) == depth)
            block = '\n'.join(lines[i:end + 1])
            assert '$(translate "Open")' in block and '$(translate "Closed")' in block or '$(translate "Probe failed")' in block
            blocks.append(block)
    return blocks


def run(code, translations=None, statuses='1', variables='', dialog=False):
    translations = translations or {}
    with tempfile.TemporaryDirectory(prefix='tui-wording-') as directory:
        root = Path(directory)
        (root / 'xx.json').write_text(json.dumps(translations))
        body = f'''LANGUAGE=xx LANG_DIR={root!s}
{function((SCRIPTS / 'utils.sh').read_text(), 'translate')}
GN='\\033[32m' RD='\\033[31m' CL='\\033[0m'
{variables}
statuses=({statuses})
nc() {{ local code=${{statuses[0]}}; statuses=("${{statuses[@]:1}}"); return "$code"; }}
pct() {{ [[ "$1" == exec && "$3" == -- && "$4" == nc ]] || return 98; shift 3; nc "$@"; }}
msg_info() {{ printf 'INFO:%s\\n' "$1"; }}
msg_error() {{ printf 'ERROR:%s\\n' "$1"; }}
msg_ok() {{ printf 'OK:%s\\n' "$1"; }}
msg_title() {{ :; }}
show_proxmenux_logo() {{ :; }}
pmx_journal_context() {{ :; }}
blkid() {{ [[ "$2" == TYPE ]] && printf 'ext4\\n' || printf 'UUID123\\n'; }}
mkdir() {{ :; }}
mount() {{ return 1; }}
dialog() {{ printf 'DIALOG:%s\\n' "$*"; }}
{code}
'''
        result = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', body],
                                env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8'},
                                capture_output=True, text=True, timeout=10)
        if result.returncode or result.stderr:
            raise AssertionError((result.returncode, result.stderr, result.stdout))
        return result.stdout


class TuiNetworkStorageWording(unittest.TestCase):
    def test_failed_tcp_probe_is_not_declared_closed_at_every_caller(self):
        for path, count in NETWORK.items():
            blocks = network_blocks(SCRIPTS / path)
            self.assertEqual(len(blocks), count, path)
            for index, block in enumerate(blocks):
                cases = [('0 1', 'Open'), ('1 1', 'Probe failed'), ('124 124', 'Probe failed')]
                if 'samba_' in path:
                    cases.append(('1 0', 'Open'))
                for codes, expected in cases:
                    with self.subTest(path=path, index=index, codes=codes):
                        output = run(block, statuses=codes, translations={'Probe failed': 'SONDAGGIO FALLITO'})
                        self.assertIn('SONDAGGIO FALLITO' if expected == 'Probe failed' else 'Open', output)
                        self.assertNotIn('Closed', output)
                        if expected == 'Open':
                            self.assertNotIn('SONDAGGIO FALLITO', output)
                        else:
                            fallback = run(block, statuses=codes)
                            self.assertIn('Probe failed', fallback)
                            self.assertNotIn('Closed', fallback)

    def test_mount_progress_is_whole_and_uses_real_lookup_with_fallback(self):
        source = (SCRIPTS / 'share/disk_host.sh').read_text()
        start = source.index('mount_existing_disk() {')
        portion = source[start:source.index('    if ! mount "$disk"', start)] + '    return 0\n}\n'
        for translation, expected in [({}, MOUNT.replace('{filesystem}', 'ext4')),
                                      ({MOUNT: 'SYNTHETIC {filesystem} in corso'}, 'SYNTHETIC ext4 in corso'),
                                      ({MOUNT: 'SYNTHETIC malformed'}, MOUNT.replace('{filesystem}', 'ext4'))]:
            with self.subTest(translation=translation):
                output = run(portion + '\nmount_existing_disk /dev/fixture /mnt/fixture', translations=translation)
                self.assertIn('INFO:' + expected, output)
                self.assertNotIn('{filesystem}', output)

    def test_raid_warning_is_complete_message_with_disk_identifier_and_fallback(self):
        source = (SCRIPTS / 'storage/disk-passthrough_ct.sh').read_text().splitlines()
        invocation = '\n'.join(source[457:460])  # original dialog invocation, not the raid detection command
        for translation, expected in [({}, RAID), ({RAID: 'SYNTHETIC RAID metadata remains'}, 'SYNTHETIC RAID metadata remains')]:
            with self.subTest(translation=translation):
                output = run(invocation, translations=translation,
                             variables="BACKTITLE=fixture DISK_INFO='/dev/fixture 2TiB' UI_RESULT_H=16 UI_RESULT_W=80")
                self.assertIn(expected, output)
                self.assertIn('/dev/fixture 2TiB', output)
                self.assertNotIn('remove the RAID metadata or format it manually using external tools. RAID metadata', output)

    def test_shipped_catalogs_use_english_fallback_for_new_keys(self):
        catalogs = sorted((ROOT / 'lang').glob('*.json'))
        self.assertTrue(catalogs)
        block = network_blocks(SCRIPTS / 'share/iscsi_host.sh')[0]
        source = (SCRIPTS / 'share/disk_host.sh').read_text()
        start = source.index('mount_existing_disk() {')
        mount = source[start:source.index('    if ! mount "$disk"', start)] + '    return 0\n}\nmount_existing_disk /dev/fixture /mnt/fixture'
        raid = '\n'.join((SCRIPTS / 'storage/disk-passthrough_ct.sh').read_text().splitlines()[457:460])
        for path in catalogs:
            with self.subTest(locale=path.name):
                catalog = json.loads(path.read_text())
                self.assertIn(catalog.get('Probe failed') or 'Probe failed', run(block, statuses='1', translations=catalog))
                self.assertIn((catalog.get(MOUNT) or MOUNT).replace('{filesystem}', 'ext4'), run(mount, translations=catalog))
                self.assertIn(catalog.get(RAID) or RAID, run(raid, translations=catalog,
                              variables="BACKTITLE=fixture DISK_INFO='/dev/fixture' UI_RESULT_H=16 UI_RESULT_W=80"))

    def test_extractor_discovers_whole_keys(self):
        spec = importlib.util.spec_from_file_location('cache_builder', ROOT / '.github/scripts/build_translation_cache.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        keys = module.extract_translate_texts(SCRIPTS)
        for key in (MOUNT, RAID, 'Probe failed'):
            self.assertTrue(key in keys, key)


if __name__ == '__main__':
    unittest.main()
