"""Actual registry/detection/checker consumers; PVE transports are isolated."""
import ast
import copy
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'AppImage/scripts'))
import managed_installs as managed


class StoppedRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / 'registry.json'
        self.now = datetime.datetime.utcnow().isoformat() + 'Z'
        self.checked = {'last_check': self.now, 'available': True, 'error': None,
                        '_count': 1, '_packages': [{'name': 'fixture-package', 'current': '1', 'latest': '2'}]}
        self.row = {'id': 'lxc:210', 'type': 'lxc', '_vmid': '210', 'name': 'fixture',
                    '_os_family': 'debian', 'update_check': copy.deepcopy(self.checked)}
        path.write_text(json.dumps({'items': [self.row]}))
        self.inventory = [{'vmid': '210', 'status': 'stopped', 'name': 'fixture'}]
        patches = [patch.object(managed, '_REGISTRY_PATH', str(path)),
                   patch.object(managed, '_DB_DIR', self.temp.name),
                   patch.object(managed, '_DETECTORS', [managed._detect_lxc_containers]),
                   patch.object(managed, '_lxc_updates_detection_enabled', return_value=True),
                   patch.object(managed, '_list_pve_lxcs', side_effect=lambda **_: self.inventory),
                   patch.object(managed, '_get_oci_managed_vmids', return_value={})]
        self.forbidden = {}
        for name in ['_probe_lxc_os', '_probe_lxc_is_oci', '_identify_helper_slug', '_run_pct_pkg_listing']:
            mock = Mock(side_effect=AssertionError('stopped guest probe forbidden'))
            self.forbidden[name] = mock
            patches.append(patch.object(managed, name, mock))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def assert_no_guest_probe(self):
        for mock in self.forbidden.values():
            mock.assert_not_called()

    def test_startup_detection_preserves_stopped_result_then_notification_check_skips_guest(self):
        managed.detect_and_register()
        self.assertEqual(managed.get_active_items()[0]['update_check'], self.checked)
        checker = Mock(side_effect=AssertionError('checker must not run on stopped guest'))
        with patch.object(managed, '_CHECKERS', {'lxc': checker}):
            self.assertEqual(managed.check_for_updates(force=True), [])
        checker.assert_not_called()
        self.assertEqual(managed.get_active_items()[0]['update_check'], self.checked)
        self.assert_no_guest_probe()

    def test_monitor_status_projection_survives_process_reinitialization(self):
        managed.detect_and_register()
        source = ast.parse((ROOT / 'AppImage/scripts/flask_server.py').read_text())
        function = next(n for n in source.body if isinstance(n, ast.FunctionDef)
                        and n.name == '_get_lxc_update_status_map')
        scope = {'os': os}
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'actual-status-map', 'exec'), scope)
        status = scope['_get_lxc_update_status_map']()['210']
        self.assertEqual(status['last_check'], self.now)
        self.assertEqual(status['count'], 1)
        self.assertTrue(status['available'])
        self.assert_no_guest_probe()

    def test_legacy_stopped_row_removed_by_startup_is_reactivated_without_new_observation(self):
        reg = managed._read_registry()
        reg['items'][0]['removed_at'] = self.now
        managed._write_registry(reg)
        managed.detect_and_register()
        active = managed.get_active_items()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]['update_check'], self.checked)
        self.assert_no_guest_probe()

    def test_genuinely_deleted_guest_and_disabled_detection_remain_removed(self):
        for disabled in [False, True]:
            managed._write_registry({'items': [copy.deepcopy(self.row)]})
            self.inventory = [] if not disabled else [{'vmid': '210', 'status': 'stopped', 'name': 'fixture'}]
            with patch.object(managed, '_lxc_updates_detection_enabled', return_value=not disabled):
                managed.detect_and_register()
            self.assertEqual(managed.get_active_items(), [])
        self.assert_no_guest_probe()

    def test_unknown_stopped_guest_does_not_get_a_fabricated_package_result(self):
        self.inventory.append({'vmid': '300', 'status': 'stopped', 'name': 'new'})
        managed.detect_and_register()
        self.assertEqual([x['id'] for x in managed.get_active_items()], ['lxc:210'])
        self.assert_no_guest_probe()

    def test_targeted_refresh_does_not_start_or_probe_stopped_guest(self):
        self.assertIsNone(managed.refresh_lxc(210, refresh_package_cache=False))
        self.assertEqual(managed.get_active_items()[0]['update_check'], self.checked)
        self.assert_no_guest_probe()

    def test_inventory_failure_preserves_known_row_without_checker_or_fresh_timestamp(self):
        with patch.object(managed, '_list_pve_lxcs', side_effect=RuntimeError('inventory unavailable')):
            managed.detect_and_register()
            managed.check_for_updates()
        self.assertEqual(managed.get_active_items()[0]['update_check'], self.checked)
        self.assert_no_guest_probe()

    def test_running_guest_uses_real_checker_and_refreshes_result(self):
        self.inventory[0]['status'] = 'running'
        checker = Mock(return_value={'available': False, 'last_check': self.now, '_count': 0})
        with patch.object(managed, '_CHECKERS', {'lxc': checker}):
            managed.check_for_updates()
        checker.assert_called_once()
        self.assertFalse(managed.get_active_items()[0]['update_check']['available'])

    def test_presence_merge_does_not_overwrite_a_newer_check_during_detection(self):
        fresh = {'entry': {**self.row, '_os_family': 'alpine'},
                 'result': {'available': True, 'last_check': self.now, '_count': 2}}
        def concurrent_check():
            self.assertTrue(managed.store_lxc_update_observation(210, fresh))
            return {}
        with patch.object(managed, '_get_oci_managed_vmids', side_effect=concurrent_check):
            managed.detect_and_register()
        row = managed.get_active_items()[0]
        self.assertEqual(row['update_check']['_count'], 2)
        self.assertEqual(row['_os_family'], 'alpine')
        self.assert_no_guest_probe()

    def test_targeted_observation_reactivates_removed_row_without_a_duplicate(self):
        registry = managed._read_registry()
        registry['items'][0]['removed_at'] = self.now
        managed._write_registry(registry)
        observation = {
            'entry': {**self.row, '_os_family': 'debian'},
            'result': {'available': True, 'last_check': self.now, '_count': 2},
        }

        self.assertTrue(managed.store_lxc_update_observation(210, observation))

        registry = managed.get_registry()
        rows = [row for row in registry['items'] if row['id'] == 'lxc:210']
        self.assertEqual(len(rows), 1)
        self.assertNotIn('removed_at', rows[0])
        self.assertEqual(rows[0]['update_check']['_count'], 2)
        self.assert_no_guest_probe()

    def test_retained_result_still_expires_at_existing_48_hour_boundary(self):
        managed.detect_and_register()
        current = managed.get_active_items()[0]['update_check']
        now = datetime.datetime.fromisoformat(self.now.rstrip('Z'))
        for seconds, expected in [(172799, False), (172800, True), (172801, True)]:
            instant = (now + datetime.timedelta(seconds=seconds)).replace(tzinfo=datetime.timezone.utc)
            class Clock(datetime.datetime):
                @classmethod
                def now(cls, tz=None):
                    return instant
            with patch.object(managed.datetime, 'datetime', Clock):
                self.assertEqual(managed.lxc_update_freshness(current)['stale'], expected)
        self.assert_no_guest_probe()


class InventoryContractTests(unittest.TestCase):
    def test_default_failure_contract_and_strict_detector_contract(self):
        result = subprocess.CompletedProcess([], 1, '', '')
        with patch.object(managed.subprocess, 'run', return_value=result):
            self.assertEqual(managed._list_pve_lxcs(), [])
            with self.assertRaises(RuntimeError):
                managed._list_pve_lxcs(strict=True)

    def test_timeout_and_malformed_rows_are_not_confirmed_removal(self):
        for failure in [subprocess.TimeoutExpired('pct', 5), FileNotFoundError(), OSError()]:
            with patch.object(managed.subprocess, 'run', side_effect=failure):
                self.assertEqual(managed._list_pve_lxcs(), [])
                with self.assertRaises(RuntimeError):
                    managed._list_pve_lxcs(strict=True)
        with patch.object(managed.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'VMID Status Lock Name\ninvalid-row\n', '')):
            with self.assertRaises(RuntimeError):
                managed._list_pve_lxcs(strict=True)

    def test_confirmed_empty_inventory_is_not_a_failed_read(self):
        for stdout in ['', '\n', 'VMID Status Lock Name\n']:
            with self.subTest(stdout=repr(stdout)), patch.object(
                managed.subprocess, 'run',
                return_value=subprocess.CompletedProcess([], 0, stdout, ''),
            ):
                self.assertEqual(managed._list_pve_lxcs(strict=True), [])


if __name__ == '__main__':
    unittest.main()
