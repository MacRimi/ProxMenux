"""Custom stacks keep each app's endpoint and actual shared storage identity."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from proxmenux_oci.casaos import convert_casaos_compose
from proxmenux_oci.stack import apply_stack_support, assess, build_stack, DefaultsUI, service_template
from proxmenux_oci.installer import DEFAULT_MODE, ADVANCED_MODE

COMPOSE = '''name: arr-test
services:
  sonarr:
    image: lscr.io/linuxserver/sonarr:latest
    ports: ['8989:8989']
    environment: {PUID: '1000', PGID: '1000'}
    volumes: [sonarr-config:/config, shared-data:/data]
  radarr:
    image: lscr.io/linuxserver/radarr:latest
    ports: ['7878:7878']
    environment: {PUID: '1000', PGID: '1000'}
    volumes: [radarr-config:/config, shared-data:/data]
volumes:
  sonarr-config:
  radarr-config:
  shared-data:
x-casaos:
  main: sonarr
  port_map: '8989'
  scheme: http
  index: /
  title: {en_US: Arr Test}
'''


def template(custom=True, text=COMPOSE):
    result = convert_casaos_compose(text, 'local', '', 'local/arr-test/docker-compose.yml', '')
    result['proxmox']['custom_compose_stack'] = custom
    apply_stack_support(result)
    return result


class UI(DefaultsUI):
    def __init__(self):
        self.asks = []
    def ask(self, text, default=None, **kwargs):
        self.asks.append(text)
        return default or ''


class CustomMultiAppStackTests(unittest.TestCase):
    def test_custom_opt_in_supports_two_web_apps_but_catalog_remains_guarded(self):
        self.assertEqual(assess(template()), [])
        self.assertTrue(assess(template(custom=False)))

    def test_app_without_own_port_is_rejected(self):
        result = template(text=COMPOSE.replace("    ports: ['7878:7878']\n", ''))
        self.assertTrue(any('health and persistence' in e for e in assess(result)))

    def test_service_image_contract_preserves_tag_and_digest(self):
        parent = template()
        service = parent['compose_stack']['services'][0]
        for reference, repository, tag, digest in (
            ('ghcr.io/example/app:2.4', 'ghcr.io/example/app', '2.4', None),
            ('ghcr.io/example/app:2.4@sha256:'+'a'*64, 'ghcr.io/example/app', '2.4', 'sha256:'+'a'*64),
        ):
            with self.subTest(reference=reference):
                service['image'] = reference
                service['compose']['image'] = reference
                image = service_template(parent, service)['container_contract']['image']
                self.assertEqual((image['reference'], image['repository'], image['tag'], image['digest']),
                                 (reference, repository, tag, digest))
                self.assertEqual(image['registry'], 'ghcr.io')

    def test_compose_extension_metadata_is_accepted_only_for_custom(self):
        text = 'x-common-environment: &common {PUID: \'1000\'}\n' + COMPOSE
        self.assertEqual(assess(template(text=text)), [])
        self.assertTrue(assess(template(custom=False, text=text)))

    def test_shared_owners_must_match(self):
        result = template(text=COMPOSE.replace("environment: {PUID: '1000', PGID: '1000'}", "environment: {PUID: '1001', PGID: '1000'}", 1))
        self.assertTrue(any('shared' in e for e in assess(result)))

    def test_advanced_addresses_are_kept_per_service(self):
        ui = UI()
        supplied = {'sonarr': '192.0.2.21/24', 'radarr': '192.0.2.22/24'}
        with patch('proxmenux_oci.installer.ask_storage', return_value='local-zfs'), \
             patch('proxmenux_oci.installer.ask_bridge', return_value='vmbr0'), \
             patch('proxmenux_oci.host.timezone', return_value='UTC'), \
             patch('proxmenux_oci.custom_mounts.ask_stack_custom_mounts'), \
             patch('proxmenux_oci.extra_devices.ask_stack_extra_devices'), \
             patch('proxmenux_oci.network.ask_addresses', return_value=(supplied, '192.0.2.1')):
            plan = build_stack(template(), ui, ADVANCED_MODE)
        self.assertEqual({s['name']:s['frontend_ipv4'] for s in plan['services']}, supplied)
        self.assertEqual(plan['network']['frontend_gateway'], '192.0.2.1')

    def test_build_assigns_distinct_endpoints_and_shared_bind_source(self):
        ui = UI()
        with patch('proxmenux_oci.installer.ask_storage', return_value='local-zfs'), \
             patch('proxmenux_oci.installer.ask_bridge', return_value='vmbr0'), \
             patch('proxmenux_oci.host.timezone', return_value='UTC'), \
             patch('proxmenux_oci.network.ask_addresses', side_effect=lambda ui, bridge, labels: ({name:'dhcp' for name in labels}, None)):
            plan = build_stack(template(), ui, DEFAULT_MODE)
        members = {s['name']:s for s in plan['services']}
        self.assertEqual(members['sonarr']['healthcheck']['endpoint']['port'], 8989)
        self.assertEqual(members['radarr']['healthcheck']['endpoint']['port'], 7878)
        for member in members.values():
            self.assertTrue(member['frontend'])
            self.assertEqual(member['frontend_ipv4'], 'dhcp')
        binds = [next(m for m in s['deployment']['mounts'] if m['container_path']=='/data') for s in members.values()]
        self.assertEqual(binds[0]['source'], binds[1]['source'])
        self.assertEqual(binds[0]['host_owner'], [101000, 101000])
        self.assertTrue(all(m['type']=='host-bind' and m['backup'] is False for m in binds))
        self.assertEqual(len([text for text in ui.asks if text.endswith('shared-data')]), 1)
        configs = [next(m for m in s['deployment']['mounts'] if m['container_path']=='/config') for s in members.values()]
        self.assertTrue(all(m['type']=='managed-volume' for m in configs))


if __name__ == '__main__':
    unittest.main()
