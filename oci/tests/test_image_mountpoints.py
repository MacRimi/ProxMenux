import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'remote/oci_image_mountpoints.py'
spec = importlib.util.spec_from_file_location('image_mountpoints', MODULE)
image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image)


class ImageMountpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.target = self.root / 'app/config'
        self.target.mkdir(parents=True)

    def normalize(self, paths=('/app/config',), mounts=()):
        return image.normalize(self.root, paths, mounts)

    def test_image_files_preserved_target_empty_and_metadata_unchanged(self):
        (self.target / 'db').mkdir()
        (self.target / 'DOCKER').touch()
        data = self.target / 'defaults.json'
        data.write_text('{"image-default":true}')
        data.chmod(0o640)
        self.target.chmod(0o750)
        before = self.target.stat()
        entries = self.normalize()
        saved = self.root / entries[0]['saved'].lstrip('/')
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertEqual((saved / 'defaults.json').read_bytes(), b'{"image-default":true}')
        self.assertEqual((saved / 'defaults.json').stat().st_mode & 0o777, 0o640)
        after = self.target.stat()
        self.assertEqual((after.st_ino, after.st_uid, after.st_gid, after.st_mode),
                         (before.st_ino, before.st_uid, before.st_gid, before.st_mode))
        self.assertEqual(saved.stat().st_uid, before.st_uid)
        self.assertEqual(saved.stat().st_mode & 0o777, 0o750)

    def test_empty_and_missing_targets_do_not_create_archive(self):
        self.assertEqual(self.normalize(('/app/config', '/absent')), [])
        self.assertFalse((self.root / image.ARCHIVE).exists())

    def test_link_inside_target_is_preserved_without_following(self):
        (self.target / 'link').symlink_to('/outside')
        saved = self.root / self.normalize()[0]['saved'].lstrip('/')
        self.assertEqual(os.readlink(saved / 'link'), '/outside')

    def test_symlink_target_and_symlink_ancestor_rejected(self):
        for value in ('/link', '/link/config'):
            with self.subTest(value=value):
                link = self.root / 'link'
                link.symlink_to(self.root / 'app')
                with self.assertRaises(ValueError):
                    self.normalize((value,))
                link.unlink()

    def test_all_paths_validated_before_changes(self):
        (self.target / 'DOCKER').touch()
        (self.root / 'unsafe').symlink_to('/tmp')
        with self.assertRaises(ValueError):
            self.normalize(('/app/config', '/unsafe'))
        self.assertTrue((self.target / 'DOCKER').exists())

    def test_attached_mounts_ancestors_and_descendants_rejected(self):
        for mount in (self.target, self.root / 'app', self.target / 'db'):
            with self.subTest(mount=mount), self.assertRaises(ValueError):
                self.normalize(mounts=(mount,))

    def test_other_mounted_volumes_are_not_touched(self):
        other = self.root / 'persistent'
        other.mkdir()
        (other / 'proof').write_text('persistent data')
        (self.target / 'DOCKER').touch()
        self.normalize(mounts=(other,))
        self.assertEqual((other / 'proof').read_text(), 'persistent data')

    def test_host_root_mount_is_not_an_attached_guest_disk(self):
        (self.target / 'DOCKER').touch()
        self.assertTrue(self.normalize(mounts=('/', self.root)))

    def test_archive_collision_preserves_everything(self):
        (self.root / image.ARCHIVE).mkdir()
        (self.target / 'proof').write_text('image data')
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.normalize()
        self.assertEqual((self.target / 'proof').read_text(), 'image data')

    def test_unsafe_paths_rejected(self):
        for path in ('/', 'relative', '/app/../data', '/app/./config', '/app//config',
                     '/app/config/', '/app\nconfig', f'/{image.ARCHIVE}/data'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.normalize((path,))

    def test_reused_volume_is_not_an_input_and_is_not_modified(self):
        with tempfile.TemporaryDirectory() as data:
            proof = Path(data) / 'live-data'
            proof.write_text('existing service data')
            (self.target / 'new-image-default').write_text('v2')
            self.normalize()
            self.assertEqual(proof.read_text(), 'existing service data')

    def test_multiple_stack_mounts_can_be_prepared_independently(self):
        (self.target / 'DOCKER').touch()
        self.normalize()
        other = self.root / 'other'
        other.mkdir()
        (other / 'defaults').write_text('keep')
        saved = self.root / self.normalize(('/other',))[0]['saved'].lstrip('/')
        self.assertEqual((saved / 'defaults').read_text(), 'keep')
        self.assertEqual(list(other.iterdir()), [])

    def test_already_prepared_target_is_idempotent(self):
        (self.target / 'DOCKER').touch()
        self.normalize()
        self.assertEqual(self.normalize(), [])


    def test_installers_keep_installing_when_a_mountpoint_is_refused(self):
        # A refused path changes nothing, so the image installs as it did before.
        remote = MODULE.parent
        script = (remote / 'install_oci.sh').read_text()
        call = script[script.index('oci_image_mountpoints.py'):]
        self.assertTrue(call.split('\n', 2)[1].strip().startswith('|| oci_log'))
        stack = (remote / 'install_generic_stack.py').read_text()
        block = stack[stack.index('normalize(root, [mount'):][:400]
        self.assertIn('except (OSError, ValueError)', block)

if __name__ == '__main__':
    unittest.main()
