"""A container mounted with `pct mount` is never left locked as `mounted` once
nothing is mounted under its root filesystem; with anything still mounted the
lock stays."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_mount_lock as lock


class Runner:
    """Answers `pct unmount` with the given results in order, like a runner
    that raises on failure."""

    def __init__(self, *unmount_results):
        self.results = list(unmount_results)
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        if args[1] == 'unmount' and not self.results.pop(0):
            raise subprocess.CalledProcessError(32, args)
        return ''


class MountLockTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.mountinfo = self.dir / 'mountinfo'
        self.configs = self.dir / 'lxc'
        self.configs.mkdir()
        for name, value in (('MOUNTINFO', self.mountinfo), ('CONFIGS', self.configs), ('RETRY_SECONDS', 0)):
            patcher = mock.patch.object(lock, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.mounts()
        self.config('lock: mounted\n')

    def mounts(self, *points):
        lines = ['22 1 0:21 / /proc rw - proc proc rw']
        lines += [f'{30 + i} 1 253:4 / {p} rw - ext4 /dev/mapper/pve-vm--188--disk--0 rw' for i, p in enumerate(points)]
        self.mountinfo.write_text('\n'.join(lines) + '\n')

    def config(self, head, snapshot=''):
        (self.configs / '188.conf').write_text('arch: amd64\n' + head + 'hostname: immich\n' + snapshot)

    def test_a_clean_unmount_does_nothing_else(self):
        run = Runner(True)
        self.assertTrue(lock.unmount(188, run))
        self.assertEqual(run.calls, [('pct', 'unmount', '188')])

    def test_a_busy_unmount_is_tried_again(self):
        run = Runner(False, True)
        self.assertTrue(lock.unmount(188, run))
        self.assertEqual([c[1] for c in run.calls], ['unmount', 'unmount'])

    def test_the_lock_left_behind_is_removed_when_nothing_is_mounted(self):
        run = Runner(False, False)
        self.assertTrue(lock.unmount(188, run))
        self.assertEqual(run.calls[-1], ('pct', 'unlock', '188'))

    def test_the_lock_stays_while_something_is_mounted(self):
        for point in ('/var/lib/lxc/188/rootfs', '/var/lib/lxc/188/rootfs/data'):
            with self.subTest(point=point):
                self.mounts(point)
                run = Runner(False, False)
                self.assertFalse(lock.unmount(188, run))
                self.assertNotIn('unlock', [c[1] for c in run.calls])
                with self.assertRaisesRegex(ValueError, 'Could not unmount the container filesystem'):
                    lock.release(188, Runner(False, False))

    def test_another_container_mounted_does_not_count(self):
        self.mounts('/var/lib/lxc/1880/rootfs')
        self.assertTrue(lock.unmount(188, Runner(False, False)))

    def test_only_a_mounted_lock_of_the_container_itself_is_removed(self):
        # Another lock (a backup, a migration) is never touched, nor the lock
        # of a snapshot section.
        for head, snapshot in (('lock: backup\n', ''), ('', '[before]\nlock: mounted\n')):
            with self.subTest(head=head, snapshot=snapshot):
                self.config(head, snapshot)
                run = Runner(False, False)
                self.assertFalse(lock.unmount(188, run))
                self.assertNotIn('unlock', [c[1] for c in run.calls])

    def test_a_runner_that_returns_its_result(self):
        failed = subprocess.CompletedProcess(['pct'], 32)
        done = subprocess.CompletedProcess(['pct'], 0)
        answers = iter([failed, failed, done])
        self.assertTrue(lock.unmount(188, lambda *args: next(answers)))

    def test_without_the_list_of_mounts_nothing_is_assumed_free(self):
        self.mountinfo.unlink()
        self.assertFalse(lock.unmount(188, Runner(False, False)))


if __name__ == '__main__':
    unittest.main()
