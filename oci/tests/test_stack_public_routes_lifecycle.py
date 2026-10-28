"""Managed frontend /32 routes remain bounded and portable across lifecycle APIs."""
import copy
import contextlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'remote'))
import oci_instance_transaction as tx
import oci_restore_recovery as recovery
import oci_stack_plan as plans
import oci_stack_public_routes as routes
import oci_remove as removal

MAIN='11111111-1111-4111-8111-111111111111'
WORKER='22222222-2222-4222-8222-222222222222'
FOREIGN='33333333-3333-4333-8333-333333333333'

def deployment():
    return {'vmid':4901,'mounts':[],'stack_public_routes':{'schema':1,'stack_id':MAIN,
        'primary_vmid':4900,'vmid':4901,'installation_id':WORKER,'private_bridge':'vmbr15',
        'private_address':'10.77.5.31/24','routes':[{'destination':'192.0.2.10','via':'10.77.5.30',
        'target_vmid':4900,'target_installation_id':MAIN}]}}

def records():
    return {4900:{'vmid':4900,'installation_id':MAIN,'deployment':{},'stack':{'members':[
        {'vmid':4900,'installation_id':MAIN},{'vmid':4901,'installation_id':WORKER}]}},
        4901:{'vmid':4901,'installation_id':WORKER,'deployment':deployment()}}

class ManagedRouteLifecycleTests(unittest.TestCase):
    @contextlib.contextmanager
    def assets(self,folder):
        with patch.multiple(routes,DIRECTORY=Path(folder)/'private',HELPER=Path(folder)/'canonical.py',ROOT_UID=os.geteuid()):
            # The installed engine is trusted; guest-carried code is never used.
            routes.HELPER.write_bytes(Path(routes.__file__).read_bytes())
            routes.HELPER.chmod(0o755)
            yield

    def test_managed_include_coexists_with_sysctl_validation_and_rejects_unknown_include(self):
        with tempfile.TemporaryDirectory() as folder,self.assets(folder):
            plan=deployment();routes.install(plan,4901,WORKER)
            config=(f'description: proxmenux-instance={WORKER}\nrootfs: local-zfs:subvol-4901-disk-0,size=8G\n'
                    f'lxc.include: {routes.include_path(4901)}\n').encode()
            tx.check_runtime_mounts(config,plan)
            with self.assertRaisesRegex(ValueError,'sysctl include'):
                tx.check_runtime_mounts(config+b'lxc.include: /unknown/profile.conf\n',plan)
            with self.assertRaisesRegex(ValueError,'differs from the contract'):
                tx.check_runtime_mounts(config,{'vmid':4901,'mounts':[]})

    def test_plan_rejects_foreign_target_even_if_supplied_in_record_inventory(self):
        good=records();plans.validate_public_route_members(4900,good)
        bad=copy.deepcopy(good);bad[4999]={'vmid':4999,'installation_id':FOREIGN,'deployment':{}}
        route=bad[4901]['deployment']['stack_public_routes']['routes'][0]
        route.update(target_vmid=4999,target_installation_id=FOREIGN)
        with self.assertRaisesRegex(ValueError,'Invalid stack contract'):
            plans.validate_public_route_members(4900,bad)

    def test_plan_rejects_changed_target_and_stack_identities(self):
        for field in ('target_installation_id','stack_id'):
            bad=records();spec=bad[4901]['deployment']['stack_public_routes']
            if field=='stack_id':spec[field]=FOREIGN
            else:spec['routes'][0][field]=FOREIGN
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'Invalid stack contract'):
                plans.validate_public_route_members(4900,bad)

    def test_restore_renumbers_only_managed_paths_and_all_route_member_ids(self):
        with tempfile.TemporaryDirectory() as folder,self.assets(folder):
            mapped=recovery.renumber(records(),{4900:4800,4901:4801})
            # Mapping dictionary keys are not VMID-valued fields: select records by their new vmid.
            mapped={value['vmid']:value for value in mapped.values()}
            plans.validate_public_route_members(4800,mapped)
            spec=mapped[4801]['deployment']['stack_public_routes']
            self.assertEqual((spec['vmid'],spec['primary_vmid'],spec['routes'][0]['target_vmid']),(4801,4800,4800))
            self.assertEqual(spec['installation_id'],WORKER)
            original=f'lxc.include: {routes.include_path(4901)}\nlxc.include: /unrelated/4901.conf\n'
            changed=recovery.renumbered_lines(original,4901,4801)
            self.assertIn(f'lxc.include: {routes.include_path(4801)}',changed)
            self.assertIn('lxc.include: /unrelated/4901.conf',changed)
            routes.check(changed.splitlines()[0]+'\n',mapped[4801]['deployment'],4801,WORKER,require_host_assets=False)

    def test_restore_republishes_only_canonical_host_code_before_start(self):
        with tempfile.TemporaryDirectory() as folder,self.assets(folder):
            plan=recovery.renumber(deployment(),{4900:4800,4901:4801})
            entry={'vmid':4801,'installation_id':WORKER,'config':f'lxc.include: {routes.include_path(4801)}\n',
                   'copy':{'record':{'deployment':plan},'untrusted_script':'do not execute'}}
            with patch.object(recovery,'renumber_config'):
                recovery.restore_host_files(entry)
            self.assertEqual(routes.HELPER.read_bytes(),Path(routes.__file__).read_bytes())
            self.assertEqual(json.loads(routes.contract_path(4801).read_text())['routes'][0]['target_vmid'],4800)
            routes.check(entry['config'],plan,4801,WORKER)

    def test_restore_plan_refuses_foreign_route_before_host_assets_are_created(self):
        bad=records();bad[4901]['deployment']['stack_public_routes']['routes'][0]['target_vmid']=4999
        plan={'primary':4900,'members':[{'vmid':v} for v in bad],'restored':[
            {'vmid':v,'copy':{'record':record}} for v,record in bad.items()],'blockers':[]}
        recovery.check_public_route_members(Path('/unused'),plan)
        self.assertTrue(any('Invalid stack contract' in value for value in plan['blockers']))

    def test_recreate_keeps_managed_routes_outside_editable_desired_state(self):
        old={'vmid':4901,'installation_id':WORKER,'status':'installed',
             'template':{'id':'fixture','proxmox':{'installer_profile':{}},
                         'first_run':{'endpoints':[{'scheme':'http','port':80,'path':'/'}]}},
             'deployment':deployment()}
        candidate=copy.deepcopy(old);candidate['deployment'].pop('stack_public_routes')
        candidate['deployment']['resources']={'cores':2,'memory_mb':1024}
        result=tx.candidate_contract(old,'recreate',{'operation':'recreate','candidate':candidate})
        self.assertEqual(result['deployment']['stack_public_routes'],old['deployment']['stack_public_routes'])
        result['deployment']['stack_public_routes']['routes'][0]['destination']='192.0.2.11'
        self.assertEqual(old['deployment']['stack_public_routes']['routes'][0]['destination'],'192.0.2.10')

    def test_orphan_sweep_cleans_only_absent_owned_routes_and_keeps_pending_or_reused_ids(self):
        for case in ('absent','pending','reused','changed'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder,self.assets(folder):
                root=Path(folder)/'records';root.mkdir()
                routes.install(deployment(),4901,WORKER)
                if case=='changed':routes.include_path(4901).write_text('foreign hook')
                with patch.object(removal.instances,'guest_exists',return_value=case=='reused'), \
                     patch.object(removal.instances,'has_contract',return_value=case=='pending'), \
                     patch.object(removal.instances,'read',return_value={'installation_id':WORKER}), \
                     patch.object(removal.instances,'release_orphan',return_value=False), \
                     patch.object(removal,'remove_host_state'), \
                     patch.object(removal.oci_console,'remove_log'), \
                     patch.object(removal,'release_shared_host_files'):
                    cleaned=removal.sweep_orphans(root)
                self.assertEqual(cleaned,[4901] if case=='absent' else [])
                self.assertEqual(routes.contract_path(4901).exists(),case!='absent')
                self.assertEqual(routes.include_path(4901).exists(),case!='absent')
