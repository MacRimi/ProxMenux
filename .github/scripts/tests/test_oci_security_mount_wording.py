"""Exercise the real OCI preview/import functions without importing host-management modules."""
import ast
import json
from pathlib import Path
import runpy
import unittest
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
CUSTOM = ROOT / 'oci/src/proxmenux_oci/custom.py'
ROWS = {
    'It needs a privileged container, which is not isolated from the host.':
        'This profile requires a privileged LXC, which reduces isolation from the host.',
    'It asks for capabilities or a relaxed confinement profile.':
        'A relaxed AppArmor or seccomp profile is requested; this may be optional.',
    'The image expects files that are given to it one by one:':
        'These container mount paths have an extension-like suffix:',
    'ProxMenux attaches directories, not single files, so this image cannot be installed yet.':
        'This import rejects these paths without checking whether they are files or directories.',
}


class ConversionError(Exception):
    pass


def extracted(name, **deps):
    node = next(n for n in ast.parse(CUSTOM.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = {'Any': Any, 'Path': Path, 'yaml': yaml, 'ConversionError': ConversionError,
             'translate': lambda text: text}
    scope.update(deps)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(CUSTOM), 'exec'), scope)
    return scope[name]


class SecurityMountWording(unittest.TestCase):
    def test_security_warnings_match_their_guards_without_claiming_capabilities(self):
        describe = extracted('describe', blocker_text=str)
        template = {'container_contract': {'image': {'reference': 'test:latest'},
                    'volumes': [], 'ports': [], 'environment': []},
                    'proxmox': {'security_profile': {}}}
        for profile, present in (
            ({}, ()),
            ({'optional_privileged_lxc': True}, ()),
            ({'requires_privileged_lxc': True}, (ROWS['It needs a privileged container, which is not isolated from the host.'],)),
            ({'requires_relaxed_confinement': True}, (ROWS['It asks for capabilities or a relaxed confinement profile.'],)),
            ({'source_requests_relaxed_confinement': True}, (ROWS['It asks for capabilities or a relaxed confinement profile.'],)),
            ({'requires_privileged_lxc': True, 'source_requests_relaxed_confinement': True},
             (ROWS['It needs a privileged container, which is not isolated from the host.'],
              ROWS['It asks for capabilities or a relaxed confinement profile.'])),
        ):
            with self.subTest(profile=profile):
                template['proxmox']['security_profile'] = profile
                text = describe(template)
                for warning in (ROWS['It needs a privileged container, which is not isolated from the host.'],
                                ROWS['It asks for capabilities or a relaxed confinement profile.']):
                    if warning in present:
                        self.assertIn('  ' + warning, text)
                    else:
                        self.assertNotIn(warning, text)
        template['proxmox']['security_profile'] = {}
        template['proxmox']['installer_profile'] = {'security': {'required_capabilities': ['NET_ADMIN']}}
        text = describe(template)
        self.assertNotIn(ROWS['It asks for capabilities or a relaxed confinement profile.'], text)

    def test_suffix_hit_rejects_dotted_directory_without_claiming_file_type(self):
        fn = extracted('template_from_compose',
            _services=lambda d: d['services'], _check_mounts=lambda s: None,
            normalize_app_id=lambda s: s, _published_port=lambda s: None,
            _dump=lambda s: '', _keep_reference=lambda *a: None,
            TIME_SETTINGS=('/etc/localtime', '/etc/timezone'),
            convert_casaos_compose=lambda *args: {'container_contract': {
                'image': {'reference': 'example:latest'},
                'volumes': [{'container_path': '/srv/data.v2', 'installation_choice': ['managed-volume', 'host-bind']}]},
                'proxmox': {}})
        with self.assertRaises(ConversionError) as caught:
            fn('services:\n  app:\n    image: example:latest\n')
        self.assertEqual(str(caught.exception),
            ROWS['The image expects files that are given to it one by one:'] + ' /srv/data.v2. ' +
            ROWS['ProxMenux attaches directories, not single files, so this image cannot be installed yet.'])

    def test_suffix_free_path_still_accepted(self):
        fn = extracted('template_from_compose',
            _services=lambda d: d['services'], _check_mounts=lambda s: None,
            normalize_app_id=lambda s: s, _published_port=lambda s: None,
            _dump=lambda s: '', _keep_reference=lambda *a: None,
            TIME_SETTINGS=('/etc/localtime', '/etc/timezone'),
            convert_casaos_compose=lambda *args: {'container_contract': {
                'image': {'reference': 'example:latest'},
                'volumes': [{'container_path': '/srv/config', 'installation_choice': ['managed-volume', 'host-bind']}]},
                'proxmox': {}})
        self.assertEqual(fn('services:\n  app:\n    image: example:latest\n')['container_contract']['volumes'][0]['container_path'], '/srv/config')

    def test_all_four_keys_extract_and_fallback_in_seven_shipped_locales(self):
        found = runpy.run_path(str(ROOT / '.github/scripts/build_translation_cache.py'))['extract_python_texts']([ROOT / 'oci/src', ROOT / 'oci/remote'])
        self.assertEqual(len(ROWS), 4)
        self.assertTrue(set(ROWS.values()) <= set(found), set(ROWS.values()) - set(found))
        import importlib.util
        spec = importlib.util.spec_from_file_location('oci_i18n', ROOT / 'oci/src/proxmenux_oci/i18n.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        paths = sorted((ROOT / 'lang').glob('*.json'))
        self.assertEqual(len(paths), 7)
        for path in paths:
            cache = json.loads(path.read_text())
            setattr(module, '_language', path.stem)
            setattr(module, '_cache', cache)
            for new in ROWS.values():
                self.assertEqual(module.translate(new), cache.get(new) or new, (path.name, new))
            setattr(module, '_cache', {})
            for new in ROWS.values():
                self.assertEqual(module.translate(new), new, (path.name, new, 'synthetic missing'))
        module._language, module._cache = 'it', {new: 'IT: ' + new for new in ROWS.values()}
        self.assertIn('IT: ' + ROWS['It needs a privileged container, which is not isolated from the host.'],
                      extracted('describe', translate=module.translate, blocker_text=str)({
                          'container_contract': {'image': {'reference': 'test:latest'}, 'volumes': [], 'ports': [], 'environment': []},
                          'proxmox': {'security_profile': {'requires_privileged_lxc': True}}}))


if __name__ == '__main__':
    unittest.main()
