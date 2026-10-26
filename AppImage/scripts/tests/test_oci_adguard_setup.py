import sys
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import lxc_apps


class AdguardSetupTests(unittest.TestCase):
    def test_non_adguard_is_not_probed(self):
        with patch.object(lxc_apps, '_oci_instance_meta', return_value={'template_id': 'image-frigate'}), \
             patch.object(lxc_apps.subprocess, 'run') as run:
            self.assertFalse(lxc_apps.oci_adguard_setup_available(190))
            run.assert_not_called()

    def test_setup_returns_true_only_for_http_response(self):
        process = MagicMock(stdout='192.168.0.42\n')
        connection = MagicMock()
        connection.__enter__.return_value.recv.return_value = b'HTTP/1.1 302 Found\r\n'
        with patch.object(lxc_apps, '_oci_instance_meta', return_value={'template_id': 'image-adguard-home'}), \
             patch.object(lxc_apps.subprocess, 'run', return_value=process), \
             patch.object(lxc_apps.socket, 'create_connection', return_value=connection) as connect:
            self.assertTrue(lxc_apps.oci_adguard_setup_available(190))
            connect.assert_called_once_with(('192.168.0.42', 3000), timeout=1)

    def test_closed_setup_port_is_not_offered(self):
        process = MagicMock(stdout='192.168.0.42\n')
        with patch.object(lxc_apps, '_oci_instance_meta', return_value={'template_id': 'image-adguard-home'}), \
             patch.object(lxc_apps.subprocess, 'run', return_value=process), \
             patch.object(lxc_apps.socket, 'create_connection', side_effect=OSError):
            self.assertFalse(lxc_apps.oci_adguard_setup_available(190))


if __name__ == '__main__':
    unittest.main()
