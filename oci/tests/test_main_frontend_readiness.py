"""Main readiness probes the same address the installation advertises."""
import copy
import ipaddress
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'remote'))
import install_generic_stack as installer

SERVICE = {'vmid':4860, 'main':True, 'name':'app', 'ip':'10.77.6.30',
           'healthcheck':{'type':'http','timeout_seconds':360,
                          'endpoint':{'scheme':'http','port':80,'path':'/'}}}

class MainFrontendReadiness(unittest.TestCase):
    def test_probe_and_persistent_health_url_use_advertised_lan_not_backend_ip(self):
        service=copy.deepcopy(SERVICE)
        with patch.object(installer,'run',return_value='10.77.6.30\n172.30.249.70\n'), \
             patch.object(installer,'wait_web') as web:
            url=installer.wait_main_web(service,ipaddress.ip_network('10.77.6.0/24'))
        self.assertEqual(url,'http://172.30.249.70:80/')
        self.assertEqual(service['healthcheck']['url'],url)
        self.assertEqual(service['ip'],'10.77.6.30')
        web.assert_called_once_with(service,url)

    def test_waits_for_dhcp_frontend_without_probing_private_host(self):
        service=copy.deepcopy(SERVICE)
        with patch.object(installer,'lan_access_urls',side_effect=[RuntimeError('not yet'),[{'url':'http://192.0.2.7:80/'}]]), \
             patch.object(installer.time,'sleep') as sleep, patch.object(installer,'wait_web') as web:
            url=installer.wait_main_web(service,ipaddress.ip_network('10.77.6.0/24'))
        self.assertEqual(url,'http://192.0.2.7:80/')
        sleep.assert_called_once_with(1)
        web.assert_called_once_with(service,url)

    def test_no_frontend_address_never_falls_back_to_private_probe(self):
        service=copy.deepcopy(SERVICE)
        with patch.object(installer.time,'monotonic',side_effect=[0,1,121]), \
             patch.object(installer.time,'sleep'), \
             patch.object(installer,'lan_access_urls',side_effect=RuntimeError('not yet')), \
             patch.object(installer,'wait_web') as web, self.assertRaisesRegex(RuntimeError,'No LAN address'):
            installer.wait_main_web(service,ipaddress.ip_network('10.77.6.0/24'))
        web.assert_not_called()

if __name__=='__main__':unittest.main()
