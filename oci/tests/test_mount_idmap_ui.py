"""Host-directory mappings must be explicit and visible before applying them."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from proxmenux_oci import mount_idmap
from proxmenux_oci.cli import _deployment_summary_text


class MountIdmapUiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.mount = {'type': 'host-bind', 'source': temporary.name,
                      'container_path': '/downloads', 'backup': False,
                      'read_only': False, 'create_if_missing': True}
        self.deployment = {'mounts': [self.mount], 'security': {'unprivileged': True},
                           'environment': [{'name': 'PUID', 'value': '1000'},
                                           {'name': 'PGID', 'value': '1000'}]}

    def ui(self, selection, answers=()):
        result = Mock()
        result.choose.return_value = selection
        result.ask.side_effect = answers
        return result

    def test_root_and_nonroot_presets_express_the_application_identity(self):
        for choice, expected in [('root', 'u:0:2000:1;g:0:2000:1'),
                                 ('application', 'u:1000:2000:1;g:1000:2000:1')]:
            with self.subTest(choice=choice):
                mount_idmap.edit_mapping(self.ui(choice, (['1000', '1000'] if choice == 'application' else []) + ['2000', '2000']), self.mount,
                                         self.deployment, {})
                self.assertEqual(set(self.mount['idmap'].split(';')), set(expected.split(';')))

    def test_invalid_or_cancelled_answer_keeps_the_saved_mapping(self):
        self.mount['idmap'] = 'u:0:2000:1;g:0:2000:1'
        original = copy.deepcopy(self.mount)
        mount_idmap.edit_mapping(self.ui(None), self.mount, self.deployment, {})
        self.assertEqual(self.mount, original)
        with self.assertRaises(ValueError):
            mount_idmap.edit_mapping(self.ui('root', ['0', '2000']), self.mount,
                                     self.deployment, {})
        self.assertEqual(self.mount, original)

    def test_removing_mapping_is_an_explicit_choice(self):
        self.mount['idmap'] = 'u:0:2000:1;g:0:2000:1'
        mount_idmap.edit_mapping(self.ui('default'), self.mount, self.deployment, {})
        self.assertNotIn('idmap', self.mount)

    def test_unsupported_profiles_and_system_paths_are_not_offered(self):
        for key, value in [('security', {'unprivileged': False}),
                           ('replay_profile', {'role': 'application'}),
                           ('deployment_kind', 'generic-multi-lxc-stack')]:
            self.assertEqual(mount_idmap.eligible(dict(self.deployment, **{key: value})), [])
        for source in ('/dev', '/sys/devices', '/run/dbus'):
            self.assertEqual(mount_idmap.eligible(dict(self.deployment,
                mounts=[dict(self.mount, source=source)])), [])
        self.assertEqual(mount_idmap.eligible(self.deployment), [self.mount])

    def test_final_review_shows_the_exact_mapping(self):
        self.mount['idmap'] = 'u:1000:2000:1;g:1000:2000:1'
        template = {'id': 'test', 'catalog_ui': {'title': {'en_US': 'Test'}},
                    'container_contract': {'image': {'reference': 'example/test:latest'}}}
        summary = _deployment_summary_text(template, self.deployment)
        self.assertIn('idmap=u:1000:2000:1;g:1000:2000:1', summary)


if __name__ == '__main__':
    unittest.main()
