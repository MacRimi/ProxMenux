"""Private real-module loaders for offline health fixtures.

Never cache test dependencies in sys.modules. Persistence uses its real global
constructor and SQLite schema, redirected to the caller's temporary directory.
Monitor methods are unmodified; only unrelated import-time host dependencies and
singleton cleanup are bounded. Runtime/deferred dependencies belong in each
calling test's patch.dict context, not in the process-wide module cache.
"""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1]
# Keep Path usable while the constructor's imported pathlib.Path is redirected.
ConcretePath = type(Path())


def load_source(name):
    spec = importlib.util.spec_from_file_location('fixture_' + name, SCRIPTS / (name + '.py'))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.object(sys, 'dont_write_bytecode', True):
        spec.loader.exec_module(module)
    return module


def load_health_persistence(data_dir):
    def fixture_path(*args, **kwargs):
        if args == ('/usr/local/share/proxmenux',):
            return ConcretePath(data_dir)
        return ConcretePath(*args, **kwargs)

    with patch('pathlib.Path', fixture_path), contextlib.redirect_stdout(io.StringIO()):
        return load_source('health_persistence')


def load_health_modules(data_dir):
    persistence = load_health_persistence(data_dir)
    # These import-only dependencies are not exercised by these unit tests.
    # Real methods and the real monitor singleton still execute from source.
    dependencies = {
        'health_persistence': persistence,
        'psutil': ModuleType('psutil'),
        'proxmox_storage_monitor': SimpleNamespace(proxmox_storage_monitor=SimpleNamespace()),
        'pbs_manager': SimpleNamespace(get_platform=lambda: {'product': 'pve'}, PBS_SERVICES=()),
        'startup_grace': ModuleType('startup_grace'),
    }
    with patch.dict(sys.modules, dependencies), \
            patch.object(persistence.health_persistence, 'cleanup_old_errors'), \
            patch('os.path.exists', return_value=False):
        monitor = load_source('health_monitor')
        events = load_source('notification_events')
    thresholds = load_source('health_thresholds')
    setattr(thresholds, '_CONFIG_PATH', str(ConcretePath(data_dir) / 'health_thresholds.json'))
    return monitor, events, thresholds
