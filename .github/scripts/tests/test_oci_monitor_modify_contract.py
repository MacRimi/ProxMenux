"""Keep the Monitor OCI editor path distinct from coordinated stack recreation."""
import ast
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[3]
MENU = ROOT / 'oci/src/proxmenux_oci/management.py'
CLI = ROOT / 'oci/src/proxmenux_oci/cli.py'
MONITOR = ROOT / 'AppImage/components/virtual-machines.tsx'
WRAPPER = ROOT / 'scripts/oci/manage_instance.sh'
EXTRA_DEVICES = ROOT / 'oci/src/proxmenux_oci/extra_devices.py'
STACK_RECREATION = ROOT / 'oci/src/proxmenux_oci/stack_recreation.py'


def extracted_stack_manager(scope):
    source = MENU.read_text(encoding='utf-8').replace(
        '            from .stack_recreation import modify_stack\n', '')
    node = next(item for item in ast.parse(source).body
                if isinstance(item, ast.FunctionDef) and item.name == '_manage_stack')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 str(MENU), 'exec'), scope)
    return scope['_manage_stack']


class MonitorModifyContractTests(TestCase):
    def test_monitor_sends_modify_for_a_stack_and_recreate_for_a_single_instance(self):
        source = MONITOR.read_text(encoding='utf-8')
        self.assertIn('action: "update" | "modify" | "recreate" | "recover"', source)
        self.assertIn('action: ociInstance.stack ? "modify" : "recreate"', source)

    def test_cli_and_monitor_wrapper_accept_the_modify_action(self):
        self.assertIn('choices=("update", "modify", "recreate")', CLI.read_text(encoding='utf-8'))
        self.assertIn('${ACTION:-} != "modify"', WRAPPER.read_text(encoding='utf-8'))

    def test_modify_device_filter_matches_the_device_prompt_contract(self):
        caller = STACK_RECREATION.read_text(encoding='utf-8')
        device_prompt = EXTRA_DEVICES.read_text(encoding='utf-8')
        prompt = next(node for node in ast.parse(device_prompt).body
                      if isinstance(node, ast.FunctionDef) and node.name == 'ask_extra_devices')
        self.assertIn('kinds', [argument.arg for argument in prompt.args.args])
        self.assertIn("ask_extra_devices(ui, attached, True, kinds=", caller)

    def test_modify_action_opens_the_stack_editor_without_running_lifecycle(self):
        primary = {'stack': {'members': [{'vmid': 101}]}}
        instances = ModuleType('oci_instances')
        instances.ROOT = Path('/inert')
        instances.read = lambda *_: primary
        modify_stack = Mock(return_value=True)
        run_lifecycle = Mock()
        manager = extracted_stack_manager({
            'sys': SimpleNamespace(path=[]),
            'Path': Path,
            'modify_stack': modify_stack,
            '_run_lifecycle': run_lifecycle,
        })
        ui = SimpleNamespace()
        with patch.dict(sys.modules, {
                'oci_instances': instances,
                'oci_stack_replay': ModuleType('oci_stack_replay'),
        }):
            result = manager(Path('/inert'), ui, {'vmid': 101}, action='modify')

        self.assertTrue(result)
        modify_stack.assert_called_once_with(Path('/inert'), ui, primary, run_lifecycle)
        run_lifecycle.assert_not_called()


if __name__ == '__main__':
    import unittest
    unittest.main()
