"""A fast Manage entry still detects config edits and verifies lifecycle work."""
import contextlib
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'remote'))
import oci_carried_record as carried


class CarriedConfigCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        contract = patch.object(carried, 'STACK_CONTRACT', str(Path(self.tmp.name) / 'stack-{}.json'))
        contract.start()
        self.addCleanup(contract.stop)
        self.root = Path(self.tmp.name) / 'instances'
        self.source = Path(self.tmp.name) / 'lxc'
        self.source.mkdir()
        self.config = self.source / '120.conf'
        self.config.write_text('# proxmenux-instance=example\nunprivileged: 1\n')
        (self.root / '120').mkdir(parents=True)
        self.cache = self.root / '120' / carried.CONFIG_CACHE
        self.patch = patch.object(carried, 'LOCAL_CONFIGS', self.source)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def response(self, text='description: proxmenux-instance=example\nunprivileged: 1\n', status=0):
        return SimpleNamespace(returncode=status, stdout=text)

    def test_warm_reads_avoid_pct_and_cache_is_private(self):
        with patch.object(carried, '_run', return_value=self.response()) as run:
            first = carried.configuration(self.root, 120)
            self.assertEqual(carried.configuration(self.root, 120), first)
        run.assert_called_once_with('pct', 'config', '120')
        self.assertEqual(self.cache.stat().st_mode & 0o777, 0o600)

    def test_native_edits_invalidate_even_when_size_and_mtime_are_restored(self):
        with patch.object(carried, '_run', side_effect=[self.response(), self.response('new')]) as run:
            carried.configuration(self.root, 120)
            info = self.config.stat()
            self.config.write_text(self.config.read_text().replace('example', 'changed'))
            os.utime(self.config, ns=(info.st_atime_ns, info.st_mtime_ns))
            self.assertEqual(carried.configuration(self.root, 120), 'new')
        self.assertEqual(run.call_count, 2)

    def test_verify_forces_a_fresh_pct_read_with_a_warm_cache(self):
        with patch.object(carried, '_run', side_effect=[self.response(), self.response('verified')]) as run:
            carried.configuration(self.root, 120)
            self.assertEqual(carried.configuration(self.root, 120, verify=True), 'verified')
        self.assertEqual(run.call_count, 2)

    def test_missing_native_source_never_uses_or_populates_a_cache(self):
        self.config.unlink()
        with patch.object(carried, '_run', return_value=self.response()) as run:
            carried.configuration(self.root, 120)
            carried.configuration(self.root, 120)
        self.assertEqual(run.call_count, 2)
        self.assertFalse(self.cache.exists())

    def test_concurrent_edit_does_not_cache_output_for_the_wrong_revision(self):
        def command(*args):
            self.config.write_text('changed while pct was reading\n')
            return self.response()
        with patch.object(carried, '_run', side_effect=command):
            carried.configuration(self.root, 120)
        self.assertFalse(self.cache.exists())

    def test_edit_during_cache_lookup_falls_back_to_pct(self):
        with patch.object(carried, '_run', return_value=self.response()):
            carried.configuration(self.root, 120)
        read_text = Path.read_text
        def edit_during_read(path, *args, **kwargs):
            text = read_text(path, *args, **kwargs)
            if path == self.cache:
                self.config.write_text('changed while reading the cache\n')
            return text
        with patch.object(Path, 'read_text', edit_during_read), \
                patch.object(carried, '_run', return_value=self.response('fresh')) as run:
            self.assertEqual(carried.configuration(self.root, 120), 'fresh')
        run.assert_called_once_with('pct', 'config', '120')

    def test_corrupt_cache_and_pct_failure_are_not_accepted(self):
        for text in ('not json', '[]', '{"schema_version": 999}'):
            with self.subTest(cache=text):
                self.cache.write_text(text)
                with patch.object(carried, '_run', return_value=self.response(status=1)) as run:
                    self.assertIsNone(carried.configuration(self.root, 120))
                run.assert_called_once()
                self.assertEqual(self.cache.read_text(), text)

    def test_symlink_cache_does_not_read_or_replace_its_target(self):
        target = Path(self.tmp.name) / 'outside'
        target.write_text('private original')
        self.cache.symlink_to(target)
        with patch.object(carried, '_run', return_value=self.response()) as run:
            self.assertEqual(carried.configuration(self.root, 120), self.response().stdout)
        run.assert_called_once()
        self.assertTrue(self.cache.is_symlink())
        self.assertEqual(target.read_text(), 'private original')

    def test_cached_config_still_detects_a_restored_container_record(self):
        installation = '488ed3cb-1145-477a-b90f-c46777d69fb2'
        record = {'schema_version': 1, 'vmid': 120, 'installation_id': installation,
                  'status': 'installed', 'deployment': {'hostname': 'current'}}
        carried.instances.write(carried.instances.location(self.root, 120), record)
        native = f'description: proxmenux-instance={installation}\n'
        with patch.object(carried, '_run', return_value=self.response(native)):
            carried.configuration(self.root, 120)
        rootfs = Path(self.tmp.name) / 'rootfs'
        rootfs.mkdir()
        previous = copy.deepcopy(record)
        previous['deployment']['hostname'] = 'restored-snapshot'
        carried.write_copy(rootfs, {'kind': carried.KIND, 'schema_version': 1,
                                   'record': previous, 'generation': 'restored-generation'},
                           (os.getuid(), os.getgid()))
        stamp = self.root / '120' / carried.STAMP
        stamp.write_text(json.dumps({'generation': 'host-generation'}))
        with patch.object(carried, '_run', side_effect=AssertionError('cached config expected')), \
                patch.object(carried, 'read_cluster', return_value=None), \
                patch.object(carried, 'running_pid', return_value=123), \
                patch.object(carried, 'container_root', return_value=contextlib.nullcontext(rootfs)):
            self.assertEqual(carried.carry(self.root, 120, mount_stopped=False), 'stale')
        self.assertFalse(carried.instances.location(self.root, 120).exists())
        self.assertTrue((self.root / '120' / f'retired-{installation}.json').exists())


if __name__ == '__main__':
    unittest.main()
