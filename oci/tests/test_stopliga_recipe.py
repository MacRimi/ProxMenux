"""StopLiga's UniFi profile preserves its upstream entrypoint and private state."""
import json
from pathlib import Path
import sys
import unittest
from contextlib import ExitStack
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(Path(__file__).parent)]
from proxmenux_oci.catalog import Catalog
from proxmenux_oci.custom import template_from_oci_compose
from proxmenux_oci.installer import build_deployment, DEFAULT_MODE, ADVANCED_MODE
from proxmenux_oci.cli import _deployment_summary_text
from test_advanced_flow_order import RecordingUI, storages


class StopLigaRecipeTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog(ROOT, catalog_dir=ROOT / 'catalog')
        self.template = self.catalog.compose('stopliga')

    def plan(self, mode):
        ui = RecordingUI({'UniFi controller hostname or IP address': 'controller.example',
                          'Local UniFi API key': 'private-test-key',
                          'Value for STOPLIGA_DRY_RUN': 'true'})
        with ExitStack() as stack:
            for name, kwargs in {
                'i18n.language': {'return_value': 'en'},
                'installer.host.storages': {'side_effect': storages},
                'installer.host.bridges': {'return_value': [{'iface': 'vmbr0'}]},
                'installer.host.timezone': {'return_value': 'UTC'},
                'installer.access.ask_ipv4': {'return_value': ('dhcp', None)},
            }.items():
                stack.enter_context(patch('proxmenux_oci.' + name, **kwargs))
            return build_deployment(self.template, ui, mode), ui

    def test_roundtrip_keeps_non_web_service_and_image_entrypoint(self):
        t = template_from_oci_compose(json.dumps(self.template))
        self.catalog.validate(t)
        self.assertEqual(t['container_contract']['image']['reference'], 'ghcr.io/jcastro/stopliga:latest')
        self.assertEqual(t['first_run']['endpoints'], [])
        self.assertIsNone(t['catalog_ui']['launch']['port'])
        self.assertEqual(t['proxmox']['image_metadata_policy']['entrypoint'], 'import-from-oci-image')

    def test_default_and_advanced_secret_and_dry_run_choices(self):
        for mode in (DEFAULT_MODE, ADVANCED_MODE):
            with self.subTest(mode=mode):
                plan, ui = self.plan(mode)
                env = {e['name']: e['value'] for e in plan['environment']}
                self.assertEqual(env['STOPLIGA_BACKEND'], 'unifi')
                self.assertEqual(env['STOPLIGA_DRY_RUN'], 'true')
                self.assertEqual(env['UNIFI_API_KEY'], 'private-test-key')
                self.assertIn('Value for STOPLIGA_DRY_RUN', ui.asked)
                self.assertNotIn('private-test-key', _deployment_summary_text(self.template, plan))

    def test_plan_has_data_ownership_and_bounded_tmpfs(self):
        plan, _ = self.plan(DEFAULT_MODE)
        self.assertEqual(plan['mounts'][0]['container_path'], '/data')
        self.assertTrue(plan['mounts'][0]['backup'])
        self.assertEqual(self.template['container_contract']['volumes'][0]['installation_choice'], ['managed-volume'])
        tmp = plan['tmpfs_mounts'][0]
        self.assertEqual((tmp['container_path'], tmp['size_mb'], tmp['mode']), ('/tmp', 64, '01777'))
        self.assertIn('noexec', tmp['mount_options'])
        profile = self.template['proxmox']['installer_profile']
        self.assertEqual(profile['volume_owner'], {'uid': 10001, 'gid': 10001})
        self.assertEqual(profile['startup_healthcheck']['type'], 'running')
