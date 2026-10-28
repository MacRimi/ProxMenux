"""Real dpkg contract shape and actual cached HealthMonitor method. No APT."""
import ast
import copy
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'AppImage/scripts'))
import kernel_reboot as kernel

def listing(*releases):
    return '\n'.join('installed\tproxmox-kernel-'+v+'-signed' for v in releases)+'\n'

class Reboot(unittest.TestCase):
    def setUp(self):
        self.uname=patch.object(kernel.os,'uname',return_value=SimpleNamespace(release='7.0.14-25-pve'))
        self.uname.start()
        self.addCleanup(self.uname.stop)
        self.marker=patch.object(Path,'exists',return_value=False)
        self.marker.start()
        self.addCleanup(self.marker.stop)

    def check(self, output, rc=0):
        with patch.object(kernel.subprocess,'run',return_value=subprocess.CompletedProcess([],rc,output,'')) as call:
            result=kernel.reboot_status()
        if call.called:
            self.assertEqual(call.call_args.args[0][0],'dpkg-query')
            self.assertNotIn('apt',call.call_args.args[0])
        return result

    def test_installed_26_running_25_requires_reboot_without_marker_or_pending_updates(self):
        result=self.check(listing('7.0.14-25-pve','7.0.14-26-pve'))
        self.assertEqual(result['state'],'required')
        self.assertEqual(result['installed_kernel'],'7.0.14-26-pve')

    def test_old_kernel_meta_and_removed_config_are_not_new_installed_kernel(self):
        text=listing('7.0.14-25-pve','6.17.13-21-pve')+'installed\tproxmox-kernel-7.0\nconfig-files\tproxmox-kernel-7.0.14-26-pve-signed\n'
        self.assertEqual(self.check(text)['state'],'current')

    def test_reboot_into_new_kernel_clears_the_requirement(self):
        with patch.object(kernel.os,'uname',return_value=SimpleNamespace(release='7.0.14-26-pve')):
            self.assertEqual(self.check(listing('7.0.14-25-pve','7.0.14-26-pve'))['state'],'current')

    def test_version_comparison_is_numeric(self):
        self.assertEqual(self.check(listing('7.0.14-9-pve','7.0.14-100-pve'))['state'],'required')

    def test_legacy_pve_package_and_arch_suffix_are_supported(self):
        self.assertEqual(self.check('installed\tpve-kernel-7.0.14-26-pve:amd64\n')['state'],'required')

    def test_missing_empty_malformed_and_partial_are_unknown_not_zero(self):
        for text in ('','garbage','installed\tother-package\n','half-configured\tproxmox-kernel-7.0.14-26-pve-signed\n','bad-state\tfoo\n'):
            with self.subTest(text=text):
                self.assertEqual(self.check(text)['state'],'unknown')
        self.assertEqual(self.check(listing('7.0.14-26-pve'),rc=1)['state'],'unknown')

    def test_timeout_and_read_error_are_unknown(self):
        for error in (subprocess.TimeoutExpired('dpkg-query',5),OSError('unreadable')):
            with patch.object(kernel.subprocess,'run',side_effect=error):
                self.assertEqual(kernel.reboot_status()['state'],'unknown')

    def test_unavailable_or_invalid_uname_never_probes_packages(self):
        with patch.object(kernel.os,'uname',side_effect=OSError('unknown')),patch.object(kernel.subprocess,'run') as packages:
            self.assertEqual(kernel.reboot_status()['state'],'unknown')
            packages.assert_not_called()
        for release in ('','invalid','7.0.14--pve'):
            with patch.object(kernel.os,'uname',return_value=SimpleNamespace(release=release)),patch.object(kernel.subprocess,'run') as packages:
                self.assertEqual(kernel.reboot_status()['state'],'unknown')
                packages.assert_not_called()

    def test_supported_marker_never_requires_a_package_probe(self):
        with patch.object(Path,'exists',return_value=True),patch.object(kernel.subprocess,'run') as packages:
            self.assertEqual(kernel.reboot_status()['state'],'required')
            packages.assert_not_called()

    def test_non_pve_kernel_is_not_a_failed_pve_read(self):
        with patch.object(kernel.os,'uname',return_value=SimpleNamespace(release='6.12.0-amd64')),patch.object(kernel.subprocess,'run') as packages:
            self.assertEqual(kernel.reboot_status()['state'],'not_applicable')
            packages.assert_not_called()

    def test_overlay_does_not_mutate_cache_or_hide_existing_error(self):
        for original in ('OK','UNKNOWN','WARNING','CRITICAL'):
            cache=dict(status=original,count=0,checks={'pending_updates':dict(status='OK')})
            before=copy.deepcopy(cache)
            result=kernel.with_reboot_status(cache,dict(state='required',running_kernel='old',installed_kernel='new'))
            self.assertEqual(cache,before)
            self.assertTrue(result['reboot_required'])
            self.assertEqual(result['status'],'INFO' if original=='OK' else original)
        result=kernel.with_reboot_status(dict(status='OK',checks={}),dict(state='unknown',running_kernel='old',installed_kernel=None))
        self.assertEqual(result['status'],'UNKNOWN')
        self.assertIsNone(result['reboot_required'])

    def test_actual_cached_health_path_refreshes_reboot_evidence_without_apt(self):
        source=ast.parse((ROOT/'AppImage/scripts/health_monitor.py').read_text())
        node=next(n for n in ast.walk(source) if isinstance(n,ast.FunctionDef) and n.name=='_check_updates')
        node.decorator_list=[]
        import __future__
        scope=dict(os=kernel.os,time=time,subprocess=kernel.subprocess)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-health','exec',flags=__future__.annotations.compiler_flag),scope)
        for age in (0,599.999):
            cache=dict(status='OK',count=0,checks={})
            owner=SimpleNamespace(last_check_times={'updates_check':time.time()-age},cached_results={'updates_check':cache})
            with patch.object(kernel.os.path,'exists',return_value=True),patch.object(kernel.os.path,'getmtime',return_value=0),patch.object(kernel.subprocess,'run',return_value=subprocess.CompletedProcess([],0,listing('7.0.14-26-pve'),'')) as probe:
                result=scope['_check_updates'](owner)
            self.assertEqual(result['status'],'INFO')
            self.assertTrue(result['reboot_required'])
            self.assertEqual(cache,dict(status='OK',count=0,checks={}))
            self.assertEqual([call.args[0][0] for call in probe.call_args_list],['dpkg-query'])

    def test_actual_health_failure_paths_keep_independent_reboot_evidence(self):
        source=ast.parse((ROOT/'AppImage/scripts/health_monitor.py').read_text())
        node=next(n for n in ast.walk(source) if isinstance(n,ast.FunctionDef) and n.name=='_check_updates')
        import __future__
        scope=dict(os=kernel.os,time=time,subprocess=kernel.subprocess)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-health','exec',flags=__future__.annotations.compiler_flag),scope)
        for age in (600,600.001):
            for error in (subprocess.TimeoutExpired('apt-get',30),OSError('fixture-unavailable')):
                owner=SimpleNamespace(last_check_times={'updates_check':time.time()-age},cached_results={})
                def command(args, **kwargs):
                    if args[0]=='dpkg-query':
                        return subprocess.CompletedProcess(args,0,listing('7.0.14-26-pve'),'')
                    raise error
                with patch.object(kernel.os.path,'exists',return_value=False),patch.object(kernel.subprocess,'run',side_effect=command) as probe:
                    result=scope['_check_updates'](owner)
                self.assertEqual(result['status'],'UNKNOWN')
                self.assertTrue(result['reboot_required'])
                self.assertEqual([call.args[0][0] for call in probe.call_args_list],['dpkg-query','apt-get'])

if __name__=='__main__':
    unittest.main(verbosity=2)
