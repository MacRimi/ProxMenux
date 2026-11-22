"""Execute the actual backend-copy recipe, then import the packaged helpers."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class Packaging(unittest.TestCase):
    def test_actual_appimage_copy_recipe_contains_importable_host_controls(self):
        script=(ROOT/'AppImage/scripts/build_appimage.sh').read_text()
        recipe='\n'.join(line for line in script.splitlines() if line.startswith('cp "$SCRIPT_DIR/') and '.py"' in line)
        self.assertTrue(recipe)
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);(folder/'usr/bin').mkdir(parents=True)
            result=subprocess.run(['bash','-eu','-c',recipe],env=dict(os.environ,SCRIPT_DIR=str(ROOT/'AppImage/scripts'),APP_DIR=str(folder)),capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            for name in ('host_update_controls.py','proxmenux_version_status.py','kernel_reboot.py','host_update_jobs.py'):
                self.assertTrue((folder/'usr/bin'/name).is_file(),name+' omitted from AppImage')
                self.assertEqual((folder/'usr/bin'/name).read_bytes(),(ROOT/'AppImage/scripts'/name).read_bytes())
            code='import sys;sys.path.insert(0,sys.argv[1]);import host_update_controls,proxmenux_version_status'
            result=subprocess.run([sys.executable,'-I','-B','-c',code,str(folder/'usr/bin')],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':unittest.main(verbosity=2)
