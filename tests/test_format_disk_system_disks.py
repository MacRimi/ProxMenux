"""Fixture-only safety tests: extract real functions, never source/run the script.
Only text utilities are on PATH; discovery is stubbed, mutations are unavailable.
Run: python3 -m unittest discover -s tests -p test_format_disk_system_disks.py -v
"""
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/storage/format-disk.sh'


class SystemDisks(unittest.TestCase):
    def run_case(self, root='/dev/mapper/pve-root', boot='/dev/sda1',
                 parents=None, candidate='/dev/sdb', fail='', block_mounts=True,
                 root_fs='/dev/mapper/pve-root', changed_root=False,
                 mount_rows=None, root_error=0, pool_rows='rpool\n\t/dev/sdb\t100\t20\t80\n',
                 pool_error=0, timeout_error=0, unresolved='', timeout_available=True):
        parents = parents or {'/dev/mapper/pve-root': ('lvm', ['/dev/sdb1']),
                              '/dev/sdb1': ('part', ['/dev/sdb']),
                              '/dev/sdb': ('disk', []),
                              '/dev/sda1': ('part', ['/dev/sda']),
                              '/dev/sda': ('disk', [])}
        text = SCRIPT.read_text()
        names = ['_is_system_mount', '_get_zfs_root_pool', '_fmt_collect_cmd',
                 '_resolve_zfs_entry', '_build_pool_disks', '_disk_in_config_text',
                 '_get_running_vm_config_text', 'get_disk_info',
                 'build_disk_candidates', 'revalidate_selected_disk']
        names += re.findall(r'^(_fmt_system_\w+)\(\) \{', text, re.M)
        functions = []
        for name in names:
            match = re.search(r'^' + name + r'\(\) \{\n.*?^\}', text, re.M | re.S)
            self.assertIsNotNone(match, name)
            assert match is not None
            functions.append(match[0])
        q = shlex.quote
        mounts = f'{root.removeprefix("/dev/").removeprefix("mapper/")} /\n{boot.removeprefix("/dev/")} /boot\n'
        cases = ["'-no PKNAME /dev/pve-root') return 32 ;;", f"'-ln -o NAME,MOUNTPOINT') printf %s {q(mounts)} ;;",
                 f"'-lnpo PATH,MOUNTPOINT') printf '%s\\n' {q(root + ' /')} {q(boot + ' /boot')} ;;",
                 f"'-dn -e 7,11 -o PATH,RO,TYPE') printf '%s\\n' '{candidate} 0 disk' ;;",
                 "'-dn -o MODEL '* ) printf 'Fixture\\n' ;;",
                 "'-dn -o SIZE '* ) printf '100G\\n' ;;",
                 "'-ln -o NAME '* ) : ;;",
                 "'-ln -o NAME,MOUNTPOINT '* ) : ;;"]
        def inverse(path):
            kind, ps = parents[path]
            return [f'{path} {kind}'] + [row for p in ps for row in inverse(p)]

        for path, (kind, ps) in parents.items():
            cases.append(f"{q('-snrpo PATH,TYPE ' + path)}) printf '%s\\n' " + ' '.join(q(row) for row in inverse(path)) + ' ;;')
            cases.append(f"{q('-no PKNAME ' + path)}) printf '%s\\n' " + ' '.join(q(p.removeprefix('/dev/')) for p in ps) + ' ;;')
        stubs = '''
translate() { printf '%s' "$*"; }
readlink() { printf '%s\\n' "${@: -1}"; }
swapon() { :; }
qm() { printf 'VMID NAME STATUS\\n'; }
pct() { printf 'VMID STATUS NAME\\n'; }

zpool() { [[ "$1" == list ]] || { printf 'MUTATION\\n' >> "$EVENTS"; return 99; }; }
umount() { printf 'MUTATION\\n' >> "$EVENTS"; return 99; }
'''
        stubs += 'fixture_lsblk() {\n'
        if changed_root:
            stubs += '[[ "$PHASE" == menu && ( "$*" == "-lnpo PATH,MOUNTPOINT" || "$*" == "-ln -o NAME,MOUNTPOINT" ) ]] && return 0\n'
        if fail == 'topology':
            stubs += '[[ "$*" == *"' + root + '" ]] && return 32\n'
        elif fail == 'empty-topology':
            stubs += '[[ "$*" == "-snrpo PATH,TYPE ' + root + '" ]] && return 0\n'
        if fail == 'mounts':
            stubs += '[[ "$*" == "-lnpo PATH,MOUNTPOINT" || "$*" == "-ln -o NAME,MOUNTPOINT" ]] && return 32\n'
        elif not block_mounts:
            stubs += '[[ "$*" == "-lnpo PATH,MOUNTPOINT" || "$*" == "-ln -o NAME,MOUNTPOINT" ]] && return 0\n'
        stubs += 'case "$*" in\n' + '\n'.join(cases) + '\n*) printf "UNEXPECTED lsblk %s\\n" "$*" >> "$EVENTS"; return 99 ;;\nesac\n}\n'
        stubs += f"df() {{ printf '%s\\n' 'Filesystem blocks used available percent mounted' '{root_fs} 100 20 80 20% /'; }}\n"
        if root_fs.startswith('rpool/'):
            stubs += f'''zpool() {{
case "$*" in
'list -v -H rpool'|'list -v -H -P -L rpool') printf %s {q(pool_rows)}; return {pool_error} ;;
'list -H -o name') : ;;
*) printf 'UNEXPECTED zpool %s\\n' "$*" >> "$EVENTS"; return 99 ;;
esac
}}
readlink() {{ [[ "${{@: -1}}" == {q(unresolved)} ]] && return 1; printf '%s\\n' "${{@: -1}}"; }}
'''
        if timeout_available:
            stubs += f'''timeout() {{
[[ "$1" == --kill-after=2 && ( "$2" == 8s || "$2" == 5s ) ]] || {{ printf 'UNEXPECTED timeout\\n' >> "$EVENTS"; return 99; }}
shift 2
[[ "$*" != 'zpool list -H -o name' && {timeout_error} != 0 ]] && return {timeout_error}
"$@"
}}
'''
        # Raw findmnt emits one row per mount, with whitespace hex-escaped.
        rows = mount_rows if mount_rows is not None else (
            f'{root if block_mounts else root_fs} / ' +
            ('zfs' if root_fs.startswith('rpool/') else 'ext4') +
            (f'\n{boot} /boot ext4' if block_mounts else '') +
            '\nproc /proc proc\nsysfs /sys sysfs\ntmpfs /run tmpfs')
        stubs += f'''findmnt() {{
case "$*" in
'-krnv -o SOURCE,TARGET,FSTYPE')
    [[ {q(fail)} == mounts ]] && return 32
    if [[ {q(str(changed_root))} == True && "$PHASE" == menu ]]; then
        printf '%s\\n' '/dev/sda1 / ext4'
    else
        printf '%s\\n' {q(rows)}
    fi ;;
'-krnv -o SOURCE,FSTYPE -T /')
    return_status={root_error}
    (( return_status )) && return "$return_status"
    printf '%s\\n' {q(root_fs + (' zfs' if root_fs.startswith('rpool/') else ' ext4'))} ;;
*) printf 'UNEXPECTED findmnt %s\\n' "$*" >> "$EVENTS"; return 99 ;;
esac
}}
'''
        if mount_rows is not None:
            # Simulate lsblk's single MOUNTPOINT hiding the system mount.
            stubs += "lsblk() { [[ \"$*\" == '-lnpo PATH,MOUNTPOINT' ]] && { printf '%s\\n' '/dev/mapper/pve-root /mnt/backup'; return; }; fixture_lsblk \"$@\"; }\n"
        else:
            stubs += 'lsblk() { fixture_lsblk "$@"; }\n'
        with tempfile.TemporaryDirectory(prefix='format-disk-test-') as td:
            for cmd in ['awk', 'grep', 'sort', 'xargs', 'echo']:
                executable = shutil.which(cmd)
                assert executable, cmd
                Path(td, cmd).symlink_to(executable)
            events = Path(td, 'events')
            source = '\n'.join(functions) + '\n' + stubs + f'''
declare -A DISK_RUNNING_VM_FLAG
SELECTED_DISK={q(candidate)}
PHASE=menu
build_disk_candidates
printf 'MENU=%s\\n' "${{DISK_OPTIONS[*]}}"
PHASE=revalidation
revalidate_selected_disk
printf 'STATUS=%s\\n' "$?"
printf 'DETAIL=%s\\n' "$REVALIDATE_ERROR_DETAIL"
'''
            result = subprocess.run(['/bin/bash', '--noprofile', '--norc'], input=source,
                                    text=True, capture_output=True, timeout=10,
                                    env={'PATH': td, 'EVENTS': str(events), 'LC_ALL': 'C'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')
            self.assertFalse(events.exists(), events.read_text() if events.exists() else '')
            return result.stdout

    def test_zfs_membership_fails_closed(self):
        for options in [dict(pool_error=1), dict(pool_error=124),
                        dict(timeout_error=124), dict(timeout_error=137),
                        dict(timeout_available=False), dict(pool_rows=''),
                        dict(pool_rows='rpool\nmirror-0\n'),
                        dict(pool_rows='rpool\n/dev/sdb\n123456789\n'),
                        dict(unresolved='/dev/sdb'),
                        dict(root='/dev/sdb', fail='topology'),
                        dict(root='/dev/sdb', fail='empty-topology')]:
            with self.subTest(options=options):
                result = self.run_case(block_mounts=False, root_fs='rpool/ROOT/pve-1',
                                       candidate='/dev/sdc', **options)
                self.assertIn('MENU=\n', result)
                self.assertIn('STATUS=1\n', result)

    def test_zfs_stacked_member_protects_all_ancestors(self):
        result = self.run_case(block_mounts=False, root_fs='rpool/ROOT/pve-1',
                               pool_rows='rpool\n/dev/mapper/pve-root\t100\t20\n')
        self.assertIn('MENU=\n', result)
        self.assertIn('STATUS=1\n', result)

    def test_zfs_class_headers_allow_unrelated_disk(self):
        result = self.run_case(block_mounts=False, root_fs='rpool/ROOT/pve-1',
                               candidate='/dev/sdc',
                               pool_rows='rpool\nmirror-0\n/dev/sdb1\t100\t20\nlogs\ndedup\nspecial\ncache\nspare\n')
        self.assertIn('MENU=/dev/sdc ', result)
        self.assertIn('STATUS=0\n', result)

    def test_root_discovery_fails_closed(self):
        for error, source in [(32, '/dev/sdb1'), (124, '/dev/sdb1'), (0, ''), (0, 'overlay')]:
            with self.subTest(error=error, source=source):
                result = self.run_case(candidate='/dev/sdc', root_error=error, root_fs=source)
                self.assertIn('MENU=\n', result)
                self.assertIn('STATUS=1\n', result)

    def test_multiple_mounts_do_not_hide_root(self):
        result = self.run_case(mount_rows='/dev/mapper/pve-root / ext4\n/dev/mapper/pve-root /mnt/backup ext4')
        self.assertIn('MENU=\n', result)
        self.assertIn('STATUS=1\n', result)

    def test_mount_scan_requires_root(self):
        for rows in ['', 'proc /proc proc', '/dev/sda1 /boot ext4']:
            with self.subTest(rows=rows):
                result = self.run_case(mount_rows=rows, candidate='/dev/sdc')
                self.assertIn('MENU=\n', result)
                self.assertIn('STATUS=1\n', result)

    def test_stacked_lvm_root_separate_boot(self):
        result = self.run_case()
        self.assertIn('MENU=\n', result)
        self.assertIn('STATUS=1\n', result)
        self.assertIn('system-critical mount', result)


    def test_revalidation_rediscovers_mounts(self):
        result = self.run_case(changed_root=True)
        self.assertIn('MENU=/dev/sdb ', result)
        self.assertIn('STATUS=1\n', result)

    def test_topology_without_physical_disk_fails_closed(self):
        result = self.run_case(parents={'/dev/mapper/pve-root': ('lvm', []),
                                       '/dev/sda1': ('part', ['/dev/sda']),
                                       '/dev/sda': ('disk', [])})
        self.assertIn('MENU=\n', result)
        self.assertIn('STATUS=1\n', result)

    def test_direct_partition_root(self):
        result = self.run_case(root='/dev/sdb1')
        self.assertIn('MENU=\n', result)
        self.assertIn('STATUS=1\n', result)

    def test_whole_disk_root(self):
        result = self.run_case(root='/dev/sdb')
        self.assertIn('MENU=\n', result)
        self.assertIn('STATUS=1\n', result)

    def test_root_and_boot_same_disk(self):
        result = self.run_case(boot='/dev/sdb1')
        self.assertIn('MENU=\n', result)
        self.assertIn('STATUS=1\n', result)

    def test_multiple_physical_parents(self):
        graph = {'/dev/mapper/pve-root': ('lvm', ['/dev/md0']),
                 '/dev/md0': ('raid1', ['/dev/sdb1', '/dev/sdc1']),
                 '/dev/sdb1': ('part', ['/dev/sdb']),
                 '/dev/sdc1': ('part', ['/dev/sdc']),
                 '/dev/sdb': ('disk', []), '/dev/sdc': ('disk', []),
                 '/dev/sda1': ('part', ['/dev/sda']), '/dev/sda': ('disk', [])}
        for candidate in ['/dev/sdb', '/dev/sdc']:
            with self.subTest(candidate=candidate):
                result = self.run_case(parents=graph, candidate=candidate)
                self.assertIn('MENU=\n', result)
                self.assertIn('STATUS=1\n', result)

    def test_unresolved_topology_fails_closed(self):
        result = self.run_case(fail='topology', candidate='/dev/sdc')
        self.assertIn('MENU=\n', result)
        self.assertIn('STATUS=1\n', result)
        self.assertIn('Unable to resolve system disk topology', result)

    def test_empty_topology_fails_closed(self):
        result = self.run_case(fail='empty-topology', candidate='/dev/sdc')
        self.assertIn('MENU=\n', result)
        self.assertIn('STATUS=1\n', result)

    def test_failed_mount_discovery_fails_closed(self):
        result = self.run_case(fail='mounts', candidate='/dev/sdc')
        self.assertIn('MENU=\n', result)
        self.assertIn('STATUS=1\n', result)

    def test_unrelated_candidate_remains_available(self):
        result = self.run_case(candidate='/dev/sdc')
        self.assertIn('MENU=/dev/sdc ', result)
        self.assertIn('STATUS=0\n', result)

    def test_successful_no_block_mounts_is_not_failure(self):
        result = self.run_case(block_mounts=False, candidate='/dev/sdc')
        self.assertIn('MENU=/dev/sdc ', result)
        self.assertIn('STATUS=0\n', result)

    def test_zfs_root_without_lsblk_root_mount_remains_protected(self):
        result = self.run_case(block_mounts=False, root_fs='rpool/ROOT/pve-1')
        self.assertIn('MENU=\n', result)
        self.assertIn('STATUS=1\n', result)
        self.assertIn('system ZFS pool', result)

    def test_zfs_root_allows_unrelated_disk(self):
        result = self.run_case(block_mounts=False, root_fs='rpool/ROOT/pve-1',
                               candidate='/dev/sdc')
        self.assertIn('MENU=/dev/sdc ', result)
        self.assertIn('STATUS=0\n', result)


if __name__ == '__main__':
    unittest.main()
