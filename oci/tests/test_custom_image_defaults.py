"""Internal service metadata is inferred from OCI, not app-specific recipes."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'remote'))
from proxmenux_oci.custom import enrich_image_defaults
import install_generic_stack as generic


class ImageDefaults(unittest.TestCase):
    def test_internal_expose_and_health_from_oci_are_preserved_without_publishing_ports(self):
        doc={'services':{'helper':{'image':'example.org/team/helper:3','healthcheck':{'disable':False,'retries':5}}}}
        config={'config':{'ExposedPorts':{'7000/tcp':{},'7001/udp':{}},'Healthcheck':{
            'Test':['CMD','/usr/bin/check-ready'],'Interval':3000000000,'Timeout':1000000000}}}
        process=SimpleNamespace(returncode=0,stdout=json.dumps(config))
        with patch('proxmenux_oci.custom.subprocess.run',return_value=process):
            result=enrich_image_defaults(None,doc)['services']['helper']
        self.assertEqual(result['expose'],['7000/tcp'])
        self.assertNotIn('ports',result)
        self.assertEqual(result['healthcheck']['test'],['CMD','/usr/bin/check-ready'])
        self.assertEqual(result['healthcheck']['retries'],5)
        self.assertEqual(result['healthcheck']['interval'],'3000000000ns')
        self.assertNotIn('expose',doc['services']['helper'])

    def test_null_image_health_does_not_crash_and_no_port_is_invented(self):
        doc={'services':{'helper':{'image':'example.org/team/helper:3','healthcheck':{'disable':False}}}}
        with patch('proxmenux_oci.custom.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='{"config":{"Healthcheck":null}}')):
            result=enrich_image_defaults(None,doc)['services']['helper']
        self.assertNotIn('healthcheck',result)
        self.assertNotIn('expose',result)

    def test_explicit_disabled_healthcheck_is_not_reenabled(self):
        doc={'services':{'web':{'image':'example.org/web:1','ports':['8080:8080'],'healthcheck':{'disable':True}}}}
        with patch('proxmenux_oci.custom.subprocess.run') as inspect:
            self.assertEqual(enrich_image_defaults(None,doc),doc)
            inspect.assert_not_called()

    def test_worker_entrypoint_or_command_does_not_inherit_a_false_web_listener(self):
        for override in [{'entrypoint':'/cron.sh'}, {'command':['worker','run']}, {'command':[]}]:
            with self.subTest(override=override):
                doc={'services':{'worker':{'image':'example.org/web-and-worker:1',**override}}}
                config={'config':{'ExposedPorts':{'80/tcp':{}},'Healthcheck':None}}
                with patch('proxmenux_oci.custom.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(config))):
                    result=enrich_image_defaults(None,doc)['services']['worker']
                self.assertNotIn('expose',result)

    def test_option_command_uses_actual_image_entrypoint_metadata(self):
        doc={'services':{'db':{'image':'mariadb:11','command':['--transaction-isolation=READ-COMMITTED']}}}
        config={'config':{'Entrypoint':['docker-entrypoint.sh'],'Cmd':['mariadbd']}}
        entrypoints={}
        with patch('proxmenux_oci.custom.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(config))):
            result=enrich_image_defaults(None,doc,image_entrypoints=entrypoints)
        self.assertEqual(entrypoints,{'mariadb:11':['docker-entrypoint.sh']})
        self.assertEqual(result,doc)

    def test_enforcing_selinux_stops_before_install_when_labels_need_translation(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'enforce'; path.write_text('1')
            with self.assertRaisesRegex(RuntimeError,'SELinux'):
                generic.check_selinux_labels({'proxmox':{'custom_compose_selinux_labels':True}},path)
            path.write_text('0')
            generic.check_selinux_labels({'proxmox':{'custom_compose_selinux_labels':True}},path)
            path.write_text('1')
            generic.check_selinux_labels({'proxmox':{}},path)

    def test_main_http_success_does_not_override_failed_declared_exec_health(self):
        service={'vmid':4800,'name':'app','healthcheck':{'type':'exec','argv':['check-ready'],'timeout_seconds':30}}
        opener=SimpleNamespace(open=lambda *args,**kwargs: __import__('contextlib').nullcontext(SimpleNamespace(status=200)))
        with patch.object(generic,'run',return_value='status: running'), \
             patch.object(generic.urllib.request,'build_opener',return_value=opener), \
             patch.object(generic.subprocess,'run',side_effect=[SimpleNamespace(returncode=1),SimpleNamespace(returncode=0)]) as execute, \
             patch.object(generic.time,'sleep'):
            generic.wait_web(service,'http://192.0.2.1:8080/')
        self.assertEqual(execute.call_count,2)
        self.assertEqual(execute.call_args.args[0],['pct','exec','4800','--','check-ready'])


if __name__=='__main__':unittest.main()
