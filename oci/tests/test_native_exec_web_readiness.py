"""A passing exec check cannot commit an update whose published web service fails."""
import http.server
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'remote'))
import oci_stack_native as native


class Reply(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(self.server.reply_status)
        self.end_headers()
    def log_message(self, *args):
        pass


class NativeExecWebReadinessTests(unittest.TestCase):
    def adapter(self, url=None, frontend=True):
        check = {'type': 'exec', 'argv': ['true'], 'timeout_seconds': 1}
        if url:
            check.update(url=url, endpoint={'port': 80})
        member = {'vmid': 4800, 'deployment': {}, 'stack': {'deployment': {'services': [
            {'vmid': 4800, 'name': 'service', 'frontend': frontend, 'healthcheck': check}]}}}
        return native.NativeAdapter(Path('/registry'), Path('/journal'),
                                    {'members': [member], 'primary_vmid': 4800})

    def check_web(self, status):
        server = http.server.HTTPServer(('127.0.0.1', 0), Reply)
        server.reply_status = status
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        adapter = self.adapter(f'http://127.0.0.1:{server.server_port}/')
        probes = []
        def execute(*args):
            probes.append(args[0])
            if args[0] == 'pct':
                return b''  # The custom CMD succeeded; web readiness is independent.
            result = subprocess.run(args, capture_output=True, timeout=5)
            if result.returncode:
                raise RuntimeError('HTTP endpoint is not ready')
            return result.stdout
        try:
            with patch.object(adapter, 'is_running', return_value=True), \
                 patch.object(native.member_tx.gpu_devices, 'validate_runtime'), \
                 patch.object(native.member_tx, 'run', side_effect=execute), \
                 patch.object(native.time, 'monotonic', side_effect=[0, 0, 2]), \
                 patch.object(native.time, 'sleep'):
                if status >= 400:
                    with self.assertRaisesRegex(ValueError, 'service check'):
                        adapter.healthcheck(4800)
                else:
                    adapter.healthcheck(4800)
            self.assertEqual(probes, ['pct', 'pct', 'curl'])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_http_failure_rejects_even_when_exec_succeeds(self):
        self.check_web(503)

    def test_web_and_exec_must_both_pass(self):
        self.check_web(200)

    def test_database_exec_without_frontend_keeps_its_existing_check(self):
        adapter = self.adapter(frontend=False)
        with patch.object(adapter, 'is_running', return_value=True), \
             patch.object(native.member_tx.gpu_devices, 'validate_runtime'), \
             patch.object(native.member_tx, 'run', return_value=b'') as run:
            adapter.healthcheck(4800)
        run.assert_called_once_with('pct', 'exec', '4800', '--', 'true')


if __name__ == '__main__':
    unittest.main()
