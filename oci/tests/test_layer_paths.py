"""Import copies preserve image content while keeping native path checks intact."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'remote')]
import oci_layer_paths as paths
import oci_runtime as runtime
from verify_oci_archive import verify_archive


def fixture(path, entries, compression='gzip'):
    layer=io.BytesIO()
    with tarfile.open(fileobj=layer,mode='w',format=tarfile.PAX_FORMAT)as tar:
        for name,kind,body in entries:
            item=tarfile.TarInfo(name);item.mode=0o755 if kind=='dir' else 0o644;item.uid=25;item.gid=26
            if kind=='dir':item.type=tarfile.DIRTYPE;tar.addfile(item)
            elif kind in ('sym','hard'):
                item.type=tarfile.SYMTYPE if kind=='sym' else tarfile.LNKTYPE;item.linkname=body;tar.addfile(item)
            else:
                item.size=len(body);item.pax_headers={'path':name,'SCHILY.xattr.user.test':'preserved'};tar.addfile(item,io.BytesIO(body))
    raw=layer.getvalue()
    content=(gzip.compress(raw) if compression=='gzip' else subprocess.check_output(['zstd','-cq'],input=raw) if compression=='zstd' else raw)
    with tarfile.open(path,'w')as tar:
        def add(name,data):
            info=tarfile.TarInfo(name);info.size=len(data);tar.addfile(info,io.BytesIO(data))
        def blob(data):
            digest='sha256:'+hashlib.sha256(data).hexdigest();add('blobs/'+digest.replace(':','/'),data);return {'digest':digest,'size':len(data)}
        desc=blob(content);desc['mediaType']='application/vnd.oci.image.layer.v1.tar'+('+'+compression if compression!='plain' else '')
        config=blob(json.dumps({'architecture':'amd64','os':'linux','config':{'Cmd':['/usr/bin/app'],'Env':['A=1'],'User':'0'},'rootfs':{'type':'layers','diff_ids':['sha256:'+hashlib.sha256(raw).hexdigest()]}}).encode())
        config['mediaType']='application/vnd.oci.image.config.v1+json'
        manifest=blob(json.dumps({'schemaVersion':2,'config':config,'layers':[desc]}).encode());manifest['mediaType']='application/vnd.oci.image.manifest.v1+json'
        add('index.json',json.dumps({'schemaVersion':2,'manifests':[manifest]}).encode());add('oci-layout',b'{"imageLayoutVersion":"1.0.0"}')
    verify_archive(path)


def contents(path):
    with tarfile.open(path)as tar:
        index=runtime._json_member(tar,'index.json');manifest=runtime._json_member(tar,runtime._blob_name(index['manifests'][0]['digest']))
        config=runtime._json_member(tar,runtime._blob_name(manifest['config']['digest']))
        result=[]
        with paths.layer_tar(tar,manifest['layers'][0])as layer:
            for item in layer:
                result.append((item.name,item.mode,item.uid,item.gid,item.linkname,layer.extractfile(item).read() if item.isfile()else None,item.pax_headers.get('SCHILY.xattr.user.test')))
        return config,result


class PathCopies(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.source=Path(self.temp.name)/'image.tar';self.target=Path(self.temp.name)/'pve-import-image.tar'

    def test_absolute_regular_and_directory_headers_are_made_relative(self):
        for compression in ('gzip','plain'):
            with self.subTest(compression=compression):
                fixture(self.source,[('/usr/bin','dir',None),('/usr/bin/app','file',b'actual-application'),('etc/config','file',b'configuration')],compression)
                original=self.source.read_bytes();oldconfig,before=contents(self.source)
                proof=paths.prepare(self.source,self.target)
                verify_archive(self.target);newconfig,after=contents(self.target)
                self.assertEqual(oldconfig['config'],newconfig['config'])
                with tarfile.open(self.target) as image:
                    idx=runtime._json_member(image,'index.json');manifest=runtime._json_member(image,runtime._blob_name(idx['manifests'][0]['digest']))
                    raw=gzip.decompress(image.extractfile(runtime._blob_name(manifest['layers'][0]['digest'])).read())
                    self.assertEqual(newconfig['rootfs']['diff_ids'][0],'sha256:'+hashlib.sha256(raw).hexdigest())
                self.assertEqual([(r[0].lstrip('/'),*r[1:])for r in before],after)
                self.assertEqual(self.source.read_bytes(),original)
                self.assertEqual(paths.validate(self.source,proof),str(self.target))
                self.assertEqual(self.target.stat().st_mode&0o777,0o600)
                self.target.unlink()

    @unittest.skipUnless(shutil.which('zstd'),'zstd executable required')
    def test_zstd_layers_are_streamed_to_a_verified_import_copy(self):
        fixture(self.source,[('/usr/bin/app','file',b'app')],'zstd')
        paths.prepare(self.source,self.target);verify_archive(self.target)
        self.assertEqual(contents(self.target)[1][0][0],'usr/bin/app')

    def test_normal_images_keep_their_original_archive_and_need_no_copy(self):
        fixture(self.source,[('usr/bin/app','file',b'app')]);before=self.source.read_bytes()
        self.assertIsNone(paths.prepare(self.source,self.target))
        self.assertFalse(self.target.exists());self.assertEqual(self.source.read_bytes(),before)

    def test_existing_relative_aliases_keep_native_archive_semantics(self):
        fixture(self.source,[('./etc','dir',None),('etc','dir',None),('etc/config','file',b'config')])
        self.assertIsNone(paths.prepare(self.source,self.target))
        self.assertFalse(self.target.exists())

    def test_parent_traversal_and_ambiguous_aliases_are_rejected(self):
        cases=[[('/usr/../escape','file',b'x')],[('usr/../../escape','file',b'x')],[('/usr/bin/app','file',b'a'),('usr/bin/app','file',b'b')]]
        for entries in cases:
            with self.subTest(entries=entries):
                fixture(self.source,entries)
                with self.assertRaises(runtime.RuntimeResolutionError):paths.prepare(self.source,self.target)
                self.assertFalse(self.target.exists())

    def test_absolute_link_headers_and_hardlink_targets_are_not_reinterpreted(self):
        for entries in [[('/link','sym','usr/bin/app')],[('link','hard','/usr/bin/app')],[('link','hard','../escape')]]:
            with self.subTest(entries=entries):
                fixture(self.source,entries)
                with self.assertRaises(runtime.RuntimeResolutionError):paths.prepare(self.source,self.target)

    def test_symlink_targets_are_preserved_for_native_validation(self):
        for target in ('../usr/bin/app','/usr/bin/app'):
            with self.subTest(target=target):
                fixture(self.source,[('/usr/bin/app','file',b'app'),('bin/link','sym',target)])
                paths.prepare(self.source,self.target)
                self.assertEqual(contents(self.target)[1][-1][4],target)
                self.target.unlink()

    def test_existing_targets_are_never_overwritten(self):
        fixture(self.source,[('/app','file',b'app')]);self.target.write_text('keep')
        with self.assertRaises(FileExistsError):paths.prepare(self.source,self.target)
        self.assertEqual(self.target.read_text(),'keep')

    def test_changed_source_and_changed_copy_are_both_refused(self):
        fixture(self.source,[('/app','file',b'app')]);proof=paths.prepare(self.source,self.target)
        self.target.write_bytes(b'corrupt')
        with self.assertRaises(runtime.RuntimeResolutionError):paths.validate(self.source,proof)
        self.target.unlink();proof=paths.prepare(self.source,self.target);self.source.write_bytes(b'changed publisher archive')
        with self.assertRaises(runtime.RuntimeResolutionError):paths.validate(self.source,proof)

    def test_write_failure_removes_partial_files_without_touching_source(self):
        fixture(self.source,[('/app','file',b'app')]);before=self.source.read_bytes()
        with patch.object(paths.os,'replace',side_effect=OSError('space unavailable')):
            with self.assertRaises(OSError):paths.prepare(self.source,self.target)
        self.assertEqual(self.source.read_bytes(),before)
        self.assertFalse(self.target.exists());self.assertFalse(Path(str(self.target)+'.partial').exists())
        self.assertEqual(list(self.source.parent.glob('oci-paths-*')),[])

    def test_prepared_paths_still_add_numeric_user_files_without_rescanning(self):
        fixture(self.source,[('app','file',b'app')])
        with patch.object(paths,'prepare',side_effect=AssertionError('duplicate path scan')):
            with runtime.creatable_archive(self.source,paths_prepared=True) as compatible:
                self.assertEqual(runtime.missing_user_databases(compatible),[])
                verify_archive(compatible)
        self.assertEqual(list(self.source.parent.iterdir()),[self.source])

    def test_creatable_archive_composes_path_and_numeric_user_adaptations(self):
        fixture(self.source,[('/app','file',b'app')]);before=self.source.read_bytes()
        with runtime.creatable_archive(self.source)as compatible:
            self.assertNotEqual(compatible,self.source)
            self.assertEqual(paths.changed_layers(compatible),[False,False])
            self.assertEqual(runtime.missing_user_databases(compatible),[])
            verify_archive(compatible)
        self.assertEqual(self.source.read_bytes(),before)
        self.assertEqual(list(self.source.parent.iterdir()),[self.source])

if __name__=='__main__':unittest.main()
