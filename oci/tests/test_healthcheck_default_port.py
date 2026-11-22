"""The startup check asks for the address a browser would use: without the
default port of its scheme. Nextcloud trusts the host of its first request."""
from pathlib import Path
import re
import subprocess
import unittest

SCRIPT = (Path(__file__).resolve().parents[1] / 'remote/install_oci.sh').read_text()


def url(scheme, port, path='/'):
    function = re.search(r'^healthcheck_url\(\) \{\n.*?^\}\n', SCRIPT, re.M | re.S).group(0)
    done = subprocess.run(['bash', '-c', function + f'HC_SCHEME={scheme} IP=192.0.2.10 HC_PATH={path}; healthcheck_url {port}'],
                          capture_output=True, text=True, check=True)
    return done.stdout


class HealthcheckUrlTests(unittest.TestCase):
    def test_default_ports_are_left_out(self):
        self.assertEqual(url('https', 443), 'https://192.0.2.10/')
        self.assertEqual(url('http', 80, '/status'), 'http://192.0.2.10/status')

    def test_other_ports_are_kept(self):
        self.assertEqual(url('http', 443), 'http://192.0.2.10:443/')
        self.assertEqual(url('https', 8443), 'https://192.0.2.10:8443/')
        self.assertEqual(url('http', 3000), 'http://192.0.2.10:3000/')

    def test_every_probe_address_uses_it(self):
        self.assertIn('HC_URL=$(healthcheck_url "$HC_PORT")', SCRIPT)
        self.assertIn('HC_URLS+=("$(healthcheck_url "$HC_ALT_PORT")")', SCRIPT)


if __name__ == '__main__':
    unittest.main()
