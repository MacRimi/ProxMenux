"""Every result the OCI engine reports has a notification the Monitor accepts and words."""
import json
from pathlib import Path
import re
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[3]
LOCALES = ('en', 'es', 'de', 'fr', 'it', 'pt', 'sk', 'sv')
EVENTS = [f'oci_{kind}_{result}' for kind in ('update', 'modify', 'recreate') for result in ('completed', 'failed')]
EVENTS += ['oci_watchdog_restarted', 'oci_watchdog_failed']


class OciOperationEvents(TestCase):
    def test_the_monitor_accepts_and_words_every_event(self):
        route = (ROOT / 'AppImage/scripts/flask_notification_routes.py').read_text()
        accepted = route[route.index('_OCI_EVENTS = {'):route.index('@notification_bp.route(\'/api/internal/oci-event\'')]
        templates = (ROOT / 'AppImage/scripts/notification_templates.py').read_text()
        for event in EVENTS:
            self.assertIn(f"'{event}':", accepted, event)
            self.assertEqual(len(re.findall(rf"^    '{event}': \{{$", templates, re.MULTILINE)), 1, event)
            self.assertEqual(len(re.findall(rf"^    '{event}': +'\\[uU]", templates, re.MULTILINE)), 1, event)

    def test_every_language_has_the_label_and_the_message_of_every_event(self):
        fields = lambda text: sorted(re.findall(r'\{(\w+)\}', text))
        english = json.loads((ROOT / 'AppImage/messages/en/common.json').read_text())['runtime']['notifications']['templates']
        for locale in LOCALES:
            catalog = json.loads((ROOT / f'AppImage/messages/{locale}/common.json').read_text())
            for event in EVENTS:
                self.assertTrue(catalog['settings']['notifications']['eventTypes'][event].strip(), f'{locale} {event}')
                message = catalog['runtime']['notifications']['templates'][event]
                for part in ('title', 'body', 'label'):
                    self.assertEqual(fields(message[part]), fields(english[event][part]), f'{locale} {event} {part}')
                    self.assertEqual(message[part].count('\n'), english[event][part].count('\n'), f'{locale} {event} {part}')

    def test_changing_an_application_is_reported_as_modified(self):
        single = (ROOT / 'oci/remote/oci_update_current.py').read_text()
        self.assertIn("kind = 'update' if operation == 'update' else 'modify'", single)
        self.assertIn('oci_operation_notice.operation([vmid], kind,', single)
        stack = (ROOT / 'oci/remote/oci_stack_modify.py').read_text()
        self.assertIn("oci_operation_notice.operation([vmid], 'modify',", stack)
        english = json.loads((ROOT / 'AppImage/messages/en/common.json').read_text())['runtime']['notifications']['templates']
        self.assertIn('new options', english['oci_modify_completed']['body'])
        self.assertNotIn('new options', english['oci_recreate_completed']['body'])
