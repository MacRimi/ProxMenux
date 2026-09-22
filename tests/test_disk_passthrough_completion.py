"""Offline completion consumers only; never source VM/CT admin entrypoints.

Run: python3 -m unittest discover -s tests -p test_disk_passthrough_completion.py -v
Bash and jq required. The existing harness exposes jq only on PATH.
"""
import importlib.util
import json
import unittest

import test_tui_count_messages as harness
from test_tui_count_messages import ROOT, between

VM = 'scripts/storage/disk-passthrough.sh'
CT = 'scripts/storage/disk-passthrough_ct.sh'


class DiskCompletion(unittest.TestCase):
    def check_consumer(self, path, target):
        seam = between(path, 'if [ "$DISKS_ADDED" -gt 0 ]; then',
                       'msg_success "$(translate "Press Enter to return to menu...")"')
        token = '{' + target.lower() + 'id}'
        key = f'Completed. Disks added to {target} {token}: {{count}}.'
        cases = [('en', None), ('missing', {}),
                 ('it', json.loads((ROOT / 'lang/it.json').read_text())),
                 ('reorder', {key: '{count} / destination ' + token + ' / done 100%.'}),
                 ('repeat', {key: token + ' {count} {count} ' + token + ' {unknown} $(literal) %s'})]
        for bad in ('No values', key.replace(token, ''), key.replace('{count}', ''),
                    key.replace(token, token.upper()), key.replace('{count}', '{renamed}')):
            cases.append(('bad', {key: bad}))
        renderer = harness.CountMessages()
        for count in (0, 1, 3):
            for identifier in ('101', '987654'):
                for language, catalog in cases:
                    with self.subTest(target=target, count=count, identifier=identifier, language=language):
                        result = renderer.render(seam, f'DISKS_ADDED={count}; {target}ID={identifier}', language, catalog)
                        if count == 0:
                            expected = 'WARN:' + ((catalog or {}).get('No disks were added.') or 'No disks were added.')
                        else:
                            template = key if language == 'bad' else ((catalog or {}).get(key) or key)
                            expected = 'OK:' + template.replace(token, identifier).replace('{count}', str(count))
                        self.assertEqual(result, expected)
        spec = importlib.util.spec_from_file_location('disk_cache', ROOT / '.github/scripts/build_translation_cache.py')
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        self.assertIn(key, builder.extract_translate_texts(ROOT / 'scripts/storage'))

    def test_assignment_outcomes_and_counts(self):
        # Execute bounded assignment consumers, with no disk discovery/formatting.
        # Configuration success is counted even if CT accessibility fails.
        for path, target, start in ((VM, 'VM', '    ASSIGN_PATH=$(get_preferred_disk_path "$DISK")'),
                                     (CT, 'CT', '    PERSISTENT_PARTITION=$(get_preferred_disk_path "$PARTITION")')):
            assignment = between(path, start, '\ndone\n')
            summary = between(path, 'if [ "$DISKS_ADDED" -gt 0 ]; then',
                              'msg_success "$(translate "Press Enter to return to menu...")"')
            for statuses, expected in (([], 0), ([0], 1), ([0, 0, 0], 3), ([1], 0), ([0, 1, 0], 2)):
                for filesystem in ('ext4', 'xfs'):
                    with self.subTest(target=target, statuses=statuses, filesystem=filesystem):
                        setup = '''DISKS_ADDED=0; VMID=101; CTID=101; INDEX=0; INTERFACE=scsi
DISK=fixture; PARTITION=fixture; MOUNT_POINT=/fixture/mount
ASSIGNED_TO=''; CT_RUNNING=true; _model=fixture; _size=1G; DISK_INFO=fixture
get_preferred_disk_path() { [[ "$1" == fixture ]] || exit 99; printf /fixture/disk; }
msg_info() { :; }
msg_error() { printf 'ERROR:%s\\n' "$1"; }
sleep() { [[ "$1" == 1 ]] || exit 99; }
qm() {
    [[ "$*" == 'set 101 -scsi0 /fixture/disk' ]] || exit 99
    printf 'CALL:qm:%s\\n' "$*" >&3
    return "$status"
}
pct() {
    if [[ "$1" == exec ]]; then
        [[ "$*" == "exec 101 -- sh -c mountpoint -q '/fixture/mount' || [ -d '/fixture/mount' ]" ]] || exit 99
        printf 'CALL:verify\\n' >&3
        return 1
    fi
    local expected='set 101 -mp0 /fixture/disk,mp=/fixture/mount,backup=0,ro=0'
    [[ "$FORMAT_TYPE" == xfs ]] || expected+=',acl=1'
    [[ "$*" == "$expected" ]] || exit 99
    printf 'CALL:pct:%s\\n' "$*" >&3
    return "$status"
}
exec 3>&1
'''
                        setup += f'FORMAT_TYPE={filesystem}\n'
                        seam = 'for status in ' + ' '.join(map(str, statuses)) + '; do\n' + assignment + '\ndone\n' + summary
                        result = harness.CountMessages().render(seam, setup)
                        final = result.splitlines()[-1]
                        self.assertEqual(final, f'OK:Completed. Disks added to {target} 101: {expected}.' if expected else 'WARN:No disks were added.')
                        calls = [line for line in result.splitlines() if line.startswith('CALL:')]
                        self.assertEqual(len(calls), len(statuses) + (expected if target == 'CT' else 0))
                        self.assertNotIn('Disk verified and accessible', result)

    def test_ct_complete_message(self):
        self.check_consumer(CT, 'CT')

    def test_vm_complete_message(self):
        self.check_consumer(VM, 'VM')


if __name__ == '__main__':
    unittest.main()
