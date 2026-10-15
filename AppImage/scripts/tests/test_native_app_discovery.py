"""Host-independent discovery fixtures; no real pct, guest, auth or registry."""
import ast
import copy
import fcntl
from functools import wraps
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import native_app_discovery as native
import lxc_apps


def service(name='handmade', exe='/opt/handmade/server', directory='/opt/handmade', manager='systemd', script='', source=None):
    path = source or ('/etc/systemd/system/' + name + '.service' if manager == 'systemd'
                      else '/etc/init.d/' + name)
    return '\t'.join(['S', path, manager, exe, script, directory]) + '\nEND\n'


class DiscoveryFixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'lxc'
        self.config.mkdir()
        (self.config / '101.conf').write_text('ostype: debian\n')
        self.oci = self.root / 'oci'
        self.oci.mkdir()
        for context in (patch.object(native, 'LOCAL_CONFIG', self.config),
                        patch.object(native, 'OCI_ROOT', self.oci),
                        patch.object(native, 'UPDATE_LOCK_ROOT', self.root)):
            context.start()
            self.addCleanup(context.stop)
        native._cache.clear()
        native._locks.clear()
        self.calls = []

    def runner(self, services=None, processes='END\n', footprint='FILE\n', status='status: running', ports='END\n'):
        def run(argv, deadline):
            self.calls.append(argv)
            self.assertLessEqual(deadline - time.monotonic(), native.TOTAL_SECONDS)
            if argv[1] == 'status':
                return status
            self.assertEqual(argv[:6], ['pct', 'exec', '101', '--', 'timeout', '-s'])
            self.assertEqual(argv[6:9], ['KILL', '2', 'sh'])
            script = argv[10]
            if script == native.SERVICE_SCRIPT:
                return services if services is not None else service()
            if script == native.PROCESS_SCRIPT:
                return processes
            if script == native.PORT_SCRIPT:
                return ports
            if script == native.FOOTPRINT_SCRIPT:
                return footprint
            self.fail('Unexpected probe')
        return run

    def test_unknown_version_is_present_with_evidence_and_no_capabilities(self):
        result = native.scan(101, self.runner())
        self.assertEqual(result['status'], 'complete')
        item, = result['candidates']
        self.assertIsNone(item['installed_version'])
        self.assertIsNone(item['tracking_suggestion'])
        self.assertEqual(item['default_ports'], [])
        self.assertEqual({e['kind'] for e in item['evidence']}, {'installation_file', 'systemd'})
        for field in ('helper_slug', 'repo', 'update_command', 'binary_path', 'upstream_type'):
            self.assertNotIn(field, item)

    def test_openrc_node_script_known_version_is_manual_and_secret_free(self):
        result = native.scan(101, self.runner(
            service(exe='/usr/bin/node', script='/opt/handmade/server.js', manager='openrc'),
            footprint='FILE\n' + json.dumps({'version': '1.2.3', 'scripts': {'start': 'SECRET'}, 'env': 'PASSWORD'})))
        item, = result['candidates']
        self.assertEqual(item['installed_version'], '1.2.3')
        self.assertEqual(item['tracking_suggestion']['installed_via'], 'manual')
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertNotIn('PASSWORD', json.dumps(result))
        self.assertFalse(any('systemctl' in arg for call in self.calls for arg in call))

    def test_inactive_service_and_packaged_application_are_not_hidden(self):
        result = native.scan(101, self.runner(service(name='legit-app', exe='/usr/bin/legit-app', directory='')))
        self.assertEqual(result['candidates'][0]['name'], 'legit-app')

    def test_system_services_and_ambiguous_runtimes_have_zero_footprint_probes(self):
        for name, exe in [('ssh', '/usr/sbin/sshd'), ('cron', '/usr/sbin/cron'),
                          ('postfix', '/usr/lib/postfix/master'), ('rsyslog', '/usr/sbin/rsyslogd'),
                          ('systemd-networkd', '/usr/lib/systemd/systemd-networkd'),
                          ('ambiguous', '/usr/bin/python3')]:
            self.calls.clear()
            result = native.scan(101, self.runner(service(name=name, exe=exe)))
            self.assertEqual(result['candidates'], [])
            self.assertFalse(any(native.FOOTPRINT_SCRIPT in call for call in self.calls))

    def test_common_system_daemons_and_vendor_units_have_zero_footprint_probes(self):
        cases = [
            ('nginx', '/usr/sbin/nginx', 'openrc', None),
            ('apache2', '/usr/sbin/apache2', 'systemd', None),
            ('redis-server', '/usr/bin/redis-server', 'systemd', None),
            ('mariadb', '/usr/sbin/mariadbd', 'systemd', None),
            ('postgresql', '/usr/lib/postgresql/16/bin/postgres', 'systemd', None),
            ('php8.3-fpm', '/usr/sbin/php-fpm8.3', 'systemd', None),
            ('vendor-daemon', '/usr/bin/vendor-daemon', 'systemd',
             '/usr/lib/systemd/system/vendor-daemon.service'),
        ]
        for name, exe, manager, source in cases:
            with self.subTest(name=name):
                self.calls.clear()
                result = native.scan(101, self.runner(
                    service(name=name, exe=exe, manager=manager, source=source)))
                self.assertEqual(result['candidates'], [])
                self.assertFalse(any(native.FOOTPRINT_SCRIPT in call for call in self.calls))

    def test_helper_services_and_templates_have_zero_footprint_probes(self):
        cases = [
            ('netpulse-stable-update', '/bin/bash', '/opt/netpulse', '/opt/netpulse/stable-apply.sh'),
            ('rent-tool-backup', '/bin/bash', '/home/app/rent-tool', '/home/app/rent-tool/scripts/backup-db.sh'),
            ('keynest-update', '/bin/bash', '/opt/keynest', '/opt/keynest/keynest-update.sh'),
            ('cortendesk-bootstrap-worker', '/bin/bash', '/opt/cortendesk', '/opt/cortendesk/bootstrap-worker.sh'),
            ('cortendesk-source-worker', '/bin/bash', '/opt/cortendesk', '/opt/cortendesk/source-worker.sh'),
            ('cortendesk-managed-password@', '/bin/bash', '/opt/cortendesk', '/opt/cortendesk/password-bridge.sh'),
        ]
        for name, exe, directory, script in cases:
            with self.subTest(name=name):
                self.calls.clear()
                result = native.scan(101, self.runner(service(
                    name=name, exe=exe, directory=directory, script=script)))
                self.assertEqual(result['candidates'], [])
                self.assertFalse(any(native.FOOTPRINT_SCRIPT in call for call in self.calls))

    def test_node_and_npm_wrappers_use_only_custom_package_roots(self):
        cases = [
            ('keynest', '/usr/bin/node', '/opt/keynest'),
            ('rent-tool', '/usr/local/bin/npm', '/home/app/rent-tool'),
        ]
        for name, exe, directory in cases:
            with self.subTest(name=name):
                self.calls.clear()
                result = native.scan(101, self.runner(
                    service(name=name, exe=exe, directory=directory),
                    footprint='FILE\n{"version":"1.2.3"}'))
                item, = result['candidates']
                self.assertEqual(item['name'], name)
                self.assertEqual(item['installation_path'], directory + '/package.json')
                self.assertEqual(item['installed_version'], '1.2.3')
                footprint_calls = [call for call in self.calls if native.FOOTPRINT_SCRIPT in call]
                self.assertEqual(len(footprint_calls), 1)
                self.assertEqual(footprint_calls[0][-2:], [directory + '/package.json', directory])

        self.calls.clear()
        result = native.scan(101, self.runner(service(
            name='ambiguous-home-runtime', exe='/usr/bin/node', directory='/home/app')))
        self.assertEqual(result['candidates'], [])
        self.assertFalse(any(native.FOOTPRINT_SCRIPT in call for call in self.calls))

    def test_helper_process_fallback_has_zero_footprint_probes(self):
        self.calls.clear()
        result = native.scan(101, self.runner(
            services='END\n', processes='P\t123\t/opt/cortendesk/run-worker\t/opt/cortendesk\nEND\n'))
        self.assertEqual(result['candidates'], [])
        self.assertFalse(any(native.FOOTPRINT_SCRIPT in call for call in self.calls))

    def test_missing_remote_qemu_stopped_busy_oci_guards_precede_exec(self):
        scenarios = ['missing', 'stopped', 'busy', 'oci', 'invalid-oci', 'unmanaged']
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                (self.config / '101.conf').write_text('ostype: debian\n')
                if scenario == 'missing':
                    (self.config / '101.conf').unlink()
                if scenario == 'busy':
                    (self.config / '101.conf').write_text('lock: backup\n')
                if scenario == 'unmanaged':
                    (self.config / '101.conf').write_text('ostype: unmanaged\n')
                if 'oci' in scenario:
                    (self.oci / '101').mkdir(exist_ok=True)
                    (self.oci / '101' / 'oci-compose.json').write_text('broken')
                self.calls.clear()
                with self.assertRaises(native.ProbeError):
                    native.scan(101, self.runner(status='status: stopped' if scenario == 'stopped' else 'status: running'))
                self.assertFalse(any(call[1] == 'exec' for call in self.calls))
                if (self.oci / '101').exists():
                    (self.oci / '101' / 'oci-compose.json').unlink()
                    (self.oci / '101').rmdir()

    def test_failure_and_partial_output_are_not_successful_empty_results(self):
        for text in ('', 'malformed\nEND\n', 'S\tpartial', 'LIMIT\n'):
            result = native.scan(101, self.runner(services=text))
            self.assertEqual(result['status'], 'partial')
        run = self.runner()
        def failed(argv, deadline):
            if argv[1] == 'exec':
                raise native.ProbeError('read_failed')
            return run(argv, deadline)
        self.assertEqual(native.scan(101, failed)['status'], 'partial')

    def test_optional_invalid_version_metadata_keeps_proven_candidate(self):
        result = native.scan(101, self.runner(footprint='FILE\n{broken'))
        self.assertEqual(result['status'], 'partial')
        item, = result['candidates']
        self.assertIsNone(item['installed_version'])
        self.assertIsNone(item['tracking_suggestion'])

    def test_working_directory_manifest_does_not_version_an_unrelated_executable(self):
        result = native.scan(101, self.runner(service(exe='/opt/other/server'),
                                             footprint='FILE\n{"version":"1.2.3"}'))
        self.assertIsNone(result['candidates'][0]['installed_version'])

    def test_path_injection_and_port_only_data_do_not_become_candidates(self):
        for text in (service(exe='/opt/app/$(id)'), service(exe='/opt/../server'),
                     service(name='app;id'), service(exe='/bin/sh')):
            self.assertEqual(native.scan(101, self.runner(text))['candidates'], [])
        with self.assertRaises(native.ProbeError):
            native.parse_records('PORT\t8080\nEND\n', 'P')

    def test_same_process_deduplicates_but_two_apps_using_node_do_not_merge(self):
        services = service(exe='/usr/bin/node', script='/opt/handmade/server.js').removesuffix('END\n')
        services += service(name='second', exe='/usr/bin/node', script='/opt/second/server.js', directory='/opt/second')
        result = native.scan(101, self.runner(services))
        self.assertEqual(len(result['candidates']), 2)
        result = native.scan(101, self.runner(processes='P\t123\t/opt/handmade/server\t/opt/handmade\nEND\n'))
        self.assertEqual(len(result['candidates']), 1)
        other = native.candidate(102, native.parse_records(service(), 'S')[0][0], 'FILE\n')
        self.assertNotEqual(other['discovery_id'], result['candidates'][0]['discovery_id'])

    def test_record_and_candidate_caps(self):
        too_many = 'P\t123\t/opt/a/app\t/opt/a\n' * 257 + 'END\n'
        with self.assertRaises(native.ProbeError):
            native.parse_records(too_many, 'P')
        services = ''.join(service(name=f'app{i}', exe=f'/opt/app{i}/server', directory=f'/opt/app{i}').removesuffix('END\n') for i in range(51)) + 'END\n'
        result = native.scan(101, self.runner(services))
        self.assertEqual(len(result['candidates']), 50)
        self.assertIn('candidate_limit', result['issues'])

    def test_cached_ttl_never_runs_scan_and_error_preserves_last_known(self):
        complete = native.scan(101, self.runner())
        with patch.object(native, 'scan', return_value=complete) as scan:
            native.discover(101)
            for age, stale in ((299.9, False), (300, True), (300.1, True)):
                with patch.object(native.time, 'time', return_value=complete['scanned_at'] + age):
                    self.assertEqual(native.cached(101)['stale'], stale)
            self.assertEqual(scan.call_count, 1)
        with patch.object(native, 'scan', side_effect=native.ProbeError('timeout')):
            result = native.discover(101)
        self.assertEqual(result['candidates'], complete['candidates'])
        self.assertEqual(native.cached(101)['status'], 'error')
        self.assertTrue(native.cached(101)['stale'])
        partial = {**complete, 'status': 'partial', 'candidates': [], 'issues': ['read_failed']}
        with patch.object(native, 'scan', return_value=partial):
            self.assertEqual(native.discover(101)['candidates'], complete['candidates'])
        with patch.object(native, 'scan', return_value={**complete, 'candidates': []}):
            self.assertEqual(native.discover(101)['candidates'], [])

    def test_same_ct_busy_and_different_ct_cache_isolation(self):
        lock = threading.Lock()
        lock.acquire()
        native._locks[101] = lock
        with patch.object(native, 'scan') as scanner:
            self.assertEqual(native.discover(101)['status'], 'busy')
            scanner.assert_not_called()
        self.assertEqual(native.cached(102)['status'], 'not_scanned')

    def test_filter_registered_curated_and_docker_children_without_mutation(self):
        result = native.scan(101, self.runner())
        original = copy.deepcopy(result)
        for suggestions, apps in (({}, [{'discovery_id': result['candidates'][0]['discovery_id']}]),
                                   ({'extras': [{'name': 'Handmade'}]}, []),
                                   ({'docker_workloads': [{'name': 'Handmade'}]}, []),
                                   ({'helper_slug': 'handmade', 'name_suggestion': 'Handmade'}, [])):
            self.assertEqual(native.filter_candidates(result, suggestions, apps)['candidates'], [])
        self.assertEqual(result, original)

    def test_actual_save_first_check_and_recheck_never_probe_or_configure_updater(self):
        with patch.object(lxc_apps, '_APPS_DIR', str(self.root / 'apps')), \
             patch.object(lxc_apps, '_pct_exec', side_effect=AssertionError('forbidden guest execution')) as execute, \
             patch.object(lxc_apps, 'fetch_latest_upstream_details', side_effect=AssertionError('forbidden upstream')) as upstream:
            for version in (None, '1.2.3'):
                item = native.candidate(101, native.parse_records(service(), 'S')[0][0],
                                        'FILE\n' + (json.dumps({'version': version}) if version else ''))
                payload = {'name': item['name'], 'discovery_id': item['discovery_id'],
                           'update_method': 'none', **(item['tracking_suggestion'] or {})}
                ok, sidecar = lxc_apps.add_app(101, payload)
                self.assertTrue(ok, sidecar)
                app = sidecar['apps'][-1]
                self.assertEqual(app['state']['installed_version'], version)
                self.assertIsNone(app['state']['update_available'])
                self.assertEqual(app['update_method'], 'none')
                for field in ('helper_slug', 'update_command', 'repo', 'upstream_type'):
                    self.assertNotIn(field, app)
                lxc_apps.check_app(101, app['id'], force=True)
            self.assertIsNone(lxc_apps.get_schedule(101))
            self.assertIsNone(lxc_apps.get_bulk_update(101))
            execute.assert_not_called()
            upstream.assert_not_called()

    def test_failed_save_has_no_first_check(self):
        with patch.object(lxc_apps, '_write_sidecar', return_value=False), \
             patch.object(lxc_apps, '_read_sidecar', return_value=None), \
             patch.object(lxc_apps, 'check_app') as check:
            self.assertFalse(lxc_apps.add_app(101, {'name': 'handmade'})[0])
            check.assert_not_called()

    def test_active_update_lock_blocks_all_guest_probes_without_writing(self):
        path = self.root / 'proxmenux-lxc-update-101.lock'
        path.write_bytes(b'unchanged')
        with path.open('rb') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            with self.assertRaisesRegex(native.ProbeError, 'guest_busy'):
                native.scan(101, self.runner())
        self.assertEqual(path.read_bytes(), b'unchanged')
        self.assertEqual(self.calls, [])

    def test_actual_service_parser_reads_data_never_executes_or_sources_it(self):
        for manager in ('systemd', 'openrc'):
            directory = self.root / manager
            directory.mkdir()
            marker = self.root / ('forbidden-' + manager)
            unit = directory / ('handmade.service' if manager == 'systemd' else 'handmade')
            content = ('[Service]\nExecStart=/usr/bin/node /opt/handmade/server.js --password SECRET\nWorkingDirectory=/opt/handmade\n'
                       if manager == 'systemd' else 'command="/usr/bin/node"\ncommand_args="/opt/handmade/server.js --password SECRET"\ndirectory="/opt/handmade"\n')
            unit.write_text(content + '\ntouch ' + str(marker) + '\n')
            script = native.SERVICE_SCRIPT.replace('/etc/systemd/system /usr/lib/systemd/system /lib/systemd/system /etc/init.d', str(directory))
            # Substitute only fixture paths, not the collector/parser behavior.
            if manager == 'openrc':
                script = script.replace('/etc/init.d:*)', str(directory) + ':*)')
            output = native.bounded_run(['sh', '-c', script], time.monotonic() + 3)
            record, = native.parse_records(output, 'S')[0]
            self.assertEqual(record['path'], '/opt/handmade/server.js')
            self.assertNotIn('SECRET', output)
            self.assertFalse(marker.exists())

    def test_actual_process_parser_skips_docker_and_never_reads_environ_cmdline(self):
        proc = self.root / 'proc'
        proc.mkdir()
        for pid, group in ((1, '0::/\n'), (2, '0::/docker/child\n')):
            directory = proc / str(pid)
            directory.mkdir()
            (directory / 'cgroup').write_text(group)
            (directory / 'exe').symlink_to('/opt/handmade/server')
            (directory / 'cwd').symlink_to('/opt/handmade')
            (directory / 'cmdline').write_text('SECRET')
            (directory / 'environ').write_text('PASSWORD')
        script = native.PROCESS_SCRIPT.replace('/proc/[0-9]*', str(proc) + '/[0-9]*')
        output = native.bounded_run(['sh', '-c', script, 'fixture', '256'], time.monotonic() + 3)
        self.assertEqual(output, 'P\t1\t/opt/handmade/server\t/opt/handmade\nEND\n')
        self.assertNotIn('"$dir/cmdline"', native.PROCESS_SCRIPT)
        self.assertNotIn('"$dir/environ"', native.PROCESS_SCRIPT)
        self.assertNotIn('SECRET', output)

    def test_ports_require_exact_process_ownership_and_do_not_infer_http(self):
        process = 'P\t123\t/opt/handmade/server\t/opt/handmade\nEND\n'
        result = native.scan(101, self.runner(processes=process, ports='L\t123\t8080\nL\t999\t9000\nEND\n'))
        item, = result['candidates']
        self.assertEqual(item['listening_ports'], [8080])
        self.assertEqual(item['default_ports'], [], 'TCP listener does not prove HTTP')
        result = native.scan(101, self.runner(ports='L\t123\t8080\nEND\n'))
        self.assertEqual(result['candidates'][0]['listening_ports'], [])

    def test_shared_runtime_ports_are_assigned_only_by_working_directory(self):
        services = service(exe='/usr/bin/node', script='/opt/handmade/server.js').removesuffix('END\n')
        services += service(name='second', exe='/usr/bin/node', script='/opt/second/server.js', directory='/opt/second')
        process = 'P\t123\t/usr/bin/node\t/opt/second\nEND\n'
        result = native.scan(101, self.runner(services, processes=process, ports='L\t123\t8080\nEND\n'))
        self.assertEqual(result['candidates'][0]['listening_ports'], [])
        self.assertEqual(result['candidates'][1]['listening_ports'], [8080])

    def test_ss_and_alpine_netstat_parser_are_bounded_and_secret_free(self):
        for tool, line in (('ss', 'LISTEN 0 128 0.0.0.0:8080 0.0.0.0:* users:(("SECRET",pid=123,fd=7))'),
                           ('netstat', 'tcp 0 0 0.0.0.0:8080 0.0.0.0:* LISTEN 123/SECRET')):
            bin_dir = self.root / tool
            bin_dir.mkdir()
            executable = bin_dir / tool
            executable.write_text('#!/bin/sh\nprintf \'%s\\n\' \'' + line + '\'\n')
            executable.chmod(0o755)
            (bin_dir / 'awk').symlink_to('/usr/bin/awk')
            (bin_dir / 'timeout').symlink_to('/usr/bin/timeout')
            script = 'PATH=' + str(bin_dir) + '\n' + native.PORT_SCRIPT
            output = native.bounded_run(['sh', '-c', script, 'fixture', '256'], time.monotonic() + 3)
            self.assertEqual(output, 'L\t123\t8080\nEND\n')
            self.assertNotIn('SECRET', output)
            executable.write_text('#!/bin/sh\nexit 1\n')
            output = native.bounded_run(['sh', '-c', script, 'fixture', '256'], time.monotonic() + 3)
            with self.assertRaises(native.ProbeError):
                native.parse_records(output, 'L')


class BoundedRunner(unittest.TestCase):
    def test_output_limit_is_enforced_during_read(self):
        with self.assertRaisesRegex(native.ProbeError, 'output_limit'):
            native.bounded_run([sys.executable, '-c', 'import os; os.write(2,b"x"*1000000)'], time.monotonic() + 3)

    def test_pipe_holding_child_does_not_bypass_timeout(self):
        start = time.monotonic()
        with self.assertRaisesRegex(native.ProbeError, 'timeout'):
            native.bounded_run([sys.executable, '-c', 'import os,time; os.fork(); time.sleep(10)'], start + .15)
        self.assertLess(time.monotonic() - start, .8)

    def test_failures_never_reveal_stderr_and_deadline_blocks_spawn(self):
        with self.assertRaisesRegex(native.ProbeError, '^read_failed$'):
            native.bounded_run([sys.executable, '-c', 'import sys; sys.stderr.write("SECRET"); sys.exit(1)'], time.monotonic() + 3)
        with patch.object(native.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(native.ProbeError, 'deadline'):
                native.bounded_run(['forbidden'], time.monotonic() - 1)
            launch.assert_not_called()


class Routes(unittest.TestCase):
    """Execute actual Flask route bodies; fixture auth, no server startup jobs."""
    def setUp(self):
        from flask import Flask, request, jsonify, g
        self.app = Flask('native-fixture')
        self.authorized = True
        def require_auth(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                if not self.authorized:
                    return jsonify({'error': 'auth_required'}), 401
                return fn(*args, **kwargs)
            return wrapped
        self.globals = {'app': self.app, 'request': request, 'jsonify': jsonify,
                        'require_auth': require_auth, '_vm_app_suggestions_cache': {},
                        '_VM_APP_SUGGESTIONS_TTL': 300,
                        '_vm_cache_get': lambda cache, vmid, ttl: cache.get(vmid),
                        '_vm_cache_put': lambda cache, vmid, value: cache.update({vmid: value}),
                        '_pvesh_cache': {}, '_vm_disk_cache': {}, '_vm_cache_invalidate': Mock(),
                        '_invalidate_lxc_ip': Mock(), '_schedule_started_guest_refresh': Mock(),
                        '_publish_guest_modal_cache_revision': Mock()}
        tree = ast.parse((SCRIPTS / 'flask_server.py').read_text())
        routes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in (
            'api_vm_apps_suggestions', 'api_vm_apps_native_discovery', 'api_vm_apps_add',
            '_handle_guest_lifecycle')]
        self.assertEqual(len(routes), 4)
        exec(compile(ast.Module(body=routes, type_ignores=[]), str(SCRIPTS / 'flask_server.py'), 'exec'), self.globals)
        self.client = self.app.test_client()

    def test_explicit_post_only_get_and_existing_post_never_native_scan(self):
        result = {'vmid': 101, 'status': 'complete', 'candidates': [], 'stale': False}
        with patch.object(native, 'discover', return_value=result) as scan, \
             patch.object(native, 'cached', return_value=result), \
             patch.object(lxc_apps, 'get_suggestions', return_value={'extras': []}) as suggestions, \
             patch.object(lxc_apps, 'load_sidecar', return_value={'apps': []}), \
             patch.object(lxc_apps, '_write_sidecar') as write:
            self.assertEqual(self.client.get('/api/vms/101/apps/native-discovery').status_code, 200)
            self.client.get('/api/vms/101/apps/suggestions')
            # OCI refresh and Find's existing catalog path retain their purpose.
            self.client.post('/api/vms/101/apps/suggestions')
            with self.app.test_request_context('/api/vms/101/apps/suggestions'):
                from flask import g
                g._internal_call = True
                self.globals['_vm_app_suggestions_cache'].clear()
                self.globals['api_vm_apps_suggestions'](101)
            scan.assert_not_called()
            self.client.post('/api/vms/101/apps/native-discovery')
            scan.assert_called_once_with(101)
            self.assertEqual(suggestions.call_count, 2)
            write.assert_not_called()

    def test_unauthorized_and_wrong_method_have_zero_scans(self):
        with patch.object(native, 'discover') as scan, patch.object(lxc_apps, 'load_sidecar') as read:
            self.authorized = False
            self.assertEqual(self.client.post('/api/vms/101/apps/native-discovery').status_code, 401)
            self.assertEqual(self.client.put('/api/vms/101/apps/native-discovery').status_code, 405)
            scan.assert_not_called()
            read.assert_not_called()

    def test_actual_lifecycle_marks_last_known_stale_without_scanning(self):
        native._cache[101] = {'vmid': 101, 'status': 'complete', 'stale': False,
                              'candidates': [], 'scanned_at': time.time()}
        with patch.object(native, 'discover') as scan, \
             patch.object(lxc_apps, 'clear_schedule_reboot_required') as clear:
            for action in ('start', 'reboot', 'stop'):
                self.globals['_handle_guest_lifecycle']('101', 'lxc', action)
                self.assertTrue(native.cached(101)['stale'])
            scan.assert_not_called()
            self.assertEqual(clear.call_count, 2)

    def test_actual_repeated_prewarmer_has_zero_native_scans(self):
        tree = ast.parse((SCRIPTS / 'flask_server.py').read_text())
        warmer = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                      and node.name == '_vm_modal_prewarmer_pass')
        environment = dict(self.globals)
        for name in ('_vm_details_cache', '_vm_backups_cache', '_vm_schedule_cache', '_vm_mounts_cache'):
            environment[name] = {}
        for name in ('_VM_DETAILS_TTL', '_VM_BACKUPS_TTL', '_VM_SCHEDULE_TTL', '_VM_MOUNTS_TTL'):
            environment[name] = 300
        for name in ('get_vm_config', 'api_vm_backups', 'api_vm_apps_schedule', 'api_lxc_mount_points'):
            environment[name] = lambda vmid: None
        environment.update({'get_cached_pvesh_cluster_resources_vm': lambda: [
            {'vmid': 101, 'type': 'lxc', 'status': 'running'}], 'time': Mock(), 'sys': sys})
        exec(compile(ast.Module(body=[warmer], type_ignores=[]), 'flask_server.py', 'exec'), environment)
        with patch.object(native, 'discover') as scan, \
             patch.object(lxc_apps, 'ensure_oci_registration'), \
             patch.object(lxc_apps, 'load_sidecar', return_value={'apps': []}), \
             patch.object(lxc_apps, 'get_suggestions', return_value={'extras': []}):
            for _ in range(2):
                environment['_vm_app_suggestions_cache'].clear()
                self.assertEqual(environment['_vm_modal_prewarmer_pass'](), 1)
            scan.assert_not_called()


if __name__ == '__main__':
    unittest.main()
