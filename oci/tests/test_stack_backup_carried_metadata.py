"""A coordinated native backup must contain its verified, original restore recipe."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'remote'))
import oci_stack_native as native

class StackBackupCarriedMetadataTests(unittest.TestCase):
    def adapter(self, folder):
        adapter=object.__new__(native.NativeAdapter)
        adapter.root=Path('/unused/registry')
        adapter.journal=Path(folder)/'transaction.json'
        adapter.plan={'primary_vmid':4901}
        adapter.records={4901:{'vmid':4901,'installation_id':'original','status':'installed'}}
        return adapter

    def test_transaction_id_does_not_replace_container_identity_before_archive_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter=self.adapter(folder);events=[]
            archive=Path(folder)/'archive.tar.zst'
            with patch.object(adapter,'validate'),patch.object(adapter,'work_base',return_value=Path(folder)), \
                 patch.object(native.member_tx,'owned',return_value=b'validated original config') as owned, \
                 patch.object(native.carried,'carry_backup',side_effect=lambda *args:events.append(('carry',args)),create=True), \
                 patch.object(native.member_tx,'verified_backup',side_effect=lambda *args:events.append(('backup',args)) or archive), \
                 patch.object(native.member_tx,'filehash',return_value='verified-sha'):
                result=adapter.backup(4901,'different-transaction-id')
            owned.assert_called_once_with(4901,'original')
            self.assertEqual([event[0] for event in events],['carry','backup'])
            self.assertEqual(events[0][1],(adapter.root,4901,adapter.records[4901],'validated original config'))
            self.assertEqual(result,{'archive':str(archive),'sha256':'verified-sha'})

    def test_missing_restore_metadata_prevents_archive_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter=self.adapter(folder)
            with patch.object(adapter,'validate'),patch.object(adapter,'work_base',return_value=Path(folder)), \
                 patch.object(native.member_tx,'owned',return_value=b'validated original config'), \
                 patch.object(native.carried,'carry_backup',side_effect=ValueError('metadata not verified'),create=True), \
                 patch.object(native.member_tx,'verified_backup') as backup:
                with self.assertRaisesRegex(ValueError,'metadata not verified'):
                    adapter.backup(4901,'different-transaction-id')
            backup.assert_not_called()
