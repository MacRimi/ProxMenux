"""Directory mount mappings survive native configuration operations."""
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'remote'))
import oci_mount_idmap as idmap
import oci_native_modify as modify
import oci_instance_transaction as transaction
import oci_instance_reconcile as reconcile
import oci_nested_mounts as nested
import oci_host_mounts as host_mounts
import oci_restore_recovery as restore

MAP='u:0:2000:1;g:0:2000:1'


def mount(source='/srv/shared',mapping=MAP):
    result={'type':'host-bind','container_path':'/data','source':source,'size_gb':None,
            'backup':False,'read_only':False,'create_if_missing':False}
    if mapping is not None: result['idmap']=mapping
    return result


class MountMappingTests(unittest.TestCase):
    def test_mapping_is_normalized_without_changing_its_meaning(self):
        self.assertEqual(idmap.normalize_idmap('g:00:2000:01;u:00:2000:1'),MAP)
        for empty in (None,''): self.assertIsNone(idmap.normalize_idmap(empty))

    def test_invalid_ranges_and_host_root_are_rejected(self):
        bad=('passthrough','u:0:0:1','g:0:0:1','u:65536:2000:1','u:1:4294967294:2',
             'u:0:2000:0','u:0:2000:2;u:1:3000:1','u:0:2000:1;u:1:2000:1',
             'u:0:2000:1;','u:0:2000:1\n',True,[])
        for value in bad:
            with self.subTest(value=value),self.assertRaises(ValueError): idmap.normalize_idmap(value)
        with self.assertRaisesRegex(ValueError,'unprivileged'): idmap.normalize_idmap(MAP,False)

    def test_root_nonroot_and_legacy_owners(self):
        self.assertEqual(idmap.mapped_host_ids(mount(),0,0),(2000,2000))
        self.assertEqual(idmap.mapped_host_ids(mount(mapping='u:1000:2000:2;g:1000:2000:2'),1001,1001),(2001,2001))
        self.assertEqual(idmap.mapped_host_ids(mount(mapping=None),1000,1000),(101000,101000))
        with self.assertRaisesRegex(ValueError,'cover the application'): idmap.mapped_host_ids(mount(),1000,1000)
        with self.assertRaisesRegex(ValueError,'cover the application'): idmap.mapped_host_ids(mount(mapping='u:0:2000:1'),0,0)

    def test_custom_global_idmap_is_refused_and_native_map_remains_supported(self):
        with tempfile.TemporaryDirectory() as folder:
            plan={'mounts':[mount(folder)]}
            with self.assertRaisesRegex(ValueError,'native unprivileged idmap'):
                idmap.check_deployment(dict(plan,custom_lxc=['lxc.idmap: u 0 200000 65536','lxc.idmap: g 0 200000 65536']))
            with self.assertRaisesRegex(ValueError,'native unprivileged idmap'):
                idmap.check_deployment(plan,config=b'lxc.idmap: u 0 100000 65536\nlxc.idmap: g 0 200000 65536\n')
            idmap.check_deployment(plan,config=b'lxc.idmap: u 0 100000 65536\nlxc.idmap: g 0 100000 65536\n')
            # Legacy deployments without a per-mount map are unchanged.
            idmap.check_deployment({'custom_lxc':['lxc.idmap: u 0 200000 65536'],'mounts':[]})

    def test_compose_user_and_profile_identity_override_the_image(self):
        template={'proxmox':{'installer_profile':{'runtime':{'user':'1000:1000'}}}}
        self.assertEqual(idmap.application_ids({},template,b'lxc.init.uid: 0\nlxc.init.gid: 0\n'),(1000,1000))
        self.assertEqual(idmap.application_ids({'environment':[{'name':'PUID','value':'1500'},{'name':'PGID','value':'1500'}]},template),(1500,1500))
        template['proxmox']['installer_profile']['volume_owner']={'uid':2000,'gid':2001}
        self.assertEqual(idmap.application_ids({},template),(2000,2001))

    def test_unsupported_mount_profiles_refuse_before_external_commands(self):
        for m in (dict(mount(),type='managed-volume'),dict(mount(),source='/etc/localtime'),dict(mount(),grant_access=True)):
            with self.subTest(m=m),patch.object(idmap,'_validate_native') as native,self.assertRaises(ValueError):
                idmap.check_deployment({'mounts':[m]},require_supported=True)
            native.assert_not_called()
        with self.assertRaisesRegex(ValueError,'standalone'):
            idmap.check_deployment({'mounts':[mount()]},standalone=False)

    def test_proxmox_validates_implicit_fallback_collisions(self):
        idmap._validate_native.cache_clear()
        proc=subprocess.CompletedProcess([],1,'','overlap')
        with patch.object(idmap,'ensure_supported'),patch.object(idmap.subprocess,'run',return_value=proc),self.assertRaisesRegex(ValueError,'conflicts'):
            idmap._validate_native('u:0:102000:1;g:0:2000:1')
        idmap._validate_native.cache_clear()

    def test_nfs_directory_refuses_before_container_mutation(self):
        proc=subprocess.CompletedProcess([],0,'nfs4\n','')
        with patch.object(idmap.subprocess,'run',return_value=proc),self.assertRaisesRegex(ValueError,'filesystem'):
            idmap._filesystem('/srv/no-such-idmap-directory')

    def test_new_directory_gets_mapped_owner_and_existing_data_is_not_reowned(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'shared'; m=dict(mount(str(target)),create_if_missing=True)
            with patch.object(idmap.os,'chown') as chown:
                self.assertTrue(idmap.create_host_directory(m,{}))
                chown.assert_called_once_with(target,2000,2000)
                chown.reset_mock();(target/'data').write_text('kept')
                self.assertFalse(idmap.create_host_directory(m,{}))
                chown.assert_not_called(); self.assertEqual((target/'data').read_text(),'kept')

    def test_existing_directory_accepts_partial_mapping_without_reownership(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(idmap.os,'chown') as chown:
            self.assertFalse(idmap.create_host_directory(mount(folder,mapping='u:0:2000:1'),{}))
            chown.assert_not_called()

    def test_invalid_new_directory_owner_fails_before_mkdir(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'missing'
            with self.assertRaises(ValueError):
                idmap.create_host_directory(mount(str(target)),{'environment':[{'name':'PUID','value':'1000'}]})
            self.assertFalse(target.exists())

    def test_adoption_retains_mapping_and_refuses_managed_volume_mapping(self):
        with patch.object(reconcile.host_mounts,'validate_source'):
            adopted=reconcile._mount('mp1',f'/srv/shared,mp=/data,backup=0,idmap={MAP}',1000)
        self.assertEqual(adopted['idmap'],MAP)
        with self.assertRaisesRegex(ValueError,'host directory'):
            reconcile._mount('mp1',f'local:vm-1000-disk-1,mp=/data,backup=1,size=1G,idmap={MAP}',1000)

    def test_runtime_validation_rejects_a_dropped_mapping(self):
        plan={'vmid':1000,'mounts':[mount()]}
        cfg=f'mp0: /srv/shared,mp=/data,backup=0,idmap={MAP}\n'.encode()
        with patch.object(transaction.public_routes,'check'),patch.object(transaction.runtime_settings,'check'),patch.object(transaction.nested_mounts,'check'):
            transaction.check_runtime_mounts(cfg,plan)
            with self.assertRaisesRegex(ValueError,'options were not kept'):
                transaction.check_runtime_mounts(b'mp0: /srv/shared,mp=/data,backup=0\n',plan)

    def test_idmapped_mount_has_no_raw_recursive_overlay(self):
        config=f'mp0: /srv/shared,mp=/data,backup=0,idmap={MAP}\n'.encode()
        self.assertEqual(nested.groups(config),[])
        nested.check(config)
        stale=config+b'lxc.mount.entry: /srv/shared data none rbind,rslave,create=dir 0 0\n'
        self.assertTrue(nested.stale(stale))
        with self.assertRaises(ValueError): nested.check(stale)
        ordinary=b'mp0: /srv/shared,mp=/data,backup=0\n'
        self.assertEqual(len(nested.groups(ordinary)),1)

    def test_adoption_of_shadowed_manual_mapping_refuses_before_follow(self):
        record={'vmid':1000,'status':'installed','installation_id':'11111111-1111-1111-1111-111111111111','deployment':{}}
        config=(f'description: proxmenux-instance={record["installation_id"]}\n'
                f'mp0: /srv/shared,mp=/data,backup=0,idmap={MAP}\n'
                'lxc.mount.entry: /srv/shared data none rbind,rslave,create=dir 0 0\n').encode()
        self.assertTrue(nested.idmapped_overlays(config))
        with patch.object(nested,'follow') as follow,self.assertRaisesRegex(ValueError,'Revert the manual mapping'):
            reconcile.propose(record,config)
        follow.assert_not_called()

    def test_restore_of_shadowed_idmapped_mount_is_blocked_before_start(self):
        with tempfile.TemporaryDirectory() as folder:
            config=(f'mp0: {folder},mp=/data,backup=0,idmap={MAP}\n'
                    f'lxc.mount.entry: {folder} data none rbind,rslave,create=dir 0 0\n')
            record={'deployment':{'mounts':[mount(folder)]},'observed':{}}
            plan={'restored':[{'vmid':1000,'config':config,'copy':{'record':record}}],
                  'blockers':[],'members':[],'notes':[]}
            with patch.object(idmap,'check_deployment') as check:
                restore.check_host_resources(plan)
            self.assertTrue(any('shadowed by a recursive bind' in blocker for blocker in plan['blockers']))
            check.assert_not_called()

    def test_nested_filesystems_are_rejected_without_changing_mounts(self):
        with patch.object(host_mounts,'MOUNTINFO') as table:
            table.read_text.return_value='1 0 0:1 / /srv/shared/child rw - zfs pool/child rw\n'
            with self.assertRaisesRegex(ValueError,'nested host mounts'): idmap._check_nested_mounts('/srv/shared')
            table.read_text.return_value='1 0 0:1 / /srv/shared rw - zfs pool/shared rw\n'
            idmap._check_nested_mounts('/srv/shared')

    def test_adoption_of_existing_mount_adds_changes_and_removes_mapping(self):
        deployment={'mounts':[mount(mapping=None)]}
        with patch.object(reconcile.host_mounts,'validate_source'):
            for mapping in (MAP,'u:1000:2000:1;g:1000:2000:1',None):
                value='/srv/shared,mp=/data,backup=0'+(',idmap='+mapping if mapping else '')
                reconcile._storage_change('mp0',value,deployment,1000)
                self.assertEqual(deployment['mounts'][0].get('idmap'),mapping)

    def test_native_modify_adds_and_removes_mapping_in_the_same_mount(self):
        old={'template':{'container_contract':{}},'deployment':{'vmid':1000,'mounts':[mount(mapping=None)]}}
        new=copy.deepcopy(old);new['deployment']['mounts'][0]['idmap']=MAP
        cfg=b'mp0: /srv/shared,mp=/data,backup=0\n'
        with patch.object(transaction,'preflight'),patch.object(modify.Path,'is_dir',return_value=True):
            operation=modify.plan(old,new,cfg)
            self.assertIn('idmap='+MAP,operation['values']['mp0'])
            removed=modify.plan(new,old,f'mp0: /srv/shared,mp=/data,backup=0,idmap={MAP}\n'.encode())
            self.assertNotIn('idmap=',removed['values']['mp0'])


if __name__=='__main__': unittest.main()
