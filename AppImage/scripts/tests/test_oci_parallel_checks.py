"""OCI registry waits run concurrently; shared app cache changes remain atomic."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lxc_apps

DIGEST = 'sha256:' + 'a' * 64
NEW = 'sha256:' + 'b' * 64


class ParallelOciChecksTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.records = {vmid: {'vmid': vmid, 'status': 'installed', 'installation_id': f'uuid-{vmid}'}
                        for vmid in range(110, 114)}
        for vmid in self.records:
            sidecar = {'vmid': vmid, 'schedule': {'enabled': False}, 'apps': [
                {'id': 'oci', 'installed_via': 'oci_image', 'name': 'App', 'state': {}},
                {'id': 'other', 'installed_via': 'manual', 'name': 'Other', 'state': {}}]}
            (self.root / f'{vmid}.json').write_text(json.dumps(sidecar))
        for item in (patch.object(lxc_apps, '_APPS_DIR', str(self.root)),
                     patch.object(lxc_apps, '_read_oci_record', side_effect=lambda vmid: copy.deepcopy(self.records.get(int(vmid))))):
            item.start(); self.addCleanup(item.stop)

    def result(self, vmid, **kwargs):
        return {'installed_digest': DIGEST, 'installed_registry_digest': DIGEST,
                'latest_digest': NEW, 'update_available': True, 'installed_version': '1',
                'latest_version': '2', 'image_reference': 'example/app:latest'}

    def test_four_native_checks_enter_registry_before_any_one_can_finish(self):
        rendezvous = threading.Barrier(4, timeout=3)
        def versions(vmid, **kwargs):
            rendezvous.wait()
            return self.result(vmid)
        with patch.object(lxc_apps, '_oci_image_versions', side_effect=versions) as query:
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda vmid: lxc_apps.check_app(vmid, 'oci', force=True, notify=False), self.records))
        self.assertEqual(query.call_count, 4)
        self.assertTrue(all(result['apps'][0]['state']['update_available'] for result in results))

    def during_query(self, edit):
        started, release, edited = threading.Event(), threading.Event(), threading.Event()
        def versions(vmid, **kwargs):
            started.set()
            if not release.wait(3): raise AssertionError('Registry wait did not end')
            return self.result(vmid)
        def change():
            with lxc_apps._cache_lock:
                sidecar = lxc_apps.load_sidecar(110)
                edit(sidecar)
                lxc_apps._write_sidecar(110, sidecar)
            edited.set()
        with patch.object(lxc_apps, '_oci_image_versions', side_effect=versions):
            with ThreadPoolExecutor(max_workers=2) as pool:
                future = pool.submit(lxc_apps.check_app, 110, 'oci', force=True, notify=False)
                try:
                    self.assertTrue(started.wait(2))
                    writer = pool.submit(change)
                    self.assertTrue(edited.wait(2), 'A registry call still holds the shared cache lock')
                finally:
                    release.set()
                future.result(); writer.result()
        return lxc_apps.load_sidecar(110)

    def test_unrelated_apps_and_schedule_edits_survive_registry_wait(self):
        def edit(sidecar):
            sidecar['schedule']['enabled'] = True
            sidecar['apps'][1]['name'] = 'Renamed while checking'
        result = self.during_query(edit)
        self.assertTrue(result['schedule']['enabled'])
        self.assertEqual(result['apps'][1]['name'], 'Renamed while checking')
        self.assertTrue(result['apps'][0]['state']['update_available'])

    def test_deleted_app_is_not_recreated_by_late_registry_answer(self):
        result = self.during_query(lambda sidecar: sidecar['apps'].pop(0))
        self.assertEqual([app['id'] for app in result['apps']], ['other'])

    def test_edited_app_is_not_overwritten_by_late_registry_answer(self):
        result = self.during_query(lambda sidecar: sidecar['apps'][0].update(name='Edited'))
        self.assertEqual(result['apps'][0]['name'], 'Edited')
        self.assertEqual(result['apps'][0]['state'], {})

    def test_replaced_installation_cannot_receive_previous_images_answer(self):
        def edit(sidecar): self.records[110]['installation_id'] = 'replacement'
        result = self.during_query(edit)
        self.assertEqual(result['apps'][0]['state'], {})

    def test_checks_for_two_apps_in_same_container_keep_both_results(self):
        sidecar = lxc_apps.load_sidecar(110)
        sidecar['apps'][1]['installed_via'] = 'oci_image'
        lxc_apps._write_sidecar(110, sidecar)
        rendezvous = threading.Barrier(2, timeout=3)
        def versions(vmid, **kwargs):
            rendezvous.wait()
            return self.result(vmid)
        with patch.object(lxc_apps, '_oci_image_versions', side_effect=versions):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(lxc_apps.check_app, 110, app, force=True, notify=False) for app in ('oci', 'other')]
                for future in futures: future.result()
        result = lxc_apps.load_sidecar(110)
        self.assertTrue(all(app['state']['update_available'] for app in result['apps']))

    def test_native_registry_failure_is_persisted_and_retried_without_blocking_others(self):
        def versions(vmid, **kwargs):
            return {'error': 'registry unreachable', 'registry_retry': True} if vmid == 110 else self.result(vmid)
        with patch.object(lxc_apps, '_oci_image_versions', side_effect=versions), \
                patch.object(lxc_apps, '_retry_oci_registry') as retry:
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda vmid: lxc_apps.check_app(vmid, 'oci', force=True, notify=False), self.records))
        self.assertEqual(results[0]['apps'][0]['state']['error'], 'registry unreachable')
        self.assertTrue(all(result['apps'][0]['state']['update_available'] for result in results[1:]))
        retry.assert_called_once_with(110, 'oci')


if __name__ == '__main__': unittest.main()
