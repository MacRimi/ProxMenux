"""Selective OCI edits stay in a draft until reviewed, then use one transaction."""
import copy
import json
from pathlib import Path
import stat
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'remote'))

from proxmenux_oci import management, recreation
from proxmenux_oci.ui import BackRequested, UserCancelled


def record():
    return {'vmid': 115, 'installation_id': 'test-installation', 'status': 'installed',
            'observed': {'config_sha256': 'native-config-fingerprint'},
            'template': {'id': 'example-app', 'catalog_ui': {'title': 'Example'},
                         'container_contract': {'image': {'reference': 'example/app:latest'}},
                         'proxmox': {'installer_profile': {}}},
            'deployment': {'vmid': 115, 'hostname': 'example', 'resources': {'cores': 2, 'memory_mb': 512},
                           'network': {'bridge': 'vmbr0', 'ipv4': 'dhcp', 'gateway': None},
                           'rootfs': {'storage': 'local-zfs', 'size_gb': 8}, 'mounts': [
                               {'container_path': '/data', 'source': 'local-zfs',
                                'type': 'managed-volume', 'size_gb': 8, 'backup': True}],
                           'devices': [], 'security': {'unprivileged': True},
                           'environment': [{'name': 'PASSWORD', 'value': 'private-test-secret',
                                            'sensitive': True}]}}


class MenuUI:
    def __init__(self, choices, answers=(), reviews=(True,), confirms=()):
        self.choices, self.answers = iter(choices), iter(answers)
        self.reviews, self.confirms = iter(reviews), iter(confirms)
        self.events = []
        self.back_enabled = False

    def choose(self, text, options, default=None, **kwargs):
        self.events.append(('menu', text, dict(options)))
        value = next(self.choices)
        if value is not None:
            assert value in dict(options), value
        return value

    def ask(self, text, default=None, **kwargs):
        self.events.append(('ask', text, default))
        value = next(self.answers)
        if isinstance(value, Exception):
            raise value
        return value

    def confirm(self, text, default=False):
        self.events.append(('confirm', text))
        return next(self.confirms)

    def review(self, text, *args, **kwargs):
        self.events.append(('review', text))
        return next(self.reviews)

    def message(self, text, *args):
        self.events.append(('message', text))


@patch('proxmenux_oci.i18n.language', return_value='en')
class ModifyMenuTests(unittest.TestCase):
    def test_ram_only_does_not_ask_about_cpu_network_paths_devices_or_catalog(self, _language):
        original = record()
        saved = copy.deepcopy(original)
        ui = MenuUI(['memory', 'apply'], ['768'])
        with patch.object(recreation, 'refresh_template') as refresh:
            result = recreation.edit_recreation(original, ui)
        self.assertEqual(result['candidate']['deployment']['resources'], {'cores': 2, 'memory_mb': 768})
        self.assertEqual([e[1] for e in ui.events if e[0] == 'ask'], ['RAM in MiB'])
        self.assertEqual(result['base_config_sha256'], 'native-config-fingerprint')
        self.assertEqual(original, saved)
        refresh.assert_not_called()
        self.assertFalse(ui.back_enabled)

    def test_several_sections_and_revisits_keep_the_current_draft(self, _language):
        ui = MenuUI(['memory', 'cores', 'memory', 'apply'], ['768', '3', '1024'])
        result = recreation.edit_recreation(record(), ui)
        self.assertEqual(result['candidate']['deployment']['resources'], {'cores': 3, 'memory_mb': 1024})
        self.assertEqual([e[2] for e in ui.events if e[0] == 'ask'], ['512', '2', '768'])
        self.assertEqual(sum(e[0] == 'review' for e in ui.events), 1)

    def test_declining_review_returns_to_menu_without_losing_edits(self, _language):
        ui = MenuUI(['cores', 'apply', 'memory', 'apply'], ['3', '768'], reviews=[False, True])
        result = recreation.edit_recreation(record(), ui)
        self.assertEqual(result['candidate']['deployment']['resources'], {'cores': 3, 'memory_mb': 768})
        self.assertEqual(sum(e[0] == 'review' for e in ui.events), 2)

    def test_unchanged_apply_does_not_propose_recreating_the_guest(self, _language):
        ui = MenuUI(['memory', 'apply'], ['512'])
        self.assertIsNone(recreation.edit_recreation(record(), ui))
        self.assertFalse(any(e[0] == 'review' for e in ui.events))
        self.assertIn(('message', 'Nothing was changed.'), ui.events)

    def test_discard_leaves_the_saved_record_untouched(self, _language):
        original = record()
        saved = copy.deepcopy(original)
        ui = MenuUI(['memory', 'discard'], ['768'], confirms=[True])
        self.assertIsNone(recreation.edit_recreation(original, ui))
        self.assertEqual(original, saved)
        self.assertFalse(any(e[0] == 'review' for e in ui.events))

    def test_declining_discard_preserves_the_draft(self, _language):
        ui = MenuUI(['memory', None, 'apply'], ['768'], confirms=[False])
        result = recreation.edit_recreation(record(), ui)
        self.assertEqual(result['candidate']['deployment']['resources']['memory_mb'], 768)

    def test_cancel_without_changes_asks_nothing_else(self, _language):
        ui = MenuUI([None])
        self.assertIsNone(recreation.edit_recreation(record(), ui))
        self.assertEqual(len(ui.events), 1)

    def test_invalid_ram_is_retried_without_restarting_other_sections(self, _language):
        ui = MenuUI(['cores', 'memory', 'apply'], ['3', 'invalid', '64', '768'])
        result = recreation.edit_recreation(record(), ui)
        self.assertEqual(result['candidate']['deployment']['resources'], {'cores': 3, 'memory_mb': 768})
        self.assertEqual(sum(e[0] == 'message' for e in ui.events), 2)
        self.assertEqual(sum(e[:2] == ('ask', 'Cores') for e in ui.events), 1)

    def test_back_from_first_field_returns_to_menu_and_keeps_other_edits(self, _language):
        ui = MenuUI(['cores', 'memory', 'apply'], ['3', BackRequested()])
        result = recreation.edit_recreation(record(), ui)
        self.assertEqual(result['candidate']['deployment']['resources'], {'cores': 3, 'memory_mb': 512})
        self.assertFalse(ui.back_enabled)

    def test_cancelling_a_partly_edited_section_rolls_back_only_that_section(self, _language):
        real_edit = recreation.edit_setting
        def edit(candidate, ui, setting):
            if setting == 'environment':
                candidate['deployment']['environment'][0]['value'] = 'partial-value'
                raise UserCancelled()
            real_edit(candidate, ui, setting)
        ui = MenuUI(['cores', 'environment', 'apply'], ['3'])
        with patch.object(recreation, 'edit_setting', side_effect=edit):
            result = recreation.edit_recreation(record(), ui)
        self.assertEqual(result['candidate']['deployment']['resources']['cores'], 3)
        self.assertEqual(result['candidate']['deployment']['environment'], record()['deployment']['environment'])

    def test_menu_and_review_do_not_expose_a_saved_secret(self, _language):
        ui = MenuUI(['cores', 'apply'], ['3'])
        recreation.edit_recreation(record(), ui)
        self.assertNotIn('private-test-secret', json.dumps(ui.events))

    def test_optional_categories_follow_the_application_profile(self, _language):
        candidate = record()
        options = dict(recreation.modification_options(candidate))
        self.assertTrue({'cores', 'memory', 'network', 'paths', 'devices', 'environment', 'catalog', 'apply'} <= options.keys())
        self.assertFalse({'shares', 'acceleration', 'detector'} & options.keys())
        candidate['template']['proxmox']['installer_profile'] = {
            'shared_directories': {'base_path': '/shares'}, 'object_detector': {'devices': []},
            'hardware_acceleration': {'profiles': [{'id': 'intel', 'label': 'Intel GPU'}]}}
        candidate['deployment']['hardware_profile'] = 'intel'
        options = dict(recreation.modification_options(candidate))
        self.assertTrue({'shares', 'acceleration', 'detector'} <= options.keys())
        self.assertIn('Intel GPU', options['acceleration'])


class ModifyDispatchTests(unittest.TestCase):
    def call_manager(self, proposal, lifecycle):
        import oci_instances
        import oci_instance_reconcile
        saved = record()
        row = {'vmid': 115, 'reason': 'matched', 'stack': False, 'pending': False, 'status': 'installed'}
        with patch.object(management, 'carry_records', return_value={}), \
                patch.object(management, 'check_selected', return_value=row), \
                patch.object(management, '_work_backup_ready', return_value=True), \
                patch.object(oci_instances, 'read', return_value=saved), \
                patch.object(oci_instances, 'command', return_value='hostname: example'), \
                patch.object(oci_instance_reconcile, 'propose', return_value=None), \
                patch.object(recreation, 'edit_recreation', return_value=proposal), \
                patch.object(management, '_run_lifecycle', side_effect=lifecycle):
            return management.manage_instance(ROOT, Mock(), row, action='modify')

    def test_cancel_does_not_start_a_lifecycle_transaction(self):
        lifecycle = Mock()
        self.assertFalse(self.call_manager(None, lifecycle))
        lifecycle.assert_not_called()

    def test_apply_sends_one_private_proposal_to_the_existing_backend(self):
        proposal = {'operation': 'recreate', 'candidate': record(), 'base_config_sha256': 'fingerprint'}
        seen = []
        def lifecycle(command, title):
            path = Path(command[command.index('--proposal') + 1])
            seen.append(json.loads(path.read_text()))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertNotIn('private-test-secret', ' '.join(command))
            self.assertIn('oci_update_current.py', command[1])
            self.assertIn('--acknowledge-external-data', command)
            return True
        self.assertTrue(self.call_manager(proposal, lifecycle))
        self.assertEqual(seen, [proposal])


if __name__ == '__main__':
    unittest.main()
