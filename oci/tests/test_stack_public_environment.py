"""Only public loopback origins bind by exact Compose port and static target."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'remote'))
from proxmenux_oci.custom import template_from_compose
from proxmenux_oci import stack
from proxmenux_oci.stack import assess,public_environment_bindings,StackError,build_stack,DefaultsUI
from proxmenux_oci.installer import DEFAULT_MODE
import install_generic_stack as runtime

SOURCE='''services:
  web:
    image: nginx:alpine
    ports: ['9001:8080']
    environment: {PUBLIC_URI: 'http://localhost:9001/app?x=1#view'}
    depends_on: [backend, mail]
  backend:
    image: example/backend:latest
    environment: {PUBLIC_URI: 'http://localhost:9001/app?x=1#view', EXPLICIT_URL: 'https://example.com:9443/keep'}
  mail:
    image: axllent/mailpit:v1
    ports: ['8025:8025']
    environment: {PUBLIC_URI: 'http://localhost:8025/mail'}
'''

def fixture(dynamic=False,jobs=False):
    result=[]
    for name,vmid,main,address in [('backend',4801,False,None),('mail',4802,False,'172.30.249.11/24'),('web',4800,True,'dhcp' if dynamic else '172.30.249.10/24')]:
        target='mail' if name=='mail' else 'web';port=8025 if name=='mail' else 8080
        value='http://@STACK_LAN_IP@:'+str(port)+'/app?x=1#view'
        result.append({'name':name,'vmid':vmid,'main':main,'frontend':name!='backend','frontend_ipv4':address,
            'healthcheck':{'type':'running'},'deployment':{'environment':[{'name':'PUBLIC_URI','value':value}]},
            'public_environment_bindings':{'PUBLIC_URI':{'target_service':target,'container_port':port,'value':value}}})
    if jobs:result.append({'name':'migration','vmid':4803,'main':False,'healthcheck':{'type':'completed'},'deployment':{'environment':[]}})
    return result

def build(template,dynamic=False):
    with patch('proxmenux_oci.installer.ask_storage',return_value='local-zfs'), \
         patch('proxmenux_oci.installer.ask_bridge',return_value='vmbr0'), \
         patch('proxmenux_oci.host.timezone',return_value='UTC'), \
         patch('proxmenux_oci.network.ask_addresses',side_effect=lambda ui,bridge,labels: ({name:('dhcp' if dynamic else '172.30.249.11/24' if name=='mail' else '172.30.249.10/24') for name in labels},None)):
        return build_stack(template,DefaultsUI(),DEFAULT_MODE)

class PublicEnvironmentTests(unittest.TestCase):
    def source(self,text=SOURCE):
        template=template_from_compose(text)
        return template,template['compose_stack']['services']

    def test_origin_port_maps_shared_url_to_web_and_mail_to_itself(self):
        template,services=self.source();bindings=public_environment_bindings(services,'web')
        self.assertEqual(assess(template),[])
        self.assertEqual(bindings['backend']['PUBLIC_URI']['target_service'],'web')
        self.assertEqual(bindings['backend']['PUBLIC_URI']['container_port'],8080)
        self.assertEqual(bindings['backend']['PUBLIC_URI']['value'],'http://@STACK_LAN_IP@:8080/app?x=1#view')
        self.assertEqual(bindings['mail']['PUBLIC_URI']['target_service'],'mail')
        self.assertNotIn('EXPLICIT_URL',bindings['backend'])

    def test_compiler_carries_targets_and_resolves_static_before_first_start(self):
        template,_=self.source();plan=build(template)
        services={service['name']:service for service in plan['services']}
        self.assertEqual(services['backend']['public_environment_bindings']['PUBLIC_URI']['target_service'],'web')
        with patch.object(runtime,'run') as run:runtime.prepare_public_environment(plan['services'])
        values={item['name']:item['value'] for item in services['backend']['deployment']['environment']}
        self.assertEqual(values['PUBLIC_URI'],'http://172.30.249.10:8080/app?x=1#view')
        self.assertEqual(values['EXPLICIT_URL'],'https://example.com:9443/keep')
        run.assert_not_called()

    def test_final_environment_override_is_not_replaced_by_original_compose_binding(self):
        template,_=self.source();original=stack.resolve_environments
        def final_override(*args,**kwargs):
            values=original(*args,**kwargs)
            values['backend']['PUBLIC_URI']='https://operator.example.com/custom'
            return values
        with patch.object(stack,'resolve_environments',side_effect=final_override):plan=build(template)
        backend=next(s for s in plan['services'] if s['name']=='backend')
        self.assertNotIn('PUBLIC_URI',backend.get('public_environment_bindings',{}))
        runtime.prepare_public_environment(plan['services'])
        self.assertEqual(next(e['value'] for e in backend['deployment']['environment'] if e['name']=='PUBLIC_URI'),'https://operator.example.com/custom')

    def test_internal_health_metrics_and_admin_urls_are_never_automatic_public_fields(self):
        extra="OTEL_EXPORTER_OTLP_ENDPOINT: 'http://localhost:4318', HEALTHCHECK_URL: 'http://127.0.0.1:9090', LOCAL_ADMIN_API: 'http://localhost:9999', TEXT: 'not:a[url', "
        template,services=self.source(SOURCE.replace('EXPLICIT_URL:',extra+'EXPLICIT_URL:'))
        self.assertEqual(assess(template),[])
        bindings=public_environment_bindings(services,'web')['backend']
        for key in ['OTEL_EXPORTER_OTLP_ENDPOINT','HEALTHCHECK_URL','LOCAL_ADMIN_API','TEXT']:self.assertNotIn(key,bindings)
        plan=build(template);backend=next(s for s in plan['services'] if s['name']=='backend');runtime.prepare_public_environment(plan['services'])
        values={e['name']:e['value'] for e in backend['deployment']['environment']}
        self.assertEqual(values['OTEL_EXPORTER_OTLP_ENDPOINT'],'http://localhost:4318')
        self.assertEqual(values['HEALTHCHECK_URL'],'http://127.0.0.1:9090')
        self.assertEqual(values['LOCAL_ADMIN_API'],'http://localhost:9999')

    def test_ambiguous_host_port_is_blocked(self):
        template,services=self.source(SOURCE.replace("['8025:8025']","['9001:8025']"))
        with self.assertRaisesRegex(StackError,'Ambiguous'):public_environment_bindings(services,'web')
        self.assertTrue(any('Ambiguous' in error for error in assess(template)))

    def test_unmatched_public_origin_does_not_guess_even_single_frontend(self):
        _,services=self.source(SOURCE.replace('localhost:9001','localhost:9999'))
        with self.assertRaisesRegex(StackError,'no matching'):public_environment_bindings(services,'web')
        only_web=[service for service in services if service['name']!='mail']
        with self.assertRaisesRegex(StackError,'no matching'):public_environment_bindings(only_web,'web')

    def test_missing_origin_port_does_not_fall_back_to_the_main(self):
        _,services=self.source(SOURCE.replace('localhost:9001','localhost'))
        with self.assertRaisesRegex(StackError,'no matching'):public_environment_bindings(services,'web')

    def test_static_bindings_with_migration_do_not_run_any_commands(self):
        with patch.object(runtime,'run') as run:runtime.prepare_public_environment(fixture(jobs=True))
        run.assert_not_called()

    def test_every_automatic_dhcp_binding_is_refused_before_any_command(self):
        for jobs in (False,True):
            with self.subTest(jobs=jobs),patch.object(runtime,'run') as run,self.assertRaisesRegex(RuntimeError,'Automatic public URLs'):
                runtime.prepare_public_environment(fixture(dynamic=True,jobs=jobs))
            run.assert_not_called()
        template,_=self.source()
        with self.assertRaisesRegex(StackError,'Automatic public URLs'):build(template,dynamic=True)

    def test_explicit_public_urls_allow_dhcp_and_are_unchanged(self):
        template,_=self.source(SOURCE.replace('localhost','operator.example.com'))
        plan=build(template,dynamic=True)
        with patch.object(runtime,'run') as run:runtime.prepare_public_environment(plan['services'])
        self.assertTrue(all(not s.get('public_environment_bindings') for s in plan['services']))
        backend=next(s for s in plan['services'] if s['name']=='backend')
        self.assertEqual(next(e['value'] for e in backend['deployment']['environment'] if e['name']=='PUBLIC_URI'),'http://operator.example.com:9001/app?x=1#view')
        run.assert_not_called()

if __name__=='__main__':unittest.main()
