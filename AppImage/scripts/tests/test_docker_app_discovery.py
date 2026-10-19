"""Docker Find contracts; no real guests, registry, auth or app writes."""
import ast
import copy
from functools import wraps
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import docker_app_discovery as docker
import native_app_discovery as native
import lxc_apps

ONE, TWO = 'a' * 64, 'b' * 64


def record(**values):
    return {'id': ONE, 'name': '/cortendesk-v1-11-0-cortendesk-1',
            'image': 'cortendesk-v1-11-0-cortendesk', 'running': True,
            'project': 'cortendesk-v1-11-0', 'service': 'cortendesk',
            'title': None, 'version': None,
            'bindings': {'8080/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '8080'}]},
            'ports': None, **values}


class Scan(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / '101.conf').write_text('ostype: debian\n')
        self.patches = [patch.object(native, 'LOCAL_CONFIG', root),
                        patch.object(native, 'OCI_ROOT', root / 'oci'),
                        patch.object(native, 'UPDATE_LOCK_ROOT', root)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.calls = []

    def runner(self, records=None, ids=None, inspect_rc=0, docker_present=True):
        def execute(argv, deadline):
            self.calls.append(argv)
            self.assertEqual(argv[:4], ['pct', 'exec', '101', '--'])
            if argv[4] == 'sh':
                self.assertEqual(argv[5:], ['-c', 'command -v docker >/dev/null 2>&1'])
                return (0 if docker_present else 1), ''
            if argv[4:6] == ['docker', 'ps']:
                return 0, '\n'.join(ids if ids is not None else [ONE])
            self.assertEqual(argv[4:8], ['docker', 'inspect', '--format', docker.INSPECT_FORMAT])
            return inspect_rc, '\n'.join(json.dumps(r) if not isinstance(r, str) else r
                                         for r in (records if records is not None else [record()]))
        return execute

    def scan(self, **kwargs):
        return docker.scan(101, run=self.runner(**kwargs), guard_run=lambda argv, deadline: 'status: running')

    def test_cortendesk_and_unrelated_compose_use_the_same_generic_contract(self):
        for app in [record(), record(name='/notes-1', image='example/notes:3', project='notes', service='web')]:
            result = self.scan(records=[app])
            self.assertEqual(result['status'], 'complete')
            item, = result['candidates']
            self.assertEqual(item['source'], 'docker_metadata')
            self.assertEqual(item['default_ports'], [8080])
            self.assertIsNone(item['installed_version'], 'no version guessed from image/project/tag')
            self.assertIsNone(item['tracking_suggestion'])
            self.assertTrue(item['discovery_id'].startswith('docker-'))
            self.assertNotIn('repo', item)
        self.assertNotIn('.Env', docker.INSPECT_FORMAT)
        self.assertNotIn('json .}}', docker.INSPECT_FORMAT, 'no whole inspect object')
        self.assertTrue(all(c[4] == 'sh' or c[4:6] in (['docker', 'ps'], ['docker', 'inspect']) for c in self.calls))

    def test_known_version_is_display_metadata_and_never_an_updater(self):
        item, = self.scan(records=[record(version='1.11.0')])['candidates']
        self.assertEqual(item['installed_version'], '1.11.0')
        self.assertIsNone(item['tracking_suggestion'])

    def test_database_stopped_and_no_published_ports_are_excluded(self):
        for app in [record(image='mysql:8.4', service='db'), record(running=False),
                    record(bindings={}), record(image='redis:7', service='cache')]:
            self.assertEqual(self.scan(records=[app])['candidates'], [])

    def test_all_loopback_bindings_excluded_and_live_mapping_preferred(self):
        for address in ['127.0.0.1', '127.0.0.2', '127.255.255.254', '::1', '::ffff:127.0.0.2']:
            value = record(bindings={'8080/tcp': [{'HostIp': address, 'HostPort': '8080'}]})
            self.assertEqual(self.scan(records=[value])['candidates'], [], address)
        value = record(ports={'8080/tcp': [{'HostIp': '::', 'HostPort': '9090'}]})
        self.assertEqual(self.scan(records=[value])['candidates'][0]['default_ports'], [9090])

    def test_service_tcp_ports_are_evidence_not_prefilled_web_addresses(self):
        app = record(bindings={'21115/tcp':[{'HostIp':'0.0.0.0','HostPort':'21115'}],
                               '8080/tcp':[{'HostIp':'0.0.0.0','HostPort':'8080'}]})
        item, = self.scan(records=[app])['candidates']
        self.assertEqual(item['default_ports'],[8080])
        self.assertIn({'kind':'tcp_listener','value':'21115'},item['evidence'])

    def test_unassigned_or_ranged_host_ports_are_skipped_not_invalid(self):
        app = record(running=False, bindings={'8080/tcp': [{'HostIp': '', 'HostPort': ''}],
                                              '9000/tcp': [{'HostIp': '', 'HostPort': '9000-9010'}],
                                              '443/tcp': [{'HostIp': '', 'HostPort': '8444'}]})
        result = self.scan(records=[app])
        self.assertEqual(result['status'], 'complete')
        endpoints = result['_containers'][0]['endpoints']
        self.assertEqual([e['host_port'] for e in endpoints], [8444])

    def test_https_container_port_prefills_its_scheme(self):
        app = record(bindings={'443/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '8444'}]})
        item, = self.scan(records=[app])['candidates']
        self.assertEqual(item['default_ports'], [8444])
        self.assertEqual([(d['port'], d['scheme']) for d in item['port_details']], [(8444, 'https')])

    def test_empty_engine_is_complete_and_missing_docker_never_calls_docker(self):
        self.assertEqual(self.scan(ids=[])['status'], 'complete')
        self.calls.clear()
        result = self.scan(docker_present=False)
        self.assertEqual(result['candidates'], [])
        self.assertEqual(len(self.calls), 1)

    def test_nonzero_inspect_retains_valid_stdout_and_marks_partial(self):
        result = self.scan(ids=[ONE, TWO], inspect_rc=1)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(result['candidates']), 1)
        self.assertIn('inspect_failed', result['issues'])
        self.assertIn('incomplete_inspect', result['issues'])

    def test_invalid_and_duplicate_records_are_partial_without_crashing(self):
        for bad in ['{broken', [], record(id=TWO), record(bindings=[]), record(running='false')]:
            result = self.scan(records=[record(), bad])
            self.assertEqual(result['status'], 'partial')
            self.assertEqual(len(result['candidates']), 1)

    def test_record_limit_is_visible_and_inspect_is_bounded(self):
        ids = [f'{i:064x}' for i in range(51)]
        result = self.scan(ids=ids, records=[record(id=ids[0])])
        self.assertIn('container_limit', result['issues'])
        self.assertEqual(len(self.calls[-1][8:]), docker.MAX_CONTAINERS)

    def test_stopped_missing_locked_and_oci_guests_have_zero_guest_probes(self):
        root = Path(self.temp.name)
        cases = [('', 'status: stopped', 'guest_stopped'),
                 ('lock: backup\nostype: debian\n', 'status: running', 'guest_busy')]
        for config, status, error in cases:
            (root / '101.conf').write_text(config or 'ostype: debian\n')
            with self.assertRaisesRegex(native.ProbeError, error):
                docker.scan(101, run=self.runner(), guard_run=lambda a, d: status)
        (root/'101.conf').unlink()
        with self.assertRaisesRegex(native.ProbeError, 'not_local_lxc'):
            self.scan()
        (root/'101.conf').write_text('ostype: unmanaged\n')
        (root/'oci'/'101').mkdir(parents=True)
        with self.assertRaisesRegex(native.ProbeError, 'managed_oci'):
            self.scan()
        self.assertEqual(self.calls, [])

    def test_guest_stopping_during_scan_never_publishes_results(self):
        states = iter(['status: running', 'status: stopped'])
        with self.assertRaisesRegex(native.ProbeError, 'guest_stopped'):
            docker.scan(101, run=self.runner(), guard_run=lambda a,d: next(states))


class Cache(unittest.TestCase):
    def setUp(self):
        docker._cache.clear(); docker._generations.clear(); docker._locks.clear()
        self.addCleanup(docker._cache.clear)
        self.addCleanup(docker._generations.clear)
        self.value = {'vmid': 101, 'status': 'complete', 'stale': False, 'issues': [],
                      'scanned_at': 1000, '_containers': [docker.parse_record(record())],
                      'candidates': [docker._candidate(101, docker.parse_record(record()))]}

    def test_get_never_scans_and_freshness_boundary_has_no_mutation(self):
        with patch.object(docker, 'scan', return_value=self.value) as scan, patch.object(docker.time, 'time', return_value=1000):
            self.assertEqual(docker.cached(101)['status'], 'not_scanned')
            scan.assert_not_called()
            docker.discover(101)
        for clock, stale in [(1299.999, False), (1300, True), (1300.001, True)]:
            with patch.object(docker.time, 'time', return_value=clock):
                self.assertEqual(docker.cached(101)['stale'], stale)
        self.assertFalse(docker._cache[101]['stale'])

    def test_failure_partial_and_lifecycle_preserve_previous_without_new_probes(self):
        with patch.object(docker, 'scan', return_value=self.value): docker.discover(101)
        with patch.object(docker, 'scan', side_effect=native.ProbeError('timeout')):
            failed = docker.discover(101)
        self.assertEqual(failed['status'], 'error'); self.assertTrue(failed['stale'])
        self.assertEqual(failed['candidates'], self.value['candidates'])
        with patch.object(docker, 'scan') as scan:
            docker.mark_stale(101)
            self.assertTrue(docker.cached(101)['stale'])
            scan.assert_not_called()

    def test_inflight_lifecycle_rejects_late_result_and_busy_has_no_second_scan(self):
        with patch.object(docker, 'scan', side_effect=lambda v: (docker.mark_stale(v), self.value)[1]):
            self.assertEqual(docker.discover(101)['issues'], ['guest_changed'])
        self.assertEqual(docker.cached(101)['status'], 'not_scanned')
        lock = docker._locks[101]; lock.acquire()
        try:
            with patch.object(docker, 'scan') as scan:
                self.assertEqual(docker.discover(101)['status'], 'busy'); scan.assert_not_called()
        finally: lock.release()

    def test_shared_web_links_avoid_duplicate_inspect_and_stop_at_snapshot_boundary(self):
        lookup = Mock(return_value={'slug': None, 'name': 'web', 'logo_url': None})
        with patch.object(docker, 'scan', return_value=self.value), patch.object(docker.time, 'time', return_value=1000):
            docker.discover(101)
        for clock, valid in [(1059.999, True), (1060, False), (1060.001, False)]:
            with patch.object(docker.time, 'time', return_value=clock), patch.object(lxc_apps, '_pct_exec') as execute:
                result = docker.cached_web_links(101, lookup)
                self.assertEqual(result is not None, valid); execute.assert_not_called()
        with patch.object(docker.time, 'time', return_value=1001), patch.object(lxc_apps, '_pct_exec') as execute:
            with patch.object(lxc_apps, '_docker_service_catalog_meta', lookup):
                self.assertEqual(lxc_apps._probe_docker_web_links(101)[0]['host_port'], 8080)
            execute.assert_not_called()

    def test_incomplete_search_never_replaces_the_web_link_probe(self):
        lookup = Mock(return_value={'slug': None, 'name': 'web', 'logo_url': None})
        partial = {**copy.deepcopy(self.value), 'status': 'partial', 'issues': ['inspect_failed']}
        with patch.object(docker, 'scan', return_value=partial), patch.object(docker.time, 'time', return_value=1000):
            docker.discover(101)
        with patch.object(docker.time, 'time', return_value=1001):
            self.assertIsNone(docker.cached_web_links(101, lookup))
        docker._cache.clear()
        with patch.object(docker, 'scan', side_effect=native.ProbeError('timeout')), \
                patch.object(docker.time, 'time', return_value=1000):
            docker.discover(101)
        with patch.object(docker.time, 'time', return_value=1001):
            self.assertIsNone(docker.cached_web_links(101, lookup))

    def test_shared_links_keep_existing_name_then_port_order(self):
        value = copy.deepcopy(self.value)
        value['_containers'][0]['name'] = 'z-last'
        second = copy.deepcopy(value['_containers'][0]); second['name'] = 'a-first'
        second['endpoints'] = [{'host_port':9090,'container_port':8080,'scheme':'http'},
                               {'host_port':8080,'container_port':8080,'scheme':'http'}]
        value['_containers'].append(second)
        lookup = lambda service,name,image: {'slug':None,'name':name,'logo_url':None}
        with patch.object(docker,'scan',return_value=value): docker.discover(101)
        links = docker.cached_web_links(101,lookup)
        self.assertEqual([(x['service_name'],x['host_port']) for x in links],
                         [('a-first',8080),('a-first',9090),('z-last',8080)])

    def test_registered_container_image_app_or_existing_port_is_not_duplicated(self):
        item = self.value['candidates'][0]
        for app in [{'discovery_id': item['discovery_id']}, {'container_name': item['container_name']},
                    {'ports': [{'port': 8080}]}]:
            self.assertEqual(docker.filter_candidates(self.value, {}, [app])['candidates'], [])
        self.assertEqual(docker.filter_candidates(self.value, {'docker_workloads': [{'container_name': item['container_name']}]}, [])['candidates'], [])

    def test_same_display_name_is_not_container_identity(self):
        item = self.value['candidates'][0]
        other = {'name': item['name'], 'discovery_id': 'docker-'+'f'*24, 'ports':[{'port':9090}]}
        self.assertEqual(docker.filter_candidates(self.value, {}, [other])['candidates'], [item])

    def test_save_identity_accepts_docker_but_does_not_enable_update(self):
        identity = self.value['candidates'][0]['discovery_id']
        ok, value = lxc_apps.validate_config({'name': 'Docker endpoint', 'discovery_id': identity,
                                            'ports': [{'port': 8080}], 'update_method': 'none'})
        self.assertTrue(ok, value); self.assertEqual(value['discovery_id'], identity)
        self.assertFalse(value.get('update_command')); self.assertFalse(value.get('repo'))
        self.assertFalse(lxc_apps.validate_config({'name':'bad', 'discovery_id':'docker-bad'})[0])


class RealContract(unittest.TestCase):
    def test_sanitized_testhost_template_and_partial_stdout_are_parsed(self):
        value = json.loads((SCRIPTS/'tests/fixtures/docker_discovery_inspect.json').read_text())
        self.assertEqual(value['normal_rc'], 0)
        self.assertEqual(value['partial_rc'], 1)
        self.assertTrue(value['partial_records'])
        for item in [*value['records'], *value['partial_records']]:
            parsed = docker.parse_record(item)
            self.assertTrue(parsed['id'])
            self.assertNotIn('Env', json.dumps(parsed))
            if parsed['running'] and parsed['service'] != 'db':
                self.assertEqual(docker._candidate(101,parsed)['default_ports'],[8080])


class Reader(unittest.TestCase):
    def test_nonzero_exit_preserves_stdout_without_leaking_stderr(self):
        rc, output = docker.read([sys.executable, '-c', 'import sys; print("valid"); print("private-fixture",file=sys.stderr); sys.exit(1)'], time.monotonic()+3)
        self.assertEqual((rc, output), (1, 'valid\n'))

    def test_timeout_and_output_limit_are_bounded_errors(self):
        with patch.object(docker, 'PROBE_SECONDS', .05):
            with self.assertRaisesRegex(native.ProbeError, 'timeout'):
                docker.read([sys.executable, '-c', 'import time; time.sleep(2)'], time.monotonic()+3)
        with patch.object(docker, 'OUTPUT_BYTES', 100):
            with self.assertRaisesRegex(native.ProbeError, 'output_limit'):
                docker.read([sys.executable, '-c', 'print("x"*1000)'], time.monotonic()+3)


class Routes(unittest.TestCase):
    def setUp(self):
        from flask import Flask, request, jsonify
        self.app = Flask(__name__)
        def auth(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                return fn(*args, **kwargs) if request.headers.get('X-Fixture') == 'yes' else ({'error':'unauthorized'},401)
            return wrapped
        source = SCRIPTS/'flask_server.py'
        routes = [n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name in ('api_vm_apps_docker_discovery','api_vm_apps_suggestions')]
        self.cache = {}
        scope = {'app':self.app, 'request':request, 'jsonify':jsonify, 'require_auth':auth,
                 '_vm_cache_get':lambda c,v,t:c.get(v), '_vm_cache_put':lambda c,v,p:c.update({v:p}),
                 '_vm_app_suggestions_cache':self.cache, '_VM_APP_SUGGESTIONS_TTL':60}
        exec(compile(ast.Module(body=routes, type_ignores=[]), str(source), 'exec'),scope)
        self.client = self.app.test_client()

    def test_existing_suggestions_refresh_preserves_docker_cache_without_new_scan(self):
        value = {'vmid':101,'status':'complete','candidates':[],'scanned_at':time.time(),'stale':False}
        docker._cache[101] = copy.deepcopy(value)
        self.addCleanup(docker._cache.clear)
        with patch.object(docker,'discover') as scan, patch.object(lxc_apps,'get_suggestions',return_value={'extras':[]}) as catalog, patch.object(lxc_apps,'_write_sidecar') as write:
            response = self.client.post('/api/vms/101/apps/suggestions',headers={'X-Fixture':'yes'})
            self.assertEqual(response.status_code,200)
            catalog.assert_called_once_with(101,force=True)
            scan.assert_not_called(); write.assert_not_called()
            self.assertEqual(docker.cached(101),value)

    def test_real_route_only_explicit_post_scans_and_never_registers(self):
        value = {'vmid':101,'status':'complete','candidates':[],'stale':False}
        with patch.object(docker,'discover',return_value=value) as scan, patch.object(docker,'cached',return_value=value), patch.object(lxc_apps,'load_sidecar',return_value={'apps':[]}), patch.object(lxc_apps,'_write_sidecar') as write:
            self.assertEqual(self.client.post('/api/vms/101/apps/docker-discovery').status_code,401)
            self.assertEqual(self.client.put('/api/vms/101/apps/docker-discovery',headers={'X-Fixture':'yes'}).status_code,405)
            self.assertEqual(self.client.get('/api/vms/101/apps/docker-discovery',headers={'X-Fixture':'yes'}).status_code,200)
            scan.assert_not_called(); write.assert_not_called()
            self.assertEqual(self.client.post('/api/vms/101/apps/docker-discovery',headers={'X-Fixture':'yes'}).status_code,200)
            scan.assert_called_once_with(101); write.assert_not_called()


if __name__ == '__main__': unittest.main()
