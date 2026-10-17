"""Opening Modify avoids backup probes while preserving operation safeguards."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'remote')]
from proxmenux_oci import management as menu,recreation
import oci_carried_record as carried
import oci_instances as instances
import oci_instance_reconcile as reconcile
from proxmenux_oci.ui import UserCancelled


def record():
    return {'vmid': 115, 'installation_id': 'test-installation', 'status': 'installed',
            'observed': {'config_sha256': 'native-config-fingerprint'},
            'template': {'id': 'example-app', 'catalog_ui': {'title': 'Example'},
                         'container_contract': {'image': {'reference': 'example/app:latest'}},
                         'proxmox': {'installer_profile': {}}},
            'deployment': {'vmid': 115, 'hostname': 'example', 'resources': {'cores': 2, 'memory_mb': 512},
                           'network': {'bridge': 'vmbr0', 'ipv4': 'dhcp', 'gateway': None},
                           'rootfs': {'storage': 'local-zfs', 'size_gb': 8}, 'mounts': [
                               {'container_path': '/data', 'source': 'local-zfs',
                                'type': 'managed-volume', 'size_gb': 8, 'backup': True}],
                           'devices': [], 'security': {'unprivileged': True},
                           'environment': [{'name': 'PASSWORD', 'value': 'private-test-secret',
                                            'sensitive': True}]}}


class SelectedConfigTests(unittest.TestCase):
    def test_valid_source_keyed_cache_avoids_another_pct_process(self):
        with patch.object(carried,'configuration',create=True,return_value='description: current\n') as reader, \
                patch.object(instances,'command') as command:
            self.assertEqual(menu._selected_configuration(115),b'description: current\n')
        reader.assert_called_once_with(instances.ROOT,115)
        command.assert_not_called()

    def test_old_or_unavailable_cache_falls_back_to_pct(self):
        for reader in (None,Mock(return_value=None),Mock(return_value={}),Mock(side_effect=OSError('cache unavailable'))):
            with self.subTest(reader=reader),patch.object(carried,'configuration',reader,create=True), \
                    patch.object(instances,'command',return_value=b'live config') as command:
                self.assertEqual(menu._selected_configuration(115),b'live config')
                command.assert_called_once_with('pct','config','115')

    def test_identity_check_is_still_performed_on_the_selected_config(self):
        r=record();r['installation_id']='11111111-1111-4111-8111-111111111111'
        import contextlib
        with patch.object(instances,'locked',return_value=contextlib.nullcontext()), \
                patch.object(instances,'read',return_value=r), \
                patch.object(menu,'_selected_configuration',return_value=b'description: another container\n'):
            self.assertEqual(menu.check_selected(ROOT,{'vmid':115})['reason'],'identity-unconfirmed')


class EditorLatencyTests(unittest.TestCase):
    def run_editor(self,proposal=None,backup_ready=True,stale=False,adoption_error=False,approved=True,declined=False):
        events=[];saved=record()
        row={'vmid':115,'reason':'matched','stack':False,'pending':False,'status':'installed'}
        def edit(*a,**kw):
            events.append('editor')
            if declined:return None
            if proposal is None:raise UserCancelled()
            return proposal
        def backup(*a,**kw):events.append('backup');return backup_ready
        ui=Mock();ui.unattended=True;ui.review.return_value=approved
        with patch.object(menu,'carry_records',return_value={115:'stale'} if stale else {}) as verify, \
                patch.object(menu,'check_selected',return_value=row), \
                patch.object(menu,'_selected_configuration',return_value=b'current config'), \
                patch.object(instances,'read',return_value=saved), \
                patch.object(reconcile,'propose',side_effect=ValueError('external changes') if adoption_error else None,return_value=None), \
                patch.object(recreation,'edit_recreation',side_effect=edit), \
                patch.object(menu,'_work_backup_ready',side_effect=backup), \
                patch.object(menu,'_run_lifecycle',side_effect=lambda *a:events.append('lifecycle') or True):
            try:result=menu.manage_instance(ROOT,ui,row,action='modify')
            except UserCancelled:result=False
        verify.assert_called_once_with(ROOT,vmids=[115],verify=True)
        return result,events

    def test_open_and_cancel_has_no_backup_or_storage_probes(self):
        result,events=self.run_editor()
        self.assertFalse(result);self.assertEqual(events,['editor'])

    def test_declining_the_review_has_no_backup_or_storage_probes(self):
        # The review is part of the Modify menu: declining it and leaving the
        # menu returns no proposal, so no probe or operation follows.
        result,events=self.run_editor(declined=True)
        self.assertFalse(result);self.assertEqual(events,['editor'])

    def test_confirmed_edit_keeps_backup_check_before_the_lifecycle(self):
        result,events=self.run_editor({'operation':'recreate','candidate':record()})
        self.assertTrue(result);self.assertEqual(events,['editor','backup','lifecycle'])

    def test_missing_backup_space_still_prevents_the_lifecycle(self):
        result,events=self.run_editor({'operation':'recreate','candidate':record()},backup_ready=False)
        self.assertFalse(result);self.assertEqual(events,['editor','backup'])

    def test_restored_or_conflicting_instance_cannot_enter_editor(self):
        for options in ({'stale':True},{'adoption_error':True}):
            result,events=self.run_editor(**options)
            self.assertFalse(result);self.assertEqual(events,[])


if __name__=='__main__':unittest.main()
