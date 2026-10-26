"""Inert, extracted producer checks for the two adoption rejection messages."""
import ast
from pathlib import Path
import re
import types
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'remote' / 'oci_instance_reconcile.py'


def mount_reader():
    tree = ast.parse(SOURCE.read_text())
    funcs: list[ast.stmt] = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                             and node.name in ('_mount', '_managed_size')]
    namespace = {'re': re, 'translate': lambda text: text,
                 'host_mounts': types.SimpleNamespace(valid_path=lambda path: path,
                                                      validate_source=lambda path: None)}
    exec(compile(ast.Module(body=funcs, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace['_mount']


class AdoptionWording(unittest.TestCase):
    def test_backup_flag_is_a_requirement_not_a_prior_backup(self):
        mount = mount_reader()
        for value in ('local-lvm:vm-200-disk-3,mp=/data,size=8G,backup=0',
                      'local-lvm:vm-200-disk-3,mp=/data,size=8G'):
            with self.subTest(value=value), self.assertRaisesRegex(
                    ValueError, 'Proxmox volume adoption requires backup=1 and a volume ID'):
                mount('mp2', value, 200)
        self.assertTrue(mount('mp2', 'local-lvm:vm-200-disk-3,mp=/data,size=8G,backup=1', 200)['backup'])

    def test_disk_name_check_does_not_claim_to_prove_ownership(self):
        mount = mount_reader()
        with self.assertRaisesRegex(ValueError,
                'The volume ID does not contain a disk name for this CT; automatic adoption is unsafe'):
            mount('mp2', 'local-lvm:vm-201-disk-3,mp=/data,size=8G,backup=1', 200)
        # A matching substring passes the actual guard; no ownership query is made.
        result = mount('mp2', 'local-lvm:other/vm-200-disk-3.raw,mp=/data,size=8G,backup=1', 200)
        self.assertEqual(result['type'], 'managed-volume')


if __name__ == '__main__':
    unittest.main()
