"""A Proxmox host without a subscription is refused by the enterprise
repositories on every apt refresh. The installers tell that apart from a
refresh that really failed."""
from pathlib import Path
import re
import subprocess
import tempfile
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[3]
INSTALLERS = ('install_proxmenux.sh', 'install_proxmenux_beta.sh')

ENTERPRISE = """Hit:1 http://deb.debian.org/debian trixie InRelease
Err:2 https://enterprise.proxmox.com/debian/ceph-squid trixie InRelease
  401  Unauthorized [IP: 51.91.38.34 443]
Err:4 https://enterprise.proxmox.com/debian/pve trixie InRelease
  401  Unauthorized [IP: 51.91.38.34 443]
Reading package lists...
E: Failed to fetch https://enterprise.proxmox.com/debian/ceph-squid/dists/trixie/InRelease  401  Unauthorized [IP: 51.91.38.34 443]
E: The repository 'https://enterprise.proxmox.com/debian/ceph-squid trixie InRelease' is not signed.
E: Failed to fetch https://enterprise.proxmox.com/debian/pve/dists/trixie/InRelease  401  Unauthorized [IP: 51.91.38.34 443]
E: The repository 'https://enterprise.proxmox.com/debian/pve trixie InRelease' is not signed.
"""
NETWORK = """Err:1 http://deb.debian.org/debian trixie InRelease
  Temporary failure resolving 'deb.debian.org'
E: Failed to fetch http://deb.debian.org/debian/dists/trixie/InRelease  Temporary failure resolving 'deb.debian.org'
"""
LOCKED = "E: Could not get lock /var/lib/apt/lists/lock. It is held by process 4321 (apt-get)\n"
# apt reports a repository it cannot reach as a warning, not as an error.
UNREACHABLE = """Err:6 http://repo.invalid/debian trixie InRelease
  Could not resolve 'repo.invalid'
W: Failed to fetch http://repo.invalid/debian/dists/trixie/InRelease  Could not resolve 'repo.invalid'
W: Some index files failed to download. They have been ignored, or old ones used instead.
"""


def function(installer, name):
    source = (ROOT / installer).read_text()
    return re.search(rf'^{name}\(\) \{{\n.*?^\}}\n', source, re.MULTILINE | re.DOTALL)[0]


class InstallerAptRefresh(TestCase):
    def refused(self, installer, log):
        with tempfile.NamedTemporaryFile('w', suffix='.log') as handle:
            handle.write(log)
            handle.flush()
            script = function(installer, 'apt_only_enterprise_refused') + \
                f'APT_ERROR_LOG={handle.name if log is not None else ""}\napt_only_enterprise_refused\n'
            return subprocess.run(['bash', '-c', script], capture_output=True).returncode == 0

    def test_a_refresh_refused_only_by_the_enterprise_repositories_is_good(self):
        for installer in INSTALLERS:
            self.assertTrue(self.refused(installer, ENTERPRISE), installer)

    def test_any_other_failure_is_still_a_failure(self):
        for installer in INSTALLERS:
            self.assertFalse(self.refused(installer, NETWORK), installer)
            self.assertFalse(self.refused(installer, LOCKED), installer)
            self.assertFalse(self.refused(installer, ENTERPRISE + NETWORK), installer)
            self.assertFalse(self.refused(installer, ENTERPRISE + UNREACHABLE), installer)
            self.assertFalse(self.refused(installer, 'Reading package lists...\n'), installer)

    def test_the_refresh_step_asks_before_it_warns(self):
        for installer in INSTALLERS:
            source = (ROOT / installer).read_text()
            step = source[source.index('if run_apt update -y; then'):]
            step = step[:step.index('\n    fi\n')]
            self.assertLess(step.index('elif apt_only_enterprise_refused; then'), step.index('apt cache refresh failed'))
            self.assertIn('discard_apt_error', step[step.index('elif'):step.index('else\n')])
