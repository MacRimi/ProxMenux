"""A container that HA manages is refused before its new image is downloaded."""
import contextlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'remote'))
import oci_instance_transaction as transaction
import oci_update_current as update


def ha_resources(*vmids):
    answer = json.dumps([{'sid': f'ct:{vmid}', 'state': 'started'} for vmid in vmids]).encode()
    return patch.object(transaction, 'run', return_value=answer)


class HighAvailabilityTests(unittest.TestCase):
    def test_the_refusal_names_the_resource_and_how_to_proceed(self):
        with ha_resources(101), self.assertRaises(ValueError) as refused:
            transaction.refuse_high_availability(101)
        self.assertIn('ha-manager remove ct:101', str(refused.exception))

    def test_a_container_outside_ha_is_not_refused(self):
        with ha_resources(200):
            transaction.refuse_high_availability(101)

    def test_a_host_without_pvesh_has_no_ha_to_refuse(self):
        with patch.object(transaction, 'run', side_effect=FileNotFoundError('pvesh')):
            transaction.refuse_high_availability(101)

    def test_the_preflight_of_a_replacement_refuses_it(self):
        record = {'vmid': 101, 'installation_id': 'install-1', 'deployment': {}}
        with patch.object(transaction.instances, 'identity', return_value='install-1'), ha_resources(101), \
                self.assertRaises(ValueError) as refused:
            transaction.preflight(record, {'deployment': {}}, b'')
        self.assertIn('ct:101', str(refused.exception))

    def test_an_in_place_edit_and_a_stack_member_are_not_refused_here(self):
        record = {'vmid': 101, 'installation_id': 'install-1', 'deployment': {}}
        refuse = Mock()
        with patch.object(transaction.instances, 'identity', return_value='install-1'), \
                patch.object(transaction, 'refuse_high_availability', refuse), \
                patch.object(transaction, 'external_changes', side_effect=RuntimeError('past the check')):
            for options in ({'in_place': True}, {'coordinated': {'id': 'stack'}}):
                with self.subTest(options=options), self.assertRaises(RuntimeError):
                    transaction.preflight(record, {'deployment': {}}, b'', **options)
        refuse.assert_not_called()

    def test_an_update_stops_before_downloading_the_image(self):
        record = {'status': 'installed', 'observed': {'image': {}}}
        resolve = Mock()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(update.instances, 'locked', return_value=contextlib.nullcontext()))
            stack.enter_context(patch.object(update.instances, 'read', return_value=record))
            stack.enter_context(patch.object(update.instances, 'command', return_value=b''))
            stack.enter_context(patch.object(update.transaction, 'candidate_contract', return_value={}))
            stack.enter_context(patch.object(update.transaction, 'external_changes', return_value={}))
            stack.enter_context(patch.object(update.transaction, 'preflight',
                                             side_effect=ValueError('managed by high availability')))
            stack.enter_context(patch.object(update, 'resolve_archive', resolve))
            stack.enter_context(patch.object(update, 'msg_info'))
            stack.enter_context(patch.object(update, 'msg_ok'))
            with self.assertRaises(ValueError):
                update.update(101)
        resolve.assert_not_called()


if __name__ == '__main__':
    unittest.main()
