"""A preview or a warning promises only what the code always does."""
import ast
import json
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[3]
LOCALES = ('en', 'es', 'de', 'fr', 'it', 'pt', 'sk', 'sv')


def oci_menu_texts():
    tree = ast.parse((ROOT / 'oci/src/proxmenux_oci/management.py').read_text())
    return [node.args[0].value for node in ast.walk(tree)
            if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'translate'
            and node.args and isinstance(node.args[0], ast.Constant)]


class OutcomePromises(TestCase):
    def test_a_failure_is_not_promised_to_end_in_a_restore(self):
        texts = oci_menu_texts()
        self.assertEqual([text for text in texts if 'If anything fails' in text], [])
        previews = [text for text in texts if 'stops halfway is recovered from the OCI management menu' in text]
        self.assertEqual(len(previews), 3)

    def test_the_recovery_preview_says_when_each_step_happens(self):
        preview = next(text for text in oci_menu_texts() if 'previous native backup' in text)
        self.assertIn('If the container had already been changed', preview)
        self.assertIn('when the cleanup succeeds', preview)

    def test_a_rclone_mount_is_not_listed_as_a_registration_problem(self):
        prompt = next(text for text in oci_menu_texts() if text.startswith('Until they are registered again'))
        self.assertIn('does not prevent it', prompt)
        self.assertIn('not started automatically', prompt)

    def test_an_empty_retention_is_the_one_of_the_storage(self):
        menu = (ROOT / 'scripts/backup_restore/vm_backup_jobs.sh').read_text()
        self.assertIn('Leave empty to use the retention of the storage.', menu)
        self.assertNotIn('keep every backup', menu)

    def test_host_backups_are_said_to_follow_the_storage(self):
        menu = (ROOT / 'scripts/backup_restore/vm_backup_jobs.sh').read_text()
        self.assertNotIn('stop running', menu)
        self.assertIn('Another job that writes to the same storage still starts them.', menu)
        english = json.loads((ROOT / 'AppImage/messages/en/common.json').read_text())['backup']['vmJobs']
        self.assertNotIn('stop running', english['deleteAttached'] + english['storageAttached'])
        self.assertIn('scheduled runs', english['disableBody'])
        for locale in LOCALES:
            texts = json.loads((ROOT / f'AppImage/messages/{locale}/common.json').read_text())['backup']['vmJobs']
            for key in ('deleteAttached', 'storageAttached'):
                self.assertEqual(texts[key].count('{ids}'), 1, f'{locale} {key}')
            self.assertEqual(texts['disableBody'].count('. '), 1, f'{locale} disableBody')
