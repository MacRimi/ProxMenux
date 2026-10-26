"""Offline icon contracts: actual codecs, HTTP, cache transactions and routes."""
import ast
import base64
import contextlib
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from flask import Flask, Response, jsonify, request
from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import local_app_icons as icons
import lxc_apps


def picture(fmt='PNG', color='red', size=(16, 16)):
    out = io.BytesIO()
    Image.new('RGB', size, color).save(out, format=fmt)
    return out.getvalue()


class Icons(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.apps = self.root / 'apps'
        self.apps.mkdir()
        self.config = self.root / 'lxc'
        self.config.mkdir()
        (self.config / '101.conf').write_text('net0: name=eth0,bridge=vmbr0,ip=dhcp\n')
        for target, name, value in ((icons, 'CACHE', self.apps / 'logo-cache'),
                (icons, 'APPS', self.apps), (icons, 'CONFIG', self.config),
                (lxc_apps, '_APPS_DIR', str(self.apps))):
            p = patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.png = picture()
        self.payload = {'port': 8080, 'scheme': 'http'}
        # Namespace identity is exercised separately by test_local_app_icon_isolation.
        for name, value in (('_network', contextlib.nullcontext((81, 'fixture'))),
                            ('_network_unchanged', True)):
            p = patch.object(icons, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def resolve(self, args):
        if args[:2] == ['/usr/sbin/pct', 'status']:
            return 'status: running\n'
        if args[0] == 'lxc-info':
            return '10.0.0.42\n'
        if args[0] == 'ip':
            return '[{"addr_info":[{"local":"10.0.0.1"}]}]'
        self.fail(args)

    def test_actual_supported_raster_codecs_are_decoded_and_reencoded(self):
        for fmt, mime in [('PNG', 'image/png'), ('JPEG', 'image/jpeg'), ('GIF', 'image/gif'),
                          ('WEBP', 'image/webp'), ('ICO', 'image/x-icon')]:
            with self.subTest(fmt=fmt):
                data, kind = icons.normalize(picture(fmt), mime)
                self.assertEqual(kind, 'image/png')
                self.assertEqual(Image.open(io.BytesIO(data)).size, (16, 16))

    def test_html_mislabeled_as_png_wrong_mime_truncation_and_oversize_rejected(self):
        for data, mime in [(b'<html>bad</html>', 'image/png'), (self.png, 'image/jpeg'),
                           (self.png[:30], 'image/png'), (self.png, 'text/html'),
                           (b'x' * (icons.MAX_BYTES + 1), 'image/png'), (b'', 'image/png'),
                           (picture(size=(2049, 1)), 'image/png'), (picture(size=(1025, 1025)), 'image/png')]:
            with self.subTest(size=len(data), mime=mime), self.assertRaises(icons.IconError):
                icons.normalize(data, mime)

    def test_svg_active_content_external_resources_and_css_are_removed(self):
        raw = b'''<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)" width="32" height="32">
          <script>alert(1)</script><foreignObject><html/></foreignObject>
          <image href="https://outside.test/icon"/><use href="https://outside.test/a"/>
          <style>path{fill:url(https://outside.test)}</style>
          <path d="M0 0h10v10z" style="fill:red" onclick="alert(1)" fill="url(https://outside.test/a)"/>
          <defs><linearGradient id="paint"><stop offset="0" stop-color="#fff"/></linearGradient></defs>
          <rect width="12" height="12" fill="url(#paint)"/>
        </svg>'''
        data, mime = icons.normalize(raw, 'image/svg+xml')
        self.assertEqual(mime, 'image/svg+xml')
        for forbidden in (b'script', b'onload', b'onclick', b'style', b'href', b'outside.test', b'foreignObject', b'<image', b'<use'):
            self.assertNotIn(forbidden, data)
        self.assertIn(b'url(#paint)', data)
        self.assertIn(b'<path', data)
        self.assertEqual(icons.normalize(data, mime), (data, mime))

    def test_svg_entities_malformed_deep_trees_rejected(self):
        for data in [b'<!DOCTYPE svg [<!ENTITY a "test">]><svg>&a;</svg>', b'<svg>', b'<html/>',
                     b'<svg>' + b'<g>' * 34 + b'</g>' * 34 + b'</svg>']:
            with self.assertRaises(icons.IconError):
                icons.normalize(data, 'image/svg+xml')

    def test_svg_embedded_raster_is_validated_and_preserved_without_external_fetch(self):
        from xml.etree import ElementTree as xml
        embedded = base64.b64encode(picture()).decode()
        raw = f'<svg width="88" height="88" viewBox="0 0 88 88"><image x="4" y="4" width="80" height="80" href="data:image/png;base64,{embedded}"/></svg>'.encode()
        with patch.object(icons, '_open') as network:
            data, mime = icons.normalize(raw, 'image/svg+xml')
            network.assert_not_called()
        image = xml.fromstring(data).find('{http://www.w3.org/2000/svg}image')
        self.assertIsNotNone(image, 'sanitizing must not report an empty SVG as a found icon')
        self.assertEqual(image.get('x'), '4')
        self.assertEqual(image.get('width'), '80')
        decoded = base64.b64decode(image.get('href').split(',', 1)[1], validate=True)
        self.assertEqual(icons.normalize(decoded, 'image/png')[0], decoded)
        self.assertEqual(icons.normalize(data, mime), (data, mime))

    def test_raster_normalization_discards_source_metadata(self):
        source = io.BytesIO()
        Image.new('RGB', (2, 2), 'red').save(source, format='PNG', icc_profile=b'fixture-private-metadata')
        data, _mime = icons.normalize(source.getvalue(), 'image/png')
        with Image.open(io.BytesIO(data)) as result:
            self.assertNotIn('icc_profile', result.info)

    def test_svg_empty_invalid_or_recursive_embedded_images_are_rejected(self):
        nested = base64.b64encode(b'<svg onload="bad()"/>').decode()
        for raw in [b'<svg/>', b'<svg><script>bad()</script></svg>',
                    b'<svg><image href="https://outside.test/icon"/></svg>',
                    b'<svg><image href="data:image/png;base64,bm90IGFuIGltYWdl"/></svg>',
                    f'<svg><image href="data:image/svg+xml;base64,{nested}"/></svg>'.encode()]:
            with self.assertRaises(icons.IconError), patch.object(icons, '_open') as network:
                icons.normalize(raw, 'image/svg+xml')
            network.assert_not_called()
        embedded = base64.b64encode(picture()).decode()
        image = f'<image href="data:image/png;base64,{embedded}"/>'
        with self.assertRaises(icons.IconError):
            icons.normalize(('<svg>' + image * 2 + '</svg>').encode(), 'image/svg+xml')

    def test_explicit_lookup_derives_address_rechecks_and_never_writes_apps(self):
        with patch.object(icons, '_run', side_effect=self.resolve) as run, patch.object(icons, '_worker', return_value=(self.png, 'image/png')) as worker:
            result = icons.discover(101, self.payload)
        worker.assert_called_once_with('http://10.0.0.42:8080', 81)
        self.assertEqual(run.call_count, 6)
        self.assertFalse((self.apps / '101.json').exists())
        self.assertEqual(icons.read(101, result['logo_url'].split('/')[-1])[1], 'image/png')

    def test_stopped_container_has_no_address_or_network_or_cache_calls(self):
        with patch.object(icons, '_run', return_value='status: stopped') as run, patch.object(icons, '_worker') as worker, patch.object(icons, 'store') as store:
            with self.assertRaises(icons.IconError) as error:
                icons.discover(101, self.payload)
        self.assertEqual(error.exception.code, 'local_logo_stopped')
        self.assertEqual(run.call_count, 1)
        worker.assert_not_called()
        store.assert_not_called()

    def test_invalid_payload_missing_guest_and_shared_network_fail_before_probe(self):
        with patch.object(icons, '_run') as run, patch.object(icons, '_worker') as worker:
            for payload in [None, [], {}, {'port': True, 'scheme': 'http'}, {'port': 0, 'scheme': 'http'},
                            {'port': 80, 'scheme': 'ftp'}, {**self.payload, 'url': 'http://outside.test'}]:
                with self.assertRaises(icons.IconError):
                    icons.discover(101, payload)
            for config in ['', 'net0: x\nlxc.net.0.type: none\n', 'net0: x\n# proxmenux/host-monitor\n']:
                (self.config / '101.conf').write_text(config)
                with self.assertRaises(icons.IconError):
                    icons.discover(101, self.payload)
            with self.assertRaises(icons.IconError):
                icons.discover(999, self.payload)
        run.assert_not_called()
        worker.assert_not_called()

    def test_nonprivate_and_host_addresses_fail_without_network(self):
        for ip in ['127.0.0.1', '169.254.169.254', '8.8.8.8', '::1', 'fe80::1', '10.0.0.1', 'invalid']:
            def run(args):
                return ip if args[0] == 'lxc-info' else self.resolve(args)
            with patch.object(icons, '_run', side_effect=run), patch.object(icons, '_worker') as worker:
                with self.assertRaises(icons.IconError):
                    icons.discover(101, self.payload)
                worker.assert_not_called()

    def test_ipv6_literal_and_default_ports(self):
        with patch.object(icons, '_run', side_effect=lambda args: 'fd12::3' if args[0] == 'lxc-info' else self.resolve(args)):
            self.assertEqual(icons._origin(101, {'port': 443, 'scheme': 'https'}), 'https://[fd12::3]:443')
        self.assertTrue(icons._same_origin('https://10.0.0.42:443', 'https://10.0.0.42/icon'))
        self.assertFalse(icons._same_origin('https://10.0.0.42', 'https://user@10.0.0.42/icon'))

    def test_multiple_private_addresses_retain_runtime_order_not_set_order(self):
        # Real CT215 lxc-info: eth0 followed by three Docker bridges and ULA.
        observed = ['10.0.0.27', '172.17.0.1', '172.18.0.1', '172.19.0.1',
                    'fd40:359f:8a1b:f9b3:be24:11ff:fe85:bd05']
        for addresses in (observed, list(reversed(observed))):
            expected = next(ip for ip in addresses if ':' not in ip)
            def resolve(args):
                return '\n'.join(addresses + addresses) if args[0] == 'lxc-info' else self.resolve(args)
            with patch.object(icons, '_run', side_effect=resolve), patch.object(icons, '_worker', return_value=(self.png, 'image/png')) as worker:
                icons.discover(101, self.payload)
                worker.assert_called_once_with(f'http://{expected}:8080', 81)

    def test_address_change_or_stop_during_request_cannot_cache(self):
        for second in ['http://10.0.0.43:8080', icons.IconError('stopped')]:
            with patch.object(icons, '_origin', side_effect=['http://10.0.0.42:8080', second]), patch.object(icons, '_worker', return_value=(self.png, 'image/png')), patch.object(icons, 'store') as store:
                with self.assertRaises(icons.IconError):
                    icons.discover(101, self.payload)
                store.assert_not_called()

    def test_saturated_lookup_and_failed_process_have_no_side_effects(self):
        slot = Mock()
        slot.acquire.return_value = False
        with patch.object(icons, 'SLOTS', slot), patch.object(icons, '_origin') as origin:
            with self.assertRaises(icons.IconError):
                icons.discover(101, self.payload)
            origin.assert_not_called()
        with patch.object(icons.subprocess, 'Popen', side_effect=OSError('cannot start worker')):
            with self.assertRaises(icons.IconError):
                icons._worker('http://10.0.0.42:80', 81)

    def test_real_worker_timeout_kills_child_and_returns_promptly(self):
        worker = self.root / 'slow.py'
        worker.write_text('import time\ntime.sleep(20)\n')
        started = time.monotonic()
        with patch.object(icons, '_worker_command', return_value=[sys.executable, str(worker)]), patch.object(icons, 'WORKER_TIMEOUT', .15):
            with self.assertRaises(icons.IconError):
                icons._run_worker(['--decode'])
        self.assertLess(time.monotonic() - started, 2)

    def test_proxy_environment_is_ignored_and_private_https_context_is_explicit(self):
        opener = Mock()
        with patch.dict(os.environ, {'http_proxy': 'http://outside.test:1234', 'https_proxy': 'http://outside.test:1234'}), patch.object(icons.urllib.request, 'build_opener', return_value=opener) as build:
            icons._open('https://10.0.0.42:443/')
        handlers = build.call_args.args
        self.assertEqual(handlers[0].proxies, {})
        self.assertFalse(handlers[2]._context.check_hostname)
        self.assertEqual(handlers[2]._context.verify_mode, 0)
        req = opener.open.call_args.args[0]
        self.assertNotIn('Authorization', req.headers)
        self.assertNotIn('Cookie', req.headers)

    def test_immutable_objects_cancel_and_failed_sidecar_write_preserve_saved_icon(self):
        first = icons.store(101, self.png, 'image/png')
        self.assertTrue(lxc_apps._write_sidecar(101, {'apps': [{'id': 'a', 'logo_url': first}]}))
        second = icons.store(101, picture(color='blue'), 'image/png')
        self.assertNotEqual(first, second)
        original = (self.apps / '101.json').read_bytes()
        self.assertEqual(icons.read(101, first.split('/')[-1])[0], icons.normalize(self.png, 'image/png')[0])
        with patch.object(lxc_apps.os, 'replace', side_effect=OSError('disk full')):
            self.assertFalse(lxc_apps._write_sidecar(101, {'apps': [{'id': 'a', 'logo_url': second}]}))
        self.assertEqual((self.apps / '101.json').read_bytes(), original)
        self.assertIsNotNone(icons.read(101, first.split('/')[-1]))

    def test_failed_delete_reports_failure_and_keeps_all_icons_and_registration(self):
        logo = icons.store(101, self.png, 'image/png')
        self.assertTrue(lxc_apps._write_sidecar(101, {'apps': [{'id': 'a', 'logo_url': logo}, {'id': 'b'}]}))
        original = (self.apps / '101.json').read_bytes()
        with patch.object(lxc_apps, '_write_sidecar', return_value=False):
            self.assertFalse(lxc_apps.delete_app(101, 'a'))
        self.assertEqual((self.apps / '101.json').read_bytes(), original)
        self.assertIsNotNone(icons.read(101, logo.split('/')[-1]))

    def test_atomic_cache_write_failure_leaves_no_partial_objects(self):
        with patch.object(icons.os, 'replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                icons.store(101, self.png, 'image/png')
        self.assertEqual([p.name for p in (icons.CACHE / '101').iterdir()], ['.lock'])

    def test_parallel_identical_requests_make_one_immutable_object(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            urls = list(pool.map(lambda _: icons.store(101, self.png, 'image/png'), range(12)))
        self.assertEqual(len(set(urls)), 1)
        self.assertEqual(len(list((icons.CACHE / '101').glob('*.icon'))), 1)

    def test_cache_ttl_boundaries_protect_saved_refs_and_reject_expired_drafts(self):
        a = icons.store(101, self.png, 'image/png')
        b = icons.store(101, picture(color='blue'), 'image/png')
        self.assertTrue(lxc_apps._write_sidecar(101, {'apps': [{'logo_url': a}]}))
        directory = icons.CACHE / '101'
        for obj in directory.glob('*.icon'):
            os.utime(obj, (1000, 1000))
        for age in [icons.UNUSED_TTL - 1, icons.UNUSED_TTL]:
            with patch.object(icons.time, 'time', return_value=1000 + age):
                icons._prune(101, directory)
            self.assertIsNotNone(icons.read(101, b.split('/')[-1]))
        with patch.object(icons.time, 'time', return_value=1001 + icons.UNUSED_TTL):
            icons._prune(101, directory)
        self.assertIsNotNone(icons.read(101, a.split('/')[-1]))
        self.assertIsNone(icons.read(101, b.split('/')[-1]))
        before = (self.apps / '101.json').read_bytes()
        self.assertFalse(lxc_apps._write_sidecar(101, {'apps': [{'logo_url': b}]}))
        self.assertEqual((self.apps / '101.json').read_bytes(), before)

    def test_rediscovered_same_content_renews_unsaved_draft_lease(self):
        url = icons.store(101, self.png, 'image/png')
        obj = next((icons.CACHE / '101').glob('*.icon'))
        original = obj.read_bytes()
        os.utime(obj, (1, 1))
        self.assertEqual(icons.store(101, self.png, 'image/png'), url)
        icons._prune(101, obj.parent)
        self.assertTrue(obj.exists(), 'a just rediscovered draft must not expire using its original creation time')
        self.assertEqual(obj.read_bytes(), original)

    def test_corrupt_sidecar_retains_cache_and_quota_cannot_evict_registered_icon(self):
        url = icons.store(101, self.png, 'image/png')
        obj = next((icons.CACHE / '101').glob('*.icon'))
        os.utime(obj, (1, 1))
        (self.apps / '101.json').write_text('{broken')
        with patch.object(icons, 'MAX_ENTRIES', 1):
            with self.assertRaises(icons.IconError):
                icons.store(101, picture(color='blue'), 'image/png')
        self.assertIsNotNone(icons.read(101, url.split('/')[-1]))

    def test_cache_read_has_no_probes_and_legacy_svg_is_sanitized(self):
        directory = icons.CACHE / '101'
        directory.mkdir(parents=True)
        token = 'a' * 32
        (directory / (token + '.bin')).write_bytes(b'<svg onload="bad()"><script>bad()</script><path d="M0 0"/></svg>')
        (directory / (token + '.json')).write_text('{"content_type":"image/svg+xml"}')
        with patch.object(icons, '_run') as run, patch.object(icons, '_worker') as worker:
            result = icons.read(101, token)
            self.assertNotIn(b'bad', result[0])
            self.assertIsNone(icons.read(102, token))
            self.assertIsNone(icons.read(101, '../' + token))
            run.assert_not_called()
            worker.assert_not_called()

    def test_config_accepts_only_same_guest_cache_urls_and_all_existing_formats(self):
        for url, expected in [('https://example.test/icon.png', True), ('', True),
                              ('/api/vms/101/apps/logo-cache/' + 'a' * 32, True),
                              ('/api/vms/102/apps/logo-cache/' + 'a' * 32, False), ('javascript:bad()', False)]:
            self.assertEqual(lxc_apps.validate_config({'name': 'Example', 'ports': [], 'logo_url': url}, vmid=101)[0], expected)

    def test_real_add_edit_diagnostic_and_delete_contracts(self):
        first = icons.store(101, self.png, 'image/png')
        second = icons.store(101, picture(color='blue'), 'image/png')
        draft = {'name': 'Example', 'ports': [], 'logo_url': first}
        with patch.object(lxc_apps, 'check_app') as check:
            ok, state = lxc_apps.add_app(101, draft)
            self.assertTrue(ok, state)
            app_id = state['apps'][0]['id']
            ok, state = lxc_apps.update_app(101, app_id, {**draft, 'logo_url': second})
            self.assertTrue(ok, state)
            self.assertEqual(state['apps'][0]['logo_url'], second)
            self.assertEqual(check.call_count, 2)
        # Register-only diagnostic must accept the cached URL without probing.
        with patch.object(lxc_apps, '_pct_exec') as execute:
            self.assertTrue(lxc_apps.test_config(101, {**draft, 'logo_url': second})[0])
            execute.assert_not_called()
        self.assertTrue(lxc_apps.delete_app(101, app_id))
        self.assertFalse((self.apps / '101.json').exists())
        for url in [first, second]:
            self.assertIsNotNone(icons.read(101, url.split('/')[-1]))

    def test_save_serializes_against_pruning_and_keeps_new_reference(self):
        url = icons.store(101, self.png, 'image/png')
        obj = next((icons.CACHE / '101').glob('*.icon'))
        os.utime(obj, (1, 1))
        entered = threading.Event()
        def prune():
            entered.set()
            with icons._cache_lock(101) as directory:
                icons._prune(101, directory)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with icons.protect_references(101, {'apps': [{'logo_url': url}]}):
                job = pool.submit(prune)
                self.assertTrue(entered.wait(1))
                self.assertFalse(job.done())
                (self.apps / '101.json').write_text(json.dumps({'apps': [{'logo_url': url}]}))
            job.result(timeout=3)
        self.assertTrue(obj.exists())


class HttpContract(unittest.TestCase):
    def test_real_http_local_redirect_relative_icon_fallback_and_blocked_redirects(self):
        png = picture()
        requests = []
        mode = ['relative']
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args): pass
            def do_GET(self):
                requests.append(self.path)
                if self.path == '/' and mode[0] in ('redirect', 'external', 'loop'):
                    self.send_response(302)
                    self.send_header('Location', {'redirect': '/login/', 'external': 'http://outside.test/', 'loop': '/'}[mode[0]])
                    self.end_headers()
                    return
                if self.path.endswith('.png') and mode[0] == 'icon-redirect':
                    self.send_response(302)
                    self.send_header('Location', '/other.png')
                    self.end_headers()
                    return
                self.send_response(200)
                image = self.path.endswith(('.png', '.ico'))
                self.send_header('Content-Type', 'image/png' if image else 'text/html')
                self.end_headers()
                self.wfile.write(png if image else {
                    'fallback': b'<html/>', 'external-icon': b'<link rel="icon" href="https://outside.test/x.png">',
                }.get(mode[0], b'<link rel="icon" href="icon.png">'))
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            origin = f'http://127.0.0.1:{server.server_port}'
            # Production rejects loopback; this fixture tests only the HTTP contract.
            with patch.object(icons, '_private_ip', return_value=True), patch.object(icons, '_owns_address', return_value=True):
                for case, paths in [('relative', ['/', '/icon.png']), ('redirect', ['/', '/login/', '/login/icon.png']), ('fallback', ['/', '/favicon.ico'])]:
                    mode[0] = case; requests.clear()
                    self.assertEqual(icons._fetch(origin)[1], 'image/png')
                    self.assertEqual(requests, paths)
                for case in ['external', 'external-icon', 'loop', 'icon-redirect']:
                    mode[0] = case; requests.clear()
                    with self.assertRaises(icons.IconError):
                        icons._fetch(origin)
                    self.assertNotIn('/other.png', requests)
        finally:
            server.shutdown(); server.server_close(); thread.join()


class Routes(unittest.TestCase):
    def setUp(self):
        app = Flask('icon-test')
        def require_auth(fn):
            @wraps(fn)
            def authenticated(*args, **kwargs):
                if request.headers.get('Authorization') != 'Bearer fixture':
                    return jsonify({'error': 'unauthorized'}), 401
                return fn(*args, **kwargs)
            return authenticated
        env = dict(app=app, require_auth=require_auth, jsonify=jsonify, request=request, Response=Response)
        tree = ast.parse((SCRIPTS / 'flask_server.py').read_text())
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('api_vm_apps_logo_discovery', 'api_vm_apps_logo_cache')]
        self.assertEqual(len(functions), 2)
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'flask_server.py', 'exec'), env)
        self.client = app.test_client()
        self.headers = {'Authorization': 'Bearer fixture'}

    def test_auth_post_only_and_cache_get_no_discovery(self):
        with patch.object(icons, 'discover', return_value={'logo_url': '/test'}) as discover, patch.object(icons, 'read', return_value=(picture(), 'image/png')) as read:
            self.assertEqual(self.client.post('/api/vms/101/apps/logo-discovery', json={}).status_code, 401)
            self.assertEqual(self.client.get('/api/vms/101/apps/logo-cache/' + 'a' * 32).status_code, 401)
            discover.assert_not_called(); read.assert_not_called()
            self.assertEqual(self.client.get('/api/vms/101/apps/logo-discovery', headers=self.headers).status_code, 405)
            response = self.client.get('/api/vms/101/apps/logo-cache/' + 'a' * 32, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
            self.assertIn('sandbox', response.headers['Content-Security-Policy'])
            discover.assert_not_called()
            self.assertEqual(self.client.post('/api/vms/101/apps/logo-discovery', json={'port': 80, 'scheme': 'http'}, headers=self.headers).status_code, 200)
            discover.assert_called_once_with(101, {'port': 80, 'scheme': 'http'})

    def test_error_code_is_safe_stopped_is_distinct_and_missing_cache_is_404(self):
        with patch.object(icons, 'discover', side_effect=icons.IconError('internal path', 'local_logo_stopped')):
            response = self.client.post('/api/vms/101/apps/logo-discovery', json={}, headers=self.headers)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json['code'], 'local_logo_stopped')
            self.assertNotIn('internal path', response.get_data(as_text=True))
        with patch.object(icons, 'read', return_value=None):
            self.assertEqual(self.client.get('/api/vms/101/apps/logo-cache/' + 'a' * 32, headers=self.headers).status_code, 404)

    def test_svg_response_preserves_real_charset_contract_for_browser(self):
        with patch.object(icons, 'read', return_value=(b'<svg xmlns="http://www.w3.org/2000/svg"/>', 'image/svg+xml')):
            response = self.client.get('/api/vms/101/apps/logo-cache/' + 'a' * 32, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Content-Type'], 'image/svg+xml; charset=utf-8')


if __name__ == '__main__':
    unittest.main()
