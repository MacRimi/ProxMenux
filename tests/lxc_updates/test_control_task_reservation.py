"""Actual Flask submission, real flock, isolated Proxmox reads and shell caller."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import test_vm_control_task as control_fixture

TASK, ROOT = control_fixture.TASK, control_fixture.ROOT

sys.path.insert(0, str(ROOT / 'AppImage/scripts'))
import lxc_check_job as job


class ControlReservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.lock_path = self.folder / 'proxmenux-lxc-update-100.lock'
        self.lock_patch = patch.object(job, 'LOCK_DIR', self.folder)
        self.lock_patch.start()
        self.addCleanup(self.lock_patch.stop)
        job._jobs.clear()
        job._attempts.clear()
        self.route = control_fixture.ControlTaskTests()
        self.route.setUp()
        self.thread = Mock()
        self.factory = patch.object(job.threading, 'Thread', return_value=self.thread)
        self.thread_factory = self.factory.start()
        self.addCleanup(self.factory.stop)
        self.reservations = []
        self.addCleanup(lambda: [handle.close() for handle in self.reservations if not handle.closed])

    def accepted(self, action='reboot'):
        task = TASK.replace('vzreboot', 'vz' + action)
        self.route.run.return_value = self.route.result(task)
        response = self.route.client.post('/api/vms/100/control', json={'action': action})
        self.assertEqual(response.status_code, 200, response.json)
        handle = self.thread_factory.call_args.kwargs['args'][1]
        self.reservations.append(handle)
        self.assertEqual(response.json['task'], task)
        return handle

    @staticmethod
    def result(payload, code=0):
        return subprocess.CompletedProcess([], code, json.dumps(payload), '')

    def test_every_power_action_keeps_reservation_after_post_and_blocks_second_caller(self):
        for action in ('start', 'shutdown', 'reboot', 'stop'):
            with self.subTest(action=action):
                handle = self.accepted(action)
                self.route.run.reset_mock()
                response = self.route.client.post('/api/vms/100/control', json={'action': 'start'})
                self.assertEqual(response.status_code, 409)
                self.route.run.assert_not_called()
                with self.assertRaises(BlockingIOError):
                    job.start(100)
                self.assertFalse(handle.closed)
                job.cancel_control(handle)
                handle.close()

    def test_waiter_survives_read_failure_and_running_until_confirmed_terminal_status(self):
        handle = self.accepted()
        probes = [subprocess.TimeoutExpired('pvesh', 5),
                  self.result({'status': 'running'}), self.result({'status': 'stopped'}),
                  self.result({'status': 'stopped', 'exitstatus': 'OK'})]
        def still_reserved(_):
            with self.assertRaises(BlockingIOError):
                job.acquire(100)
            self.assertFalse(handle.closed)
        with patch.object(job.subprocess, 'run', side_effect=probes) as reads, \
             patch.object(job.time, 'sleep', side_effect=still_reserved) as sleeps:
            job._wait_control(100, handle)
        self.assertEqual(sleeps.call_count, 3)
        self.assertTrue(handle.closed)
        self.assertEqual(self.lock_path.read_text(), '')
        self.assertTrue(all(call.args[0][:2] == ['pvesh', 'get'] for call in reads.call_args_list))
        job.acquire(100).close()

    def test_restart_releases_fd_but_marker_blocks_until_pve_verifies_completion(self):
        handle = self.accepted()
        handle.close()  # simulate Monitor shutdown, not guest task termination
        with patch.object(job.subprocess, 'run', return_value=self.result({'status': 'running'})):
            with self.assertRaises(BlockingIOError):
                job.acquire(100)
        with patch.object(job.subprocess, 'run', return_value=self.result(
                {'status': 'stopped', 'exitstatus': 'start failed'})):
            job.acquire(100).close()
        self.assertEqual(self.lock_path.read_text(), '')

    def test_unknown_or_malformed_records_make_no_pve_probe_and_keep_blocked(self):
        for content in ['not-json', '{}', json.dumps({'node': 'fixture', 'task': None}),
                        json.dumps({'node': 'other', 'task': TASK}),
                        json.dumps({'node': 'fixture', 'task': TASK.replace(':100:', ':200:')}),
                        'x' * 1025]:
            self.lock_path.write_text(content)
            with patch.object(job.subprocess, 'run') as probe:
                with self.assertRaises(BlockingIOError):
                    job.acquire(100)
                probe.assert_not_called()
            self.assertEqual(self.lock_path.read_text(), content)

    def test_plain_lock_acquire_has_no_new_probe(self):
        with patch.object(job.subprocess, 'run') as probe:
            job.acquire(100).close()
            probe.assert_not_called()

    def test_definite_failure_or_unidentified_submission_never_leaves_a_permanent_reservation(self):
        self.route.run.return_value = self.result({}, code=1)
        self.assertEqual(self.route.client.post('/api/vms/100/control', json={'action': 'start'}).status_code, 500)
        self.assertEqual(self.lock_path.read_text(), '')
        for response in [subprocess.TimeoutExpired('pvesh', 30), self.result('')]:
            self.route.run.side_effect = response if isinstance(response, Exception) else None
            self.route.run.return_value = response
            response = self.route.client.post('/api/vms/100/control', json={'action': 'start'})
            self.assertIn(response.status_code, (500, 502), response.json)
            self.assertEqual(self.lock_path.read_text(), '')
            job.acquire(100).close()

    def test_ha_task_recovers_like_a_native_lxc_task(self):
        task = TASK.replace('vzreboot', 'hastop')
        self.lock_path.write_text(json.dumps({'node': 'fixture', 'task': task}))
        with patch.object(job.subprocess, 'run', return_value=self.result(
                {'status': 'stopped', 'exitstatus': 'OK'})) as probe:
            job.acquire(100).close()
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(self.lock_path.read_text(), '')

    def test_wait_deadline_releases_fd_but_keeps_known_task_for_recovery(self):
        handle = self.accepted()
        with patch.object(job, 'CONTROL_TASK_WAIT_SECONDS', 0):
            job._wait_control(100, handle)
        self.assertTrue(handle.closed)
        record = json.loads(self.lock_path.read_text())
        self.assertEqual(record['task'], TASK)
        with patch.object(job.subprocess, 'run', return_value=self.result(
                {'status': 'stopped', 'exitstatus': 'OK'})):
            job.acquire(100).close()
        self.assertEqual(self.lock_path.read_text(), '')

    def test_thread_launch_failure_retains_marker_for_recovery(self):
        self.thread.start.side_effect = RuntimeError('thread failed')
        self.route.run.return_value = self.route.result(TASK)
        self.assertEqual(self.route.client.post('/api/vms/100/control', json={'action': 'reboot'}).status_code, 500)
        self.assertEqual(json.loads(self.lock_path.read_text())['task'], TASK)
        with patch.object(job.subprocess, 'run', return_value=self.result({'status': 'running'})):
            with self.assertRaises(BlockingIOError):
                job.acquire(100)

    def test_failed_task_record_write_keeps_uncertainty_before_any_next_operation(self):
        original = job._write_control
        calls = 0
        def fail_second(handle, record):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('persistence failed')
            original(handle, record)
        self.route.run.return_value = self.route.result(TASK)
        with patch.object(job, '_write_control', side_effect=fail_second):
            response = self.route.client.post('/api/vms/100/control', json={'action': 'reboot'})
        self.assertEqual(response.status_code, 500)
        self.assertIsNone(json.loads(self.lock_path.read_text())['task'])
        with patch.object(job.subprocess, 'run') as probe:
            with self.assertRaises(BlockingIOError):
                job.acquire(100)
            probe.assert_not_called()

    def test_shell_blocked_by_live_reservation_runs_no_probe_or_guest_action(self):
        self.accepted()
        import os
        env = {**os.environ, 'PROXMENUX_LOCK_DIR': str(self.folder),
               'VMID': '100', 'TARGET': 'os', 'BACKUP': '1'}
        result = subprocess.run(['/bin/bash', str(ROOT / 'scripts/lxc/apply_updates.sh')],
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertIn('another ProxMenux update', result.stderr)
        self.assertEqual(result.stdout, '')

    def test_retired_combined_mode_fails_before_lock_or_any_guest_operation(self):
        import os
        env = {**os.environ, 'PROXMENUX_LOCK_DIR': str(self.folder),
               'VMID': '100', 'TARGET': 'os', 'CHECK_APPLY_OS': '1'}
        result = subprocess.run(['/bin/bash', str(ROOT / 'scripts/lxc/apply_updates.sh')],
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertFalse(self.lock_path.exists())
        self.assertEqual(result.stdout, '')

    def test_shell_caller_preserves_pending_record_and_performs_no_guest_operation(self):
        # Covers process-restart recovery: no Python thread holds this flock.
        self.lock_path.write_text(json.dumps({'node': 'fixture', 'task': TASK}))
        binary = self.folder / 'bin'
        binary.mkdir()
        call_log = self.folder / 'calls'
        for name, body in [('pvesh', 'echo \'{"status":"running"}\''),
                           ('pct', f'echo pct >> "{call_log}"; exit 99')]:
            script = binary / name
            script.write_text('#!/bin/sh\n' + body + '\n')
            script.chmod(0o755)
        import os
        before = self.lock_path.read_text()
        env = {**os.environ, 'PATH': str(binary) + ':' + os.environ['PATH'],
               'PYTHONPATH': str(ROOT / 'AppImage/scripts'),
               'PROXMENUX_LOCK_DIR': str(self.folder), 'VMID': '100', 'TARGET': 'os', 'BACKUP': '1'}
        result = subprocess.run(['/bin/bash', str(ROOT / 'scripts/lxc/apply_updates.sh')],
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertFalse(call_log.exists())
        self.assertEqual(self.lock_path.read_text(), before)


if __name__ == '__main__':
    unittest.main()
