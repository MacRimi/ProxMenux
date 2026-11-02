import sys
import unittest
from pathlib import Path
from queue import Queue
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import notification_events  # noqa: E402


class DiskIoObservationDevice(unittest.TestCase):
    """A kernel I/O error is recorded on its disk, by name alone."""

    def setUp(self):
        self.watcher = notification_events.JournalWatcher(Queue())

    def recorded(self, message):
        with patch.object(self.watcher, '_record_disk_io_observation') as record, \
             patch.object(self.watcher, '_quick_smart_health', return_value='PASSED'):
            self.watcher._check_disk_io(message, 'kernel', 3)
        return [call.args[0] for call in record.call_args_list]

    def test_the_comma_after_the_device_is_not_part_of_its_name(self):
        self.assertEqual(self.recorded('Buffer I/O error on dev sdf1, logical block 0, async page read'), ['sdf'])
        self.assertEqual(self.recorded('blk_update_request: I/O error, dev sdc, sector 2048 op 0x0:(READ)'), ['sdc'])

    def test_the_older_wording_is_still_read(self):
        self.assertEqual(self.recorded('Buffer I/O error on device sdb2, logical block 8'), ['sdb'])


if __name__ == '__main__':
    unittest.main()
