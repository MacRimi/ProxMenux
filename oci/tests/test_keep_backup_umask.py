"""PBS backup traversal modes must not loosen the OCI caller's private files."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

REMOTE = Path(__file__).resolve().parents[1] / 'remote'


class KeptBackupPermissions(unittest.TestCase):
    def scenario(self, code, exit_code=0):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            binary = root / 'vzdump'
            binary.write_text(f'#!{sys.executable}\n' + textwrap.dedent(f'''
                import os
                from pathlib import Path
                import sys
                assert sys.argv[1:] == ['4242', '--storage', 'pbs-fixture', '--mode',
                    'snapshot', '--compress', 'zstd', '--notes-template',
                    'ProxMenux OCI: before the image update']
                root = Path(os.environ['BACKUP_FIXTURE'])
                (root / 'pve-tmp').mkdir()
                (root / 'pve-tmp/pct.conf').write_text('fixture only')
                sys.exit({exit_code})
            '''))
            binary.chmod(0o700)
            script = textwrap.dedent('''
                import os
                from pathlib import Path
                import stat
                import subprocess
                import sys
                sys.path.insert(0, sys.argv[1])
                import oci_instances as instances
                import oci_keep_backup as backup
                root = Path(os.environ['BACKUP_FIXTURE'])
                backup.dump_dir = lambda storage: None
                instances.write(root / 'private-before/record.json', {'secret': 'fixture'})
            ''') + textwrap.dedent(code)
            result = subprocess.run(
                [sys.executable, '-c', script, str(REMOTE)],
                env={**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'],
                     'BACKUP_FIXTURE': str(root)},
                umask=0o077, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_pbs_child_is_readable_while_parent_records_stay_private(self):
        self.scenario('''
            assert backup.before_update(4242, 'pbs-fixture') == 'pbs-fixture'
            assert stat.S_IMODE((root / 'pve-tmp').stat().st_mode) == 0o755
            assert stat.S_IMODE((root / 'pve-tmp/pct.conf').stat().st_mode) == 0o644
            assert os.umask(0o077) == 0o077
            instances.write(root / 'private-after/record.json', {'secret': 'fixture'})
            for name in ('private-before', 'private-after'):
                assert stat.S_IMODE((root / name).stat().st_mode) == 0o700
                assert stat.S_IMODE((root / name / 'record.json').stat().st_mode) == 0o600
        ''')

    def test_backup_failure_still_propagates_without_changing_parent_umask(self):
        self.scenario('''
            try:
                backup.before_update(4242, 'pbs-fixture')
            except subprocess.CalledProcessError as error:
                assert error.returncode == 7
            else:
                raise AssertionError('backup failure was hidden')
            assert os.umask(0o077) == 0o077
            assert stat.S_IMODE((root / 'private-before/record.json').stat().st_mode) == 0o600
        ''', exit_code=7)

    def test_file_storage_keeps_the_existing_no_extra_backup_route(self):
        self.scenario('''
            backup.dump_dir = lambda storage: root / 'dump'
            assert backup.before_update(4242, 'pbs-fixture') is None
            assert not (root / 'pve-tmp').exists()
            assert os.umask(0o077) == 0o077
        ''')


if __name__ == '__main__':
    unittest.main()
