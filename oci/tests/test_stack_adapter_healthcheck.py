"""A stack application that answers at all is running.

Settings a user adds in Proxmox, such as the hosts Paperless or Tandoor allow,
may turn the plain request of the probe away with a 4xx. The update must not
fail for it: only no answer or a server error means the application is down."""
from pathlib import Path
import http.server
import socketserver
import subprocess
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'remote'))

import oci_stack_adapters  # noqa: E402

WEB_ADAPTERS = ('install_paperless_stack.sh', 'install_tandoor_stack.sh')


def probe(adapter, status):
    """Run the adapter's probe against a local server answering `status`."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.end_headers()
            self.wfile.write(b'x')

        def log_message(self, *args):
            pass

    server = socketserver.TCPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    code = oci_stack_adapters.ADAPTERS[adapter]['healthcheck'][2]
    local = f'http://127.0.0.1:{server.server_address[1]}/'
    code = code.replace('http://127.0.0.1:8000/', local).replace('http://127.0.0.1/', local)
    try:
        return subprocess.run([sys.executable, '-c', code], capture_output=True, timeout=30).returncode
    finally:
        server.server_close()


class StackAdapterHealthcheckTests(unittest.TestCase):
    def test_a_refused_host_still_means_the_application_is_up(self):
        for adapter in WEB_ADAPTERS:
            for status in (200, 302, 400, 403):
                with self.subTest(adapter=adapter, status=status):
                    self.assertEqual(probe(adapter, status), 0)

    def test_a_server_error_means_it_is_not_up_yet(self):
        for adapter in WEB_ADAPTERS:
            with self.subTest(adapter=adapter):
                self.assertNotEqual(probe(adapter, 502), 0)

    def test_no_answer_means_it_is_not_up_yet(self):
        for adapter in WEB_ADAPTERS:
            code = oci_stack_adapters.ADAPTERS[adapter]['healthcheck'][2]
            code = code.replace('http://127.0.0.1:8000/', 'http://127.0.0.1:1/').replace('http://127.0.0.1/', 'http://127.0.0.1:1/')
            with self.subTest(adapter=adapter):
                self.assertNotEqual(subprocess.run([sys.executable, '-c', code], capture_output=True, timeout=30).returncode, 0)


if __name__ == '__main__':
    unittest.main()
