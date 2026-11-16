"""Second maintainer review: cached OCI images are not system templates."""
import json
from copy import deepcopy
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import sys
import unittest
from unittest.mock import patch

import test_plain_lxc as fixture
import plain_lxc as engine
import plain_lxc_state as state
from plain_lxc_pve import inventory
from plain_lxc_spec import LxcError, digest, normalize
import plain_lxc_resources as resources
import lxc_hardware as shared
import test_plain_lxc_review as review_fixture


class TemplateFilterTests(unittest.TestCase):
    setUp = fixture.EngineTests.setUp

    def test_37_oci_archives_are_hidden_but_remain_occupied(self):
        images = [f'local:vztmpl/image-app{i}_amd64_{i:016x}.tar' for i in range(35)]
        images += ['local:vztmpl/linuxserver-jellyfin_amd64_0123456789abcdef.tar',
                   'local:vztmpl/proxmenux-update-amd64-' + 'a'*64 + '.tar']
        systems = [fixture.VOLUME, 'local:vztmpl/turnkey-core_amd64.tar.gz',
                   'local:vztmpl/image-my-custom-system.tar']
        raw = json.loads(self.api.run(['/usr/bin/perl', str(self.api.bridge)],
                                     json.dumps({'node':fixture.NODE,'action':'inventory','params':{}}).encode()))
        raw['storages'][0]['templates'] = [{'volid':name,'size':100} for name in images + systems]
        result = inventory(self.api, fixture.NODE, raw=raw)
        self.assertEqual(set(result['templates']), set(systems))
        self.assertEqual(result['volumes'], set(images + systems))
        self.assertEqual(self.api.writes, [])
        self.assertFalse(self.store.path.exists())

    def test_unreleased_migration_is_removed(self):
        for name in ('LEGACY_STATE','migrate_state','remove_legacy_alias','exchange_directories'):
            self.assertFalse(hasattr(state, name), name)

    def test_direct_cli_cannot_plan_a_cached_oci_archive(self):
        spec=deepcopy(self.spec)
        spec['template']['volume_id']='local:vztmpl/image-blinko_amd64_0123456789abcdef.tar'
        with self.assertRaisesRegex(LxcError,'template_unverified'):
            engine.execute({'schema_version':2,'action':'plan','spec':spec},self.api,self.store)
        self.assertEqual(self.api.writes,[])
        self.assertFalse(self.store.path.exists())


def intel(gid=993):
    return {'path':'/dev/dri/renderD128','profile':'intel-drm','name':'Intel GPU',
            'kind':'GPU','vendor':'0x8086','pci_path':'/sys/devices/0000:00:02.0',
            'identity':{'dev':'10','ino':'12','rdev':'226','uid':0,'gid':gid,'mode':0o660}}


class HardwareContractTests(unittest.TestCase):
    setUp=fixture.EngineTests.setUp

    def call(self,action,**body):
        return engine.execute({'schema_version':2,'action':action,**body},self.api,self.store,wait_seconds=0)

    def selection(self,row):
        self.api.hardware[row['path']]=row
        profile=next(iter(resources.profiles(self.api.hardware).values()))
        return {'profile':profile['profile'],'selection_id':profile['selection_id']}

    def test_real_inventory_type_keeps_partial_probe_errors_and_usable_devices(self):
        actual=resources.DeviceInventory();actual['/dev/dri/renderD128']=intel()
        actual.errors=['usb_inventory_unavailable']
        with patch.object(self.api,'hardware_inventory',return_value=actual):
            result=self.call('context')
        self.assertEqual(result['hardware_errors'],['usb_inventory_unavailable'])
        self.assertEqual(next(iter(result['hardware'].values()))['devices'][0]['gid'],993)
        self.assertEqual(self.api.writes,[])

    def payload(self,hardware,**flags):
        checked=self.call('plan',spec={**self.spec,'prepare_system':False,'hardware':hardware,**flags})
        return {**checked,'request_id':fixture.REQUEST_ID,'confirmed':True,
                'accepted_warnings':checked['plan']['warnings'],'secret':{'password':fixture.PASSWORD}}

    def test_host_gid_is_automatic_and_v2_input_cannot_override_permissions(self):
        selection=self.selection(intel())
        checked=self.payload([selection])
        device=checked['plan']['resources']['attachments']['devices'][0]
        self.assertEqual((device['uid'],device['gid'],device['mode']),(0,993,'0660'))
        self.assertNotIn('devices',checked['plan']['spec'])
        self.assertEqual(self.call('create',**checked)['status'],'succeeded')
        self.assertEqual(self.api.writes[0][1]['dev0'],'path=/dev/dri/renderD128,uid=0,gid=993,mode=0660')
        self.assertEqual([name for name,_ in self.api.writes],['create'])

    def test_legacy_hardware_request_is_rejected_before_inventory_or_admission(self):
        with self.assertRaisesRegex(LxcError,'hardware_requires_v2'):
            engine.execute(fixture.body('plan',spec={**self.spec,'devices':[{'path':'/dev/dri/renderD128'}]}),self.api,self.store)
        self.assertEqual(self.api.calls,[])
        self.assertEqual(self.api.writes,[])
        self.assertFalse(self.store.path.exists())

    def test_already_admitted_v1_hardware_request_remains_observable_without_replay(self):
        row=intel();self.api.hardware={row['path']:row}
        old_spec=normalize({**self.spec,'devices':[{'path':row['path'],'gid':993}]})
        context=inventory(self.api,fixture.NODE,fixture.VMID)
        from plain_lxc_pve import checked_plan
        plan=checked_plan(self.api,old_spec,context)
        plan_hash=digest(plan)
        original={'request_id':fixture.REQUEST_ID,'node':fixture.NODE,'action':'create',
                  'fingerprint':digest(['create',plan_hash]),'status':'succeeded',
                  'phase':'create','vmid':fixture.VMID}
        self.store.admit(original,'vmid:'+str(fixture.VMID));self.store.save(original)
        before=len(self.api.calls)
        repeated=engine.execute(fixture.body('create',request_id=fixture.REQUEST_ID,plan=plan,
                plan_hash=plan_hash,accepted_warnings=plan['warnings'],confirmed=True,
                secret={'password':fixture.PASSWORD}),self.api,self.store)
        self.assertEqual(repeated['status'],'succeeded')
        self.assertEqual(len(self.api.calls),before)
        self.assertEqual(self.api.writes,[])

    def test_native_payload_cannot_override_resolved_gid(self):
        selection=self.selection(intel())
        chosen=resources.selected_hardware([selection],resources.profiles(self.api.hardware))
        devices=[{**chosen[0]['devices'][0],'gid':0}]
        with patch.object(resources,'discover_devices') as discovery,patch.object(resources.subprocess,'run') as run:
            with self.assertRaisesRegex(LxcError,'resource_unavailable'):
                resources.check_hardware_request({'hardware':chosen,'devices':devices,'lxc':[]},fixture.VMID,True)
            discovery.assert_not_called();run.assert_not_called()

    def test_duplicate_or_mixed_hardware_has_zero_probes(self):
        selection={'profile':'intel-drm','selection_id':'example'}
        for changes in ({'hardware':[selection,selection]},
                        {'hardware':[selection],'devices':[]},
                        {'hardware':[{**selection,'gid':0}]},
                        {'hardware':[{'profile':'shell','selection_id':'command'}]}):
            with self.subTest(changes=changes),self.assertRaises(LxcError):
                self.call('plan',spec={**self.spec,**changes})
            self.assertEqual(self.api.calls,[])
            self.assertEqual(self.api.writes,[])

    def test_changed_gid_or_usb_serial_stops_before_create(self):
        for changed in ('gid','serial'):
            with self.subTest(changed=changed):
                row=intel()
                row['usb']={'serial':'first'}
                selection=self.selection(row)
                payload=self.payload([selection])
                if changed=='gid': row['identity']['gid']=44
                else: row['usb']['serial']='other-device'
                with self.assertRaisesRegex(LxcError,'plan_changed'):
                    self.call('create',**payload)
                self.assertEqual(self.api.writes,[])
                self.assertFalse(self.store.path.exists())

    def nvidia_selection(self):
        row=intel(44)
        row.update(path='/dev/nvidia0',name='NVIDIA GPU')
        row.pop('profile');row.pop('vendor');row.pop('pci_path')
        value={'gpus':['GPU-123, 00000000:01:00.0, 550.0'],
               'toolkit_version':['cli-version: 1','lib-version: 1'],
               'devices':{'/dev/nvidia0':{}},'files':{'/usr/lib/libcuda.so':{}},'links':{}}
        row['runtime']=resources.nvidia_runtime(value)
        self.api.hardware={row['path']:row}
        return {'profile':'nvidia-runtime','selection_id':'nvidia-runtime'}

    def test_nvidia_preparation_runs_with_system_preparation_and_start_both_off(self):
        selection=self.nvidia_selection()
        payload=self.payload([selection])
        result=self.call('create',**payload)
        self.assertEqual([name for name,_ in self.api.writes],['create','prepare'])
        self.assertIs(self.api.writes[-1][1]['expected']['prepare_system'],False)
        self.assertIs(result['hardware_prepared'],True)
        self.assertNotIn('prepared',result)
        self.assertNotIn('system_prepared',result)
        self.assertEqual(self.api.boot_attempts,0)
        self.assertEqual(self.call('status',request_id=fixture.REQUEST_ID),result)
        self.assertEqual(self.call('create',**payload),result)
        self.assertEqual(len(self.api.writes),2)

    def test_nvidia_prepare_failure_never_boots_or_replays(self):
        selection=self.nvidia_selection()
        self.api.start_exit='ProxMenux preparation failed: invalid NVIDIA runtime'
        payload=self.payload([selection],start_after_create=True)
        result=self.call('create',**payload)
        self.assertEqual((result['status'],result['reason']),('partial','preparation_failed'))
        self.assertEqual(self.api.boot_attempts,0)
        before=deepcopy(self.api.writes)
        self.call('status',request_id=fixture.REQUEST_ID)
        self.call('create',**payload)
        self.assertEqual(self.api.writes,before)

    def test_driver_inventory_change_requires_new_review(self):
        selection=self.nvidia_selection()
        payload=self.payload([selection])
        self.api.hardware['/dev/nvidia0']['runtime']['inventory']['gpus'][0]='GPU-123, 00000000:01:00.0, 560.0'
        with self.assertRaisesRegex(LxcError,'plan_changed'):
            self.call('create',**payload)
        self.assertEqual(self.api.writes,[])

    def test_amd_compute_requires_kfd_and_topology_and_rejects_overlapping_profiles(self):
        row=intel(44);row.update(profile='amd-drm',vendor='0x1002',name='AMD GPU',gfx_target=100300)
        devices={row['path']:row}
        with patch.object(shared,'amd_gfx_target',return_value=100300):
            self.assertEqual(len(resources.profiles(devices)),1)
            devices['/dev/kfd']={**intel(109),'path':'/dev/kfd','name':'AMD compute'}
            devices['/dev/kfd'].pop('profile')
            candidates=resources.profiles(devices)
        compute=next(item for item in candidates.values() if item['profile']=='amd-rocm')
        self.assertEqual([d['path'] for d in compute['devices']],['/dev/dri/renderD128','/dev/kfd'])
        self.assertEqual(compute['devices'][1]['gid'],109)
        selections=[{'profile':item['profile'],'selection_id':item['selection_id']} for item in candidates.values()]
        with self.assertRaisesRegex(LxcError,'invalid_field'):
            resources.selected_hardware(selections,candidates)

    def test_arbitrary_lxc_directive_cannot_install_hook(self):
        selection=self.nvidia_selection()
        chosen=resources.selected_hardware([selection],resources.profiles(self.api.hardware))
        devices=[d for item in chosen for d in item['devices']]
        with patch.object(resources,'discover_devices',return_value=self.api.hardware), \
             patch.object(resources,'device_assignments',return_value={}), \
             patch.object(resources.subprocess,'run') as run:
            with self.assertRaisesRegex(LxcError,'resource_unavailable'):
                resources.check_hardware_request({'hardware':chosen,'devices':devices,
                                                  'lxc':[['lxc.apparmor.profile','unconfined']]},fixture.VMID,True)
            run.assert_not_called()


class SharedInventoryTests(unittest.TestCase):
    def test_hardware_menu_displays_names_without_opaque_ids_or_permission_questions(self):
        profiles=resources.profiles({'/dev/dri/renderD128':intel()})
        identity=next(iter(profiles))
        class UI(fixture.wizard.Dialog):
            def __init__(self):
                super().__init__('en');self.answers=iter([identity,'done']);self.menus=[]
            def confirm(self,*args,**kwargs):return True
            def dimensions(self,*args,**kwargs):return ('20','100')
            def number(self,*args,**kwargs):raise AssertionError('numeric permission question')
            def input(self,*args,**kwargs):raise AssertionError('manual device field')
            def run(self,*args,**kwargs):
                self.menus.append((args,kwargs));return 0,next(self.answers)
        ui=UI()
        result=fixture.wizard.device_fields(ui,{}, {'hardware':profiles,'capabilities':{'devices':16}})
        self.assertEqual(result,[{'profile':'intel-drm','selection_id':identity}])
        self.assertEqual(len(ui.menus),2)
        self.assertTrue(all(options['hide_tags'] for _,options in ui.menus))
        self.assertEqual(fixture.wizard.hardware_label(ui,profiles[identity]),'Intel GPU · 0000:00:02.0')

    def test_intentionally_excluded_usb_hub_is_not_an_inventory_failure(self):
        def paths(path,pattern):
            return [Path('/dev/bus/usb/001/001')] if pattern=='dev/bus/usb/*/*' else []
        with patch.object(resources.hardware,'usb_devices',return_value=[]), \
             patch.object(resources.shutil,'which',return_value=None), \
             patch.object(Path,'glob',paths),patch.object(resources,'path_identity') as identity:
            result=resources.discover_devices()
        self.assertEqual(result,{})
        self.assertEqual(result.errors,[])
        identity.assert_not_called()

    def test_kfd_generation_is_bound_to_selected_render_minor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for index,minor,target in [(0,128,100300),(1,129,110000)]:
                path=root/'sys/class/kfd/kfd/topology/nodes'/str(index)
                path.mkdir(parents=True)
                (path/'properties').write_text(f'drm_render_minor {minor}\ngfx_target_version {target}\n')
            self.assertEqual(shared.amd_compute_target('/dev/dri/renderD128',root),100300)
            self.assertEqual(shared.amd_compute_target('/dev/dri/renderD129',root),110000)
            self.assertIsNone(shared.amd_compute_target('/dev/dri/renderD130',root))

    def test_vendor_is_read_from_sysfs_not_render_node_number(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for node,vendor in [('renderD128','0x1002'),('renderD129','0x8086'),('renderD130','0x10de')]:
                path=root/'sys/class/drm'/node/'device';path.mkdir(parents=True)
                (path/'vendor').write_text(vendor)
            with patch.object(shared.shutil,'which',return_value=None):
                found=shared.gpus(root)
            self.assertEqual(found['intel'],['/dev/dri/renderD129'])
            self.assertEqual(found['amd'],['/dev/dri/renderD128'])
            self.assertIs(found['nvidia'],False)

    def test_nvidia_snapshot_requires_both_devices_and_libraries(self):
        with tempfile.TemporaryDirectory() as temporary:
            library=Path(temporary)/'libcuda.so';library.write_bytes(b'driver component')
            original=Path
            def path(name):
                if name=='/dev/nvidia0':
                    return SimpleNamespace(stat=lambda:SimpleNamespace(st_mode=0o20660,st_uid=0,st_gid=44,st_rdev=os.makedev(195,0)),
                                           resolve=lambda:original('/dev/nvidia0'))
                return original(name)
            def command(*args):
                if args[0]=='nvidia-smi':return 'GPU-123, 00000000:01:00.0, 550.0\n'
                if args[1]=='--version':return 'cli-version: 1\nlib-version: 1\n'
                return '/dev/nvidia0\n'+str(library)+'\n'
            with patch.object(shared,'Path',side_effect=path):
                value=shared.nvidia_snapshot(command)
                self.assertEqual(value['devices']['/dev/nvidia0']['gid'],44)
                self.assertEqual(value['files'][str(library)]['sha256'],hashlib.sha256(library.read_bytes()).hexdigest())
                def partial(*args):
                    return '/dev/nvidia0\n' if len(args)>1 and args[1]=='list' else command(*args)
                with self.assertRaisesRegex(ValueError,'Incomplete NVIDIA inventory'):
                    shared.nvidia_snapshot(partial)

    def test_usb_without_serial_keeps_port_and_sysfs_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);usb=root/'devices/usb1/1-3';usb.mkdir(parents=True)
            for name,value in [('idVendor','10c4'),('idProduct','ea60'),('bDeviceClass','00')]:
                (usb/name).write_text(value)
            node=root/'dev/char/189:2';node.parent.mkdir(parents=True);node.symlink_to(usb)
            identity={'rdev':str(os.makedev(189,2))}
            first=resources.usb_identifiers('/dev/bus/usb/001/003',root,identity)
            self.assertIsNone(first['serial']);self.assertEqual(first['port'],'1-3')
            (usb/'serial').write_text('SONOFF-123')
            second=resources.usb_identifiers('/dev/bus/usb/001/003',root,identity)
            self.assertEqual(second['serial'],'SONOFF-123')
            self.assertNotEqual(first,second)


class NativeHardwareTests(unittest.TestCase):
    setUpClass=classmethod(fixture.PerlBridgeTests.setUpClass.__func__)
    call=fixture.PerlBridgeTests.call

    def test_nvidia_native_prepare_and_start_keep_system_preparation_independent(self):
        device={'path':'/dev/nvidia0','uid':0,'gid':44,'mode':'0660',
                'identity':{'dev':'10','ino':'12','rdev':'226','uid':0,'gid':0,'mode':0o660}}
        hardware={'mounts':[],'devices':[device],
                  'hardware':[{'profile':'nvidia-runtime','selection_id':'nvidia-runtime','runtime':{}}]}
        entries=[['lxc.environment','NVIDIA_VISIBLE_DEVICES=all'],
                 ['lxc.environment','NVIDIA_DRIVER_CAPABILITIES=compute,utility,video'],
                 ['lxc.hook.mount','/usr/local/lib/proxmenux/oci/nvidia-mount-'+'a'*64+'.sh']]
        stat_driver=review_fixture.STAT_DRIVER.replace('/dev/dri/renderD128','/dev/nvidia0')
        with tempfile.TemporaryDirectory() as temporary,patch.object(fixture,'PERL_DRIVER',stat_driver+fixture.PERL_DRIVER):
            for prepare in (False,True):
                for start in (False,True):
                    with self.subTest(prepare=prepare,start=start):
                        log=Path(temporary)/f'{prepare}-{start}'
                        env={'TEST_RESOURCE_STATS':'1','TEST_MARKER':'ProxMenux request '+fixture.REQUEST_ID,
                             'TEST_EXTRA_CONFIG':json.dumps({'dev0':'path=/dev/nvidia0,uid=0,gid=44,mode=0660'}),
                             'TEST_HARDWARE_LXC':json.dumps(entries),'TEST_CALL_LOG':str(log)}
                        result=self.call('start' if start else 'prepare',vmid=240,description=env['TEST_MARKER'],
                                         expected={**fixture.NATIVE_EXPECTED,'prepare_system':prepare,'resources':hardware},environment=env)
                        self.assertEqual(result.returncode,0,result.stderr)
                        calls=log.read_text().splitlines()
                        self.assertEqual(calls.count('PREPARE_HARDWARE'),1)
                        self.assertEqual(calls.count('WRITE_HARDWARE'),1)
                        self.assertEqual(calls.count('PREPARE'),int(prepare))
                        self.assertEqual(calls.count('MOUNT'),int(prepare))
                        self.assertEqual(calls.count('START'),int(start))
                        if start:self.assertLess(calls.index('PREPARE_HARDWARE'),calls.index('START'))
            for change in ({'TEST_HARDWARE_FAIL':'1'}, {'TEST_HARDWARE_PREPARE_FAIL':'1'},
                           {'TEST_EXTRA_CONFIG':json.dumps({'dev0':'path=/dev/nvidia0,uid=0,gid=44,mode=0660',
                                                          'lxc':[['lxc.apparmor.profile','unconfined']]})}):
                log=Path(temporary)/('negative'+str(len(list(Path(temporary).iterdir()))))
                result=self.call('start',vmid=240,description=env['TEST_MARKER'],
                                 expected={**fixture.NATIVE_EXPECTED,'prepare_system':False,'resources':hardware},
                                 environment={**env,**change,'TEST_CALL_LOG':str(log)})
                self.assertNotEqual(result.returncode,0)
                calls=log.read_text().splitlines()
                self.assertNotIn('START',calls);self.assertNotIn('MOUNT',calls)
                self.assertNotIn('WRITE_HARDWARE',calls)


if __name__ == '__main__':
    unittest.main()
