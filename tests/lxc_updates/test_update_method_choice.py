"""Updater consent regressions: temporary sidecars, no guests or network."""
import ast
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import types
import unittest
import uuid
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'AppImage/scripts'))
import lxc_apps as apps


def routes():
    names = {'_scheduled_helper_enabled', '_resolve_bulk_update_plan',
             '_compose_scheduled_update_command', '_run_scheduled_update',
             '_normalise_schedule_targets'}
    nodes = [node for node in ast.parse((ROOT / 'AppImage/scripts/flask_server.py').read_text()).body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    ns = dict(json=json, os=os, re=re, time=time, uuid=uuid, datetime=datetime,
              subprocess=types.SimpleNamespace(run=Mock(return_value=types.SimpleNamespace(returncode=0)),
                                               TimeoutExpired=subprocess.TimeoutExpired),
              _DOCKER_ENGINE_INTEGRATED_COMMAND='integrated-docker',
              _APPLY_UPDATES_SCRIPT=str(ROOT / 'scripts/lxc/apply_updates.sh'),
              _create_lxc_update_log=lambda *_: ('test.log', None),
              _fast_guest_status=lambda *_: 'running',
              _lxc_update_snapshot=lambda *_: {'ct_name': 'test'},
              _lxc_update_target_labels=lambda *_: [],
              _append_lxc_update_log=lambda *_: None,
              _prune_lxc_update_logs=lambda *_: None,
              _finalize_lxc_update=Mock(return_value={}),
              _inspect_lxc_reboot_requirement=lambda *_, **__: (False, [], None))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'update-routes', 'exec'), ns)
    return ns


class UpdateChoiceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.addCleanup(patch.stopall)
        patch.object(apps, '_APPS_DIR', directory.name).start()
        patch.object(apps, 'check_app', return_value=None).start()
        self.item = {'type': 'lxc', '_vmid': 101, '_has_app_updater': True,
                     '_helper_slug_source': 'update_wrapper', '_helper_slug': 'qbittorrent'}
        patch.dict(sys.modules, {'lxc_apps': apps, 'managed_installs': types.SimpleNamespace(
            get_active_items=lambda: [self.item])}).start()
        self.api = routes()

    def save(self, records, **extra):
        data = {'vmid': 101, 'apps': copy.deepcopy(records), **extra}
        self.assertTrue(apps._write_sidecar(101, data))
        return apps._read_sidecar(101)

    def helper(self, method='helper', **extra):
        return {'id': 'qbit', 'name': 'qBittorrent', 'helper_slug': 'qbittorrent',
                'update_method': method, **extra}

    def test_registration_does_not_enable_helper_even_in_legacy_wildcard_schedule(self):
        self.save([], schedule={'enabled': True, 'target': 'both'})
        ok, sidecar = apps.add_app(101, {'name': 'qBittorrent', 'helper_slug': 'qbittorrent'})
        self.assertTrue(ok, sidecar)
        self.assertEqual(sidecar['apps'][0]['update_method'], 'none')
        self.assertFalse(self.api['_scheduled_helper_enabled'](101, 'app', ['apps']))

    def test_legacy_commands_and_explicit_selections_survive_migration(self):
        helper = self.helper()
        helper.pop('update_method')
        result = self.save([helper, {'id': 'manual', 'update_command': 'my-updater'}],
                           bulk_update={'targets': ['os', 'app:qbit']})
        self.assertEqual([a['update_method'] for a in result['apps']], ['helper', 'custom'])
        result = self.save([helper], schedule={'enabled': True, 'target': 'both'})
        self.assertEqual(result['apps'][0]['update_method'], 'helper')
        result = self.save([helper], schedule={'enabled': False, 'target': 'both'})
        self.assertEqual(result['apps'][0]['update_method'], 'none')
        self.assertEqual(self.save([helper])['apps'][0]['update_method'], 'none')

    def test_choice_survives_editing_ports_and_disable_never_falls_back(self):
        self.save([self.helper()], schedule={'enabled': True, 'targets': ['apps']})
        record = apps._read_sidecar(101)['apps'][0]
        ok, result = apps.update_app(101, 'qbit', {**record, 'ports': [{'port': 8090}]})
        self.assertTrue(ok, result)
        self.assertEqual(result['apps'][0]['update_method'], 'helper')
        ok, result = apps.update_app(101, 'qbit', {**record, 'update_method': 'custom', 'update_command': 'my-updater'})
        self.assertTrue(ok, result)
        self.assertFalse(self.api['_scheduled_helper_enabled'](101, 'app', ['apps']))
        ok, result = apps.update_app(101, 'qbit', {**record, 'update_method': 'none', 'update_command': ''})
        self.assertTrue(ok, result)
        self.assertFalse(apps.helper_update_selected(101, 'qbittorrent'))
        self.assertTrue(result['schedule']['enabled'])

    def test_conflicting_or_empty_methods_are_rejected(self):
        for payload in ({'update_method': 'custom'}, {'update_method': 'helper'},
                        {'update_method': 'helper', 'helper_slug': 'qbittorrent', 'update_command': 'true'},
                        {'update_method': 'none', 'update_command': 'true'}, {'update_method': 'automatic'}):
            self.assertFalse(apps.validate_config({'name': 'test', **payload})[0], payload)

    def test_multi_app_bulk_keeps_methods_separate(self):
        self.save([self.helper(), {'id': 'other', 'name': 'Other', 'update_method': 'custom',
                                  'update_command': '/opt/other/update.sh'},
                   {'id': 'unconfigured', 'helper_slug': 'jellyfin', 'update_method': 'none'}])
        plan = self.api['_resolve_bulk_update_plan'](101, ['os', 'app:qbit', 'app:other'])
        self.assertTrue(plan['ok'], plan)
        self.assertTrue(plan['run_helper'])
        self.assertTrue(plan['allow_helper_with_custom'])
        self.assertEqual(plan['update_command'], '/opt/other/update.sh')
        plan = self.api['_resolve_bulk_update_plan'](101, ['os', 'app:unconfigured'])
        self.assertFalse(plan['ok'])
        self.assertFalse(apps.helper_update_selected(101, 'qbittorrent', ['app:other']))

    def test_helper_for_one_app_never_authorizes_a_different_helper(self):
        self.save([self.helper(), {'id': 'wrong', 'helper_slug': 'jellyfin', 'update_method': 'helper'}])
        plan = self.api['_resolve_bulk_update_plan'](101, ['os', 'app:qbit', 'app:wrong'])
        self.assertFalse(plan['ok'])
        self.assertEqual(plan['unavailable'][0]['target'], 'app:wrong')

    def test_legacy_download_guard_covers_bulk_and_schedule_without_rewriting_settings(self):
        command = 'PHS_SILENT=1 bash -c "$(wget -qLO - \'https://example.com/odoo.sh2\')"'
        self.save([{'id': 'odoo', 'name': 'Odoo', 'update_method': 'custom', 'update_command': command},
                   {'id': 'other', 'name': 'Other', 'update_method': 'custom', 'update_command': 'echo OTHER'}])
        saved_before = Path(apps._sidecar_path(101)).read_bytes()
        plan = self.api['_resolve_bulk_update_plan'](101, ['os', 'app:odoo', 'app:other'])
        self.assertTrue(plan['ok'])
        self.assertIn('updater download failed', plan['update_command'])
        self.assertTrue(plan['update_command'].endswith(') && echo OTHER'))
        self.api['subprocess'].run.return_value.returncode = 4
        result = self.api['_run_scheduled_update'](101, {'targets': ['app:odoo', 'app:other']})
        self.assertEqual(result['status'], 'failure')
        actual = self.api['subprocess'].run.call_args.kwargs['env']['UPDATE_COMMAND']
        self.assertEqual(actual, plan['update_command'])
        self.assertEqual(self.api['_finalize_lxc_update'].call_args.kwargs['status'], 'failure')
        self.assertEqual(Path(apps._sidecar_path(101)).read_bytes(), saved_before)
        self.assertEqual(apps._read_sidecar(101)['apps'][0]['update_command'], command)

    def test_detection_and_duplicate_conflicts_do_not_authorize_execution(self):
        self.save([self.helper('none')])
        self.assertFalse(apps.helper_update_selected(101, 'qbittorrent'))
        self.save([self.helper(), {**self.helper('custom'), 'id': 'duplicate', 'update_command': 'my-update'}])
        self.assertFalse(apps.helper_update_selected(101, 'qbittorrent'))
        self.save([self.helper()])
        self.item['_helper_slug_source'] = 'tag_hostname'
        self.assertFalse(self.api['_scheduled_helper_enabled'](101, 'app', ['apps']))

    def test_disabled_app_schedule_reports_skipped_without_running(self):
        self.save([self.helper('none')])
        result = self.api['_run_scheduled_update'](101, {'targets': ['app:qbit']})
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(result['executed_targets'], [])
        self.api['subprocess'].run.assert_not_called()

    def test_disabled_app_does_not_block_os_or_custom_app_and_reports_partial(self):
        self.save([self.helper('none'), {'id': 'other', 'update_command': 'my-updater'}])
        result = self.api['_run_scheduled_update'](101, {'targets': ['os', 'app:qbit', 'app:other']})
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['executed_targets'], ['os', 'app:other'])
        env = self.api['subprocess'].run.call_args.kwargs['env']
        self.assertEqual(env['RUN_HELPER'], '0')
        self.assertEqual(env['UPDATE_COMMAND'], 'my-updater')

    def test_wildcard_only_runs_selected_methods(self):
        self.save([self.helper(), {'id': 'other', 'update_command': 'my-updater'},
                   {'id': 'links', 'name': 'Links only', 'update_method': 'none'}])
        result = self.api['_run_scheduled_update'](101, {'targets': ['apps']})
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['executed_targets'], ['app:qbit', 'app:other'])
        env = self.api['subprocess'].run.call_args.kwargs['env']
        self.assertEqual(env['RUN_HELPER'], '1')
        self.assertEqual(env['UPDATE_COMMAND'], 'my-updater')


if __name__ == '__main__':
    unittest.main()
