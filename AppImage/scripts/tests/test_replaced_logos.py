"""A logo address that now serves another image shows the one it was chosen
for: in the Community Scripts list and in applications already registered."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import managed_installs  # noqa: E402
import lxc_apps  # noqa: E402

OLD = 'https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/docker.webp'
NEW = 'https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/docker-2017.webp'
OTHER = 'https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/jellyfin.webp'


class ReplacedLogoTests(unittest.TestCase):
    def test_only_a_replaced_address_changes(self):
        self.assertEqual(managed_installs.current_logo(OLD), NEW)
        self.assertEqual(managed_installs.current_logo(OTHER), OTHER)
        self.assertEqual(managed_installs.current_logo(''), '')

    def test_the_community_scripts_list_uses_the_current_logo(self):
        index = managed_installs._current_logos({
            'docker': {'logo': OLD, 'logo_dark': 'https://example.com/dark.webp'},
            'jellyfin': {'logo': OTHER, 'logo_dark': ''}})
        self.assertEqual(index['docker'], {'logo': NEW, 'logo_dark': ''})
        self.assertEqual(index['jellyfin']['logo'], OTHER)

    def test_the_tracking_hints_use_the_current_logo(self):
        hints = lxc_apps._current_hint_logos({'docker': {'logo': OLD, 'repo': 'moby/moby'},
                                              'jellyfin': {'logo': OTHER}, 'bare': {}})
        self.assertEqual(hints['docker'], {'logo': NEW, 'repo': 'moby/moby'})
        self.assertEqual(hints['jellyfin']['logo'], OTHER)
        self.assertEqual(hints['bare'], {})

    def test_a_registered_application_shows_the_current_logo(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(lxc_apps, '_APPS_DIR', folder):
                Path(lxc_apps._sidecar_path(104)).write_text(json.dumps({'vmid': 104, 'apps': [
                    {'id': 'a', 'name': 'Docker', 'logo_url': OLD,
                     'ports': [{'port': 9000, 'logo_url': OLD}, {'port': 80}]},
                    {'id': 'b', 'name': 'Jellyfin', 'logo_url': OTHER}]}))
                apps = lxc_apps._read_sidecar(104)['apps']
        self.assertEqual(apps[0]['logo_url'], NEW)
        self.assertEqual(apps[0]['ports'][0]['logo_url'], NEW)
        self.assertNotIn('logo_url', apps[0]['ports'][1])
        self.assertEqual(apps[1]['logo_url'], OTHER)


if __name__ == '__main__':
    unittest.main()
