"""Menu speedups avoid unused probes, retaining confirmation and capacity checks."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'remote')]
from proxmenux_oci import management as menu
import oci_instances as instances
import oci_instance_reconcile as reconcile
import oci_remove as remover
import oci_work_backup as backup


class UpdateEntryTests(unittest.TestCase):
    def run_update(self,approved,ready):
        events=[]
        record={'status':'installed','vmid':110,'deployment':{},'template':{}}
        row={'vmid':110,'reason':'matched','stack':False,'pending':False,'status':'installed'}
        ui=Mock();ui.unattended=True
        ui.review.side_effect=lambda *a,**kw:events.append('review') or approved
        with patch.object(menu,'carry_records',return_value={}) as carry, \
                patch.object(menu,'check_selected',return_value=row), \
                patch.object(menu,'_selected_configuration',return_value=b'current config'), \
                patch.object(instances,'read',return_value=record),patch.object(reconcile,'propose',return_value=None), \
                patch.object(menu,'_work_backup_ready',side_effect=lambda *a:events.append('backup') or ready), \
                patch.object(menu,'_run_lifecycle',side_effect=lambda *a:events.append('lifecycle') or True):
            result=menu.manage_instance(ROOT,ui,row,action='update')
        carry.assert_called_once_with(ROOT,vmids=[110],verify=True)
        return result,events

    def test_declining_update_does_not_probe_disks_or_storages(self):
        result,events=self.run_update(False,False)
        self.assertFalse(result);self.assertEqual(events,['review'])

    def test_accepted_update_checks_backup_space_before_starting(self):
        result,events=self.run_update(True,True)
        self.assertTrue(result);self.assertEqual(events,['review','backup','lifecycle'])

    def test_insufficient_space_still_prevents_the_update(self):
        result,events=self.run_update(True,False)
        self.assertFalse(result);self.assertEqual(events,['review','backup'])


class BackupDestinationTests(unittest.TestCase):
    def status(self,local_free,saved_free=None,only_needed=True):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);saved= root/'nas';saved.mkdir()
            record={'deployment':{backup.KEY:'nas'}}
            with patch.object(backup,'application',return_value=(110,[110,111])), \
                    patch.object(instances,'read',return_value=record), \
                    patch.object(backup,'required',return_value=100) as required, \
                    patch.object(backup,'available',side_effect=lambda p:saved_free if Path(p)==saved else local_free), \
                    patch.object(backup,'storage_path',return_value=saved if saved_free is not None else None) as path, \
                    patch.object(backup,'file_storages',return_value=[{'storage':'enough','free':200},{'storage':'small','free':50}]) as alternatives:
                result=backup.status(root,110,only_needed=only_needed)
            required.assert_called_once_with([110,111])
            return result,path.call_count,alternatives.call_count

    def test_local_room_avoids_saved_storage_and_alternative_queries(self):
        result,saved,alternatives=self.status(200,saved_free=1000)
        self.assertTrue(result['fits']);self.assertEqual((saved,alternatives),(0,0))

    def test_saved_destination_that_fits_avoids_alternative_queries(self):
        result,saved,alternatives=self.status(50,saved_free=200)
        self.assertTrue(result['saved_fits']);self.assertEqual((saved,alternatives),(1,0))

    def test_when_neither_fits_all_available_destinations_are_checked(self):
        result,saved,alternatives=self.status(50,saved_free=40)
        self.assertFalse(result['fits']);self.assertFalse(result['saved_fits'])
        self.assertEqual(result['candidates'],[{'storage':'enough','free':200}])
        self.assertEqual(alternatives,1)

    def test_missing_saved_storage_still_offers_alternatives(self):
        result,saved,alternatives=self.status(50)
        self.assertEqual(result['candidates'],[{'storage':'enough','free':200}])
        self.assertEqual(alternatives,1)

    def test_complete_status_keeps_legacy_fields_and_all_candidates(self):
        result,saved,alternatives=self.status(200,saved_free=300,only_needed=False)
        self.assertTrue(result['fits']);self.assertTrue(result['saved_fits'])
        self.assertEqual((saved,alternatives),(1,1))
        self.assertEqual(result['candidates'],[{'storage':'enough','free':200}])


class RemovalPreviewTests(unittest.TestCase):
    def preview(self,reader):
        record={'vmid':110,'deployment':{},'template':{'catalog_ui':{'title':'Example'}}}
        with patch.object(remover,'members_of',return_value=(110,record,[110])), \
                patch.object(instances,'read',return_value=record), \
                patch.object(menu,'_selected_configuration',side_effect=reader), \
                patch.object(remover,'guest_config',side_effect=AssertionError('Duplicate pct process')), \
                patch.object(remover,'host_directories',return_value=[]), \
                patch.object(remover,'private_bridge',return_value=None):
            return menu._removal_summary(ROOT,110)

    def test_preview_reuses_verified_config_and_keeps_volume_and_host_path_details(self):
        config=b'hostname: example\nrootfs: local:subvol-110-disk-0,size=8G\nmp0: /mnt/media,mp=/media,backup=0\n'
        text=self.preview(lambda v:config)
        self.assertIn('8G',text);self.assertIn('/mnt/media',text)
        self.assertIn('not targeted for removal',text)

    def test_missing_guest_can_still_be_reviewed_without_a_second_probe(self):
        text=self.preview(lambda v:(_ for _ in ()).throw(RuntimeError('guest missing')))
        self.assertIn('CT 110',text);self.assertIn('rootfs -',text)


if __name__=='__main__':unittest.main()
