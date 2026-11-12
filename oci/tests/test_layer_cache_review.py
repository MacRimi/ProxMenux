"""Complete OCI references and optional-cache failures must not break updates."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'remote'),str(Path(__file__).parent)]
import oci_layer_cache as cache
import oci_update_current as update
from verify_oci_archive import verify_archive, VerificationError
from test_stack_image_cache import archive_fixture

class References(unittest.TestCase):
    def test_every_referenced_blob_is_mandatory_even_if_present_blobs_are_intact(self):
        with tempfile.TemporaryDirectory() as d:
            original=Path(d)/'valid.tar'; archive_fixture(original,'test')
            with tarfile.open(original) as tar:
                entries=[(m.name,tar.extractfile(m).read()) for m in tar.getmembers()]
            # Drop individually: layer, config and manifest, while keeping OCI metadata.
            blobs=[name for name,data in entries if name.startswith('blobs/')]
            for absent in blobs:
                broken=Path(d)/'broken.tar'
                with tarfile.open(broken,'w') as tar:
                    for name,data in entries:
                        if name==absent: continue
                        info=tarfile.TarInfo(name);info.size=len(data);tar.addfile(info,io.BytesIO(data))
                with self.subTest(absent=absent),self.assertRaises(VerificationError):verify_archive(broken)

    def test_manifest_descriptor_size_and_duplicate_metadata_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            original=Path(d)/'valid.tar';archive_fixture(original,'test')
            with tarfile.open(original) as tar:entries={m.name:tar.extractfile(m).read() for m in tar.getmembers()}
            index=json.loads(entries['index.json']);index['manifests'][0]['size']+=1
            for duplicate in (False,True):
                broken=Path(d)/'broken.tar'
                with tarfile.open(broken,'w') as tar:
                    for name,data in entries.items():
                        if name=='index.json' and not duplicate:data=json.dumps(index).encode()
                        info=tarfile.TarInfo(name);info.size=len(data);tar.addfile(info,io.BytesIO(data))
                        if duplicate and name=='index.json':tar.addfile(info,io.BytesIO(data))
                with self.subTest(duplicate=duplicate),self.assertRaises(VerificationError):verify_archive(broken)

class OptionalCache(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'cache';cache.prepare(self.root)

    def test_only_candidate_blob_contents_are_hashed(self):
        paths=[]
        for data in (b'wanted',b'unrelated'):
            p=self.root/'sha256'/hashlib.sha256(data).hexdigest();p.write_bytes(data);paths.append(p)
        with patch.object(cache,'hash_file',wraps=cache.hash_file) as hashed:
            cache.validate_blobs(self.root,{'sha256:'+paths[0].name})
        self.assertEqual([c.args[0] for c in hashed.call_args_list],[paths[0]])

    def test_pruning_removes_the_blob_lock_together_with_its_blob(self):
        digest=hashlib.sha256(b'content').hexdigest();blob=self.root/'sha256'/digest;blob.write_bytes(b'content')
        with cache.locked(self.root,blob=digest):pass
        self.assertTrue((self.root/'locks'/(digest+'.lock')).exists())
        cache.prune(self.root,0)
        self.assertFalse((self.root/'locks'/(digest+'.lock')).exists())

    def test_invalid_budget_is_rejected_before_the_pull_or_prune(self):
        with patch.dict(os.environ,{'PROXMENUX_OCI_LAYER_CACHE_BYTES':'not-a-number'}), \
             patch.object(cache,'prune') as prune:
            run=Mock()
            with self.assertRaises(cache.CacheUnavailable):cache.pull('docker://image','amd64',self.root.parent/'out',[],{},run)
            run.assert_not_called();prune.assert_not_called()

    def test_pruning_error_does_not_replace_original_registry_error(self):
        with patch.dict(os.environ,{'PROXMENUX_OCI_LAYER_CACHE_ROOT':str(self.root)}), \
             patch.object(cache,'prune',side_effect=ValueError('cleanup unavailable')),patch.object(cache,'msg_warn'):
            with self.assertRaisesRegex(RuntimeError,'registry rejected credentials'):
                cache.pull('docker://image','amd64',self.root.parent/'out',[],{},Mock(side_effect=RuntimeError('registry rejected credentials')))

    def test_cache_local_errors_fall_back_to_complete_download_and_verification(self):
        for fault in ('empty-marker','foreign-entry','permissions','invalid-budget'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as d:
                root=Path(d);local=root/'cache';cache.prepare(local)
                env={'PROXMENUX_OCI_LAYER_CACHE':'1','PROXMENUX_OCI_LAYER_CACHE_ROOT':str(local)}
                if fault=='empty-marker':(local/'format.json').write_text('')
                elif fault=='foreign-entry':(local/'sha256'/'foreign').write_text('keep')
                elif fault=='permissions':local.chmod(0o755)
                elif fault=='invalid-budget':env['PROXMENUX_OCI_LAYER_CACHE_BYTES']='broken'
                source=root/'source.tar';candidate=archive_fixture(source,'new');candidate['registry_digest']=candidate['manifest_digest']
                output=root/'resolved.tar';downloads=[]
                def quiet(args,*a,**kw):
                    if '-c' in args:return json.dumps(candidate)
                    if args[0]=='skopeo':
                        self.assertTrue(args[-1].startswith('oci-archive:'))
                        downloads.append(args);shutil.copyfile(source,args[-1].removeprefix('oci-archive:'))
                    else:verify_archive(Path(args[-1]))
                record={'template':{'container_contract':{'image':{'reference':'example/app:latest'}}},'deployment':{'template_storage':'local'}}
                with patch.dict(os.environ,env),patch.object(update.instances,'command',return_value=str(output).encode()), \
                     patch.object(update,'run_quiet',side_effect=quiet),patch.object(update.transaction,'log'), \
                     patch.object(update.work_backup,'available',return_value=1024**4),patch.object(update,'msg_warn') as warn:
                    path,digest=update.resolve_archive(record,b'arch: amd64\n')
                self.assertEqual(path,output);self.assertEqual(len(downloads),1);warn.assert_called_once()
                verify_archive(output)
                if fault=='foreign-entry':self.assertEqual((local/'sha256'/'foreign').read_text(),'keep')

if __name__=='__main__':unittest.main()
