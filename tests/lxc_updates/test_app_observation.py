"""Installed versions must survive a temporary CT's post-update shutdown."""
import copy
from datetime import datetime, timezone, timedelta
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'AppImage/scripts'))
import lxc_apps as apps
import lxc_update_observation as handoff


class InstalledObservationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.data = {'apps': [dict(id='docker', name='Docker', installed_via='binary',
            binary_path='/usr/bin/docker', state=dict(installed_version='29.8.1',
                latest_version='29.9.0', update_available=True, checked_at='2026-01-01T00:00:00Z')),
            dict(id='manual', installed_via='manual', installed_version='1.0',
                 state=dict(installed_version='1.0', latest_version='2.0', update_available=True))],
            'bulk_update': {'targets': ['os', 'app:manual']}, 'schedule': {'enabled': False}}
        self.write = Mock(return_value=True)
        self.probe = Mock(return_value=('29.9.0', None))
        for name, value in [('_read_sidecar', lambda _: copy.deepcopy(self.data)),
                            ('_write_sidecar', self.write),
                            ('detect_installed_version', self.probe)]:
            p = patch.object(apps, name, value)
            p.start()
            self.addCleanup(p.stop)

    def capture(self):
        return apps.capture_installed_observations(210)

    def test_new_docker_version_clears_old_pending_without_upstream_or_updater(self):
        with patch.object(apps, 'fetch_latest_upstream_details') as upstream:
            observations = self.capture()
            result = apps.store_installed_observations(210, observations)
        self.assertEqual(result['errors'], [])
        state = self.write.call_args.args[1]['apps'][0]['state']
        self.assertEqual(state['installed_version'], '29.9.0')
        self.assertFalse(state['update_available'])
        self.assertEqual(state['latest_version'], '29.9.0')
        self.assertEqual(self.probe.call_count, 1, 'manual versions cannot be auto-proven')
        upstream.assert_not_called()
        self.assertEqual(self.write.call_args.args[1]['bulk_update'], self.data['bulk_update'])
        self.assertEqual(self.write.call_args.args[1]['schedule'], self.data['schedule'])

    def test_capture_never_writes_shared_sidecar_and_skips_manual_docker_oci(self):
        self.data['apps'].extend([dict(id='oci', installed_via='oci_image'),
                                 dict(id='image', installed_via='docker')])
        self.assertEqual(len(self.capture()), 1)
        self.write.assert_not_called()
        self.assertEqual(self.probe.call_count, 1)

    def test_failed_probe_preserves_last_known_separately_and_does_not_claim_current(self):
        self.probe.return_value = (None, 'secret must never be copied to handoff')
        observations = self.capture()
        self.assertNotIn('secret', str(observations))
        result = apps.store_installed_observations(210, observations)
        self.assertTrue(result['errors'])
        state = self.write.call_args.args[1]['apps'][0]['state']
        self.assertEqual(state['last_known_installed_version'], '29.8.1')
        self.assertIsNone(state['installed_version'])
        self.assertIsNone(state['update_available'])
        self.assertTrue(state['error'])

    def test_config_edit_deletion_and_newer_check_cannot_be_overwritten(self):
        for kind in ('config', 'deleted', 'newer'):
            with self.subTest(kind=kind):
                observations = self.capture()
                original = copy.deepcopy(self.data)
                if kind == 'config': self.data['apps'][0]['binary_path'] = '/other/docker'
                if kind == 'deleted': self.data['apps'] = []
                if kind == 'newer': self.data['apps'][0]['state']['checked_at'] = '9999-01-01T00:00:00Z'
                result = apps.store_installed_observations(210, observations)
                self.assertTrue(result['errors'])
                self.write.assert_not_called()
                self.data = original

    def test_malformed_duplicate_future_and_expired_observations_never_write_or_probe(self):
        observation = self.capture()[0]
        for value in (None, {}, [{}], [observation, observation],
                      [{**observation, 'fingerprint': '../unsafe'}],
                      [{**observation, 'checked_at': '9999-01-01T00:00:00Z'}],
                      [{**observation, 'checked_at': '2000-01-01T00:00:00Z'}],
                      [{**observation, 'installed_version': ['29.9.0']}],
                      [{**observation, 'verified': 'yes'}]):
            with self.subTest(value=value):
                self.assertTrue(apps.store_installed_observations(210, value)['errors'])
                self.write.assert_not_called()
        self.assertEqual(self.probe.call_count, 1)

    def test_stale_boundary_has_margin_and_rejects_only_after_hour(self):
        observation = self.capture()[0]
        fixed = datetime(2026, 1, 2, tzinfo=timezone.utc)
        with patch.object(apps.time, 'time', return_value=fixed.timestamp()):
            for age in (3599, 3600, 3601):
                self.write.reset_mock()
                value = {**observation, 'checked_at': (fixed - timedelta(seconds=age)).isoformat()}
                result = apps.store_installed_observations(210, [value])
                self.assertEqual(bool(result['errors']), age > 3600)
                self.assertEqual(self.write.called, age <= 3600)

    def test_failed_persistence_is_an_error(self):
        self.write.return_value = False
        with self.assertRaises(OSError):
            apps.store_installed_observations(210, self.capture())

    def test_installed_probe_does_not_hide_upstream_error(self):
        self.data['apps'][0]['state']['error'] = 'upstream unavailable'
        apps.store_installed_observations(210, self.capture())
        self.assertEqual(self.write.call_args.args[1]['apps'][0]['state']['error'], 'upstream unavailable')


class CaptureScopeTests(unittest.TestCase):
    def test_check_only_and_oci_never_capture_app_probes(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(handoff, 'OBSERVATION_DIR', Path(directory) / 'observations'), \
             patch.object(handoff.managed_installs, '_detect_lxc_containers',
                          return_value=[{'_vmid': '210', '_is_oci': True}]), \
             patch.object(handoff.managed_installs, '_check_lxc_updates', return_value={}), \
             patch.object(apps, 'capture_installed_observations') as capture:
            handoff.capture(210, 'check-only')
            handoff.capture(210, 'oci', include_apps=True)
        capture.assert_not_called()

    def test_missing_guest_or_maintenance_preflight_never_capture_apps(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(handoff, 'OBSERVATION_DIR', Path(directory) / 'observations'), \
             patch.object(handoff.managed_installs, '_detect_lxc_containers', return_value=[]) as detect, \
             patch.object(handoff.managed_installs, '_probe_lxc_os', return_value='debian'), \
             patch.object(handoff.managed_installs, '_check_lxc_updates', return_value={}), \
             patch.object(handoff.subprocess, 'run', return_value=Mock(returncode=0)), \
             patch.object(apps, 'capture_installed_observations') as capture:
            handoff.capture(210, 'missing', include_apps=True)
            detect.return_value = [{'_vmid': '210'}]
            handoff.capture(210, 'maintenance', refresh_indexes=True, include_apps=True)
        capture.assert_not_called()


if __name__ == '__main__':
    unittest.main()
