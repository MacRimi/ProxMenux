"""Each host backup in the list carries the node it belongs to, read from its
name, so a cluster node can show its own backups apart from the others, and
a local backup says when the job that made it no longer exists."""
import ast
import os
from pathlib import Path
import re
import shlex
import tempfile
import unittest

SERVER = Path(__file__).resolve().parents[1] / 'flask_server.py'
HELPERS = ('_parse_job_env', '_host_backup_own_names', '_host_backup_node',
           '_host_backup_from_former_job')


class HostBackupNodeTests(unittest.TestCase):
    def setUp(self):
        text = SERVER.read_text(encoding='utf-8')
        tree = ast.parse(text)
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in HELPERS]
        self.assertEqual(sorted(n.name for n in nodes), sorted(HELPERS))
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.jobs = folder.name
        self.scope = {'os': os, 're': re, 'shlex': shlex,
                      '_BACKUP_JOBS_DIR': self.jobs,
                      '_BACKUP_TAR_SUFFIXES': ('.tar', '.tar.zst', '.tar.gz'),
                      '_HOST_BACKUP_STAMP_RE': re.compile(r'-\d{8}_\d{6}$')}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SERVER), 'exec'), self.scope)
        self.own_names = self.scope['_host_backup_own_names']
        self.node = self.scope['_host_backup_node']
        self.former = self.scope['_host_backup_from_former_job']

    def job(self, job_id, backup_id=None):
        lines = [f'JOB_ID={job_id}']
        if backup_id:
            lines.append(f'PBS_BACKUP_ID={backup_id}')
        Path(self.jobs, f'{job_id}.env').write_text('\n'.join(lines) + '\n')

    def test_the_default_name_says_the_node(self):
        own = self.own_names('pve1')
        self.assertEqual(self.node('hostcfg-pve1', 'pve1', own), 'pve1')
        self.assertEqual(self.node('hostcfg-pve2', 'pve1', own), 'pve2')

    def test_a_local_archive_name_says_the_node(self):
        own = self.own_names('pve1')
        self.assertEqual(self.node('hostcfg-pve2-20261014_031500.tar.zst', 'pve1', own), 'pve2')

    def test_a_job_of_this_node_is_this_node(self):
        self.job('nightly-pbs', backup_id='my-host-config')
        own = self.own_names('pve1')
        self.assertEqual(self.node('nightly-pbs-20261014_031500.tar.zst', 'pve1', own), 'pve1')
        self.assertEqual(self.node('my-host-config', 'pve1', own), 'pve1')

    def test_a_name_that_does_not_say_is_unknown(self):
        own = self.own_names('pve1')
        self.assertIsNone(self.node('custom-backup', 'pve1', own))
        self.assertIsNone(self.node('hostcfg-', 'pve1', own))
        self.assertIsNone(self.node(None, 'pve1', own))

    def test_a_missing_jobs_folder_leaves_the_default_name(self):
        self.scope['_BACKUP_JOBS_DIR'] = os.path.join(self.jobs, 'absent')
        self.assertEqual(self.own_names('pve1'), {'hostcfg-pve1'})

    def sidecar(self, job_id, hostname='pve1'):
        return {'kind': 'scheduled', 'job_id': job_id, 'source_hostname': hostname,
                'detected_via': 'sidecar'}

    def test_a_backup_of_a_job_that_no_longer_exists_is_from_a_former_job(self):
        self.assertTrue(self.former(self.sidecar('PVE1-local-backuo'), 'pve1', {'PVE1-local-backup'}))

    def test_a_backup_of_an_existing_job_is_not(self):
        self.assertFalse(self.former(self.sidecar('PVE1-local-backup'), 'pve1', {'PVE1-local-backup'}))

    def test_a_backup_made_on_another_node_is_left_unknown(self):
        self.assertFalse(self.former(self.sidecar('pve2-nightly', hostname='pve2'), 'pve1', set()))

    def test_a_backup_without_its_sidecar_is_left_unknown(self):
        for info in ({'kind': 'legacy', 'job_id': None, 'source_hostname': None, 'detected_via': 'tar_peek'},
                     {'kind': 'manual', 'job_id': None, 'source_hostname': None, 'detected_via': 'hostcfg_prefix'}):
            self.assertFalse(self.former(info, 'pve1', set()))

    def test_a_manual_backup_has_no_job(self):
        info = self.sidecar(None)
        info['kind'] = 'manual'
        self.assertFalse(self.former(info, 'pve1', set()))


if __name__ == '__main__':
    unittest.main()
