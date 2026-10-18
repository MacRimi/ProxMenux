"""A web address guessed from the compose file may belong to a service that does
not speak HTTP. Updates, Modify and recovery must accept its answer instead of
waiting for an HTTP reply that never comes."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'remote'))

import oci_instance_transaction as transaction

INSTALLER = ROOT / 'remote/install_oci.sh'
GUESSED = {'first_run': {'endpoints': [{'label': 'Web UI', 'scheme': 'http', 'port': 3306, 'path': '/',
                                        'source': 'compose-first-tcp-port-fallback'}]}}
DECLARED = {'first_run': {'endpoints': [{'label': 'Web UI', 'scheme': 'http', 'port': 8080, 'path': '/'}]}}


def probe_function():
    source = INSTALLER.read_text()
    start = source.index('healthcheck_probe() {')
    end = source.index('\n}\n', start) + 3
    return source[start:end]


class GuessedEndpointCheckTests(unittest.TestCase):
    def test_only_a_guessed_endpoint_accepts_other_protocols(self):
        self.assertTrue(transaction.effective_healthcheck(GUESSED)['accept_non_http'])
        self.assertNotIn('accept_non_http', transaction.effective_healthcheck(DECLARED))

    def run_probe(self, exit_code, code='000', accept_non_http='true', any_status='true'):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'curl'
            fake.write_text(f'#!/bin/sh\nprintf %s {code}\nexit {exit_code}\n')
            fake.chmod(0o755)
            script = (probe_function() + '\nCURL_ARGS=()\nHC_URL=http://192.0.2.1:3306/\n'
                      f'HC_ANY_STATUS={any_status}\nHC_ACCEPT_NON_HTTP={accept_non_http}\nhealthcheck_probe\n')
            env = {**os.environ, 'PATH': f'{directory}:{os.environ["PATH"]}'}
            return subprocess.run(['bash', '-c', script], env=env, capture_output=True).returncode

    def test_installer_probe_accepts_a_non_http_answer_only_when_guessed(self):
        for status in transaction.NON_HTTP_ANSWER:
            with self.subTest(status=status):
                self.assertEqual(self.run_probe(status), 0)
                self.assertNotEqual(self.run_probe(status, accept_non_http='false'), 0)
        # A closed port, a timeout or a server error still fail.
        for status, code in ((7, '000'), (28, '000'), (0, '503')):
            with self.subTest(status=status, code=code):
                self.assertNotEqual(self.run_probe(status, code), 0)
        self.assertEqual(self.run_probe(0, '200'), 0)
        self.assertEqual(self.run_probe(0, any_status='false', accept_non_http='false'), 0)

    def test_recovery_check_accepts_a_database_answer(self):
        check = transaction.effective_healthcheck(GUESSED)
        check.update(timeout_seconds=6, stability_seconds=0)
        template = {'proxmox': {'installer_profile': {'startup_healthcheck': check}}}

        def run(*args):
            if args[:2] == ('pct', 'status'):
                return b'status: running\n'
            if args[:2] == ('pct', 'config'):
                return b''
            if args[0] == 'lxc-info':
                return b'192.0.2.10\n'
            raise AssertionError(args)

        with patch.object(transaction, 'run', side_effect=run), \
                patch.object(transaction, 'probe_http', return_value=(b'000', 1)), \
                patch.object(transaction, 'log'):
            self.assertEqual(transaction.healthcheck(113, template), 'http://192.0.2.10:3306/')
        declared = transaction.effective_healthcheck(DECLARED)
        declared.update(timeout_seconds=4, stability_seconds=0)
        template = {'proxmox': {'installer_profile': {'startup_healthcheck': declared}}}
        with patch.object(transaction, 'run', side_effect=run), \
                patch.object(transaction, 'probe_http', return_value=(b'000', 1)), \
                patch.object(transaction, 'log'), patch.object(transaction.time, 'sleep'):
            with self.assertRaises(ValueError):
                transaction.healthcheck(113, template)


if __name__ == '__main__':
    unittest.main()
