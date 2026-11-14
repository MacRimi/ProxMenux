"""An operation stopped by a changed configuration names the settings that
changed, never their values."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_instances as instances

SAVED = ('arch: amd64\ndescription: <!-- proxmenux-instance=abc -->\nhostname: immich\n'
         'mp0: /data,mp=/data,backup=0\nnet0: name=eth0,bridge=vmbr0\ntags: oci\n'
         '[vzdump]\nsnaptime: 1\n')


class ChangedSettingsTests(unittest.TestCase):
    def changed(self, config, ignore_tags=True):
        return instances.changed_settings({'observed': {'config': SAVED}}, config.encode(), ignore_tags)

    def test_nothing_changed(self):
        self.assertEqual(self.changed(SAVED), [])

    def test_a_lock_and_a_mount_point_are_named_without_their_values(self):
        config = SAVED.replace('hostname: immich\n', 'hostname: immich\nlock: mounted\n') \
                      .replace('mp0: /data,mp=/data,backup=0', 'mp0: /secret,mp=/data,backup=0')
        changed = self.changed(config)
        self.assertEqual(changed, ['lock', 'mp0'])
        self.assertNotIn('/secret', ' '.join(changed))

    def test_notes_and_tags_are_not_settings(self):
        config = SAVED.replace('proxmenux-instance=abc -->', 'proxmenux-instance=abc --> notes').replace('tags: oci', 'tags: oci;media')
        self.assertEqual(self.changed(config), [])
        self.assertEqual(self.changed(config, ignore_tags=False), ['tags'])

    def test_a_snapshot_section_is_named_as_such(self):
        self.assertEqual(self.changed(SAVED.replace('snaptime: 1', 'snaptime: 2')), ['[vzdump] snaptime'])


if __name__ == '__main__':
    unittest.main()
