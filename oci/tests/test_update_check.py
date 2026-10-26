"""The OCI menu shares the Monitor's checker and cache, with no fallback."""
import datetime
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'remote'), str(ROOT.parent / 'AppImage/scripts')]
import oci_update_check as check
import oci_menu_bridge as bridge
import lxc_apps

OLD = 'sha256:' + 'a' * 64
NEW = 'sha256:' + 'b' * 64


class UpdateCheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.root, self.configs, self.apps = [self.folder / name for name in ('instances', 'configs', 'apps')]
        for path in (self.root, self.configs, self.apps): path.mkdir()
        self.now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)

    def record(self, vmid=110, reference='example/app:latest', **changes):
        identifier = str(uuid.uuid4())
        record = {'schema_version': 1, 'vmid': vmid, 'installation_id': identifier,
                  'status': 'installed', 'deployment': {'hostname': f'app-{vmid}'},
                  'template': {'container_contract': {'image': {'reference': reference}}},
                  'observed': {'image': {'manifest_digest': OLD}}}
        record.update(changes)
        directory = self.root / str(vmid); directory.mkdir(exist_ok=True)
        (directory / 'oci-compose.json').write_text(json.dumps(record))
        (self.configs / f'{vmid}.conf').write_text(f'#proxmenux-instance={identifier}\narch: amd64\n')
        return record

    def sidecar(self, vmid=110, **changes):
        state = {'checked_at': self.now.strftime('%Y-%m-%dT%H:%M:%SZ'),
                 'installed_digest': OLD, 'latest_digest': NEW,
                 'image_reference': 'example/app:latest', 'update_available': True}
        state.update(changes)
        data = {'vmid': vmid, 'apps': [{'id': f'app-{vmid}', 'installed_via': 'oci_image', 'state': state}]}
        (self.apps / f'{vmid}.json').write_text(json.dumps(data))
        return data

    def status(self, **kwargs):
        return check.cached(self.root, self.configs, apps=self.apps, now=self.now.timestamp(), **kwargs)

    def test_menu_reads_only_native_cache_without_subprocess_or_socket(self):
        self.record(); self.sidecar()
        before = {str(p): p.read_bytes() for p in self.folder.rglob('*') if p.is_file()}
        with patch.object(subprocess, 'run') as run, patch.object(socket, 'socket') as connection:
            state = self.status()
        self.assertEqual([r['vmid'] for r in state['available']], [110])
        run.assert_not_called(); connection.assert_not_called()
        after = {str(p): p.read_bytes() for p in self.folder.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertNotIn('resolve_candidate', check.__dict__)
        self.assertNotIn('query', check.__dict__)

    def test_missing_native_cache_is_unknown_even_with_old_separate_cache(self):
        self.record()
        (self.root / '.update-check.json').write_text(json.dumps({'applications': [{'vmid': 110, 'status': 'available'}]}))
        state = self.status()
        self.assertFalse(state['checked']); self.assertEqual(state['unknown'], 1)
        self.assertFalse(state['available'])

    def test_native_false_is_current_without_recomputing_digests(self):
        self.record(); self.sidecar(update_available=False)
        state = self.status()
        self.assertTrue(state['checked']); self.assertEqual(state['unknown'], 0)
        self.assertFalse(state['available'])

    def test_native_retry_retains_available_result_and_unknown_state(self):
        self.record(); self.sidecar(registry_retry=True)
        self.assertEqual(len(self.status()['available']), 1)
        self.assertEqual(self.status()['unknown'], 1)

    def test_native_error_or_missing_result_never_means_up_to_date(self):
        self.record()
        for changes in ({'error': 'registry unreachable'}, {'update_available': None}, {'latest_digest': None}):
            self.sidecar(**changes)
            state = self.status()
            self.assertFalse(state['available']); self.assertEqual(state['unknown'], 1)

    def test_stale_future_or_different_image_cache_is_not_available(self):
        self.record()
        for changes in ({'checked_at': (self.now - datetime.timedelta(days=2)).strftime('%Y-%m-%dT%H:%M:%SZ')},
                        {'checked_at': (self.now + datetime.timedelta(days=2)).strftime('%Y-%m-%dT%H:%M:%SZ')},
                        {'installed_digest': NEW}, {'image_reference': 'other/image:latest'}):
            self.sidecar(**changes)
            self.assertFalse(self.status()['available'])
            self.assertEqual(self.status()['unknown'], 1)

    def test_invalid_identity_or_pending_native_edit_invalidates_cached_update(self):
        self.record(); self.sidecar()
        (self.configs / '110.conf').write_text('arch: amd64\n')
        self.assertFalse(self.status()['available'])
        self.record(pending_transaction={'operation': 'update'})
        self.assertFalse(self.status()['available'])

    def test_snapshot_identity_cannot_replace_current_identity(self):
        record = self.record(); self.sidecar()
        (self.configs / '110.conf').write_text(
            f"arch: amd64\n\n[previous]\n#proxmenux-instance={record['installation_id']}\n")
        self.assertFalse(self.status()['available'])

    def test_remote_or_deleted_guest_is_excluded(self):
        self.record(); self.sidecar(); (self.configs / '110.conf').unlink()
        self.assertEqual(self.status()['applications'], 0)
        self.assertFalse(self.status()['available'])

    def test_corrupt_ambiguous_or_symlinked_sidecars_are_unknown(self):
        self.record(); path = self.apps / '110.json'
        path.write_text('{broken')
        self.assertEqual(self.status()['unknown'], 1)
        data = self.sidecar(); data['apps'] *= 2; path.write_text(json.dumps(data))
        self.assertEqual(self.status()['unknown'], 1)
        path.unlink(); path.symlink_to(self.root / '110/oci-compose.json')
        self.assertEqual(self.status()['unknown'], 1)

    def test_stack_counts_once_and_follows_monitors_primary_tracking_rule(self):
        self.record(110, stack_member={'primary_vmid': 110}, stack={'members': [{'vmid': 110}, {'vmid': 111}]})
        self.record(111, stack_member={'primary_vmid': 110})
        self.sidecar(110, update_available=False); self.sidecar(111, update_available=True)
        self.assertEqual(self.status()['applications'], 1)
        self.assertFalse(self.status()['available'])
        self.sidecar(110)
        self.assertEqual([r['vmid'] for r in self.status()['available']], [110])

    def test_incomplete_stack_is_not_offered_for_update(self):
        self.record(110, stack={'members': [{'vmid': 110}, {'vmid': 111}]}); self.sidecar()
        self.assertFalse(self.status()['available'])
        self.assertEqual(self.status()['unknown'], 1)

    def test_real_bridge_calls_native_checker_and_publishes_its_sidecar(self):
        record = self.record(); self.sidecar(update_available=False)
        path = self.folder / 'check.sock'
        server = bridge._Server(str(path), bridge._Handler); server.apps = lxc_apps
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        result = {'installed_digest': OLD, 'installed_registry_digest': OLD,
                  'image_reference': 'example/app:latest', 'installed_version': '1.0',
                  'latest_version': '2.0', 'latest_digest': NEW, 'update_available': True}
        events = []
        with patch.object(bridge, '_root_peer', return_value=True), \
                patch.object(check, 'monitor_available', return_value=True), \
                patch.object(lxc_apps, '_APPS_DIR', str(self.apps)), \
                patch.object(lxc_apps, '_read_oci_record', return_value=record), \
                patch.object(lxc_apps, 'ensure_oci_registration'), \
                patch.object(lxc_apps, '_oci_image_versions', return_value=result) as native, \
                patch.object(lxc_apps, '_fire_update_notification') as notify, \
                patch.object(subprocess, 'run') as external:
            check.check(self.root, self.configs, path=path, progress=lambda *event: events.append(event))
        native.assert_called_once(); notify.assert_not_called(); external.assert_not_called()
        self.assertEqual(events[0], (0, 1)); self.assertEqual(events[-1], (1, 1))
        self.assertEqual([r['vmid'] for r in self.status()['available']], [110])
        self.assertFalse((self.root / '.update-check.json').exists())

    def test_missing_monitor_never_falls_back_to_registry_commands(self):
        self.record()
        with patch.object(check, 'monitor_available', return_value=False), patch.object(subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'Monitor'):
                check.check(self.root, self.configs)
        run.assert_not_called()

    def test_readonly_monitor_availability_rejects_non_private_endpoints(self):
        path = Mock(); path.parent.lstat.return_value = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=0)
        path.lstat.return_value = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=0)
        with patch.object(check.socket, 'socket'):
            self.assertTrue(check.monitor_available(path))
        path.lstat.return_value.st_mode |= 0o066
        self.assertFalse(check.monitor_available(path))
        path.lstat.return_value.st_mode = stat.S_IFREG | 0o600
        self.assertFalse(check.monitor_available(path))
        path.lstat.return_value.st_mode = stat.S_IFSOCK | 0o600
        path.parent.lstat.return_value.st_uid = 1000
        self.assertFalse(check.monitor_available(path))

    def test_socket_left_by_a_stopped_monitor_is_not_available(self):
        folder = Path(tempfile.mkdtemp(dir='/tmp')); self.addCleanup(lambda: __import__('shutil').rmtree(folder))
        folder.chmod(0o700); path = folder / 'check.sock'
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); listener.bind(str(path)); path.chmod(0o600)
        listener.listen(1)
        owner = SimpleNamespace(st_uid=0)
        real_lstat = Path.lstat
        def lstat(self):
            value = real_lstat(self)
            return SimpleNamespace(st_mode=value.st_mode, st_uid=owner.st_uid)
        with patch.object(Path, 'lstat', lstat):
            self.assertTrue(check.monitor_available(path))
            listener.close()  # The socket file stays, nothing listens.
            self.assertTrue(path.exists())
            self.assertFalse(check.monitor_available(path))

    def test_failed_application_keeps_no_older_result(self):
        self.record(); self.sidecar(update_available=True)
        self.assertEqual([r['vmid'] for r in self.status()['available']], [110])
        state = self.status(failed={110})
        self.assertEqual(state['available'], [])
        self.assertEqual(state['unknown'], 1)
        self.assertTrue(state['checked'])

    def test_full_or_closed_progress_pipe_does_not_abort_client(self):
        for error in (BlockingIOError(), BrokenPipeError()):
            with patch.object(check.os, 'write', side_effect=error), patch.object(check.sys, 'stdout'):
                check.emit_progress(1, 2)


class BridgeTests(unittest.TestCase):
    def module(self):
        module = Mock()
        module._read_oci_record.return_value = {'vmid': 110, 'installation_id': 'id-110', 'status': 'installed'}
        module._oci_secondary_member.return_value = False
        module.load_sidecar.return_value = {'apps': [{'id': 'native-app', 'installed_via': 'oci_image'},
                                                    {'id': 'other-app', 'installed_via': 'dpkg'}]}
        return module

    def test_only_native_oci_app_is_checked_without_unsolicited_notifications(self):
        module = self.module(); events = []
        bridge.check_applications(module, [{'vmid': 110, 'installation_id': 'id-110'}], events.append)
        module.check_app.assert_called_once_with(110, 'native-app', force=True, notify=False)
        self.assertEqual(events, [{'completed': 0, 'total': 1}, {'completed': 1, 'total': 1}, {'done': True, 'failed': []}])

    def test_replaced_guest_pending_operation_and_secondary_are_not_queried(self):
        for changes, secondary in (({'installation_id': 'replacement'}, False),
                                   ({'pending_transaction': {'operation': 'update'}}, False),
                                   ({'pending_stack_transaction': {'operation': 'update'}}, False),
                                   ({}, True)):
            module = self.module(); module._read_oci_record.return_value.update(changes)
            module._oci_secondary_member.return_value = secondary
            bridge.check_applications(module, [{'vmid': 110, 'installation_id': 'id-110'}], lambda _: None)
            module.check_app.assert_not_called()

    def test_dismissed_registration_is_not_reinvented(self):
        module = self.module(); module.load_sidecar.return_value = None
        bridge.check_applications(module, [{'vmid': 110, 'installation_id': 'id-110'}], lambda _: None)
        module.check_app.assert_not_called()

    def test_progress_advances_when_fast_app_finishes_before_first_slow_app(self):
        module = self.module(); release = threading.Event(); events = []
        module._read_oci_record.side_effect = lambda vmid: {
            'vmid': vmid, 'installation_id': f'id-{vmid}', 'status': 'installed'}
        def run(vmid, *args, **kwargs):
            if vmid == 110 and not release.wait(3):
                raise AssertionError('The fast app was blocked by the slow app')
        def report(event):
            events.append(event)
            if event.get('completed') == 1: release.set()
        module.check_app.side_effect = run
        bridge.check_applications(module, [{'vmid': 110, 'installation_id': 'id-110'},
                                          {'vmid': 111, 'installation_id': 'id-111'}], report)
        self.assertEqual(events, [{'completed': 0, 'total': 2}, {'completed': 1, 'total': 2},
                                  {'completed': 2, 'total': 2}, {'done': True, 'failed': []}])
        self.assertEqual(module.check_app.call_count, 2)

    def test_unexpected_failure_does_not_skip_other_apps_and_names_the_failed_app(self):
        module = self.module(); events = []
        module._read_oci_record.side_effect = lambda vmid: {
            'vmid': vmid, 'installation_id': f'id-{vmid}', 'status': 'installed'}
        module.check_app.side_effect = lambda vmid, *a, **kw: (_ for _ in ()).throw(RuntimeError()) if vmid == 110 else None
        bridge.check_applications(module, [{'vmid': 110, 'installation_id': 'id-110'},
                                          {'vmid': 111, 'installation_id': 'id-111'}], events.append)
        self.assertEqual(module.check_app.call_count, 2)
        self.assertEqual(events[-2], {'completed': 2, 'total': 2})
        self.assertEqual(events[-1], {'done': True, 'failed': [110]})

    def test_requests_cannot_specify_commands_images_paths_or_duplicate_guests(self):
        valid = {'vmid': 110, 'installation_id': 'id'}
        for request in ({'command': ['sh']}, {'applications': '110'}, {'applications': [valid, valid]},
                        {'applications': [{**valid, 'image': 'private:image'}]},
                        {'applications': [{**valid, 'vmid': '../110'}]},
                        {'applications': [{**valid, 'vmid': True}]}):
            with self.subTest(request=request), self.assertRaises(ValueError): bridge._applications(request)

    def test_client_disconnect_stops_before_next_application(self):
        module = self.module(); calls = []
        def report(event):
            calls.append(event)
            if event.get('completed') == 1: raise BrokenPipeError()
        with self.assertRaises(BrokenPipeError):
            bridge.check_applications(module, [{'vmid': 110, 'installation_id': 'id-110'},
                                               {'vmid': 111, 'installation_id': 'id-111'}], report)
        self.assertEqual(module.check_app.call_count, 1)

    def test_non_root_peers_are_rejected_before_reading_requests(self):
        handler = object.__new__(bridge._Handler); handler.request = Mock(); handler.rfile = Mock()
        with patch.object(bridge, '_root_peer', return_value=False): handler.handle()
        handler.rfile.readline.assert_not_called()

    def test_build_and_monitor_startup_include_bridge(self):
        scripts = ROOT.parent / 'AppImage/scripts'
        self.assertIn('oci_menu_bridge.py', (scripts / 'build_appimage.sh').read_text())
        self.assertIn('oci_menu_bridge.start(lxc_apps)', (scripts / 'flask_server.py').read_text())


if __name__ == '__main__':
    unittest.main()
