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
    start = source.index('healthcheck_probe_url() {')
    end = source.index('\n}\n', source.index('healthcheck_probe() {')) + 3
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
            script = (probe_function() + '\noci_curl() { shift; curl "$@"; }\nCURL_ARGS=()\nHC_URLS=(http://192.0.2.1:3306/)\n'
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


ADGUARD = {'id': 'image-adguard-home',
           'first_run': {'endpoints': [{'label': 'Web UI', 'scheme': 'http', 'port': 3000, 'path': '/'}]}}


class SetupThenWebPortTests(unittest.TestCase):
    """AdGuard Home answers on 3000 until it is set up, then on 80: an update of
    a configured installation must not wait for the setup port."""

    def test_adguard_also_accepts_its_web_port(self):
        check = transaction.effective_healthcheck(ADGUARD)
        self.assertEqual((check['port'], check['alternative_ports']), (3000, [80]))
        self.assertNotIn('alternative_ports', transaction.effective_healthcheck(DECLARED))

    def test_a_check_saved_with_an_installation_takes_the_web_port_too(self):
        # An installation stores the check it was given: still on 3000 only.
        saved = {'scheme': 'http', 'port': 3000, 'path': '/', 'timeout_seconds': 300, 'accept_any_status': True}
        template = dict(ADGUARD, proxmox={'installer_profile': {'startup_healthcheck': saved}})
        self.assertEqual(transaction.effective_healthcheck(template)['alternative_ports'], [80])
        self.assertNotIn('alternative_ports', saved)
        other = dict(template, id='image-other')
        self.assertNotIn('alternative_ports', transaction.effective_healthcheck(other))

    def test_recovery_check_passes_on_the_web_port_when_setup_is_closed(self):
        check = transaction.effective_healthcheck(ADGUARD)
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

        def probe(args):
            return (b'200', 0) if args[-1].endswith(':80/') else (b'000', 7)
        with patch.object(transaction, 'run', side_effect=run), \
                patch.object(transaction, 'probe_http', side_effect=probe), \
                patch.object(transaction, 'log'):
            self.assertEqual(transaction.healthcheck(101, template), 'http://192.0.2.10:80/')

    def test_installer_probe_tries_every_address_and_keeps_the_one_that_answered(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'curl'
            fake.write_text('#!/bin/sh\nfor last; do :; done\ncase "$last" in *:80/) printf 200; exit 0;; esac\n'
                            'printf 000\nexit 7\n')
            fake.chmod(0o755)
            script = (probe_function() + '\noci_curl() { shift; curl "$@"; }\nCURL_ARGS=()\n'
                      'HC_URLS=(http://192.0.2.1:3000/ http://192.0.2.1:80/)\nHC_ANY_STATUS=true\n'
                      'healthcheck_probe && echo "$HC_URL"\n')
            env = {**os.environ, 'PATH': f'{directory}:{os.environ["PATH"]}'}
            done = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, 'http://192.0.2.1:80/'))


if __name__ == '__main__':
    unittest.main()
