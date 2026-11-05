"""Real self-signed image HTTPS readiness, without weakening strict probes."""
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'remote'))
import install_generic_stack as installer


@unittest.skipUnless(shutil.which('openssl'), 'openssl needed for local TLS fixture')
class HTTPSReadiness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cert, key = (Path(cls.directory.name) / name for name in ('cert.pem', 'key.pem'))
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(key), '-out', str(cert), '-days', '1',
                        '-subj', '/CN=localhost'], check=True, capture_output=True)
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(503 if self.path == '/unhealthy' else 200)
                self.end_headers()
            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        cls.server.socket = context.wrap_socket(cls.server.socket, server_side=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'https://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.directory.cleanup()

    def probe(self, *, verify_tls=False, path='/'):
        service = {'vmid': 9070, 'name': 'test', 'healthcheck': {
            'type': 'http', 'timeout_seconds': 1, 'verify_tls': verify_tls}}
        # Only Proxmox command discovery is mocked; TLS and HTTP are real.
        with patch.object(installer, 'run', return_value='status: running'), \
             patch('oci_installation_state.container_curl', return_value=['curl']):
            installer.wait_web(service, self.url + path)

    def test_image_generated_certificate_passes_readiness(self):
        self.probe()

    def test_explicit_strict_tls_still_rejects_self_signed_certificate(self):
        with self.assertRaisesRegex(RuntimeError, 'HTTP check'):
            self.probe(verify_tls=True)

    def test_tls_tolerance_does_not_accept_http_failure(self):
        with self.assertRaisesRegex(RuntimeError, 'HTTP check'):
            self.probe(path='/unhealthy')


class NamespaceTLSReadiness(unittest.TestCase):
    def test_vlan_curl_obeys_the_same_verification_policy(self):
        for strict in (False, True):
            with self.subTest(strict=strict), \
                 patch('oci_installation_state.container_curl', return_value=['nsenter', '--net=/proc/123/ns/net', 'curl']), \
                 patch.object(installer, 'run') as run:
                installer.web_answers(9070, 'https://192.0.2.7/', None, verify_tls=strict)
                args = run.call_args.args
                self.assertEqual('--insecure' in args, not strict)
                self.assertIn('-fsS', args)
                self.assertIn('--noproxy', args)


if __name__ == '__main__':
    unittest.main()
