"""Opening Manage shows the sync notice only while some configuration is still unread."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'remote'))

from proxmenux_oci import management
import oci_carried_record as carried


class ManageSyncNoticeTests(unittest.TestCase):
    def test_notice_only_while_an_installed_application_has_no_cache(self):
        rows = [{'vmid': 101, 'status': 'installed', 'pending': False},
                {'vmid': 102, 'status': 'installed', 'pending': True},
                {'vmid': 103, 'status': 'failed', 'pending': False}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(carried.instances, 'ROOT', root), \
                    patch.object(management, 'saved_inventory', return_value=rows):
                self.assertTrue(management._records_unread(ROOT))
                cache = carried.instances.location(root, 101).parent / carried.CONFIG_CACHE
                cache.parent.mkdir(parents=True)
                cache.write_text('{}')
                # The pending and failed applications are never cached by the sync.
                self.assertFalse(management._records_unread(ROOT))


if __name__ == '__main__':
    unittest.main()
