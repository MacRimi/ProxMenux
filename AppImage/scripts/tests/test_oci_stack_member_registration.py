"""A secondary container of an OCI stack is registered with the version it
runs and no version tracking; its application is updated with the stack."""
from contextlib import nullcontext
import json
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import lxc_apps
import oci_instance_info

DIGEST = 'sha256:' + 'ab' * 32


class StackMemberRegistrationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'catalog').mkdir()
        (self.root / 'catalog/index.json').write_text(json.dumps({'applications': []}))
        patches = [patch.object(lxc_apps, '_OCI_INSTANCE_ROOT', str(self.root / 'instances')),
                   patch.object(oci_instance_info, '_installation', side_effect=lambda vmid: f'install-{vmid}'),
                   patch.object(lxc_apps, '_OCI_CATALOG_INDEX', str(self.root / 'catalog/index.json')),
                   patch.object(lxc_apps, '_oci_catalog_cache', None),
                   patch.object(lxc_apps, '_APPS_DIR', str(self.root / 'apps')),
                   patch.object(lxc_apps, '_OCI_DISMISSED_FILE', str(self.root / 'apps/.oci-dismissed.json'))]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def record(self, vmid, primary, reference):
        folder = self.root / f'instances/{vmid}'
        folder.mkdir(parents=True)
        (folder / 'oci-compose.json').write_text(json.dumps({
            'vmid': vmid, 'status': 'installed', 'installation_id': f'install-{vmid}',
            'stack_member': {'name': 'database', 'primary_vmid': primary},
            'stack': {'template': {'id': 'stack-nextcloud', 'catalog_ui': {'title': 'Nextcloud'},
                                   'first_run': {'endpoints': [{'port': 80, 'scheme': 'http', 'path': '/'}]}}},
            'observed': {'image': {'manifest_digest': DIGEST, 'architecture': 'amd64'}},
            'template': {'id': f'stack-nextcloud-{vmid}',
                         'container_contract': {'image': {'reference': reference},
                                                'ports': [{'container_port': 5432}]}}}))

    def test_the_database_of_a_stack_is_registered_without_a_web_port(self):
        self.record(131, 129, 'docker.io/library/postgres:16-alpine')
        with patch.object(lxc_apps, 'add_app', return_value=(True, {})) as add:
            self.assertTrue(lxc_apps.ensure_oci_registration(131))
        payload = add.call_args.args[1]
        self.assertEqual(payload['name'], 'Postgres')
        self.assertEqual(payload['installed_via'], 'oci_image')
        self.assertEqual(payload['ports'], [])

    def test_a_secondary_container_is_told_apart_from_the_main_one(self):
        self.assertTrue(lxc_apps._oci_secondary_member({'vmid': 131, 'stack_member': {'primary_vmid': 129}}))
        self.assertFalse(lxc_apps._oci_secondary_member({'vmid': 129, 'stack_member': {'primary_vmid': 129}}))
        self.assertFalse(lxc_apps._oci_secondary_member({'vmid': 120}))
        self.assertFalse(lxc_apps._oci_secondary_member(None))

    def test_the_registry_is_not_asked_for_a_secondary_container(self):
        self.record(131, 129, 'docker.io/library/postgres:16-alpine')

        class Engine:
            @staticmethod
            def resolve_candidate(reference, architecture):
                assert '@' in reference, 'only the installed digest is read'
                return {'version': '16.15', 'created': '2026-09-01T00:00:00Z', 'manifest_digest': DIGEST}

        with patch.object(lxc_apps, '_oci_state_module', return_value=Engine):
            result = lxc_apps._oci_image_versions(
                131, with_latest=not lxc_apps._oci_secondary_member(lxc_apps._read_oci_record(131)))
        self.assertEqual(result['installed_version'], '16.15')
        self.assertNotIn('update_available', result)
        self.assertNotIn('latest_version', result)


if __name__ == '__main__':
    unittest.main()


class StackLogoTests(StackMemberRegistrationTests):
    ICON = 'https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/immich.webp'

    def stack(self):
        (self.root / 'catalog/index.json').write_text(json.dumps({'applications': [
            {'id': 'immich', 'template_id': 'image-immich', 'template': 'apps/immich.json', 'icon': self.ICON}]}))
        members = {115: ('server', 'ghcr.io/immich-app/immich-server:release'),
                   116: ('machine-learning', 'ghcr.io/immich-app/immich-machine-learning:release'),
                   117: ('database', 'ghcr.io/immich-app/postgres:14-vectorchord0.4.3'),
                   118: ('valkey', 'docker.io/valkey/valkey:9')}
        for vmid, (role, reference) in members.items():
            folder = self.root / f'instances/{vmid}'
            folder.mkdir(parents=True)
            record = {'vmid': vmid, 'status': 'installed', 'installation_id': f'install-{vmid}',
                      'stack_member': {'name': role, 'primary_vmid': 115},
                      'observed': {'image': {'manifest_digest': DIGEST, 'architecture': 'amd64'}},
                      'template': {'id': f'image-immich-{role}',
                                   'container_contract': {'image': {'reference': reference}, 'ports': []}}}
            if vmid == 115:
                record['stack'] = {'template': {'id': 'image-immich', 'catalog_ui': {'title': 'Immich', 'icon': None}}}
            (folder / 'oci-compose.json').write_text(json.dumps(record))

    def test_the_main_container_and_machine_learning_wear_the_application_logo(self):
        self.stack()
        self.assertEqual(lxc_apps._oci_instance_meta(115)['logo'], self.ICON)
        self.assertEqual(lxc_apps._oci_instance_meta(116)['logo'], self.ICON)

    def test_the_database_and_the_cache_wear_their_own(self):
        self.stack()
        self.assertTrue(lxc_apps._oci_instance_meta(117)['logo'].endswith('/postgresql.webp'))
        self.assertTrue(lxc_apps._oci_instance_meta(118)['logo'].endswith('/valkey.webp'))

    def test_an_application_registered_without_logo_takes_it_later(self):
        self.stack()
        sidecar = {'vmid': 115, 'apps': [{'id': 'a', 'name': 'Immich', 'installed_via': 'oci_image', 'logo_url': ''},
                                          {'id': 'b', 'name': 'Other', 'installed_via': '', 'logo_url': ''}]}
        written = {}
        with patch.object(lxc_apps, '_read_sidecar', return_value=sidecar), \
                patch.object(lxc_apps, '_write_sidecar', side_effect=lambda vmid, data, **_: written.update(data)):
            self.assertFalse(lxc_apps.ensure_oci_registration(115))
        self.assertEqual(written['apps'][0]['logo_url'], self.ICON)
        self.assertEqual(written['apps'][1]['logo_url'], '')


class ComposeStackMainTests(StackMemberRegistrationTests):
    """A Compose stack gives every member a sheet named after its service."""

    def stack(self):
        folder = self.root / 'instances/152'
        folder.mkdir(parents=True)
        (folder / 'oci-compose.json').write_text(json.dumps({
            'vmid': 152, 'status': 'installed', 'installation_id': 'install-152',
            'stack_member': {'name': 'web', 'primary_vmid': 152},
            'stack': {'template': {'id': 'image-sure', 'catalog_ui': {'title': {'en_US': 'Sure'},
                                                                      'category_label': 'Finance & Budgeting'},
                                   'first_run': {'endpoints': [{'port': 3000, 'scheme': 'http', 'path': '/'}]}}},
            'observed': {'image': {'manifest_digest': DIGEST, 'architecture': 'amd64'}},
            'template': {'id': 'image-web', 'catalog_ui': {'title': {'en_US': 'web'}},
                         'first_run': {'endpoints': []},
                         'container_contract': {'image': {'reference': 'ghcr.io/we-promise/sure:stable'},
                                                'ports': [{'container_port': 3000}]}}}))

    def test_the_main_container_is_registered_as_the_application(self):
        self.stack()
        with patch.object(lxc_apps.local_app_icons, 'protect_references', side_effect=lambda *_: nullcontext()), \
                patch.object(lxc_apps, '_sync_copies') as sync, \
                patch.object(lxc_apps, 'check_app') as check:
            self.assertTrue(lxc_apps.ensure_oci_registration(152))
            self.assertFalse(lxc_apps.ensure_oci_registration(152))
        stored = json.loads((self.root / 'apps/152.json').read_text())
        self.assertEqual(len(stored['apps']), 1)
        app = stored['apps'][0]
        self.assertEqual(app['name'], 'Sure')
        self.assertEqual([(p['port'], p['scheme']) for p in app['ports']], [(3000, 'http')])
        self.assertEqual(lxc_apps.load_sidecar(152)['apps'][0]['id'], app['id'])
        sync.assert_called_once()
        check.assert_called_once_with(152, app['id'], force=True, notify=False)

    def test_a_registration_named_after_the_service_takes_the_application(self):
        self.stack()
        sidecar = {'vmid': 152, 'apps': [{'id': 'a', 'name': 'web', 'installed_via': 'oci_image',
                                          'logo_url': 'https://example.com/sure.webp', 'ports': []}]}
        written = {}
        with patch.object(lxc_apps, '_read_sidecar', return_value=sidecar), \
                patch.object(lxc_apps, '_write_sidecar', side_effect=lambda vmid, data, **_: written.update(data)):
            self.assertFalse(lxc_apps.ensure_oci_registration(152))
        self.assertEqual(written['apps'][0]['name'], 'Sure')
        self.assertEqual(written['apps'][0]['ports'][0]['port'], 3000)

    def test_a_registration_the_user_named_is_left_alone(self):
        self.stack()
        sidecar = {'vmid': 152, 'apps': [{'id': 'a', 'name': 'Finances', 'installed_via': 'oci_image',
                                          'logo_url': 'https://example.com/sure.webp', 'ports': []}]}
        with patch.object(lxc_apps, '_read_sidecar', return_value=sidecar), \
                patch.object(lxc_apps, '_write_sidecar') as write:
            self.assertFalse(lxc_apps.ensure_oci_registration(152))
        write.assert_not_called()

    def test_reused_vmid_stops_registration_and_migration_before_writing(self):
        self.stack()
        old_app = {'id': 'a', 'name': 'web', 'installed_via': 'oci_image',
                   'logo_url': 'https://example.com/sure.webp', 'ports': []}
        original_ports = lxc_apps._oci_registration_ports
        for existing in (False, True):
            with self.subTest(existing=existing), \
                    patch.object(oci_instance_info, '_installation', return_value='install-152') as identity:
                sidecar = {'vmid': 152, 'apps': [dict(old_app)]} if existing else None

                def ports_after_reuse(meta, secondary):
                    ports = original_ports(meta, secondary)
                    identity.return_value = 'replacement-152'
                    return ports

                with patch.object(lxc_apps, '_read_sidecar', return_value=sidecar), \
                        patch.object(lxc_apps, '_oci_registration_ports', side_effect=ports_after_reuse), \
                        patch.object(lxc_apps, 'add_app', return_value=(True, {})) as add, \
                        patch.object(lxc_apps, '_write_sidecar') as write:
                    registered = lxc_apps.ensure_oci_registration(152)
                add.assert_not_called()
                write.assert_not_called()
                self.assertFalse(registered)
                if existing:
                    self.assertEqual(sidecar['apps'], [old_app])
