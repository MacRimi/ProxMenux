"""Persist route contracts before startup without losing other LXC includes."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'remote'))
import install_generic_stack as runtime
import oci_stack_public_routes as routes

class PublicRouteInstallTests(unittest.TestCase):
    def test_private_members_route_to_all_static_frontends_with_real_identities(self):
        services = [
            {'name':'web','vmid':4810,'main':True,'ip':'10.77.0.30','frontend_ipv4':'10.0.1.246/24','deployment':{}},
            {'name':'mail','vmid':4811,'main':False,'frontend':True,'ip':'10.77.0.31','frontend_ipv4':'10.0.1.245/24','deployment':{}},
            {'name':'worker','vmid':4812,'main':False,'ip':'10.77.0.32','deployment':{}},
        ]
        identities = {service['vmid']: {'installation_id':str(uuid.uuid4())} for service in services}
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / '4812.conf'
            config.write_text('hostname: worker\nlxc.include: /existing/sysctl.conf\n')
            def path(value):
                return config if str(value) == '/etc/pve/lxc/4812.conf' else Path(value)
            def install(deployment, vmid, identity):
                routes.validate(deployment,vmid,identity)
                return f'lxc.include: {routes.include_path(vmid)}'
            with patch.object(runtime,'Path',side_effect=path), patch.object(runtime.oci_instances,'read',side_effect=lambda root,vmid:identities[vmid]), patch.object(routes,'install',side_effect=install), patch.object(routes,'check',wraps=lambda text,plan,vmid,identity=None,**kw:routes.validate(plan,vmid,identity)):
                runtime.install_public_routes(services,4810,'vmbr10')
            self.assertIn('lxc.include: /existing/sysctl.conf\n',config.read_text())
            spec=services[2]['deployment']['stack_public_routes']
            self.assertEqual(spec['installation_id'],identities[4812]['installation_id'])
            self.assertEqual(spec['stack_id'],identities[4810]['installation_id'])
            self.assertEqual(spec['primary_vmid'],4810)
            self.assertEqual(spec['routes'],[
                {'destination':'10.0.1.245','via':'10.77.0.31','target_vmid':4811,'target_installation_id':identities[4811]['installation_id']},
                {'destination':'10.0.1.246','via':'10.77.0.30','target_vmid':4810,'target_installation_id':identities[4810]['installation_id']}])
            self.assertNotIn('stack_public_routes',services[0]['deployment'])
            self.assertNotIn('stack_public_routes',services[1]['deployment'])

    def test_dhcp_without_static_targets_does_not_invent_routes(self):
        services=[{'main':True,'frontend_ipv4':'dhcp','deployment':{}}]
        with patch.object(runtime.oci_instances,'read') as read:
            runtime.install_public_routes(services,4810,'vmbr10')
        read.assert_not_called()

    def test_duplicate_static_ip_rejected_before_read_or_write(self):
        services=[{'main':True,'frontend_ipv4':'10.0.1.246/24'}, {'frontend':True,'frontend_ipv4':'10.0.1.246/24'}]
        with patch.object(runtime.oci_instances,'read') as read:
            with self.assertRaisesRegex(RuntimeError,'Duplicate'):runtime.install_public_routes(services,4810,'vmbr10')
        read.assert_not_called()

    def test_recreate_route_include_is_last_after_other_managed_includes(self):
        source=(ROOT/'remote/install_oci.sh').read_text()
        flow=source[source.index('prepare_managed_format_directories "/var/lib/lxc/'):]
        self.assertLess(flow.index('apply_host_monitor\n'),flow.index('ROUTE_INCLUDE=$(python3'))
        self.assertLess(flow.index('apply_kept_settings\n'),flow.index('ROUTE_INCLUDE=$(python3'))

    def test_routes_installed_before_jobs_and_main_start(self):
        source=(ROOT/'remote/install_generic_stack.py').read_text()
        main=source[source.index('def main('):]
        self.assertLess(main.index('install_public_routes(services, primary_id, bridge)'),main.index('bind_completed_jobs(services)'))
        self.assertLess(main.index('install_public_routes(services, primary_id, bridge)'),main.index("run('pct','start',primary_id"))

if __name__ == '__main__':unittest.main()
