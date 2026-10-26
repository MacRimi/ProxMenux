"""A health problem of a VM or CT names the guest in its title, and health
categories are shown by their name, not by their internal key."""
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import notification_templates as templates

QMP = {'category': 'vms', 'severity': 'WARNING', 'error_key': 'vm_101',
       'reason': 'VM 101 (web): QMP command failed or timed out.',
       'id': '101', 'vmname': 'web', 'type': 'VM'}


class VmHealthTitleTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(templates, '_get_hostname', return_value='pve')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_guest_problem_names_the_guest(self):
        title = templates.render_template('system_problem', dict(QMP))['title']
        self.assertEqual(title, 'pve: System problem detected — VM 101 (web)')

    def test_a_container_without_a_name_is_named_by_its_id(self):
        data = dict(QMP, id='105', vmname='', type='CT')
        self.assertTrue(templates.render_template('system_problem', data)['title'].endswith('— CT 105'))

    def test_the_recovery_names_the_category_and_the_guest(self):
        data = dict(QMP, severity='OK', original_severity='WARNING', duration='6m', is_recovery=True)
        title = templates.render_template('error_resolved', data)['title']
        self.assertEqual(title, 'pve: Resolved - VMs and containers — VM 101 (web)')

    def test_the_category_follows_the_language_of_the_reader(self):
        data = dict(QMP, severity='OK', original_severity='WARNING', duration='6m', is_recovery=True)
        title = templates.render_template('error_resolved', data, 'es')['title']
        self.assertIn('Máquinas virtuales y contenedores', title)
        self.assertNotIn(' vms', title)

    def test_a_category_without_a_name_keeps_its_key(self):
        data = {'category': 'temperature', 'severity': 'OK', 'reason': 'Back to normal',
                'original_severity': 'WARNING', 'duration': '3m', 'is_recovery': True}
        self.assertIn('Resolved - temperature', templates.render_template('error_resolved', data)['title'])

    def test_other_events_with_an_id_are_not_given_a_guest(self):
        data = {'category': 'storage', 'severity': 'WARNING', 'reason': 'x', 'id': '7', 'type': 'VM'}
        self.assertNotIn('VM 7', templates.render_template('system_problem', data)['title'])


if __name__ == '__main__':
    unittest.main()
