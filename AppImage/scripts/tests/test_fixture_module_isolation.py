"""Test collection must not publish a fixture as a runtime dependency."""
import importlib.util
from importlib.machinery import SourceFileLoader
import tempfile
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch


TESTS = Path(__file__).resolve().parent


class FixtureCollectionIsolationTests(unittest.TestCase):
    def test_private_persistence_loader_never_writes_bytecode(self):
        from health_fixture_modules import load_health_persistence
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sys, 'dont_write_bytecode', False), \
                patch.object(sys, 'pycache_prefix', str(Path(directory) / 'empty-cache')), \
                patch.object(SourceFileLoader, 'set_data') as cache_write:
            module = load_health_persistence(directory)
            self.assertEqual(module.health_persistence.db_path,
                             Path(directory) / 'health_monitor.db')
            self.assertEqual(cache_write.call_count, 0, 'Fixture imports must not write source bytecode')

    def assert_collection_preserves_modules(self, filename):
        names = ('health_persistence', 'psutil', 'flask_server', 'health_monitor')
        # A pre-existing monitor prevents the old fixture from constructing a
        # host singleton. No runtime method is replaced in the behavioral tests.
        with patch.dict(sys.modules), patch.object(sys, 'path', list(sys.path)):
            for name in names:
                sys.modules.pop(name, None)
            sys.modules['health_monitor'] = ModuleType('health_monitor')
            before = {name: sys.modules.get(name) for name in names}
            spec = importlib.util.spec_from_file_location('collection_fixture', TESTS / filename)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertEqual({name: sys.modules.get(name) for name in names}, before)

    def assert_collection_defers_runtime_import(self, filename):
        original_import = __import__

        def fixture_import(name, *args, **kwargs):
            self.assertNotIn(name, ('health_monitor', 'health_persistence'),
                             'Collection must not construct host singletons')
            return original_import(name, *args, **kwargs)

        spec = importlib.util.spec_from_file_location('collection_fixture', TESTS / filename)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        with patch('builtins.__import__', side_effect=fixture_import), \
                patch.object(sys, 'path', list(sys.path)):
            spec.loader.exec_module(module)

    def test_permanent_cleanup_does_not_open_host_uptime(self):
        spec = importlib.util.spec_from_file_location(
            'cleanup_fixture', TESTS / 'test_permanent_dismissal_is_kept.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        case = module.PermanentDismissalTests('test_it_is_still_dismissed_weeks_later')
        case.setUp()
        self.addCleanup(case.doCleanups)
        with patch('builtins.open', side_effect=AssertionError('No host reads')) as host_open, \
                patch.dict(sys.modules, {'psutil': ModuleType('psutil')}):
            case.cleanup()
        host_open.assert_not_called()

    def test_permanent_dismissal_collection_defers_runtime_import(self):
        self.assert_collection_defers_runtime_import('test_permanent_dismissal_is_kept.py')

    def test_disk_observation_collection_defers_runtime_import(self):
        self.assert_collection_defers_runtime_import('test_disk_observations_follow_the_disk.py')

    def test_idle_bridge_collection_defers_runtime_import(self):
        self.assert_collection_defers_runtime_import('test_idle_bridge.py')

    def test_benign_notice_collection_defers_runtime_import(self):
        self.assert_collection_defers_runtime_import('test_benign_disk_notices.py')

    def test_remote_mount_collection_does_not_publish_dependency_stubs(self):
        self.assert_collection_preserves_modules('test_remote_mount_dismissal.py')

    def test_cluster_collection_does_not_publish_dependency_stubs(self):
        self.assert_collection_preserves_modules('test_cluster_guest_storage_ownership.py')


if __name__ == '__main__':
    unittest.main()
