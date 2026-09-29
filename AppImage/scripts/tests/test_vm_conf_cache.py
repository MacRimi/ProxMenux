"""The VM/LXC modal caches notice a .conf edited outside the Monitor."""
import ast
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest

SERVER = Path(__file__).resolve().parents[1] / 'flask_server.py'
NAMES = ('_vm_cache_get', '_vm_cache_put', '_vm_conf_signature', '_vm_conf_cache_get', '_vm_conf_cache_put')


class ConfAwareCacheTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse(SERVER.read_text(encoding='utf-8'))
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in NAMES]
        self.assertEqual(sorted(n.name for n in nodes), sorted(NAMES))
        self.files = {'/etc/pve/lxc/111.conf': (1, 300)}

        def stat(path):
            if path not in self.files:
                raise OSError(path)
            mtime, size = self.files[path]
            return SimpleNamespace(st_mtime_ns=mtime, st_size=size)

        self.scope = {'os': SimpleNamespace(stat=stat), 'time': time, '_vm_modal_cache_lock': threading.Lock(),
                      '_vm_conf_built': {}}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SERVER), 'exec'), self.scope)
        self.cache = {}

    def build(self, value):
        signature = self.scope['_vm_conf_signature'](111)
        self.scope['_vm_conf_cache_put'](self.cache, 'details', 111, value, signature)

    def get(self):
        return self.scope['_vm_conf_cache_get'](self.cache, 'details', 111, 10 ** 9)

    def test_unchanged_conf_serves_the_cache(self):
        self.build({'onboot': 1})
        self.assertEqual(self.get(), {'onboot': 1})

    def test_conf_edited_outside_the_monitor_drops_the_entry(self):
        self.build({'onboot': 1})
        self.files['/etc/pve/lxc/111.conf'] = (2, 300)   # `pct set 111 --onboot 0`
        self.assertIsNone(self.get())
        self.build({'onboot': 0})
        self.assertEqual(self.get(), {'onboot': 0})

    def test_entry_without_a_recorded_conf_is_rebuilt(self):
        self.scope['_vm_cache_put'](self.cache, 111, {'old': True})
        self.assertIsNone(self.get())

    def test_vm_conf_path_and_missing_guest(self):
        self.files = {'/etc/pve/qemu-server/200.conf': (5, 10)}
        self.assertEqual(self.scope['_vm_conf_signature'](200), (5, 10))
        self.assertIsNone(self.scope['_vm_conf_signature'](999))


if __name__ == '__main__':
    unittest.main()
