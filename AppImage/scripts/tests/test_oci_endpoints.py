import json
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import lxc_apps

ICON = 'https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/go2rtc.webp'
VERSION_FILE = {'path': '/opt/frigate/frigate/version.py', 'regex': 'VERSION = "([0-9]+(?:\\.[0-9]+)+)'}
ENDPOINTS = [
    {'label': 'Frigate WebUI', 'scheme': 'http', 'port': 5000, 'path': '/', 'source': 'x'},
    {'label': 'go2rtc WebUI', 'scheme': 'http', 'port': 1984, 'path': '/', 'source': 'x'},
]


class CatalogFixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'catalog/apps').mkdir(parents=True)
        (self.root / 'catalog/index.json').write_text(json.dumps({'applications': [
            {'id': 'frigate', 'template_id': 'image-frigate', 'template': 'apps/frigate.json',
             'icon': 'https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/frigate.webp'}]}))
        catalog_endpoints = [dict(ENDPOINTS[0]), dict(ENDPOINTS[1], icon=ICON)]
        (self.root / 'catalog/apps/frigate.json').write_text(json.dumps(
            {'id': 'image-frigate', 'first_run': {'endpoints': catalog_endpoints, 'version_file': VERSION_FILE}}))
        patches = [patch.object(lxc_apps, '_OCI_INSTANCE_ROOT', str(self.root / 'instances')),
                   patch.object(lxc_apps, '_OCI_CATALOG_INDEX', str(self.root / 'catalog/index.json')),
                   patch.object(lxc_apps, '_oci_catalog_cache', None)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def install(self, endpoints, template_id='image-frigate', status='installed'):
        (self.root / 'instances/190').mkdir(parents=True)
        (self.root / 'instances/190/oci-compose.json').write_text(json.dumps({
            'vmid': 190, 'status': status, 'installation_id': 'install-190',
            'observed': {'image': {'manifest_digest': 'sha256:' + 'b1' * 32, 'architecture': 'amd64'}},
            'template': {'id': template_id, 'catalog_ui': {'title': 'Frigate'},
                         'first_run': {'endpoints': endpoints},
                         'container_contract': {'image': {'reference': 'ghcr.io/blakeblackshear/frigate:stable'},
                                                'ports': [{'container_port': 8971}]}}}))
        return lxc_apps._oci_instance_meta(190)


class OciEndpointTests(CatalogFixture):
    def test_second_endpoint_is_its_own_service_with_the_current_catalog_icon(self):
        # The record was written before the catalog gave go2rtc an icon.
        meta = self.install(ENDPOINTS)
        self.assertEqual(meta['endpoints'], [
            {'port': 5000, 'scheme': 'http', 'path': '/', 'description': '', 'logo_url': ''},
            {'port': 1984, 'scheme': 'http', 'path': '/', 'description': 'go2rtc', 'logo_url': ICON},
        ])
        self.assertEqual(meta['endpoint_port'], 5000)

    def test_the_record_names_the_container_while_it_is_being_installed(self):
        self.assertEqual(self.install(ENDPOINTS, status='installing')['template_id'], 'image-frigate')

    def test_a_failed_installation_names_nothing(self):
        self.assertIsNone(self.install(ENDPOINTS, status='failed'))

    def test_single_endpoint_and_unknown_template(self):
        meta = self.install([ENDPOINTS[0]], template_id='image-other')
        self.assertEqual(meta['endpoints'], [
            {'port': 5000, 'scheme': 'http', 'path': '/', 'description': '', 'logo_url': ''}])

    def test_generic_second_endpoint_is_not_a_service(self):
        # LinuxServer lists the same interface over http and https as "Web UI 1" and "Web UI 2".
        meta = self.install([dict(ENDPOINTS[0], label='Web UI 1', port=3000),
                             dict(ENDPOINTS[0], label='Web UI 2', port=3001, scheme='https')],
                            template_id='image-krita')
        self.assertEqual([e['port'] for e in meta['endpoints']], [3000])

    def test_service_name_from_label(self):
        for label, name in [('go2rtc WebUI', 'go2rtc'), ('Admin Web UI', 'Admin'), ('Setup UI', 'Setup'),
                            ('Dashboard', 'Dashboard'), ('WebUI', 'WebUI'), ('', '')]:
            with self.subTest(label=label):
                self.assertEqual(lxc_apps._oci_service_name(label), name)

    def test_suggestion_offers_every_endpoint(self):
        self.install(ENDPOINTS)
        with patch.object(lxc_apps, '_probe_listening_ports', return_value=[]), \
             patch.object(lxc_apps, '_helper_slug_meta', return_value=None), \
             patch.object(lxc_apps, '_fetch_tracking_hints', return_value={}), \
             patch.object(lxc_apps, '_oci_image_versions', return_value={'error': 'offline'}), \
             patch.object(lxc_apps, '_read_sidecar', return_value=None):
            suggestion = lxc_apps.get_suggestions(190)
        self.assertEqual(suggestion['default_ports'], [5000, 1984])
        self.assertEqual([d['description'] for d in suggestion['port_details']], ['', 'go2rtc'])
        self.assertEqual(suggestion['port_details'][1]['logo_url'], ICON)

    def test_automatic_registration_registers_every_endpoint(self):
        self.install(ENDPOINTS)
        with patch.object(lxc_apps, '_read_sidecar', return_value=None), \
             patch.object(lxc_apps, '_oci_dismissed', return_value={}), \
             patch.object(lxc_apps, 'add_app', return_value=(True, {})) as add:
            self.assertTrue(lxc_apps.ensure_oci_registration(190))
        ports = add.call_args.args[1]['ports']
        self.assertEqual([(p['port'], p['description']) for p in ports], [(5000, ''), (1984, 'go2rtc')])
        self.assertNotIn('logo_url', ports[0])
        self.assertEqual(ports[1]['logo_url'], ICON)


class OciGuestVersionTests(CatalogFixture):
    def test_version_read_from_the_file_the_catalog_names(self):
        with patch.object(lxc_apps, '_pct_exec', return_value=(0, 'VERSION = "0.18.0-77a66e7"\n', '')) as run:
            self.assertEqual(lxc_apps._oci_guest_version(190, 'image-frigate'), '0.18.0')
        run.assert_called_once_with(190, ['cat', '/opt/frigate/frigate/version.py'])

    def test_stopped_container_and_template_without_version_file(self):
        with patch.object(lxc_apps, '_pct_exec', return_value=(1, '', 'CT 190 not running')):
            self.assertIsNone(lxc_apps._oci_guest_version(190, 'image-frigate'))
        with patch.object(lxc_apps, '_pct_exec') as run:
            self.assertIsNone(lxc_apps._oci_guest_version(190, 'image-other'))
            run.assert_not_called()

    def test_image_without_version_label_uses_the_guest(self):
        self.install(ENDPOINTS)
        # A cached answer without a version must not stop the guest read.
        known = {'installed_digest': 'sha256:' + 'b1' * 32, 'installed_version': None, 'image_created': '2026-09-06'}
        with patch.object(lxc_apps, '_oci_operation_running', return_value=False), \
             patch.object(lxc_apps, '_oci_state_module', return_value=object()), \
             patch.object(lxc_apps, '_pct_exec', return_value=(0, 'VERSION = "0.18.0-77a66e7"', '')):
            result = lxc_apps._oci_image_versions(190, known=known, with_latest=False)
        self.assertEqual(result['installed_version'], '0.18.0')
        self.assertEqual(result['image_created'], '2026-09-06')


if __name__ == '__main__':
    unittest.main()
