"""Compose aliases remain single, safe /etc/hosts tokens, including underscores."""
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from proxmenux_oci.converter import _extra_hosts


class ComposeHostAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / 'remote/install_oci.sh').read_text()
        cls.shell = re.search(r'^oci_valid_extra_hostname\(\) \{\n.*?^\}', source, re.M | re.S)[0]

    def shell_accepts(self, value):
        return subprocess.run(['bash', '-c', self.shell + '\noci_valid_extra_hostname "$1"', 'alias-test', value],
                              capture_output=True).returncode == 0

    def test_compose_container_aliases_are_accepted_by_import_and_installer(self):
        for value in ('affine_postgres', 'affine_migration_job', 'db-1', 'db.internal', 'a', 'x' * 253):
            with self.subTest(value=value):
                self.assertTrue(self.shell_accepts(value))
                self.assertEqual(_extra_hosts({value: '10.77.8.2'}),
                                 [{'hostname': value, 'address': '10.77.8.2'}])

    def test_multiline_whitespace_and_shell_syntax_are_refused(self):
        for value in ('', 'db name', 'db\tname', 'db\n127.0.0.1 injected', '#comment',
                      '-db', '_db', '$(id)', 'db;id', 'db/../host', 'x' * 254):
            with self.subTest(value=value):
                self.assertFalse(self.shell_accepts(value))
                self.assertIsNone(_extra_hosts({value: '10.77.8.2'}))

    def test_apply_extra_hosts_uses_validated_token_before_writing(self):
        source = (ROOT / 'remote/install_oci.sh').read_text()
        apply = source.split('apply_extra_hosts() {', 1)[1].split('\n}', 1)[0]
        self.assertLess(apply.index('oci_valid_extra_hostname "$hostname"'),
                        apply.index("printf '%s %s\\n'"))
