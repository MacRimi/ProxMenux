"""The name of the local node is read from the link Proxmox keeps for it, so
finding it out never waits for the API, however slow the host."""
import ast
import os
from pathlib import Path
import re
import socket
import tempfile
import time
import unittest

SERVER = Path(__file__).resolve().parents[1] / 'flask_server.py'


class NodeNameTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse(SERVER.read_text(encoding='utf-8'))
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'get_proxmox_node_name']
        self.assertEqual(len(nodes), 1)
        self.source = ast.get_source_segment(SERVER.read_text(encoding='utf-8'), nodes[0])
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.link = os.path.join(folder.name, 'local')

        def no_subprocess(*args, **kwargs):
            raise AssertionError('the node name must not run a command')

        self.scope = {'os': os, 're': re, 'socket': socket, 'time': time,
                      'subprocess': type('S', (), {'run': staticmethod(no_subprocess)}),
                      '_PROXMOX_NODE_CACHE': {'name': None, 'timestamp': 0.0}, '_PROXMOX_NODE_CACHE_TTL': 300,
                      '_PVE_LOCAL_NODE_LINK': self.link}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SERVER), 'exec'), self.scope)
        self.name = self.scope['get_proxmox_node_name']

    def test_the_name_is_the_folder_the_link_points_to(self):
        os.symlink('nodes/Hades-01', self.link)
        self.assertEqual(self.name(), 'Hades-01')

    def test_the_api_is_not_asked(self):
        self.assertNotIn('pvesh', self.source)
        self.assertNotIn('subprocess', self.source)

    def test_without_the_link_the_hostname_is_used_and_not_kept(self):
        hostname = socket.gethostname().split('.', 1)[0].lower()
        self.assertEqual(self.name(), hostname)
        os.symlink('nodes/pve2', self.link)
        self.assertEqual(self.name(), 'pve2')

    def test_the_answer_is_kept_once_read(self):
        os.symlink('nodes/pve1', self.link)
        self.assertEqual(self.name(), 'pve1')
        os.unlink(self.link)
        self.assertEqual(self.name(), 'pve1')

    def test_a_link_that_names_no_node_is_not_taken(self):
        os.symlink('nodes/bad name', self.link)
        self.assertEqual(self.name(), socket.gethostname().split('.', 1)[0].lower())


class StorageMonitorNodeNameTests(unittest.TestCase):
    """The storage monitor finds the node the same way."""

    def setUp(self):
        import subprocess
        import sys
        from unittest.mock import patch
        sys.path.insert(0, str(SERVER.parent))
        with patch.object(subprocess, 'run', side_effect=OSError('no Proxmox tools in the test')):
            import proxmox_storage_monitor
        self.module = proxmox_storage_monitor
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.link = os.path.join(folder.name, 'local')
        self.monitor = proxmox_storage_monitor.ProxmoxStorageMonitor.__new__(proxmox_storage_monitor.ProxmoxStorageMonitor)
        self.monitor._node_name_cache = {'name': None, 'time': 0}
        self.monitor._PVE_LOCAL_NODE_LINK = self.link

    def test_the_name_comes_from_the_link_without_running_anything(self):
        from unittest.mock import patch
        os.symlink('nodes/pve2', self.link)
        with patch.object(self.module.subprocess, 'run', side_effect=AssertionError('no command')):
            self.assertEqual(self.monitor._get_node_name(), 'pve2')

    def test_without_the_link_the_hostname_is_used(self):
        self.assertEqual(self.monitor._get_node_name(), socket.gethostname())


if __name__ == '__main__':
    unittest.main()
