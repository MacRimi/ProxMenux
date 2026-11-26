"""The host update of the Monitor runs the update of the product the host has:
a Proxmox Backup Server gets its own, which needs no pveversion and keeps its
repositories."""

from pathlib import Path
import shlex
import sys
import tempfile
import time
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'AppImage/scripts'))
import host_update_jobs as jobs  # noqa: E402


def platform(product):
    module = ModuleType('pbs_manager')
    module.is_pbs_host = lambda: product == 'pbs'
    return patch.dict(sys.modules, {'pbs_manager': module})


class HostUpdatePlatformTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name)
        self.pve, self.pbs, self.ran = folder / 'pve.sh', folder / 'pbs.sh', folder / 'ran'
        for script, name in ((self.pve, 'pve'), (self.pbs, 'pbs')):
            script.write_text(f'echo {name} > {shlex.quote(str(self.ran))}\n')
        for name, value in (('SCRIPT', str(self.pve)), ('PBS_SCRIPT', str(self.pbs))):
            fixed = patch.object(jobs, name, value)
            fixed.start()
            self.addCleanup(fixed.stop)
        jobs._jobs.clear()
        self.addCleanup(jobs._jobs.clear)

    def run_job(self, identity):
        callback = Mock()
        job = jobs.start(identity, callback)
        limit = time.monotonic() + 6
        while job.state != 'complete' and time.monotonic() < limit:
            time.sleep(.02)
        return job, callback

    def test_a_pbs_host_runs_the_pbs_update(self):
        with platform('pbs'):
            self.assertEqual(jobs.update_script(), str(self.pbs))
            job, callback = self.run_job('pbs-host')
        self.assertEqual(self.ran.read_text().strip(), 'pbs')
        self.assertEqual(callback.call_args.args[0], str(self.pbs))

    def test_a_pve_host_keeps_the_proxmox_update(self):
        with platform('pve'):
            self.assertEqual(jobs.update_script(), str(self.pve))
            self.run_job('pve-host')
        self.assertEqual(self.ran.read_text().strip(), 'pve')

    def test_an_unknown_platform_keeps_the_proxmox_update(self):
        broken = ModuleType('pbs_manager')
        broken.is_pbs_host = Mock(side_effect=OSError('unreadable'))
        with patch.dict(sys.modules, {'pbs_manager': broken}):
            self.assertEqual(jobs.update_script(), str(self.pve))


if __name__ == '__main__':
    unittest.main()
