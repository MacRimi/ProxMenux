"""Non-consecutive stack IDs are optional and validated before host changes."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'remote'), str(ROOT / 'tests')]

import oci_stack_vmids as allocator
from proxmenux_oci import stack_vmids
from proxmenux_oci.catalog import Catalog
from proxmenux_oci.installer import build_deployment, DEFAULT_MODE, ADVANCED_MODE
from proxmenux_oci.cli import _deployment_summary_text
from proxmenux_oci.ui import UserCancelled
from test_advanced_flow_order import RecordingUI, addresses, storages

SERVICES = [{'name': 'web', 'offset': 0}, {'name': 'db', 'offset': 2}, {'name': 'cache', 'offset': 1}]
SELECTION = {'web': 9100, 'db': 9120, 'cache': 9110}


class AllocationTests(unittest.TestCase):
    def test_explicit_ids_need_neither_a_free_block_nor_nextid(self):
        next_id = Mock(side_effect=AssertionError('must not query nextid'))
        result = allocator.resolve({'base_vmid': 110, 'service_vmids': SELECTION}, SERVICES,
                                   {110, 9101, 9102}, next_id)
        self.assertEqual(result, SELECTION)

    def test_default_allocation_skips_occupied_blocks(self):
        self.assertEqual(allocator.resolve({}, SERVICES, {101, 103, 105}, lambda: 100),
                         {'web': 106, 'db': 108, 'cache': 107})

    def test_explicit_base_keeps_legacy_failure_and_offsets(self):
        self.assertEqual(allocator.resolve({'base_vmid': 210}, SERVICES, set(), lambda: 100),
                         {'web': 210, 'db': 212, 'cache': 211})
        with self.assertRaisesRegex(ValueError, 'already in use'):
            allocator.resolve({'base_vmid': 210}, SERVICES, {212}, lambda: 100)

    def test_duplicate_missing_unknown_and_empty_choices_fail(self):
        for choice in ({'web': 9100, 'db': 9100, 'cache': 9110}, {}, None,
                       {'web': 9100, 'db': 9120}, dict(SELECTION, other=9130)):
            with self.subTest(choice=choice), self.assertRaises(ValueError):
                allocator.resolve({'service_vmids': choice}, SERVICES, set(), lambda: 100)

    def test_invalid_values_and_range_overflow_fail(self):
        for value in (True, 99, 0, -100, 1000000000, 210.5, '210.0', '210\n', '1e3', ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                allocator.resolve({'service_vmids': dict(SELECTION, web=value)}, SERVICES, set(), lambda: 100)
        with self.assertRaises(ValueError):
            allocator.resolve({'base_vmid': 999999999}, SERVICES, set(), lambda: 100)

    def test_occupied_selection_reports_exact_conflicts(self):
        with self.assertRaisesRegex(ValueError, '9110, 9120'):
            allocator.resolve({'service_vmids': SELECTION}, SERVICES, {9110, 9120}, lambda: 100)

    @patch.object(allocator.subprocess, 'run')
    def test_cluster_inventory_includes_other_nodes_and_virtual_machines(self, run):
        run.return_value.stdout = json.dumps([{'vmid': 9120, 'node': 'other', 'type': 'qemu'}])
        with self.assertRaisesRegex(ValueError, '9120'):
            allocator.allocate({'service_vmids': SELECTION}, SERVICES)
        self.assertIn('/cluster/resources', run.call_args.args[0])
        self.assertEqual(run.call_count, 1)

    @patch.object(allocator.subprocess, 'run')
    def test_failed_or_malformed_inventory_does_not_become_an_empty_cluster(self, run):
        for output in ('invalid', '{}', '[{}]'):
            run.return_value.stdout = output
            with self.subTest(output=output), self.assertRaises(ValueError):
                allocator.allocate({'service_vmids': SELECTION}, SERVICES)
        run.side_effect = subprocess.TimeoutExpired('pvesh', 30)
        with self.assertRaises(subprocess.TimeoutExpired):
            allocator.allocate({'service_vmids': SELECTION}, SERVICES)


class WizardTests(unittest.TestCase):
    def plan(self):
        return {'deployment_kind': 'generic-multi-lxc-stack', 'base_vmid': 210,
                'services': copy.deepcopy(SERVICES)}

    def test_declining_preserves_the_original_plan_without_host_queries(self):
        plan = self.plan()
        ui = Mock()
        ui.confirm.return_value = False
        with patch.object(allocator, 'allocate') as allocate:
            stack_vmids.configure(ui, {}, plan)
        self.assertNotIn('service_vmids', plan)
        allocate.assert_not_called()
        ui.ask.assert_not_called()

    def test_proposes_consecutive_ids_in_offset_order(self):
        ui = Mock()
        ui.ask.side_effect = ['9100', '9110', '9120']
        plan = self.plan()
        with patch.object(allocator, 'allocate', return_value={'web': 210, 'cache': 211, 'db': 212}):
            stack_vmids.configure(ui, {}, plan)
        self.assertEqual(plan['service_vmids'], SELECTION)
        self.assertEqual([c.args[1] for c in ui.ask.call_args_list], ['210', '211', '212'])
        self.assertEqual([s['offset'] for s in plan['services']], [0, 2, 1])

    def test_duplicate_answers_can_be_corrected(self):
        ui = Mock()
        ui.ask.side_effect = ['9100', '9100', '9120', '9100', '9110', '9120']
        plan = self.plan()
        with patch.object(allocator, 'allocate', return_value=SELECTION):
            stack_vmids.configure(ui, {}, plan)
        self.assertEqual(plan['service_vmids'], SELECTION)
        ui.message.assert_called_once()

    def test_cancel_does_not_save_a_partial_selection(self):
        ui = Mock()
        ui.ask.side_effect = ['9100', None]
        plan = self.plan()
        with patch.object(allocator, 'allocate', return_value=SELECTION), self.assertRaises(UserCancelled):
            stack_vmids.configure(ui, {}, plan)
        self.assertNotIn('service_vmids', plan)


@patch('proxmenux_oci.host.gpus', return_value={'intel': [], 'amd': [], 'nvidia': False})
@patch('proxmenux_oci.i18n.language', return_value='en')
@patch('proxmenux_oci.host.storages', side_effect=storages)
@patch('proxmenux_oci.host.bridges', return_value=[{'iface': 'vmbr0', 'cidr': '192.0.2.10/24'}])
@patch('proxmenux_oci.host.timezone', return_value='UTC')
@patch('proxmenux_oci.network.ask_addresses', side_effect=addresses)
class AllInstallerTests(unittest.TestCase):
    apps = ('immich', 'nextcloud-stack', 'paperless-ngx', 'tandoor', 'linkwarden', 'suite-arr')

    def test_all_six_advanced_installers_offer_selection_and_show_exact_ids(self, *_):
        for app in self.apps:
            with self.subTest(app=app):
                template = Catalog(ROOT).compose(app)
                ui = RecordingUI()
                original_confirm = ui.confirm
                ui.confirm = lambda text, default=False: (True if text == 'Choose a VMID for each service?'
                                                         else original_confirm(text, default))
                original_ask = ui.ask
                chosen = {}

                def ask(text, default=None, required=True, **kwargs):
                    if text.startswith('VMID for service:'):
                        name = text.partition(': ')[2]
                        chosen[name] = 9100 + len(chosen) * 10
                        return str(chosen[name])
                    return original_ask(text, default, required, **kwargs)

                ui.ask = ask
                with patch.object(allocator, 'allocate', side_effect=OSError('not on PVE')):
                    plan = build_deployment(template, ui, ADVANCED_MODE)
                self.assertEqual(plan['service_vmids'], chosen)
                self.assertGreaterEqual(len(chosen), 2)
                summary = _deployment_summary_text(template, plan)
                for name, value in chosen.items():
                    self.assertIn(f'{name}: CT {value}', summary)

    def test_default_installers_add_no_questions_or_explicit_selection(self, *_):
        with patch.object(allocator, 'allocate') as allocate:
            for app in self.apps:
                ui = RecordingUI()
                plan = build_deployment(Catalog(ROOT).compose(app), ui, DEFAULT_MODE)
                self.assertNotIn('service_vmids', plan)
                self.assertNotIn('Choose a VMID for each service?', ui.asked)
        allocate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
