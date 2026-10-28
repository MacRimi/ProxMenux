"""Pasted Compose files enter the same checked stack flow as catalog recipes."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from proxmenux_oci import custom
from proxmenux_oci.converter import ConversionError
from proxmenux_oci.stack import ordered_services, resolve_environments, service_template

COMPOSE = '''services:
  db:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: supplied-password
    volumes: [dbdata:/var/lib/postgresql/data]
  app:
    image: adminer:4
    ports: ['8080:8080']
    depends_on: [db]
volumes:
  dbdata:
'''


class CustomComposeStacks(unittest.TestCase):
    def test_stack_uses_existing_installer_and_preserves_versions_and_environment(self):
        template = custom.template_from_compose(COMPOSE)
        self.assertTrue(template['compatibility']['automatic_install_candidate'])
        self.assertEqual(template['proxmox']['installer_profile']['stack_driver'], 'generic-multi-lxc-stack')
        self.assertEqual(template['compose_stack']['main_service'], 'app')
        services = ordered_services(template)
        self.assertEqual([s['name'] for s in services], ['db', 'app'])
        self.assertEqual([s['image'] for s in services], ['postgres:16', 'adminer:4'])
        self.assertEqual(resolve_environments(services, 'UTC')['db']['POSTGRES_PASSWORD'], 'supplied-password')
        self.assertEqual(service_template(template, services[0])['container_contract']['image']['reference'], 'postgres:16')
        self.assertNotIn('supplied-password', custom.describe(template))

    def test_stack_summary_hides_credentials_embedded_in_a_url(self):
        document = COMPOSE.replace(
            "    ports:",
            "    environment: {DATABASE_URL: 'postgres://user:embedded-secret@db/app'}\n    ports:")
        template = custom.template_from_compose(document)
        summary = custom.describe(template)
        self.assertIn('DATABASE_URL', summary)
        self.assertNotIn('embedded-secret', summary)
        self.assertNotIn('postgres://user:', summary)
        app = next(service for service in ordered_services(template) if service['name'] == 'app')
        self.assertIn('embedded-secret', app['compose']['environment']['DATABASE_URL'])

    def test_invalid_stack_metadata_has_a_conversion_error(self):
        for metadata in ('x-casaos: not-a-mapping', 'x-casaos: [app]',
                         'x-casaos: {main: missing-service}'):
            with self.subTest(metadata=metadata), self.assertRaises(ConversionError):
                custom.template_from_compose(COMPOSE + metadata + '\n')

    def test_written_digest_and_tag_survive_in_full_image_contracts(self):
        digest = 'sha256:' + 'a' * 64
        reference = 'ghcr.io/example/adminer:4@' + digest
        template = custom.template_from_compose(COMPOSE.replace('adminer:4', reference))
        main_image = template['container_contract']['image']
        for image in (main_image, service_template(template, next(
                service for service in ordered_services(template) if service['name'] == 'app'),
                main=True)['container_contract']['image']):
            self.assertEqual(image['reference'], reference)
            self.assertEqual(image['registry'], 'ghcr.io')
            self.assertEqual(image['repository'], 'ghcr.io/example/adminer')
            self.assertEqual(image['tag'], '4')
            self.assertEqual(image['digest'], digest)
            self.assertEqual(image['pull_policy'],
                             'resolve-written-reference-to-architecture-digest-at-install')
        dependency = service_template(template, ordered_services(template)[0])['container_contract']['image']
        self.assertEqual(dependency['reference'], 'postgres:16')
        self.assertEqual(dependency['repository'], 'postgres')
        self.assertEqual(dependency['tag'], '16')
        self.assertIsNone(dependency['digest'])

    def test_reject_unsafe_dependency_mount_or_build(self):
        for value in ('    volumes: [/var/run/docker.sock:/var/run/docker.sock]',
                      '    build: .'):
            with self.subTest(value=value), self.assertRaises(ConversionError):
                custom.template_from_compose(COMPOSE.replace('    volumes: [dbdata:/var/lib/postgresql/data]', value))

    def test_shared_storage_is_supported_by_custom_stack(self):
        template = custom.template_from_compose(COMPOSE.replace("    ports:", "    volumes: [dbdata:/shared]\n    ports:"))
        self.assertTrue(template['compatibility']['automatic_install_candidate'])
        self.assertEqual(template['compatibility']['untranslated_blockers'], [])

    def test_every_image_checked_before_install(self):
        class UI:
            def message(self, text, title):
                self.text = text
        ui = UI()
        with patch.object(custom, 'read_definition', return_value=(COMPOSE, 'Compose')), \
             patch.object(custom, 'registry_report', side_effect=[(True, 'db ok'), (False, 'app missing')]) as report, \
             patch.object(custom, '_registry_refused', return_value=False), \
             patch.object(custom, 'install_template') as install:
            custom.explore(ui)
        self.assertEqual([c.args[0] for c in report.call_args_list], ['postgres:16', 'adminer:4'])
        install.assert_not_called()
        self.assertIn('app missing', ui.text)

    def test_single_image_still_uses_single_container_flow(self):
        template = custom.template_from_compose('services: {app: {image: nginx:1.27}}')
        self.assertNotEqual(template['proxmox'].get('installer_profile', {}).get('stack_driver'), 'generic-multi-lxc-stack')
        self.assertEqual(template['container_contract']['image']['reference'], 'nginx:1.27')


if __name__ == '__main__':
    unittest.main()
