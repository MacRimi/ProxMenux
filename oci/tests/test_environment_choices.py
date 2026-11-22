"""A recipe can select an image argument without adding a dedicated wizard."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from proxmenux_oci.custom import template_from_oci_compose
from proxmenux_oci.converter import ConversionError
from proxmenux_oci.installer import choose_environment_value, InstallError
from proxmenux_oci.ui import UserCancelled
import json


def variable():
    return {'name': 'VERSION', 'example': '11', 'required': True, 'sensitive': False,
            'prompt': 'Windows version',
            'choices': [{'value': '11', 'label': 'Windows 11 Pro'},
                        {'value': '2025', 'label': 'Windows Server 2025'}]}


class EnvironmentChoicesTests(unittest.TestCase):
    def test_selected_value_is_saved_not_the_label(self):
        ui = Mock()
        ui.choose.return_value = '2025'
        with patch('proxmenux_oci.installer.translate', side_effect=lambda text: 'translated ' + text):
            self.assertEqual(choose_environment_value(variable(), ui, '11'), '2025')
        ui.choose.assert_called_once_with('translated Windows version', [
            ('11', 'translated Windows 11 Pro'), ('2025', 'translated Windows Server 2025')], '11')

    def test_invalid_selection_is_not_accepted(self):
        for result in ('shell text', '', 'Windows 11 Pro'):
            with self.subTest(result=result), self.assertRaises(InstallError):
                choose_environment_value(variable(), Mock(choose=Mock(return_value=result)), '11')

    def test_cancel_stays_cancel(self):
        with self.assertRaises(UserCancelled):
            choose_environment_value(variable(), Mock(choose=Mock(return_value=None)), '11')
        with self.assertRaises(UserCancelled):
            choose_environment_value(variable(), Mock(choose=Mock(side_effect=UserCancelled())), '11')

    def test_invalid_default_and_duplicate_values_are_rejected(self):
        with self.assertRaises(InstallError):
            choose_environment_value(variable(), Mock(), '12')
        item = variable()
        item['choices'][1]['value'] = '11'
        with self.assertRaises(InstallError):
            choose_environment_value(item, Mock(), '11')

    def test_choices_round_trip_through_the_real_loader(self):
        document = {'kind': 'proxmenux.oci-template', 'container_contract': {
            'image': {'reference': 'dockurr/windows:latest'}, 'environment': [variable()]}}
        loaded = template_from_oci_compose(json.dumps(document))
        self.assertEqual(loaded['container_contract']['environment'][0]['choices'], variable()['choices'])
        for setting in ({'sensitive': True}, {'prompt_user': False},
                        {'container_address': '@CONTAINER_ADDRESS@'}):
            invalid = copy.deepcopy(document)
            invalid['container_contract']['environment'][0].update(setting)
            with self.subTest(setting=setting), self.assertRaises(ConversionError):
                template_from_oci_compose(json.dumps(invalid))


if __name__ == '__main__':
    unittest.main()
