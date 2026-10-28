"""Real cross-process contention at the late stack publication boundary."""
import contextlib
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'remote'))
import oci_instances as instances

HOLDER = '''import fcntl,sys,time
with open(sys.argv[1], 'a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    print('locked', flush=True)
    sys.stdin.readline()
'''


@contextlib.contextmanager
def competing_owner(root):
    process = subprocess.Popen([sys.executable, '-u', '-c', HOLDER, str(root / '.lock')],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        if process.stdout.readline().strip() != 'locked':
            raise RuntimeError('Lock fixture did not acquire the lock')
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        process.stdout.close()
        process.stdin.close()


class InstanceLockWaitTests(unittest.TestCase):
    def test_waiting_publication_succeeds_after_another_process_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with competing_owner(root) as process:
                def release():
                    process.stdin.write('release\n')
                    process.stdin.flush()
                timer = threading.Timer(0.35, release)
                start = time.monotonic()
                timer.start()
                try:
                    with instances.locked(root, timeout=2):
                        elapsed = time.monotonic() - start
                    self.assertGreaterEqual(elapsed, 0.2)
                    self.assertLess(elapsed, 2)
                finally:
                    timer.cancel()
                    timer.join()

    def test_default_remains_immediate_when_another_operation_owns_the_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with competing_owner(root):
                start = time.monotonic()
                with self.assertRaises(BlockingIOError), instances.locked(root):
                    self.fail('Contended default lock was acquired')
                self.assertLess(time.monotonic() - start, 0.5)

    def test_wait_has_a_finite_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with competing_owner(root):
                start = time.monotonic()
                with self.assertRaises(BlockingIOError), instances.locked(root, timeout=0.1):
                    self.fail('Contended timed lock was acquired')
                elapsed = time.monotonic() - start
                self.assertGreaterEqual(elapsed, 0.08)
                self.assertLess(elapsed, 0.6)

    def test_error_inside_operation_is_propagated_without_repeating_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entered = []
            with self.assertRaises(BlockingIOError):
                with instances.locked(root, timeout=2):
                    entered.append(True)
                    raise BlockingIOError('unrelated operation failure')
            self.assertEqual(entered, [True])
            with instances.locked(root):
                pass

    def test_permission_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(instances.fcntl, 'flock', side_effect=PermissionError('denied')), \
                    patch.object(instances.time, 'sleep') as sleep:
                with self.assertRaises(PermissionError), instances.locked(Path(directory), timeout=2):
                    pass
                sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
