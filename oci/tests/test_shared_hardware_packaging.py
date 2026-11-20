"""Shared hardware helpers must reach local and SSH installers intact."""
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from proxmenux_oci import installer

HELPERS={'lxc_hardware.py','lxc_nvidia_setup.sh','oci_image_names.py',
         'oci_gpu_devices.py','oci_nvidia_runtime.py','oci_nvidia_dynamic.py',
         'nvidia_lxc_mount_lab.sh','oci_nvidia_setup.sh','oci_image_cache.py'}


class HardwarePackagingTests(unittest.TestCase):
    def test_local_installer_gets_all_shared_helpers_without_dispatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            template=Path(temporary)/'template.json';template.write_text('{}')
            def inspect(command,body=None):
                self.assertIsNone(body)
                folder=Path(command[1]).parent
                self.assertTrue(HELPERS <= {path.name for path in folder.iterdir()})
                for name in HELPERS:
                    self.assertEqual((folder/name).read_bytes(),(ROOT/'remote'/name).read_bytes())
                return {'inspected':True}
            with patch.object(installer,'_stream_process',side_effect=inspect) as dispatch:
                result=installer._run_remote_install(ROOT,template,{},'local',dry_run=True)
            self.assertEqual(result,{'inspected':True})
            self.assertEqual(dispatch.call_count,1)

    def test_ssh_bundle_has_same_helpers_and_source_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            template=Path(temporary)/'template.json';template.write_text('{}')
            def inspect(command,body=None):
                self.assertEqual(command[0],'ssh')
                with tarfile.open(fileobj=io.BytesIO(body),mode='r:gz') as archive:
                    self.assertTrue(HELPERS <= set(archive.getnames()))
                    for name in HELPERS:
                        self.assertEqual(archive.extractfile(name).read(),(ROOT/'remote'/name).read_bytes())
                return {'inspected':True}
            with patch.object(installer,'_stream_process',side_effect=inspect) as dispatch:
                result=installer._run_remote_install(ROOT,template,{},'fixture.invalid',dry_run=True)
            self.assertEqual(result,{'inspected':True})
            self.assertEqual(dispatch.call_count,1)


if __name__=='__main__':unittest.main()
