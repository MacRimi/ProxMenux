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

    def test_an_update_stops_before_downloading_the_image(self):
        record = {'status': 'installed', 'observed': {'image': {}}}
        resolve = Mock()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(update.instances, 'locked', return_value=contextlib.nullcontext()))
            stack.enter_context(patch.object(update.instances, 'read', return_value=record))
            stack.enter_context(patch.object(update.instances, 'command', return_value=b''))
            stack.enter_context(patch.object(update.transaction, 'candidate_contract', return_value={}))
            stack.enter_context(patch.object(update.transaction, 'external_changes', return_value={}))
            stack.enter_context(patch.object(update.transaction, 'preflight'))
            stack.enter_context(patch.object(update, 'resolve_archive', resolve))
            stack.enter_context(patch.object(update, 'msg_info'))
            stack.enter_context(patch.object(update, 'msg_ok'))
            stack.enter_context(ha_resources(101))
            with self.assertRaises(ValueError):
                update.update(101)
        resolve.assert_not_called()


if __name__ == '__main__':
    unittest.main()
