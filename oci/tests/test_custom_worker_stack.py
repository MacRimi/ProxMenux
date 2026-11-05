"""Custom internal helpers need explicit readiness and never gain a LAN by expose."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from proxmenux_oci.custom import template_from_compose
from proxmenux_oci.stack import (assess, build_stack, compose_healthcheck,
                                DefaultsUI, kind, resolve_environments, StackError)
from proxmenux_oci.installer import DEFAULT_MODE

COMPOSE = '''name: worker-example
services:
  web:
    image: nginx:1.27
    ports: ['8080:80']
    depends_on: [helper]
  helper:
    image: example/helper:1
    expose: ['3000']
'''


def build(template):
    with patch('proxmenux_oci.installer.ask_storage', return_value='local-zfs'), \
         patch('proxmenux_oci.installer.ask_bridge', return_value='vmbr0'), \
         patch('proxmenux_oci.host.timezone', return_value='UTC'), \
         patch('proxmenux_oci.network.ask_addresses', side_effect=lambda ui, bridge, labels: ({name: 'dhcp' for name in labels}, None)):
        return build_stack(template, DefaultsUI(), DEFAULT_MODE)


class WorkerStackTests(unittest.TestCase):
    def test_exposed_helper_gets_internal_tcp_check_without_frontend(self):
        template = template_from_compose(COMPOSE)
        self.assertEqual(assess(template), [])
        services = {service['name']: service for service in build(template)['services']}
        self.assertEqual(services['helper']['healthcheck']['port'], 3000)
        self.assertEqual(services['helper']['healthcheck']['type'], 'tcp')
        self.assertNotIn('frontend', services['helper'])
        self.assertTrue(services['web']['frontend'])
        self.assertEqual(services['web']['healthcheck']['endpoint']['port'], 80)

    def test_service_healthy_does_not_invent_an_http_or_tcp_health_contract(self):
        document = COMPOSE.replace('depends_on: [helper]', 'depends_on: {helper: {condition: service_healthy}}')
        template = template_from_compose(document)
        self.assertFalse(template['compatibility']['automatic_install_candidate'])
        self.assertTrue(any('health and persistence' in error for error in assess(template)))
        checked = document + "    healthcheck: {test: ['CMD', 'test', '-f', '/ready']}\n"
        self.assertEqual(assess(template_from_compose(checked)), [])

    def test_worker_exec_check_is_preserved_without_exposing_a_port(self):
        document = COMPOSE.replace("    expose: ['3000']", "    healthcheck:\n      test: ['CMD', 'test', '-f', '/ready']\n      interval: 10s\n      timeout: 2s\n      start_period: 20s\n      retries: 3")
        template = template_from_compose(document)
        self.assertEqual(assess(template), [])
        services = {service['name']: service for service in build(template)['services']}
        check = services['helper']['healthcheck']
        self.assertEqual(check['type'], 'exec')
        self.assertEqual(check['argv'], ['test', '-f', '/ready'])
        self.assertEqual(check['timeout_seconds'], 56)
        self.assertNotIn('frontend', services['helper'])

    def test_explicit_check_takes_precedence_over_inferred_internal_http(self):
        document = COMPOSE + "    healthcheck: {test: ['CMD-SHELL', 'test -f /ready && test -f /worker-ready']}\n"
        template = template_from_compose(document)
        self.assertEqual(assess(template), [])
        helper = next(service for service in build(template)['services'] if service['name'] == 'helper')
        self.assertEqual(helper['healthcheck']['type'], 'exec')
        self.assertEqual(helper['healthcheck']['argv'], ['sh', '-c', 'test -f /ready && test -f /worker-ready'])

    def test_main_exec_check_retains_the_published_web_endpoint(self):
        document = COMPOSE.replace("    ports: ['8080:80']", "    ports: ['8080:80']\n    healthcheck: {test: ['CMD', 'test', '-f', '/ready']}")
        template = template_from_compose(document)
        self.assertEqual(assess(template), [])
        web = next(service for service in build(template)['services'] if service['name'] == 'web')
        self.assertEqual(web['healthcheck']['type'], 'exec')
        self.assertEqual(web['healthcheck']['argv'], ['test', '-f', '/ready'])
        self.assertEqual(web['healthcheck']['endpoint'], {'scheme': 'http', 'port': 80, 'path': '/'})
        self.assertTrue(web['frontend'])

    def test_main_dependency_is_still_rejected_before_allocation(self):
        document = COMPOSE.replace('    depends_on: [helper]\n', '').replace("    expose: ['3000']", "    expose: ['3000']\n    depends_on: [web]")
        template = template_from_compose(document)
        self.assertFalse(template['compatibility']['automatic_install_candidate'])
        self.assertTrue(any('main service' in error for error in assess(template)))

    def test_disabled_check_without_endpoint_is_explicitly_running_only(self):
        document = COMPOSE.replace("    expose: ['3000']", '    healthcheck: {disable: true}')
        template = template_from_compose(document)
        self.assertEqual(assess(template), [])
        helper = next(service for service in build(template)['services'] if service['name'] == 'helper')
        self.assertEqual(helper['healthcheck']['type'], 'running')

    def test_invalid_healthcheck_or_runtime_environment_requirement_needs_review(self):
        for check in ({'test': ['CMD-SHELL', 'test -n "$TOKEN"']},
                      {'test': ['CMD', '']}, {'test': ['CMD', 'a\nb']},
                      {'test': ['CMD', 'true'], 'interval': '0s'},
                      {'test': ['CMD', 'true'], 'retries': -1},
                      {'test': ['CMD', 'true'], 'start_period': '2h'},
                      {'test': ['CMD', 'true'], 'timeout': 'nonsense'}):
            with self.subTest(check=check), self.assertRaises(StackError):
                compose_healthcheck({'compose': {'healthcheck': check}})

    def test_dockerhub_aliases_keep_the_existing_database_health_profiles(self):
        for image, expected in [('docker.io/library/postgres:16', 'postgres'),
                                ('docker.io/library/redis:7', 'redis'),
                                ('docker.io/valkey/valkey:8', 'valkey/valkey'),
                                ('index.docker.io/library/mariadb:11', 'mariadb')]:
            with self.subTest(image=image):
                self.assertEqual(kind(image), expected)

    def test_custom_server_flags_preserve_native_health_check(self):
        document = COMPOSE.replace('example/helper:1', 'docker.io/library/redis:7').replace(
            "    expose: ['3000']", "    command: ['redis-server', '--appendonly', 'yes', '--maxmemory-policy', 'noeviction']")
        template = template_from_compose(document)
        self.assertEqual(assess(template), [])
        helper = next(service for service in build(template)['services'] if service['name'] == 'helper')
        self.assertEqual(helper['kind'], 'redis')
        self.assertEqual(helper['healthcheck']['type'], 'exec')
        self.assertIn('redis-cli', str(helper['healthcheck']['argv']))

    def test_a_different_binary_or_unhandled_auth_does_not_use_default_database_readiness(self):
        for command in ("['sh', '-c', 'redis-server']", "['redis-server', '--requirepass', 'secret']"):
            document = COMPOSE.replace('example/helper:1', 'redis:7').replace(
                "    expose: ['3000']", '    command: ' + command)
            template = template_from_compose(document)
            self.assertTrue(any('custom dependency commands' in error for error in assess(template)))

    def test_plain_worker_uses_running_only_when_dependency_requires_started(self):
        template = template_from_compose(COMPOSE.replace("    expose: ['3000']", "    command: ['worker', '--watch']"))
        self.assertEqual(assess(template), [])
        helper = next(service for service in build(template)['services'] if service['name'] == 'helper')
        self.assertEqual(helper['healthcheck'], {'type': 'running', 'timeout_seconds': 30})
        self.assertNotIn('frontend', helper)
        self.assertEqual(helper['template']['proxmox']['installer_profile']['runtime']['command'], ['worker', '--watch'])

    def test_running_only_worker_cannot_satisfy_service_healthy(self):
        document = COMPOSE.replace('depends_on: [helper]', 'depends_on: {helper: {condition: service_healthy}}').replace("    expose: ['3000']", "    command: ['worker', '--watch']")
        template = template_from_compose(document)
        self.assertFalse(template['compatibility']['automatic_install_candidate'])
        self.assertTrue(any('helper: service_healthy' in error for error in assess(template)))

    def test_exposed_tcp_port_alone_is_not_a_declared_service_healthy_check(self):
        template = template_from_compose(COMPOSE.replace('depends_on: [helper]', 'depends_on: {helper: {condition: service_healthy}}'))
        self.assertTrue(any('helper: service_healthy' in error for error in assess(template)))

    def test_explicit_worker_check_can_satisfy_service_healthy(self):
        document = COMPOSE.replace('depends_on: [helper]', 'depends_on: {helper: {condition: service_healthy}}').replace("    expose: ['3000']", "    healthcheck: {test: ['CMD', 'test', '-f', '/ready']}")
        template = template_from_compose(document)
        self.assertEqual(assess(template), [])
        helper = next(service for service in build(template)['services'] if service['name'] == 'helper')
        self.assertEqual(helper['healthcheck']['type'], 'exec')

    def test_option_only_database_command_requires_verified_entrypoint_and_keeps_argv(self):
        command = ['--transaction-isolation=READ-COMMITTED', '--binlog-format=ROW']
        document = COMPOSE.replace('example/helper:1', 'mariadb:11').replace("    expose: ['3000']", "    command: ['--transaction-isolation=READ-COMMITTED', '--binlog-format=ROW']")
        template = template_from_compose(document)
        self.assertTrue(any('custom dependency commands' in error for error in assess(template)))
        template = template_from_compose(document, image_entrypoints={'mariadb:11': ['docker-entrypoint.sh']})
        self.assertTrue(template['compatibility']['automatic_install_candidate'])
        self.assertEqual(assess(template), [])
        helper = next(service for service in build(template)['services'] if service['name'] == 'helper')
        self.assertEqual(helper['template']['proxmox']['installer_profile']['runtime']['command'], command)
        self.assertEqual(helper['healthcheck']['argv'], ['healthcheck.sh', '--connect', '--innodb_initialized'])

    def test_literal_environment_preserves_all_explicit_dollar_values(self):
        services = [{'name': 'helper', 'image': 'example/helper:1',
                     'compose': {'environment': {'PASSWORD': 'cash$VALUE${OTHER}', 'TOKEN': '${GENERATED_LOCAL_TOKEN}'}}}]
        result = resolve_environments(services, 'UTC', literal=True)['helper']
        self.assertEqual(result['PASSWORD'], 'cash$VALUE${OTHER}')
        self.assertEqual(result['TOKEN'], '${GENERATED_LOCAL_TOKEN}')
        with self.assertRaises(StackError):
            resolve_environments(services, 'UTC')

    def test_literal_explicit_empty_environment_clears_inherited_image_value(self):
        document = COMPOSE.replace("    expose: ['3000']", "    expose: ['3000']\n    environment: {CLEAR_IMAGE_DEFAULT: ''}")
        template = template_from_compose(document, interpolated=True)
        helper = next(service for service in build(template)['services'] if service['name'] == 'helper')
        self.assertEqual({item['name']: item['value'] for item in helper['deployment']['environment']},
                         {'CLEAR_IMAGE_DEFAULT': ''})
        template['proxmox']['custom_compose_interpolated'] = False
        helper = next(service for service in build(template)['services'] if service['name'] == 'helper')
        self.assertEqual(helper['deployment']['environment'], [])

    def test_literal_database_url_is_not_rebound_or_forced_to_have_a_password(self):
        services = [
            {'name': 'db', 'image': 'postgres:16', 'compose': {'environment': {'POSTGRES_USER': 'bootstrap', 'POSTGRES_HOST_AUTH_METHOD': 'trust'}}},
            {'name': 'app', 'image': 'example/app:1', 'compose': {'environment': {'DATABASE_URL': 'postgresql://explicit-user@db/app'}}},
        ]
        result = resolve_environments(services, 'UTC', literal=True)
        self.assertEqual(result['app']['DATABASE_URL'], 'postgresql://explicit-user@db/app')
        services[0]['compose']['environment']['POSTGRES_PASSWORD'] = 'bootstrap-password'
        services[1]['compose']['environment']['DATABASE_URL'] = 'postgresql://other-user:explicit-password@db/app'
        result = resolve_environments(services, 'UTC', literal=True)
        self.assertEqual(result['app']['DATABASE_URL'], 'postgresql://other-user:explicit-password@db/app')

    def test_fully_interpolated_custom_stack_does_not_reparse_literal_environment(self):
        template = template_from_compose(COMPOSE.replace("    expose: ['3000']", "    expose: ['3000']\n    environment: {PASSWORD: 'cash$VALUE'}"))
        template['proxmox']['custom_compose_interpolated'] = True
        self.assertEqual(assess(template), [])
        helper = next(service for service in build(template)['services'] if service['name'] == 'helper')
        self.assertEqual(helper['deployment']['environment'][0]['value'], 'cash$VALUE')


if __name__ == '__main__':
    unittest.main()
