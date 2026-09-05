"""PR integration regressions. No network, guests, sidecars or notifications."""
import copy
import hashlib
import json
import sys
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

from test_update_method_choice import apps, routes


ITEM = {'api_host': 'ghcr.io', 'repository': 'example/app',
        'reference': 'ghcr.io/example/app:latest', 'used_by': ['example'], 'standalone_containers': ['example'],
        'remote_digest': 'sha256:' + 'a' * 64,
        'installed_version': '1.0.0', 'update_available': True,
        'available_version_source': 'remote_metadata_pending',
        'installed_version_source': 'image_label:org.opencontainers.image.version',
        'platform': {'os': 'linux', 'architecture': 'amd64', 'variant': ''}}
LABELS = {'org.opencontainers.image.version': '2.0.0'}
APP = {'id': 'a1', 'name': 'Example', 'installed_via': 'docker_exec',
       'container_name': 'example', 'binary_path': '/app',
       'binary_args': ['--version'], 'installed_regex': r'(\d+\.\d+\.\d+)',
       'update_via': 'docker'}


class RegistryRegressions(unittest.TestCase):
    def setUp(self):
        apps._docker_remote_config_cache.clear()

    def test_container_reference_does_not_follow_unused_aliases(self):
        self.assertEqual(apps._docker_reference_identity('redis'), apps._docker_reference_identity('docker.io/library/redis:latest'))
        self.assertNotEqual(apps._docker_reference_identity('redis:7-alpine'), apps._docker_reference_identity('redis:7.2.4-alpine'))
        self.assertIsNone(apps._docker_reference_identity('redis@sha256:' + 'a' * 64))
        self.assertIsNone(apps._docker_reference_identity('sha256:' + 'a' * 64))

    def test_inventory_tracks_running_image_and_ignores_unused_alias_tag(self):
        repo = 'ghcr.io/demo/app'
        old_id, new_id = 'sha256:' + '1'*64, 'sha256:' + '2'*64
        old_digest, new_digest = 'sha256:' + 'a'*64, 'sha256:' + 'b'*64
        container = {'Name': '/example', 'Image': old_id, 'Config': {'Image': repo + ':latest', 'Labels': {}}}
        image = lambda image_id, digest, version: {'Id': image_id, 'RepoDigests': [repo+'@'+digest],
            'Config': {'Labels': {'org.opencontainers.image.version': version}}, 'Os': 'linux', 'Architecture': 'amd64'}
        for pulled in (False, True):
            def execute(vmid, argv, **kwargs):
                if argv[:2] == ['docker', 'version']:
                    return 0, '26.1.5', ''
                if argv[:2] == ['docker', 'ps']:
                    return 0, f'example\t{repo}:latest\tUp 1 minute', ''
                if argv[:2] == ['docker', 'inspect']:
                    return 0, json.dumps(container), ''
                if argv[:3] == ['docker', 'image', 'ls']:
                    return 0, '\n'.join([
                        f'{repo}\tlatest\t{new_digest if pulled else old_digest}\t{new_id if pulled else old_id}',
                        f'{repo}\t1.0.0\t{old_digest}\t{old_id}',
                    ]), ''
                if argv[:3] == ['docker', 'image', 'inspect']:
                    return 0, '\n'.join(json.dumps(item) for item in [image(old_id, old_digest, '1.0.0'), image(new_id, new_digest, '2.0.0')]), ''
                raise AssertionError(argv)
            with patch.object(apps, '_pct_exec', side_effect=execute), \
                 patch.object(apps, '_docker_service_catalog_meta', return_value={}), \
                 patch.object(apps, '_fetch_registry_manifest_digest', return_value=(new_digest, None)):
                inventory = apps._docker_inventory_from_ct(101)
            self.assertEqual(len(inventory['images']), 1, 'unused alias is not a workload')
            actual = inventory['images'][0]
            self.assertEqual(actual['reference'], repo+':latest')
            self.assertEqual(actual['installed_version'], '1.0.0', 'a pull alone does not update a container')
            self.assertEqual(actual['image_id'], old_id)
            self.assertEqual(actual['local_digest'], old_digest)
            self.assertTrue(actual['update_available'])

    def test_transient_error_does_not_poison_retry(self):
        with patch.object(apps, '_remote_image_config_labels', side_effect=[(None, 'timeout'), (LABELS, None)]) as read:
            self.assertEqual(apps._docker_available_version_from_registry(ITEM)[1], 'remote_fetch_error')
            self.assertEqual(apps._docker_available_version_from_registry(ITEM)[0], '2.0.0')
            self.assertEqual(apps._docker_available_version_from_registry(ITEM)[0], '2.0.0')
            self.assertEqual(read.call_count, 2)

    def test_cache_key_includes_os_and_variant(self):
        with patch.object(apps, '_remote_image_config_labels', side_effect=[({'Version': str(i)}, None) for i in range(3)]) as read:
            for i, platform in enumerate([
                {'os': 'linux', 'architecture': 'arm', 'variant': 'v7'},
                {'os': 'linux', 'architecture': 'arm', 'variant': 'v6'},
                {'os': 'other', 'architecture': 'arm', 'variant': 'v6'},
            ]):
                self.assertEqual(apps._fetch_remote_image_config_labels(ITEM, ITEM['remote_digest'], platform)[0], {'Version': str(i)})
            self.assertEqual(read.call_count, 3)

    def test_concurrent_identical_images_only_fetch_once(self):
        import concurrent.futures
        def read(*_):
            time.sleep(.02)
            return LABELS, None
        with patch.object(apps, '_remote_image_config_labels', side_effect=read) as fetch:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(apps._docker_available_version_from_registry, [ITEM] * 4))
            self.assertEqual(fetch.call_count, 1)
            self.assertTrue(all(result[0] == '2.0.0' for result in results))

    def test_valid_digest_with_non_object_document_is_rejected(self):
        for payload in ([], None, 'text', 42):
            body = json.dumps(payload).encode()
            digest = 'sha256:' + hashlib.sha256(body).hexdigest()
            with patch.object(apps, '_registry_request', return_value=({}, body, None, None)):
                document, _, error = apps._registry_get_document('https://example.test', digest, {}, None)
            self.assertIsNone(document)
            self.assertIn('not an object', error)

    def test_malformed_nested_configs_do_not_escape(self):
        for payload in ({'config': []}, {'config': {'Labels': ['bad']}}, {'config': {'Labels': {'version': {}}}}):
            body = json.dumps(payload).encode()
            digest = 'sha256:' + hashlib.sha256(body).hexdigest()
            manifest = {'config': {'mediaType': 'application/vnd.oci.image.config.v1+json', 'digest': digest}}
            with patch.object(apps, '_registry_get_document', return_value=(manifest, None, None)), \
                 patch.object(apps, '_registry_request', return_value=({}, body, None, None)):
                labels, error = apps._remote_image_config_labels(ITEM, ITEM['remote_digest'], ITEM['platform'])
            self.assertIsNone(labels)
            self.assertTrue(error)

    def test_redirect_authentication_failure_is_not_success(self):
        with patch.object(apps, '_registry_open', side_effect=[
            ({}, None, 307, 'https://cdn.example.test/blob', None),
            ({}, None, 401, None, None),
        ]) as request:
            self.assertEqual(apps._registry_request('https://registry.example.test', {}, token='secret')[3], 'registry HTTP 401')
            self.assertNotIn('Authorization', request.call_args.args[1])

    def test_no_network_on_cached_inventory_reads(self):
        with patch.object(apps, '_docker_inventory_cache', {'101': {'available': True, 'checked_at_unix': time.time(), 'images': [ITEM]}}), \
             patch.object(apps, '_remote_image_config_labels', side_effect=AssertionError('network')), \
             patch.object(apps, '_docker_inventory_from_ct', side_effect=AssertionError('scan')):
            self.assertEqual(len(apps.get_docker_inventory(101)['images']), 1)
            self.assertEqual(len(apps.get_cached_docker_inventories()['101']['images']), 1)

    def test_optional_metadata_does_not_block_or_overwrite_a_new_boot(self):
        started, release = threading.Event(), threading.Event()
        futures = []
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            def submit(*args):
                future = pool.submit(*args)
                futures.append(future)
                return future
            def resolve(_):
                started.set()
                self.assertTrue(release.wait(2))
                return '2.0.0', 'remote_image_label:version'
            snapshot = {'available': True, 'images': [dict(ITEM)]}
            new_boot = {'available': False, 'refreshing': True, 'images': []}
            with patch.object(apps, '_docker_inventory_cache', {'101': snapshot}), \
                 patch.object(apps, '_docker_metadata_pool', types.SimpleNamespace(submit=submit)), \
                 patch.object(apps, '_docker_available_version_from_registry', side_effect=resolve):
                try:
                    apps._queue_docker_metadata('101', snapshot)
                    self.assertTrue(started.wait(1))
                    self.assertIs(apps._docker_inventory_cache['101'], snapshot)
                    apps._docker_inventory_cache['101'] = new_boot
                finally:
                    release.set()
                for future in futures:
                    future.result(2)
                self.assertIs(apps._docker_inventory_cache['101'], new_boot)
                self.assertNotIn('available_version', snapshot['images'][0])

    def test_failed_image_does_not_prevent_other_image_metadata(self):
        import concurrent.futures
        futures = []
        snapshot = {'available': True, 'checked_at': 'original-scan', 'images': [dict(ITEM), dict(ITEM)]}
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            def submit(*args):
                future = pool.submit(*args)
                futures.append(future)
                return future
            with patch.object(apps, '_docker_inventory_cache', {'101': snapshot}), \
                 patch.object(apps, '_docker_metadata_pool', types.SimpleNamespace(submit=submit)), \
                 patch.object(apps, '_docker_available_version_from_registry', side_effect=[ValueError('bad image'), ('2.0.0', 'remote_image_label:version')]):
                apps._queue_docker_metadata('101', snapshot)
                for future in futures:
                    future.result(2)
                self.assertEqual(snapshot['images'][0]['available_version_source'], 'remote_fetch_error')
                self.assertEqual(snapshot['images'][1]['available_version'], '2.0.0')
                self.assertTrue(snapshot['images'][0]['update_available'])
                self.assertEqual(snapshot['checked_at'], 'original-scan')


class DelegationRegressions(unittest.TestCase):
    def test_delegated_label_reads_actual_image_not_preserved_container_label(self):
        image_id = 'sha256:' + 'a' * 64
        config = {**APP, 'installed_via': 'docker_label', 'label': 'org.opencontainers.image.version'}
        with patch.object(apps, '_pct_exec', side_effect=[(0, image_id, ''), (0, '2.0.0', '')]) as execute:
            self.assertEqual(apps.detect_installed_version(101, config), ('2.0.0', None))
        self.assertEqual(execute.call_args.args[1][:3], ['docker', 'image', 'inspect'])
        self.assertEqual(execute.call_args.args[1][-1], image_id)
        with patch.object(apps, '_pct_exec', return_value=(0, '1.0.0', '')) as execute:
            self.assertEqual(apps.detect_installed_version(101, {**config, 'update_via': ''}), ('1.0.0', None))
        self.assertEqual(execute.call_count, 1, 'existing non-delegated detector semantics remain unchanged')

    def inventory(self):
        return {'available': True, 'images': [dict(ITEM), {'reference': 'other:latest', 'used_by': ['other']}],
                'update_units': [
                    {'id': 'docker-unit:aaaaaaaaaaaaaaaaaaaa', 'kind': 'standalone', 'references': [ITEM['reference']],
                     'standalone_containers': ['example']},
                    {'id': 'docker-unit:bbbbbbbbbbbbbbbbbbbb', 'kind': 'standalone', 'references': ['other:latest'],
                     'standalone_containers': ['other']}]}

    def test_missing_inventory_clears_old_decoration(self):
        records = [{**APP, 'docker_available_version': '2.0.0', 'docker_update_available': True}]
        apps.annotate_delegated_apps(records, None)
        self.assertIsNone(records[0]['docker_available_version'])
        self.assertIsNone(records[0]['docker_update_available'])
        self.assertEqual(records[0]['docker_binding_error'], 'inventory_unavailable')

    def test_delegated_and_custom_or_helper_cannot_both_be_selected(self):
        for extra in ({'update_command': '/opt/update.sh'}, {'update_method': 'helper', 'helper_slug': 'vaultwarden'}):
            self.assertFalse(apps.validate_config({**APP, **extra})[0])
        self.assertTrue(apps.validate_config({**APP, 'update_via': '', 'update_command': '/opt/update.sh'})[0])

    def test_only_followed_workloads_are_offered(self):
        inventory = self.inventory()
        scoped = apps.docker_inventory_for_apps([APP], inventory)
        self.assertEqual([image['reference'] for image in scoped['images']], [ITEM['reference']])
        self.assertEqual([unit['id'] for unit in scoped['update_units']], ['docker-unit:aaaaaaaaaaaaaaaaaaaa'])
        self.assertEqual(len(inventory['images']), 2)

    def test_notifications_without_engine_registration_honor_opt_out_and_dedup(self):
        manager = Mock()
        inventory = self.inventory()
        records = [dict(APP), {**APP, 'id': 'a2'}]
        with patch.object(apps, 'get_cached_docker_inventories', return_value={'101': inventory}), \
             patch.object(apps, '_read_sidecar', return_value={'apps': records}), \
             patch.dict(sys.modules, {'notification_manager': types.SimpleNamespace(notification_manager=manager)}):
            self.assertEqual(apps.emit_all_pending_docker_stacks(), 1)
            first = manager.emit_event.call_args.kwargs
            self.assertEqual(first['data']['count'], 1)
            inventory['images'][0]['available_version'] = '2.0.0'
            self.assertEqual(apps.emit_all_pending_docker_stacks(), 1)
            self.assertEqual(first['entity_id'], manager.emit_event.call_args.kwargs['entity_id'])
            for record in records:
                record['notifications_enabled'] = False
            self.assertEqual(apps.emit_all_pending_docker_stacks(), 0)

    def test_bulk_allows_followed_image_but_not_engine_or_other_image(self):
        api = routes()
        with patch.object(apps, 'load_sidecar', return_value={'apps': [APP]}), \
             patch.object(apps, '_read_sidecar', return_value={'apps': [APP]}), \
             patch.object(apps, 'get_docker_inventory', return_value=self.inventory()):
            plan = api['_resolve_bulk_update_plan'](101, ['os', 'docker-unit:aaaaaaaaaaaaaaaaaaaa'])
            self.assertTrue(plan['ok'], plan)
            self.assertFalse(plan['unavailable'], plan)
            self.assertIn('example', plan['docker_standalone_targets'])
            plan = api['_resolve_bulk_update_plan'](101, ['os', 'docker-unit:bbbbbbbbbbbbbbbbbbbb', 'docker-engine'])
            self.assertEqual(len(plan['unavailable']), 2, plan)

    def test_schedule_runs_only_selected_followed_container(self):
        api = routes()
        with patch.object(apps, '_read_sidecar', return_value={'apps': [APP]}), \
             patch.object(apps, 'load_sidecar', return_value={'apps': [APP]}), \
             patch.object(apps, 'get_docker_inventory', return_value=self.inventory()):
            result = api['_run_scheduled_update'](101, {'targets': ['docker-container:example', 'docker-container:other', 'docker-engine']})
        self.assertEqual(result['status'], 'partial', result)
        self.assertEqual(result['executed_targets'], ['docker-container:example'])
        env = api['subprocess'].run.call_args.kwargs['env']
        self.assertEqual(env['DOCKER_STANDALONE_TARGETS'], 'example')
        self.assertEqual(env['UPDATE_DOCKER_ENGINE'], '0')
        self.assertEqual(env['RUN_HELPER'], '0')


if __name__ == '__main__':
    unittest.main()
