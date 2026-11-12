"""Shared blobs stay checked, bounded and export as native-readable OCI archives."""
import concurrent.futures
import errno
import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
import shutil
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'remote'))
import oci_layer_cache as layers
from test_stack_image_cache import archive_fixture
from verify_oci_archive import verify_archive
import oci_update_current as update

class LayerCache(unittest.TestCase):
 def test_cache_is_opt_in(self):
  with patch.dict(os.environ,{},clear=True):self.assertFalse(layers.enabled())
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name)/'cache';layers.prepare(self.root)
 def blob(self,data):
  name=hashlib.sha256(data).hexdigest();path=self.root/'sha256'/name;path.write_bytes(data);return path
 def test_skopeo_callback_receives_cluster_auth_and_keeps_explicit_auth(self):
  for selected in (None,'/explicit/auth.json'):
   env={'PROXMENUX_OCI_LAYER_CACHE_ROOT':str(self.root)}
   if selected:env['REGISTRY_AUTH_FILE']=selected
   seen=[]
   with patch.dict(os.environ,env,clear=True),patch.object(layers.os.path,'isfile',return_value=True),patch.object(layers,'pack'):
    layers.pull('docker://private/app','amd64',self.root.parent/'archive.tar',[],{'layers':[]},lambda _:seen.append(os.environ.get('REGISTRY_AUTH_FILE')))
   self.assertEqual(seen,[selected or layers.REGISTRY_AUTH_FILE])
 def test_corrupt_blob_is_removed_before_skopeo_can_reuse_it(self):
  path=self.blob(b'good');path.write_bytes(b'bad')
  with layers.locked(self.root):self.assertEqual(layers.validate_blobs(self.root),[path.name])
  self.assertFalse(path.exists())
 def test_valid_blobs_are_retained(self):
  path=self.blob(b'good')
  with layers.locked(self.root):self.assertEqual(layers.validate_blobs(self.root),[])
  self.assertEqual(path.read_bytes(),b'good')
 def test_symlinks_are_rejected_without_touching_the_target(self):
  target=self.root/'target';target.write_text('keep');name='0'*64
  (self.root/'sha256'/name).symlink_to(target)
  with self.assertRaises(ValueError):layers.validate_blobs(self.root)
  self.assertEqual(target.read_text(),'keep')
 def test_pruning_is_bounded_and_keeps_recent_blobs(self):
  older=self.blob(b'a'*10);os.utime(older,(1,1));recent=self.blob(b'b'*10)
  self.assertEqual(layers.prune(self.root,10),10);self.assertFalse(older.exists());self.assertTrue(recent.exists())
 def test_foreign_nonempty_directory_is_not_adopted(self):
  other=self.root.parent/'foreign';other.mkdir(mode=0o700);(other/'keep').write_text('data')
  with self.assertRaises(ValueError):layers.prepare(other)
  self.assertEqual((other/'keep').read_text(),'data')
 def test_seed_only_copies_requested_content_addressed_blobs(self):
  archive=self.root.parent/'image.tar';image=archive_fixture(archive,'old')
  wanted=set(image['layers'])
  with layers.locked(self.root):layers.seed(self.root,[str(archive)],wanted)
  self.assertEqual({p.name for p in(self.root/'sha256').iterdir()},{x[7:]for x in wanted})
 def test_export_is_self_contained_and_native_import_can_read_members(self):
  source=self.root.parent/'source.tar';archive_fixture(source,'old')
  layout=self.root/'layout-test';layout.mkdir()
  with tarfile.open(source)as archive:
   for member in archive.getmembers():
    content=archive.extractfile(member).read()
    destination=layout/member.name if '/'not in member.name else self.root/'sha256'/member.name.rsplit('/',1)[-1]
    destination.write_bytes(content);destination.chmod(0o600)
  exported=self.root.parent/'export.tar';layers.pack(layout,self.root,exported)
  verify_archive(exported)
  with tarfile.open(exported)as archive:
   self.assertTrue(all(m.uid==m.gid==0 and m.mode==0o644 for m in archive.getmembers()))
 def test_concurrent_initialization_has_one_complete_private_format(self):
  root=self.root.parent/'concurrent'
  with concurrent.futures.ThreadPoolExecutor(max_workers=4)as executor:
   list(executor.map(lambda _:layers.prepare(root),range(12)))
  self.assertEqual(json.loads((root/'format.json').read_text())['kind'],layers.KIND)
  self.assertEqual(root.stat().st_mode&0o777,0o700)
 def test_space_budget_covers_both_files_on_the_same_filesystem(self):
  available=Mock(return_value=int(100*1.1)+256*1024**2)
  with self.assertRaises(OSError)as caught:layers.check_space(self.root,self.root.parent,100,available)
  self.assertEqual(caught.exception.errno,errno.ENOSPC)
 def test_space_budget_checks_a_separate_cache_filesystem(self):
  cache=Mock();cache.stat.return_value=SimpleNamespace(st_dev=1)
  archive=Mock();archive.stat.return_value=SimpleNamespace(st_dev=2)
  with self.assertRaises(OSError)as caught:
   layers.check_space(cache,archive,100,lambda p:0 if p is cache else 1024**4)
  self.assertEqual(caught.exception.errno,errno.ENOSPC)
 def test_failed_pull_does_not_leave_a_temporary_layout_or_export(self):
  target=self.root.parent/'failed.tar'
  with patch.dict(os.environ,{'PROXMENUX_OCI_LAYER_CACHE_ROOT':str(self.root)}):
   with self.assertRaisesRegex(RuntimeError,'registry unavailable'):
    layers.pull('docker://example/private','amd64',target,[],{'size':1},Mock(side_effect=RuntimeError('registry unavailable')))
  self.assertFalse(target.exists());self.assertEqual(list(self.root.glob('layout-*')),[])


class Resolver(unittest.TestCase):
 def test_enabled_cache_seeds_the_old_archive_and_still_fully_verifies_export(self):
  with tempfile.TemporaryDirectory()as folder:
   root=Path(folder);old=root/'old.tar';archive_fixture(old,'old');before=old.read_bytes()
   new=root/'new.tar';candidate=archive_fixture(new,'new');candidate['registry_digest']='sha256:'+'f'*64
   destination=root/'resolved.tar';calls=[];verified=[]
   def quiet(args,*a,**kw):
    if '-c'in args:return json.dumps(candidate)
    self.assertEqual(Path(args[1]).name,'verify_oci_archive.py');verified.append(Path(args[-1]));verify_archive(Path(args[-1]))
   def pull(source,arch,output,seeds,*a,**kw):
    calls.append((source,arch,seeds));shutil.copyfile(new,output)
   record={'template':{'container_contract':{'image':{'reference':'example/app:latest'}}},'deployment':{'template_storage':'local'}}
   with patch.dict(os.environ,{'PROXMENUX_OCI_LAYER_CACHE':'1'}),patch.object(update.instances,'command',return_value=str(destination).encode()),patch.object(update,'run_quiet',side_effect=quiet),patch.object(update.transaction,'log'),patch.object(update.work_backup,'available',return_value=1024**4),patch.object(layers,'pull',side_effect=pull):
    result,digest=update.resolve_archive(record,b'arch: amd64\n',local_archives=[str(old)])
   self.assertEqual(result,destination);self.assertEqual(digest,candidate['manifest_digest'])
   self.assertEqual(calls,[('docker://example/app@'+candidate['manifest_digest'],'amd64',[str(old)])])
   self.assertEqual(len(verified),2);self.assertEqual(old.read_bytes(),before)
   verify_archive(destination)

if __name__=="__main__":unittest.main()
