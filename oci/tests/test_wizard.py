"""Shared wizard navigation and device choices do not depend on app overlays."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from subprocess import CompletedProcess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from proxmenux_oci.extra_devices import (ask_extra_devices, ask_stack_extra_devices,
                                         device_permissions)
from proxmenux_oci.ui import BackRequested, BacktrackUI, DialogUI, RestartWizard


class SequenceUI:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.back_enabled = False

    def ask(self, *_args, **_kwargs):
        result = next(self.answers)
        if result == 'back':
            raise BackRequested()
        return result

    def confirm(self, *_args, **_kwargs):
        return next(self.answers)

    def choose(self, *_args, **_kwargs):
        return next(self.answers)

    def checklist(self, *_args, **_kwargs):
        return next(self.answers)

    def info(self, _text):
        pass


class WizardTests(unittest.TestCase):
    def test_back_returns_to_previous_answer_without_reasking_first(self):
        base = SequenceUI(['first', 'second', 'back', 'corrected', 'third'])
        wizard = BacktrackUI(base)
        try:
            self.assertEqual(wizard.ask('first'), 'first')
            self.assertEqual(wizard.ask('second'), 'second')
            with self.assertRaises(RestartWizard):
                wizard.ask('third')
            wizard.restart()
            self.assertEqual(wizard.ask('first'), 'first')
            self.assertEqual(wizard.ask('second'), 'corrected')
            self.assertEqual(wizard.ask('third'), 'third')
        finally:
            wizard.close()
        self.assertFalse(base.back_enabled)

    def test_back_from_review_reopens_last_question(self):
        class ReviewUI(SequenceUI):
            def review(self, *_args, **_kwargs):
                raise BackRequested()

        wizard = BacktrackUI(ReviewUI(['value', 'replacement']))
        try:
            self.assertEqual(wizard.ask('value'), 'value')
            with self.assertRaises(RestartWizard):
                wizard.review('summary')
            wizard.restart()
            self.assertEqual(wizard.ask('value'), 'replacement')
        finally:
            wizard.close()

    def test_manual_usb_is_available_without_profile(self):
        ui = SequenceUI([True, 'usb', '/dev/ttyACM0', False])
        devices = ask_extra_devices(ui, [], True)
        self.assertEqual(devices[0]['host_path'], '/dev/ttyACM0')
        self.assertEqual(devices[0]['container_path'], '/dev/ttyACM0')

    def test_linuxserver_device_permissions_are_generic(self):
        permissions = device_permissions('lscr.io/linuxserver/chromium:latest',
                                         [{'kind': 'character-device'}])
        self.assertEqual(permissions['strategy'], 'linuxserver-native-init')

    def test_stack_device_goes_only_to_selected_member(self):
        ui = SequenceUI([True, 'usb', '/dev/ttyACM0', False, ['server']])
        services = [
            {'name': name, 'main': name == 'server',
             'template': {'container_contract': {'image': {'reference': 'example/app:latest'}}},
             'deployment': {'devices': [], 'security': {'unprivileged': True}}}
            for name in ('database', 'server')
        ]
        ask_stack_extra_devices(ui, services)
        self.assertEqual(services[0]['deployment']['devices'], [])
        self.assertEqual(services[1]['deployment']['devices'][0]['host_path'], '/dev/ttyACM0')

    def test_dialog_back_button_is_only_on_wizard_inputs(self):
        ui = DialogUI(back_enabled=True)
        with patch('proxmenux_oci.ui.subprocess.run', return_value=CompletedProcess([], 3, '', '')) as run:
            with self.assertRaises(BackRequested):
                ui._run(['--inputbox', 'Name', '10', '50', ''])
        self.assertIn('--extra-button', run.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
