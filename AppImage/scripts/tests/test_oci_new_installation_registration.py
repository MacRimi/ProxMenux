"""An application installed from the OCI menu is registered by the Monitor
without opening its container: the list of guests looks at the records of the
installer and registers the ones written since its last look."""
import json
import sys
import tempfile
import threading
import time
from pathlib import Path
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import lxc_apps


class NewInstallationRegistrationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'catalog').mkdir()
        (self.root / 'catalog/index.json').write_text(json.dumps({'applications': []}))
        (self.root / 'instances').mkdir()
        patches = [patch.object(lxc_apps, '_OCI_INSTANCE_ROOT', str(self.root / 'instances')),
                   patch.object(lxc_apps, '_OCI_CATALOG_INDEX', str(self.root / 'catalog/index.json')),
                   patch.object(lxc_apps, '_oci_catalog_cache', None),
                   patch.object(lxc_apps, '_APPS_DIR', str(self.root / 'apps')),
                   patch.object(lxc_apps, '_OCI_DISMISSED_FILE', str(self.root / 'apps/.oci-dismissed.json')),
                   patch.object(lxc_apps, '_oci_records_seen', {})]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.moment = time.time_ns()

    def record(self, vmid, status='installed'):
        folder = self.root / f'instances/{vmid}'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / 'oci-compose.json'
        path.write_text(json.dumps({
            'vmid': vmid, 'status': status, 'installation_id': f'install-{vmid}',
            'template': {'id': 'image-duplicati-official', 'catalog_ui': {'title': 'Duplicati Official'},
                         'first_run': {'endpoints': [{'port': 8200, 'scheme': 'http', 'path': '/'}]},
                         'container_contract': {'image': {'reference': 'duplicati/duplicati:latest'},
                                                'ports': [{'container_port': 8200}]}}}))
        # Every write of a record leaves a later time on it.
        self.moment += 1_000_000_000
        import os
        os.utime(path, ns=(self.moment, self.moment))

    def sidecar(self, vmid):
        folder = self.root / 'apps'
        folder.mkdir(exist_ok=True)
        (folder / f'{vmid}.json').write_text(json.dumps(
            {'apps': [{'id': 'a', 'name': 'Duplicati Official', 'installed_via': 'oci_image', 'logo_url': 'x'}]}))

    def test_a_new_installation_is_registered_without_opening_its_container(self):
        self.record(125)
        with patch.object(lxc_apps, 'add_app', return_value=(True, {})) as add:
            self.assertEqual(lxc_apps.register_new_oci_installations(wait=True), [125])
        self.assertEqual(add.call_args.args[0], 125)
        self.assertEqual(add.call_args.args[1]['name'], 'Duplicati Official')
        self.assertEqual(add.call_args.args[1]['installed_via'], 'oci_image')

    def test_a_record_is_looked_at_once_until_it_is_written_again(self):
        self.record(125)
        with patch.object(lxc_apps, 'ensure_oci_registration') as ensure:
            self.assertEqual(lxc_apps.register_new_oci_installations(wait=True), [125])
            self.assertEqual(lxc_apps.register_new_oci_installations(wait=True), [])
            self.assertEqual(lxc_apps.register_new_oci_installations(wait=True), [])
            self.record(126)
            self.assertEqual(lxc_apps.register_new_oci_installations(wait=True), [126])
            self.record(125)
            self.assertEqual(lxc_apps.register_new_oci_installations(wait=True), [125])
        self.assertEqual([call.args[0] for call in ensure.call_args_list], [125, 126, 125])

    def test_an_installation_is_registered_when_it_ends(self):
        self.record(125, status='installing')
        with patch.object(lxc_apps, 'add_app', return_value=(True, {})) as add:
            lxc_apps.register_new_oci_installations(wait=True)
            add.assert_not_called()
            self.record(125)
            lxc_apps.register_new_oci_installations(wait=True)
        add.assert_called_once()

    def test_the_request_that_notices_it_does_not_wait_for_the_registration(self):
        self.record(125)
        started, release = threading.Event(), threading.Event()

        def slow(vmid):
            started.set()
            release.wait(5)

        with patch.object(lxc_apps, 'ensure_oci_registration', side_effect=slow):
            self.assertEqual(lxc_apps.register_new_oci_installations(), [125])
            self.assertTrue(started.wait(5))
            # Still registering: a second look starts nothing more.
            self.assertEqual(lxc_apps.register_new_oci_installations(), [])
            release.set()

    def test_two_requests_for_the_same_container_register_it_once(self):
        self.record(125)
        calls = []

        def add(vmid, payload, notify=True):
            calls.append(vmid)
            time.sleep(0.2)
            self.sidecar(vmid)
            return True, {}

        with patch.object(lxc_apps, 'add_app', side_effect=add):
            threads = [threading.Thread(target=lxc_apps.ensure_oci_registration, args=(125,)) for _ in range(3)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(calls, [125])

    def test_no_records_and_no_folder_are_not_an_error(self):
        self.assertEqual(lxc_apps.register_new_oci_installations(wait=True), [])
        with patch.object(lxc_apps, '_OCI_INSTANCE_ROOT', str(self.root / 'missing')):
            self.assertEqual(lxc_apps.register_new_oci_installations(wait=True), [])

    def test_the_list_of_guests_looks_for_new_installations(self):
        source = (SCRIPTS / 'flask_server.py').read_text()
        body = source.split('def _get_lxc_app_watch_map() -> dict:', 1)[1].split('\ndef ', 1)[0]
        self.assertLess(body.index('lxc_apps.register_new_oci_installations()'), body.index('lxc_apps.get_active_apps()'))


if __name__ == '__main__':
    unittest.main()
