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

    def test_the_host_restore_notice_reports_tasks_and_does_not_call_the_node_ready(self):
        for locale in LOCALES:
            body = json.loads((ROOT / f'AppImage/messages/{locale}/common.json').read_text())['runtime']['notifications']['templates']['system_restore_completed']['body']
            self.assertEqual(body.split('\n')[-1], '{warnings_block}', locale)
            self.assertEqual(body.count('\n'), 7, locale)

    def test_the_watchdog_failure_covers_an_application_that_did_not_start(self):
        english = json.loads((ROOT / 'AppImage/messages/en/common.json').read_text())['runtime']['notifications']['templates']['oci_watchdog_failed']
        self.assertNotIn('keeps stopping', english['title'] + english['body'] + english['label'])
        self.assertIn('did not start', english['body'])

    def test_other_wording_that_promised_too_much(self):
        texts = oci_menu_texts()
        self.assertIn('Private network kept, because other guests still use it:', texts)
        recreation = (ROOT / 'oci/src/proxmenux_oci/stack_recreation.py').read_text()
        self.assertNotIn('if anything fails', recreation)
        self.assertIn('a stopped one is left stopped', recreation)
        for script in ('scripts/post_install/customizable_post_install.sh', 'scripts/post_install/uninstall-tools.sh'):
            self.assertNotIn('leaving it unchanged', (ROOT / script).read_text(), script)
