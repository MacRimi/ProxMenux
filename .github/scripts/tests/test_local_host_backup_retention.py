"""Exercise the local runner; replace only the PVE library absent from CI."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / 'scripts/backup_restore/run_scheduled_backup.sh'


def function(name, path=RUNNER):
    text = path.read_text()
    start = text.index(name + '() {')
    return text[start:text.index('\n}', start) + 2] + '\n'


# This boundary double does not implement retention. The test supplies native
# marks and checks the exact policy/group passed to PVE::Storage. Calendar
# selection belongs to PVE, not to a second algorithm in ProxMenux or its tests.
PVE_STORAGE = r'''
package PVE::Storage;
use JSON::PP;
BEGIN {
    *CORE::GLOBAL::unlink = sub {
        if (($ENV{UNLINK_FAIL} // '') eq $_[0]) { $! = 13; return 0; }
        return CORE::unlink($_[0]);
    };
}
sub prune_mark_backup_group {
    my ($group, $keep) = @_;
    open(my $out, '>', "$ENV{FIXTURE}/native-call.json") or die $!;
    print $out encode_json({group => $group, keep => $keep});
    close($out) or die $!;
    die "native planner failed\n" if $ENV{PLANNER_FAIL};
    my $marks = decode_json($ENV{NATIVE_MARKS});
    for my $entry (@$group) {
        $entry->{mark} = $marks->{$entry->{name}} // $marks->{$entry->{ctime}} // 'keep';
    }
}
1;
'''


class LocalHostRetention(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='local-host-retention-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.dest = self.root / 'archives with spaces'
        self.logs = self.root / 'logs'
        self.dest.mkdir()
        self.logs.mkdir()
        module = self.root / 'PVE' / 'Storage.pm'
        module.parent.mkdir()
        module.write_text(PVE_STORAGE)

    def archive(self, stamp, extension='tar.zst', job='fixture'):
        archive = self.dest / f'{job}-{stamp}.{extension}'
        archive.write_text('archive')
        Path(str(archive) + '.proxmenux.json').write_text('{}')
        (self.logs / f'{job}-{stamp}.log').write_text('log')
        return archive

    def prune(self, policy, marks=None, setup='', **extra):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith('KEEP_')}
        env.update(PATH='/usr/bin:/bin', PERL5LIB=str(self.root),
                   FIXTURE=str(self.root), LOG_DIR=str(self.logs), TZ='UTC',
                   NATIVE_MARKS=json.dumps(marks or {}))
        env.update(policy)
        env.update(extra)
        return subprocess.run(
            ['/bin/bash', '--noprofile', '--norc', '-uc',
             setup + function('_sb_prune_local') + '_sb_prune_local fixture "$1" tar.zst',
             'test', str(self.dest)], env=env, text=True, capture_output=True,
        )

    def test_calendar_policy_reaches_native_selector_and_prunes_local_archive(self):
        old = self.archive('20260101_040000')
        newest = self.archive('20260102_040000')
        result = self.prune({'KEEP_DAILY': '1'}, {'1767240000': 'remove'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(old.exists(), 'calendar-only retention left the old archive')
        self.assertTrue(newest.exists())
        self.assertFalse(Path(str(old) + '.proxmenux.json').exists())
        self.assertFalse((self.logs / 'fixture-20260101_040000.log').exists())
        call = json.loads((self.root / 'native-call.json').read_text())
        self.assertEqual(call['keep'].get('keep-daily'), 1)
        self.assertEqual({entry['ctime'] for entry in call['group']},
                         {1767240000, 1767326400})


    def test_all_six_retention_values_are_forwarded(self):
        self.archive('20260101_040000')
        periods = ('last', 'hourly', 'daily', 'weekly', 'monthly', 'yearly')
        policy = {'KEEP_' + period.upper(): str(index)
                  for index, period in enumerate(periods, 1)}
        result = self.prune(policy)
        self.assertEqual(result.returncode, 0, result.stderr)
        call = json.loads((self.root / 'native-call.json').read_text())
        self.assertEqual(call['keep'], {'keep-' + period: index
                                       for index, period in enumerate(periods, 1)})

    def test_unset_and_zero_policy_keep_everything(self):
        old = self.archive('20260101_040000')
        newest = self.archive('20260102_040000')
        for policy in ({}, {'KEEP_LAST': '0', 'KEEP_DAILY': '0'},
                       {'KEEP_LAST': '', 'KEEP_DAILY': ''}):
            with self.subTest(policy=policy):
                result = self.prune(policy)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(old.exists())
                self.assertTrue(newest.exists())
                call = json.loads((self.root / 'native-call.json').read_text())
                self.assertTrue(all(value == 0 for value in call['keep'].values()))

    def test_compression_changes_do_not_split_the_backup_group(self):
        old = self.archive('20260101_040000', 'tar.gz')
        newest = self.archive('20260102_040000', 'tar.zst')
        result = self.prune({'KEEP_LAST': '1'}, {'1767240000': 'remove'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(old.exists())
        self.assertTrue(newest.exists())
        call = json.loads((self.root / 'native-call.json').read_text())
        self.assertEqual(len(call['group']), 2)

    def test_retained_compression_variant_preserves_the_shared_run_log(self):
        old = self.archive('20260101_040000', 'tar.gz')
        retained = self.archive('20260101_040000', 'tar.zst')
        result = self.prune({'KEEP_LAST': '1'}, {old.name: 'remove'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(old.exists())
        self.assertTrue(retained.exists())
        self.assertTrue(Path(str(retained) + '.proxmenux.json').exists())
        self.assertTrue((self.logs / 'fixture-20260101_040000.log').exists())

    def test_only_exact_valid_regular_archives_of_this_job_are_candidates(self):
        valid = self.archive('20260101_040000')
        unrelated = [self.archive('20260101_040000', job='fixture-other'),
                     self.archive('20260101_040000', job='vzdump-lxc-100'),
                     self.archive('20260230_040000'),
                     self.archive('20260101_250000'),
                     self.archive('20260104_040000', 'tar.zst\n'),
                     self.archive('renamed')]
        outside = self.root / 'outside'
        outside.write_text('outside')
        link = self.dest / 'fixture-20260102_040000.tar.zst'
        link.symlink_to(outside)
        directory = self.dest / 'fixture-20260103_040000.tar.zst'
        directory.mkdir()
        result = self.prune({'KEEP_LAST': '1'}, {'1767240000': 'remove'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(valid.exists())
        self.assertTrue(all(path.exists() for path in unrelated))
        self.assertTrue(link.is_symlink())
        self.assertTrue(outside.exists())
        self.assertTrue(directory.is_dir())
        call = json.loads((self.root / 'native-call.json').read_text())
        self.assertEqual(len(call['group']), 1)

    def test_empty_directory_is_safe(self):
        result = self.prune({'KEEP_DAILY': '4'})
        self.assertEqual(result.returncode, 0, result.stderr)
        call = json.loads((self.root / 'native-call.json').read_text())
        self.assertEqual(call['group'], [])

    def test_modification_time_does_not_replace_the_backup_timestamp(self):
        old = self.archive('20260101_040000')
        os.utime(old, (0, 0))
        result = self.prune({'KEEP_DAILY': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)
        call = json.loads((self.root / 'native-call.json').read_text())
        self.assertEqual(call['group'][0]['ctime'], 1767240000)

    def test_invalid_policy_fails_before_any_archive_is_deleted(self):
        old = self.archive('20260101_040000')
        for value in ('-1', 'invalid', '1.5'):
            with self.subTest(value=value):
                result = self.prune({'KEEP_DAILY': value}, {'1767240000': 'remove'})
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(old.exists())
                self.assertFalse((self.root / 'native-call.json').exists())

    def test_native_planner_failure_preserves_archives_and_metadata(self):
        old = self.archive('20260101_040000')
        result = self.prune({'KEEP_DAILY': '1'}, {'1767240000': 'remove'},
                            PLANNER_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(old.exists())
        self.assertTrue(Path(str(old) + '.proxmenux.json').exists())
        self.assertTrue((self.logs / 'fixture-20260101_040000.log').exists())

    def test_missing_directory_is_reported(self):
        self.dest.rmdir()
        result = self.prune({'KEEP_DAILY': '1'})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'native-call.json').exists())

    def test_missing_optional_sidecar_and_log_do_not_fail_pruning(self):
        old = self.archive('20260101_040000')
        Path(str(old) + '.proxmenux.json').unlink()
        (self.logs / 'fixture-20260101_040000.log').unlink()
        result = self.prune({'KEEP_LAST': '1'}, {'1767240000': 'remove'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(old.exists())

    def test_attached_job_uses_live_parent_retention_not_stale_snapshot(self):
        self.archive('20260101_040000')
        config = self.root / 'jobs.cfg'
        config.write_text('vzdump: parent\n\tprune-backups keep-daily=4,keep-weekly=1,keep-monthly=1,keep-yearly=1\n')
        # Only relocate the external file inside the fixture; production has no
        # extra configuration knob or alternate planner for tests.
        hydrate = function('_sb_hydrate_attached_retention').replace(
            'local cfg=/etc/pve/jobs.cfg', 'local cfg="$FIXTURE/jobs.cfg"')
        common = ROOT / 'scripts/backup_restore/lib_host_backup_common.sh'
        setup = (function('hb_pve_prune_to_keep_env', common) + hydrate
                 + 'PVE_PARENT_JOB=parent\n_sb_hydrate_attached_retention\n')
        result = self.prune({'KEEP_LAST': '7', 'KEEP_DAILY': '7'}, setup=setup)
        self.assertEqual(result.returncode, 0, result.stderr)
        call = json.loads((self.root / 'native-call.json').read_text())
        self.assertEqual(call['keep'], {'keep-last': 0, 'keep-hourly': 0,
                                       'keep-daily': 4, 'keep-weekly': 1,
                                       'keep-monthly': 1, 'keep-yearly': 1})
        config.write_text('vzdump: parent\n\tstorage local\n')
        result = self.prune({'KEEP_LAST': '7', 'KEEP_DAILY': '7'}, setup=setup)
        self.assertEqual(result.returncode, 0, result.stderr)
        call = json.loads((self.root / 'native-call.json').read_text())
        self.assertTrue(all(value == 0 for value in call['keep'].values()))

    def test_failed_archive_removal_preserves_sidecar_and_log(self):
        old = self.archive('20260101_040000')
        result = self.prune({'KEEP_LAST': '1'}, {'1767240000': 'remove'},
                            UNLINK_FAIL=str(old))
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(old.exists())
        self.assertTrue(Path(str(old) + '.proxmenux.json').exists())
        self.assertTrue((self.logs / 'fixture-20260101_040000.log').exists())

    def test_failed_metadata_removal_is_reported(self):
        old = self.archive('20260101_040000')
        sidecar = Path(str(old) + '.proxmenux.json')
        result = self.prune({'KEEP_LAST': '1'}, {'1767240000': 'remove'},
                            UNLINK_FAIL=str(sidecar))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(old.exists())
        self.assertTrue(sidecar.exists())
        self.assertTrue((self.logs / 'fixture-20260101_040000.log').exists())

    def test_local_backup_reports_a_pruning_failure(self):
        stage = self.root / 'stage'
        stage.mkdir()
        (stage / 'data').write_text('fixture data')
        script = (function('_sb_run_local')
                  + '_sb_prune_local() { return 73; }\n'
                  + 'hb_write_archive_sidecar() { :; }\n'
                  + '_sb_run_local "$1" fixture 20260103_040000 "$2"\n')
        result = subprocess.run(
            ['/bin/bash', '-uc', script, 'test', str(stage), str(self.dest)],
            env={'PATH': '/usr/bin:/bin', 'LOCAL_ARCHIVE_EXT': 'tar.gz'},
            text=True, capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0, 'pruning failure reported as success')
        self.assertNotIn('LOCAL_ARCHIVE=', result.stdout)
        self.assertTrue((self.dest / 'fixture-20260103_040000.tar.gz').exists())


if __name__ == '__main__':
    unittest.main()
