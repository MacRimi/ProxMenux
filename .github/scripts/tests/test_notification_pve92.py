"""Frozen PVE 9.2 report through inert actual receiver and renderers.

No git history, host-management import, notification send or generated fixture.
"""
import ast
import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / 'AppImage/scripts'
sys.path.insert(0, str(SCRIPTS))
import notification_templates as templates

PVE92 = '''Details
=======
VMID    Name    Status    Time     Size     Filename
100     web     ok        1m 1s    1 GiB    vm/100/2026-09-29T17:00:00Z

Total running time: 1m 1s
Total size: 1 GiB
'''


def receiver():
    tree = ast.parse((SCRIPTS / 'notification_events.py').read_text())
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ProxmoxHookWatcher')
    names = ('_classify_pve', '_map_severity', '_backup_outcome', 'process_webhook')
    ns = {'re': re, 'capture_journal_context': lambda **kw: ''}
    class Event:
        def __init__(self, **kw): self.__dict__.update(kw); self.event_id = 'inert'
    ns['NotificationEvent'] = Event
    for name in names:
        node = next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == name)
        node.decorator_list = []
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<inert-webhook>', 'exec'), ns)
    class Queue:
        def __init__(self): self.items = []
        def put(self, event): self.items.append(event)
    class Receiver:
        _hostname = 'node-a'
        _classify_pve = ns['_classify_pve']
        _map_severity = staticmethod(ns['_map_severity'])
        _backup_outcome = staticmethod(ns['_backup_outcome'])
        process_webhook = ns['process_webhook']
        def __init__(self): self._queue = Queue()
    return Receiver()


def event_for(message, severity='info'):
    target = receiver()
    target.process_webhook({'fields': {'type': 'vzdump'}, 'severity': severity,
                            'title': 'Backup', 'message': message})
    return target._queue.items[0]


class PVE92Tests(unittest.TestCase):
    def test_exact_maintainer_report_is_confirmed(self):
        event = event_for(PVE92)
        self.assertEqual(event.data['backup_outcome'], 'confirmed')
        result = templates.render_template(event.event_type, event.data, 'en')
        self.assertIn('Backup complete', result['title'])
        self.assertIn('web (100)', result['title'])
        self.assertIn('✅', result['body'])

    def test_failed_guest_identity_does_not_come_from_timestamp_or_ok_guest(self):
        failed = '101     db      err       1m 1s    0 B      ct/101/2026-09-29T17:00:00Z'
        ok = PVE92.splitlines()[3]
        for rows in (ok + '\n' + failed, failed + '\n' + ok):
            for severity in ('info', 'error'):
                with self.subTest(rows=rows, severity=severity):
                    message = ('INFO: 100 01:01:06 OK\nINFO: Starting Backup of VM 100 (qemu)\n'
                               + PVE92.replace(ok, rows))
                    event = event_for(message, severity)
                    self.assertEqual(event.data['backup_outcome'], 'failed')
                    self.assertEqual(event.data.get('vmname'), 'db')
                    self.assertEqual(event.data.get('vmid'), '101')
                    result = templates.render_template(event.event_type, event.data, 'en')
                    self.assertIn('db (101)', result['title'])
                    self.assertNotIn('web', result['title'])
                    self.assertNotIn('01:01:06', result['title'])
                    self.assertIn('❌ CT db (101)', result['body'])

    def test_pbs_prefix_is_used_in_parsed_type_and_title(self):
        for prefix, kind, label in (('vm', 'qemu', 'VM'), ('ct', 'lxc', 'CT'),
                                    ('other', '', 'VM/CT')):
            with self.subTest(prefix=prefix):
                message = PVE92.replace('vm/100/', prefix + '/100/')
                parsed = templates._parse_vzdump_message(message)
                self.assertEqual(parsed['vms'][0]['type'], kind)
                event = event_for(message)
                result = templates.render_template(event.event_type, event.data, 'en')
                self.assertIn(label + ' web (100)', result['title'])

    def test_slovak_uses_normal_locale_resolution_without_source_sentence_overrides(self):
        from unittest.mock import patch
        data = {'hostname': 'node-a', 'category': 'temperature', 'entity_suffix': '',
                'reason': 'old', 'duration': '3d', 'original_severity': 'WARNING',
                'vmname': 'web', 'vmid': '100', 'storage': 'PBS', 'size': '1 GiB',
                'guests': 3, 'stubs': 0, 'stale_nodes': 0, 'components': 1,
                'warnings_block': ''}
        slovak = templates._load_runtime_catalog('sk')
        english = templates._load_runtime_catalog('en')
        for event, field in (('error_resolved', 'title'), ('error_resolved', 'body'),
                             ('system_restore_completed', 'body'),
                             ('backup_complete', 'title'), ('backup_complete', 'body')):
            with self.subTest(event=event, field=field):
                value = slovak['templates'][event][field]
                result = templates.render_template(event, data, 'sk')
                self.assertEqual(result[field], value.format(**data))
                self.assertNotIn(value, (SCRIPTS / 'notification_templates.py').read_text())
                # Independently updated and absent leaves use the usual provider.
                import copy
                future = copy.deepcopy(slovak)
                future['templates'][event][field] = 'REVIEWED {hostname}'
                with patch.object(templates, '_load_runtime_catalog', side_effect=lambda lang: future if lang == 'sk' else english):
                    self.assertEqual(templates.render_template(event, data, 'sk')[field], 'REVIEWED node-a')
                future['templates'][event].pop(field)
                with patch.object(templates, '_load_runtime_catalog', side_effect=lambda lang: future if lang == 'sk' else english):
                    self.assertEqual(templates.render_template(event, data, 'sk')[field],
                                     templates.render_template(event, data, 'en')[field])

    def test_complete_table_beats_only_truncated_supplemental_log(self):
        message = ('INFO: Starting Backup of VM 100 (qemu)\n' + PVE92 +
                   '\nLogs\n====\nINFO: Log output was too long to be displayed. Please see task log for details.')
        self.assertEqual(event_for(message).data['backup_outcome'], 'confirmed')
        for message, severity, expected in (
            (PVE92.replace('ok ', 'OK '), 'info', 'confirmed'),
            (message, 'warning', 'unconfirmed'),
            (message, 'error', 'failed'),
            (message + '\nERROR: archive write failed', 'info', 'failed'),
            (message + '\nWARNING: skipped file', 'info', 'unconfirmed'),
            (PVE92.replace('ok        ', 'WARNINGS  '), 'info', 'unconfirmed'),
        ):
            with self.subTest(message=message, severity=severity):
                self.assertEqual(event_for(message, severity).data['backup_outcome'], expected)

    def test_incomplete_and_unrelated_sections_cannot_certify_table(self):
        for message in (
            PVE92.split('Total running time:')[0],
            PVE92.replace('vm/100/2026-09-29T17:00:00Z', ''),
            PVE92.replace('\n\nTotal', '\n\nLogs\n======\nTotal'),
            PVE92.replace('\n\nTotal', '\n\nUnrelated section\n100     web     ok\nTotal'),
            PVE92.replace('1m 1s    1 GiB', 'nonsense 1 GiB'),
            PVE92.replace('1 GiB    vm/', 'garbage  vm/'),
            PVE92.replace('1m 1s    1 GiB    vm/', '1m 1s'),
        ):
            with self.subTest(message=message):
                # Complete guest logs cannot rescue a genuinely incomplete table.
                message += '\nINFO: Starting Backup of VM 100 (qemu)\nINFO: Finished Backup of VM 100 (00:01:01)'
                self.assertEqual(event_for(message).data['backup_outcome'], 'unconfirmed')

    def test_blank_line_between_rows_does_not_hide_a_failure(self):
        message = PVE92.replace('\n\nTotal',
            '\n\n101     db      err       1m 1s    0 B      ct/101/2026-09-29T17:00:00Z\n\nTotal')
        event = event_for(message)
        self.assertEqual(event.data['backup_outcome'], 'failed')
        result = templates.render_template(event.event_type, event.data, 'en')
        self.assertIn('db (101)', result['title'])
        self.assertIn('❌ CT db (101)', result['body'])

    def test_changed_titles_and_rows_reach_actual_html_email_in_all_locales(self):
        import html
        from notification_channels import EmailChannel
        email = object.__new__(EmailChannel)
        email.subject_prefix = '[ProxMenux]'
        failed = PVE92.replace('\n\nTotal',
            '\n101     db      err       1m 1s    0 B      ct/101/2026-09-29T17:00:00Z\n\nTotal')
        for lang in ('en', 'de', 'es', 'fr', 'it', 'pt', 'sk', 'sv'):
            for message, severity in ((PVE92, 'info'), (failed, 'info'), (failed, 'error')):
                with self.subTest(lang=lang, severity=severity, message=message):
                    event = event_for(message, severity)
                    result = templates.render_template(event.event_type, event.data, lang)
                    context = {**event.data, '_event_type': event.event_type,
                               '_notification_language': lang, '_group': result['group']}
                    markup = html.unescape(email._format_html(result['title'], result['body'], event.severity, context))
                    self.assertIn(result['title'], markup)
                    if event.data['backup_outcome'] == 'failed':
                        self.assertIn('db (101)', result['title'])
                        self.assertNotIn('web', result['title'])
                        self.assertIn('❌ CT db (101)', markup)
                        status = templates.runtime_message('channels.email.status.failed', lang)
                    else:
                        self.assertIn('VM web (100)', result['title'])
                        self.assertIn('✅ VM web (100)', markup)
                        status = templates.runtime_message('channels.email.status.completed', lang)
                    badge = (templates.runtime_message('channels.email.severity.critical', lang)
                             if event.event_type == 'backup_fail' else status)
                    self.assertIn('>' + badge.upper() + '</span>', markup)


if __name__ == '__main__': unittest.main()
