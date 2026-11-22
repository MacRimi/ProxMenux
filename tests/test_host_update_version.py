"""Actual installed-version function; package changes invalidate its old display."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


class VersionCache(unittest.TestCase):
    def setUp(self):
        source = ast.parse((ROOT/'AppImage/scripts/flask_server.py').read_text())
        node = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'get_proxmox_version')
        self.cache = dict(proxmox_version='9.2.21', proxmox_version_time=100, proxmox_version_stamp=1)
        self.command = Mock(return_value=SimpleNamespace(returncode=0, stdout='pve-manager/9.2.24/hash\n'))
        self.stamp = Mock(return_value=1)
        self.scope = dict(is_pbs_host=Mock(return_value=False), get_platform=Mock(return_value={'version':'4.1.0'}),
                          _system_info_cache=self.cache, _SYSTEM_INFO_CACHE_TTL=21600,
                          _AVAILABLE_UPDATES_MIN_INTERVAL=30, _apt_state_stamp=self.stamp,
                          time=SimpleNamespace(time=Mock(return_value=200)), subprocess=SimpleNamespace(run=self.command))
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'actual-installed-version', 'exec'), self.scope)

    def test_unchanged_package_state_has_zero_commands(self):
        self.assertEqual(self.scope['get_proxmox_version'](), '9.2.21')
        self.command.assert_not_called()

    def test_package_change_at_floor_refreshes_version_without_apt(self):
        self.stamp.return_value=2
        self.scope['time'].time.return_value=129.999
        self.assertEqual(self.scope['get_proxmox_version'](), '9.2.21')
        self.command.assert_not_called()
        self.scope['time'].time.return_value=130
        self.assertEqual(self.scope['get_proxmox_version'](), '9.2.24')
        self.command.assert_called_once_with(['pveversion'],capture_output=True,text=True,timeout=5)
        self.assertEqual(self.cache['proxmox_version_stamp'],2)

    def test_failed_read_returns_unknown_but_keeps_last_known_cache(self):
        self.stamp.return_value=2
        before=dict(self.cache)
        self.command.side_effect=OSError('inert unavailable command')
        self.assertIsNone(self.scope['get_proxmox_version']())
        self.assertEqual(self.cache,before)

    def test_pbs_guard_precedes_all_pve_package_probes(self):
        self.scope['is_pbs_host'].return_value=True
        self.assertEqual(self.scope['get_proxmox_version'](),'4.1.0')
        self.stamp.assert_not_called();self.command.assert_not_called()


if __name__=='__main__':
    unittest.main(verbosity=2)
