"""Inert producer-to-renderer checks for notification outcome claims."""
import ast
import copy
import json
import re
import time
import sys
import types
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / 'AppImage/scripts'
CATALOG = ROOT / 'AppImage/messages/en/common.json'
EXPECTED = {
    'error_resolved': {
        'title': '{hostname}: No longer reported - {category}{entity_suffix}',
        'body': 'The {category} issue is no longer in active health records.\n{reason}\n🚦 Previous severity: {original_severity}\n⏱️ Time since first observation: {duration}',
        'label': 'Recovery notification',
    },

    'system_restore_completed': {
        'body': 'Post-restore tasks completed in background.\n\nGuests applied: {guests}\nBind-mount stubs: {stubs}\nStale node dirs removed: {stale_nodes}\nComponents reinstalled: {components}\nDuration: {duration}\n{warnings_block}',
    },
}


def extract(path, name, owner=None, namespace=None):
    tree = ast.parse(path.read_text())
    nodes = tree.body
    if owner:
        nodes = next(n.body for n in nodes if isinstance(n, ast.ClassDef) and n.name == owner)
    node = next(n for n in nodes if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    ns = namespace if namespace is not None else {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), ns)
    return ns[name]


def renderer(catalog, translated=None):
    path = SCRIPTS / 'notification_templates.py'
    tree = ast.parse(path.read_text())
    templates = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'TEMPLATES' for t in n.targets)))
    def lookup(obj, key):
        for part in key.split('.'):
            obj = obj.get(part) if isinstance(obj, dict) else None
        return obj
    def message(key, language='en', **values):
        source = translated if language == 'it' and translated is not None else catalog
        namespace = source['runtime']['notifications']
        value = lookup(namespace, key) or lookup(catalog['runtime']['notifications'], key) or ''
        return value.format_map(type('Safe', (dict,), {'__missing__': lambda self, k: ''})(values))
    ns = {'TEMPLATES': templates, 'Dict': dict, 'Any': Any, 'time': time, 're': re,
          '_get_hostname': lambda: 'node-a',
          '_load_runtime_catalog': lambda lang: (translated if lang == 'it' and translated is not None
                                                 else catalog)['runtime']['notifications'],
          '_catalog_value': lookup, 'runtime_message': message}
    from typing import Optional
    ns['Optional'] = Optional
    extract(path, '_parse_vzdump_message', namespace=ns)
    extract(path, '_format_vzdump_body', namespace=ns)
    return templates, extract(path, 'render_template', namespace=ns)


class OutcomeWording(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG.read_text())
        cls.templates, render = renderer(cls.catalog)
        cls.render = staticmethod(render)

    def test_upstream_slovak_stale_claims_use_english_report_fallback(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('isolated_slovak_report', SCRIPTS / 'notification_templates.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        recovered = module.render_template('error_resolved', {'hostname':'node-a',
            'category':'temperature','reason':'old','duration':'3d',
            'original_severity':'WARNING'}, 'sk')
        self.assertIn('No longer reported',recovered['title'])
        self.assertIn('no longer in active health records',recovered['body'])
        restored = module.render_template('system_restore_completed', {'hostname':'node-a',
            'guests':3,'stubs':0,'stale_nodes':0,'components':1,'duration':'2m',
            'warnings_block':'⚠️ Boot check pending'}, 'sk')
        self.assertIn('Post-restore tasks completed',restored['body'])
        self.assertNotIn('úplne pripravený',restored['body'])

    def test_slovak_fallback_is_per_stale_leaf_not_unrelated_key_presence(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('isolated_slovak_future', SCRIPTS / 'notification_templates.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        upstream = json.loads((ROOT / 'AppImage/messages/sk/common.json').read_text())['runtime']['notifications']
        english = self.catalog['runtime']['notifications']
        data = {'hostname': 'node-a', 'category': 'temperature', 'reason': 'old',
                'duration': '3d', 'original_severity': 'WARNING', 'guests': 3}
        for event, field in (('error_resolved', 'title'), ('error_resolved', 'body'),
                             ('system_restore_completed', 'body'),
                             ('backup_complete', 'title'), ('backup_complete', 'body')):
            # A new translation must work independently of another family's key.
            translated = copy.deepcopy(upstream)
            translated['templates'][event][field] = 'REVIEWED TRANSLATION {hostname}'
            with self.subTest(event=event, field=field, case='future translation'):
                with patch.object(module, '_load_runtime_catalog', side_effect=lambda lang: translated if lang == 'sk' else english):
                    result = module.render_template(event, data, 'sk')
                self.assertEqual(result[field], 'REVIEWED TRANSLATION node-a')
            # Adding outcome keys must not re-enable unrelated stale claims.
            stale = copy.deepcopy(upstream)
            stale.setdefault('backup', {})['unconfirmedBody'] = 'REVIEWED OUTCOME'
            with self.subTest(event=event, field=field, case='stale after key addition'):
                with patch.object(module, '_load_runtime_catalog', side_effect=lambda lang: stale if lang == 'sk' else english):
                    result = module.render_template(event, data, 'sk')
                self.assertEqual(result[field], module.render_template(event, data, 'en')[field])
        # The unchanged restore title is not an unsafe readiness claim.
        self.assertEqual(module.render_template('system_restore_completed', data, 'sk')['title'],
                         upstream['templates']['system_restore_completed']['title'].format(**data))

    def test_spanish_restore_uses_maintainer_guests_terminology(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('isolated_spanish_restore', SCRIPTS / 'notification_templates.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.render_template('system_restore_completed', {
            'hostname':'node-a','guests':3,'stubs':0,'stale_nodes':0,
            'components':1,'duration':'2m','warnings_block':''}, 'es')
        self.assertIn('Configuraciones de guests aplicadas: 3', result['body'])
        self.assertNotIn('invitados', result['body'].lower())

    def test_settings_labels_stay_at_upstream_values_in_all_locales(self):
        # Frozen from develop eb7cc548; CI shallow checkouts have no base history.
        labels = {'en': {'backup_complete': 'Backup complete', 'error_resolved': 'Recovery notification'}, 'de': {'backup_complete': 'Sicherung abgeschlossen', 'error_resolved': 'Wiederherstellungsbenachrichtigung'}, 'es': {'backup_complete': 'Backup completado', 'error_resolved': 'Notificación de recuperación'}, 'fr': {'backup_complete': 'Sauvegarde terminée', 'error_resolved': 'Notification de récupération'}, 'it': {'backup_complete': 'Backup completato', 'error_resolved': 'Notifica di recupero'}, 'pt': {'backup_complete': 'Backup concluído', 'error_resolved': 'Notificação de recuperação'}, 'sk': {'backup_complete': 'Záloha bola dokončená', 'error_resolved': 'Problém bol vyriešený'}, 'sv': {'backup_complete': 'Säkerhetskopieringen är klar', 'error_resolved': 'Återställningsmeddelande'}}
        for lang in labels:
            path = f'AppImage/messages/{lang}/common.json'
            current = json.loads((ROOT / path).read_text())
            for event in ('backup_complete', 'error_resolved'):
                with self.subTest(lang=lang, event=event):
                    expected = labels[lang][event]
                    self.assertEqual(current['runtime']['notifications']['templates'][event]['label'], expected)
                    if lang == 'en': self.assertEqual(self.templates[event]['label'], expected)

    def test_exact_four_english_leaves_match_source_and_catalog(self):
        for event, fields in EXPECTED.items():
            for field, value in fields.items():
                with self.subTest(event=event, field=field):
                    self.assertEqual(self.templates[event][field], value)
                    self.assertEqual(self.catalog['runtime']['notifications']['templates'][event][field], value)

    def test_webhook_backup_outcome_is_evidence_based_without_rerouting(self):
        path = SCRIPTS / 'notification_events.py'
        ns = {'re': re, 'capture_journal_context': lambda **kw: ''}
        classify = extract(path, '_classify_pve', 'ProxmoxHookWatcher', ns)
        severity_map = extract(path, '_map_severity', 'ProxmoxHookWatcher', ns)
        backup_outcome = extract(path, '_backup_outcome', 'ProxmoxHookWatcher', ns)
        class Event:
            def __init__(self, **kw): self.__dict__.update(kw); self.event_id = 'inert'
        class Queue:
            def __init__(self): self.items = []
            def put(self, event): self.items.append(event)
        ns['NotificationEvent'] = Event
        receive = extract(path, 'process_webhook', 'ProxmoxHookWatcher', ns)
        class Receiver:
            _hostname = 'node-a'
            _classify_pve = classify
            _map_severity = staticmethod(severity_map)
            _backup_outcome = staticmethod(backup_outcome)
            def __init__(self): self._queue = Queue()
        header = '{:<8}{:<22}{:<10}{:<10}{:<14}{}'.format('VMID','Name','Status','Time','Size','Filename')
        row_ok = '{:<8}{:<22}{:<10}{:<10}{:<14}{}'.format('104','alpha','OK','00:01:00','1.5 GiB','archive')
        row_warning = '{:<8}{:<22}{:<10}{:<10}{:<14}{}'.format('105','beta','WARNINGS','00:01:00','1.5 GiB','archive')
        row_error = '{:<8}{:<22}{:<10}{:<10}{:<14}{}'.format('105','beta','ERROR','00:01:00','1.5 GiB','archive')
        row_err = '{:<8}{:<22}{:<10}{:<10}{:<14}{}'.format('105','beta','err','00:01:00','1.5 GiB','archive')
        truncated = 'INFO: Log output was too long to be displayed. Please see task log for details.'
        cases = [
            ('vzdump', 'info', header+'\n'+row_ok+'\n'+row_err+'\nTotal running time: 00:02:00', 'failed'),
            ('vzdump', 'info', 'INFO: Starting Backup of VM 104 (qemu)\n'+header+'\n'+row_ok+'\nTotal running time: 00:01:00\n'+truncated, 'confirmed'),
            ('vzdump', 'info', header+'\n'+row_ok+'\nTotal running time: 00:01:00\n'+truncated, 'confirmed'),
            ('vzdump', 'info', header+'\n'+row_err+'\nTotal running time: 00:01:00\n'+truncated, 'failed'),
            ('vzdump', 'warning', header+'\n'+row_ok+'\nTotal running time: 00:01:00', 'unconfirmed'),
            ('vzdump', 'info', header+'\n'+row_ok, 'unconfirmed'),
            ('vzdump', 'info', 'INFO: Starting Backup of VM 104 (qemu)\nINFO: Finished Backup of VM 104 (00:01:00)\n'+header+'\n'+row_ok, 'unconfirmed'),
            ('vzdump', 'warning', header+'\n'+row_err+'\nTotal running time: 00:01:00', 'failed'),
            ('vzdump', 'info', header+'\n'+row_ok+'\n'+row_warning+'\nTotal running time: 00:02:00\n'+truncated, 'unconfirmed'),
            ('vzdump', 'info', header+'\n'+row_ok+'\nTotal running time: 00:01:00\nERROR: archive write failed', 'failed'),
            ('vzdump', 'info', header+'\n'+row_ok+'\n'+row_error+'\nTotal running time: 00:02:00', 'failed'),
            ('vzdump', 'info', 'INFO: Starting Backup of VM 104 (qemu)\nINFO: Finished Backup of VM 104 (00:01:00)\n'+header+'\n'+row_error+'\nTotal running time: 00:02:00', 'failed'),
            ('vzdump', 'info', header+'\n'+row_error, 'failed'),
            ('vzdump', 'info', header+'\n'+row_ok+'\nTotal running time: 00:01:00', 'confirmed'),
            ('vzdump', 'info', header+'\n'+row_ok+'\n'+row_warning+'\nTotal running time: 00:02:00', 'unconfirmed'),
            ('vzdump', 'info', header+'\n'+row_ok[:30], 'unconfirmed'),
            ('vzdump', 'info', 'INFO: Starting Backup of VM 104 (qemu)\nINFO: Finished Backup of VM 104 (00:01:00)', 'confirmed'),
            ('vzdump', 'warning', 'INFO: Starting Backup of VM 104 (qemu)\nINFO: Finished Backup of VM 104 (00:01:00)', 'unconfirmed'),
            ('vzdump', 'info', 'INFO: Starting Backup of VM 104 (qemu)', 'unconfirmed'),
            ('vzdump', 'info', 'INFO: Starting Backup of VM 104 (qemu)\nINFO: Starting Backup of VM 105 (lxc)\nINFO: Finished Backup of VM 105 (00:01:00)', 'unconfirmed'),
            ('vzdump', 'info', 'INFO: Starting Backup of VM 104 (qemu)\nINFO: Finished Backup of VM 104 (00:01:00)\nWARNING: skipped file', 'unconfirmed'),
            ('vzdump', 'info', 'INFO: Starting Backup of VM 104 (qemu)\nINFO: Finished Backup of VM 104 (00:01:00)\nINFO: TASK OK\n104 alpha WARNINGS: 1', 'unconfirmed'),
            ('vzdump', 'info', 'INFO: Starting Backup of VM 104 (qemu)\nINFO: Finished Backup of VM 105 (00:01:00)', 'unconfirmed'),
            ('vzdump', 'info', 'INFO: Starting Backup of VM 104 (qemu)\nINFO: Starting Backup of VM 105 (lxc)\nINFO: Finished Backup of VM 104 (00:01:00)\nINFO: Finished Backup of VM 105 (00:01:00)', 'confirmed'),
            ('vzdump', 'info', 'INFO: Starting Backup of VM 104 (qemu)\nERROR: backup failed for VM 104', 'failed'),
            ('vzdump', 'warning', 'INFO: Starting Backup of VM 104 (qemu)\nERROR: backup failed', 'failed'),
            ('', 'warning', 'Backup scheduled', 'unconfirmed'),
            ('', 'info', 'Backup complete', 'unconfirmed'),
        ]
        for kind, severity, message, expected in cases:
            with self.subTest(message=message, severity=severity):
                receiver = Receiver()
                receive(receiver, {'fields': {'type': kind}, 'severity': severity,
                                   'title': 'Backup', 'message': message})
                event = receiver._queue.items[0]
                self.assertEqual(event.event_type, 'backup_complete')
                self.assertEqual(event.data['backup_outcome'], expected)

    def test_backup_classifier_preserves_confirmed_and_unverified_paths(self):
        path = SCRIPTS / 'notification_events.py'
        ns = {'re': re, 'capture_journal_context': lambda **kw: ''}
        classify = extract(path, '_classify_pve', 'ProxmoxHookWatcher', ns)
        severity_map = extract(path, '_map_severity', 'ProxmoxHookWatcher', ns)
        backup_outcome = extract(path, '_backup_outcome', 'ProxmoxHookWatcher', ns)
        class Event:
            def __init__(self, **kw): self.__dict__.update(kw); self.event_id = 'inert'
        class Queue:
            def __init__(self): self.items = []
            def put(self, event): self.items.append(event)
        ns['NotificationEvent'] = Event
        receive = extract(path, 'process_webhook', 'ProxmoxHookWatcher', ns)
        class Receiver:
            _hostname = 'node-a'
            _classify_pve = classify
            _map_severity = staticmethod(severity_map)
            _backup_outcome = staticmethod(backup_outcome)
            def __init__(self): self._queue = Queue()
        samples = [('vzdump', 'info', 'Backup', 'job finished'),
                   ('vzdump', 'warning', 'Backup', 'job incomplete'),
                   ('', 'warning', 'backup job', 'Backup scheduled')]
        for kind, severity, title, message in samples:
            with self.subTest(kind=kind, message=message):
                event, entity, _ = classify(None, kind, severity, title, message)
                self.assertEqual((event, entity), ('backup_complete', 'vm'))
                receiver = Receiver()
                reply = receive(receiver, {'fields': {'type': kind}, 'severity': severity,
                                           'title': title, 'message': message})
                self.assertEqual(reply['event_type'], event)
                self.assertEqual(len(receiver._queue.items), 1)
                emitted = receiver._queue.items[0]
                self.assertEqual(emitted.severity, 'WARNING' if severity == 'warning' else 'INFO')
                output = self.render(emitted.event_type, emitted.data, 'en')
                self.assertIn('Backup outcome unconfirmed', output['title'])
                self.assertEqual(output['body'].splitlines()[-1], message)  # raw PVE body retained
        self.assertEqual(classify(None, 'vzdump', 'error', 'Backup', 'failed')[0], 'backup_fail')

    def test_incomplete_vzdump_log_does_not_certify_a_guest(self):
        from typing import Dict, Optional
        ns = {'re': re, 'Dict': Dict, 'Optional': Optional, 'Any': Any,
              'runtime_message': lambda key, lang, **kw: key}
        parser = extract(SCRIPTS / 'notification_templates.py', '_parse_vzdump_message', namespace=ns)
        formatter = extract(SCRIPTS / 'notification_templates.py', '_format_vzdump_body', namespace=ns)
        incomplete = parser('INFO: Starting Backup of VM 104 (qemu)')
        table_header = '{:<8}{:<22}{:<10}{:<10}{:<14}{}'.format('VMID','Name','Status','Time','Size','Filename')
        table_err = '{:<8}{:<22}{:<10}{:<10}{:<14}{}'.format('104','alpha','err','00:01:00','1.5 GiB','archive')
        failed_table = parser(table_header+'\n'+table_err+'\nTotal running time: 00:01:00')
        self.assertEqual(failed_table['vms'][0]['status'].lower(), 'error')
        self.assertIn('❌', formatter(failed_table, False, 'en'))
        self.assertEqual(incomplete['vms'][0]['status'], 'unknown')
        self.assertNotIn('✅', formatter(incomplete, False, 'en'))
        mixed = parser('INFO: Starting Backup of VM 104 (qemu)\nINFO: Finished Backup of VM 104 (00:01:00)\nINFO: Starting Backup of VM 105 (lxc)')
        self.assertEqual([vm['status'] for vm in mixed['vms']], ['ok', 'unknown'])
        formatted = formatter(mixed, False, 'en')
        self.assertEqual(formatted.count('✅'), 1)
        self.assertNotIn('❌', formatted)
        conflicting = parser('INFO: Starting Backup of VM 104 (qemu)\nERROR: backup failed\nINFO: Finished Backup of VM 104 (00:01:00)')
        self.assertEqual(conflicting['vms'][0]['status'], 'error')

    def test_backup_render_preserves_success_and_marks_unconfirmed_and_failure(self):
        for outcome, message, title_part, body_part in (
            ('confirmed', 'INFO: Starting Backup of VM 104 (qemu)\nINFO: Finished Backup of VM 104 (00:01:00)', 'Backup complete', '✅'),
            ('unconfirmed', 'INFO: Starting Backup of VM 104 (qemu)', 'Backup outcome unconfirmed', '❔'),
            ('failed', 'INFO: Starting Backup of VM 104 (qemu)\nERROR: backup failed', 'Backup error reported', '❌'),
        ):
            with self.subTest(outcome=outcome):
                output = self.render('backup_complete', {'hostname': 'node-a', 'pve_type': 'vzdump',
                    'pve_message': message, 'pve_title': 'Backup complete', 'backup_outcome': outcome}, 'en')
                self.assertIn(title_part, output['title'])
                self.assertIn(body_part, output['body'])
                if outcome != 'confirmed': self.assertNotIn('Backup complete', output['title'])
        output = self.render('backup_complete', {'hostname': 'node-a', 'vmname': 'vm', 'vmid': '104'}, 'en')
        self.assertIn('Backup outcome unconfirmed', output['title'])
        self.assertNotIn('successfully', output['body'])
        conflict = self.render('backup_complete', {'hostname': 'node-a','backup_outcome':'failed',
            'pve_message':'INFO: Starting Backup of VM 104 (qemu)\nINFO: Finished Backup of VM 104 (00:01:00)\nERROR: archive write failed'}, 'en')
        self.assertIn('ERROR: archive write failed', conflict['body'])
        self.assertNotIn('Backup complete', conflict['title'])

    def test_confirmed_title_keeps_single_guest_and_destination_without_misnaming_batches(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('isolated_backup_title', SCRIPTS / 'notification_templates.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        actual_render = module.render_template
        log = ('INFO: starting new backup job: vzdump 104 --storage PBS-Cloud --mode snapshot\n'
               'INFO: Starting Backup of VM 104 (qemu)\nINFO: VM Name: Alpha\n'
               'INFO: Finished Backup of VM 104 (00:01:00)')
        single = actual_render('backup_complete', {'hostname':'node-a','backup_outcome':'confirmed',
                               'pve_message':log}, 'en')
        self.assertIn('PBS-Cloud',single['title'])
        self.assertIn('VM Alpha (104)',single['title'])
        batch = actual_render('backup_complete', {'hostname':'node-a','backup_outcome':'confirmed',
                              'pve_message':log+'\nINFO: Starting Backup of VM 105 (lxc)\n'
                                            'INFO: Finished Backup of VM 105 (00:01:00)'}, 'en')
        self.assertIn('PBS-Cloud',batch['title'])
        self.assertNotIn('Alpha (104)',batch['title'])
        no_context = actual_render('backup_complete', {'hostname':'node-a','backup_outcome':'confirmed'}, 'en')
        self.assertEqual(no_context['title'], 'node-a: Backup complete')
        named = actual_render('backup_complete', {'hostname':'node-a','backup_outcome':'confirmed',
            'pve_message':log.replace('Alpha','Alpha {literal}')}, 'en')
        self.assertIn('Alpha {literal} (104)', named['title'])

    def test_html_email_badge_and_backup_status_are_context_specific(self):
        import html
        path = SCRIPTS / 'notification_channels.py'
        for lang in ('en', 'de', 'es', 'fr', 'it', 'pt', 'sk', 'sv'):
            with self.subTest(lang=lang):
                catalog = json.loads((ROOT / 'AppImage/messages' / lang / 'common.json').read_text())['runtime']['notifications']
                english = self.catalog['runtime']['notifications']
                def text(key, data=None, **values):
                    def lookup(source):
                        value = source['channels']
                        for part in key.split('.'):
                            value = value.get(part) if isinstance(value, dict) else None
                        return value
                    return (lookup(catalog) or lookup(english) or '').format(**values)
                ns = {'Dict': dict, 'Optional': __import__('typing').Optional,
                      '_runtime_text': text, '_runtime_notification_text': lambda key, data=None: ''}
                build = extract(path, '_build_detail_rows', 'EmailChannel', ns)
                fmt = extract(path, '_format_html', 'EmailChannel', ns)
                class Email:
                    _SEV_STYLE = {'OK': {'color':'#16a34a','bg':'#f0fdf4','border':'#bbf7d0'},
                                  'CRITICAL': {'color':'#dc2626','bg':'#fef2f2','border':'#fecaca'},
                                  'INFO': {'color':'blue','bg':'white','border':'gray'}}
                    _SEV_DEFAULT = {'color':'#6b7280','bg':'#f9fafb','border':'#e5e7eb'}
                    subject_prefix = 'ProxMenux'
                    _build_detail_rows = staticmethod(build)
                badge = catalog['channels']['email']['severity'].get('observation') or english['channels']['email']['severity']['observation']
                recovery = fmt(Email(), 'No longer reported', 'Body', 'OK', {'_event_type': 'error_resolved',
                    '_notification_language': lang, '_group': 'health'})
                self.assertIn('>' + badge.upper() + '</span>', recovery)
                self.assertIn('color:#6b7280;', recovery)
                unrelated = fmt(Email(), 'Reconnected', 'Body', 'OK', {'_event_type': 'node_reconnect',
                    '_notification_language': lang, '_group': 'cluster'})
                self.assertIn('>' + catalog['channels']['email']['severity']['ok'].upper() + '</span>', unrelated)
                for outcome, status in [('confirmed', 'completed'), ('unconfirmed','unconfirmed'), ('failed','failed')]:
                    email = fmt(Email(), 'Backup', 'Details', 'INFO', {'_event_type': 'backup_complete',
                        'backup_outcome': outcome, '_notification_language': lang, '_group': 'backup'})
                    label = catalog['channels']['email']['status'].get(status) or english['channels']['email']['status'][status]
                    self.assertIn(label, html.unescape(email))
                    badge_label = label.upper()
                    self.assertIn('>' + badge_label + '</span>', html.unescape(email))
                    if outcome == 'failed':
                        self.assertIn('color:#dc2626;font-weight:600;', email)
                        self.assertIn('background:#fef2f2;', email)
                    elif outcome == 'unconfirmed':
                        self.assertIn('background:#f9fafb;', email)
                    else:
                        self.assertIn('background:#f0fdf4;', email)

    def test_actual_all_locale_rendering_and_fallback_for_backup_outcomes(self):
        import importlib.util
        module_path = SCRIPTS / 'notification_templates.py'
        spec = importlib.util.spec_from_file_location('isolated_notification_templates', module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # templates and catalogs only; no manager or sends
        samples = {
            'confirmed': 'INFO: Starting Backup of VM 104 (qemu)\nINFO: Finished Backup of VM 104 (00:01:00)',
            'unconfirmed': 'INFO: Starting Backup of VM 104 (qemu)',
            'failed': 'INFO: Starting Backup of VM 104 (qemu)\nERROR: backup failed',
        }
        for lang in ('en', 'de', 'es', 'fr', 'it', 'pt', 'sk', 'sv'):
            catalog = json.loads((ROOT / 'AppImage/messages' / lang / 'common.json').read_text())['runtime']['notifications']
            for state, message in samples.items():
                with self.subTest(lang=lang, state=state):
                    data = {'hostname':'node-with-a-long-name','backup_outcome':state,'pve_type':'vzdump',
                            'pve_message':message, 'pve_title':'Backup complete', '_notification_language':lang}
                    result = module.render_template('backup_complete', data, lang)
                    if state != 'unconfirmed':
                        key = 'confirmedTitle' if state == 'confirmed' else 'errorTitle'
                        expected_title = (catalog.get('backup', {}).get(key) or
                                          self.catalog['runtime']['notifications']['backup'][key]).format(hostname=data['hostname'])
                        self.assertTrue(result['title'].startswith(expected_title), result['title'])
                    else:
                        source = (catalog if catalog.get('backup', {}).get('unconfirmedBody')
                                  else self.catalog['runtime']['notifications'])
                        self.assertEqual(result['title'], source['templates']['backup_complete']['title'].format(hostname=data['hostname']))
                    self.assertNotIn('{hostname}', result['title'])
                    if state == 'unconfirmed':
                        source = (catalog if catalog.get('backup', {}).get('unconfirmedBody')
                                  else self.catalog['runtime']['notifications'])
                        self.assertIn(source['backup']['unconfirmedBody'], result['body'])
                    if state == 'failed':
                        self.assertIn(catalog.get('backup', {}).get('errorBody') or
                                      self.catalog['runtime']['notifications']['backup']['errorBody'], result['body'])
                    enriched, _ = module.enrich_with_emojis('backup_complete', result['title'], result['body'], data)
                    self.assertTrue(enriched.startswith({'confirmed':'💾✅','unconfirmed':'💾❔','failed':'💾❌'}[state]))
            recovery = module.render_template('error_resolved', {'hostname':'node','category':'temperature',
                'reason':'Old observation','duration':'3d','original_severity':'WARNING'}, lang)
            recovery_source = (catalog if catalog.get('backup', {}).get('unconfirmedBody')
                               else self.catalog['runtime']['notifications'])
            self.assertEqual(recovery['title'], recovery_source['templates']['error_resolved']['title'].format(hostname='node',category='temperature',entity_suffix=''))
            self.assertNotIn('resolved', recovery['title'].lower()) if lang == 'en' else None
            restore = module.render_template('system_restore_completed', {'hostname':'node', 'guests':4,
                'stubs':1,'stale_nodes':2,'components':1,'duration':'2m','warnings_block':'Missing module'},lang)
            self.assertIn('Missing module',restore['body'])
            self.assertNotIn('fully ready',restore['body'].lower())

    def test_stale_record_disappearance_is_not_claimed_recovery(self):
        data = {'hostname': 'node-a', 'category': 'temperature', 'reason': 'Temperature observation (no longer reported)',
                'original_severity': 'WARNING', 'duration': '2d 0h', 'severity': 'OK'}
        output = self.render('error_resolved', data, 'en')
        self.assertIn('no longer in active health records', output['body'])
        self.assertNotIn('resolved', (output['title'] + output['body']).lower())
        self.assertIn('Time since first observation', output['body'])

    def test_actual_poller_stale_disappearance_keeps_reason_factual(self):
        class Store:
            def get_active_errors(self): return []
            def is_error_acknowledged(self, key): return False
        class Event:
            def __init__(self, *args, **kwargs): self.kind, self.severity, self.data = args[:3]
        class Queue:
            def __init__(self): self.items = []
            def put(self, event): self.items.append(event)
        ns = {'time': time, 'json': json, 'NotificationEvent': Event, 'Dict': dict}
        poll = extract(SCRIPTS / 'notification_events.py', '_check_persistent_health', 'PollingCollector', ns)
        class Collector:
            _hostname = 'node-a'
            _ENTITY_MAP = {'temperature': ('node', '')}
            _first_poll_done = True
            _known_errors = {'temp': {'category': 'temperature', 'reason': 'Temperature high',
                                      'severity': 'WARNING', 'first_seen': '2026-09-25T00:00:00'}}
            _notified_severity = {'temp': 'WARNING'}
            _last_notified = {'temp': 1}
            _queue = Queue()
            def _guest_storage_error_is_now_foreign(self, *a): return False
            def _save_known_errors_meta(self): pass
        with patch.dict(sys.modules, {'health_persistence': types.SimpleNamespace(health_persistence=Store())}):
            poll(Collector())
        events = Collector._queue.items
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0].kind, events[0].severity), ('error_resolved', 'OK'))
        self.assertEqual(events[0].data['reason'], 'Temperature high (no longer reported)')
        rendered = self.render(events[0].kind, events[0].data, 'en')
        self.assertNotIn('recovered', rendered['body'].lower())

    def test_warning_and_clean_restore_keep_only_reported_outcome(self):
        for warnings in ('', '⚠️  Boot sanity: missing modules\n'):
            with self.subTest(warnings=warnings):
                events = []
                ns = {'request': types.SimpleNamespace(remote_addr='127.0.0.1', get_json=lambda **kw: {
                    'hostname': 'node-a', 'guests': '2', 'stubs': '0', 'stale_nodes': '0',
                    'components': 'none', 'duration': '2m',
                    'warnings': 'missing modules' if warnings else ''}),
                    'notification_manager': types.SimpleNamespace(emit_event=lambda **kw: events.append(kw)),
                    'jsonify': lambda obj: obj}
                handler = extract(SCRIPTS / 'flask_notification_routes.py', 'internal_restore_event', namespace=ns)
                response, status = handler()
                self.assertEqual((status, response['event_type']), (200, 'system_restore_completed'))
                event = events[0]
                self.assertEqual(event['severity'], 'WARNING' if warnings else 'INFO')
                result = self.render(event['event_type'], event['data'], 'en')
                self.assertIn('Post-restore tasks completed', result['body'])
                self.assertNotIn('fully ready', result['body'])
                if warnings: self.assertIn('missing modules', result['body'])

    def test_missing_key_fallback_and_synthetic_translation(self):
        catalog = copy.deepcopy(self.catalog)
        translated = copy.deepcopy(self.catalog)
        for event, fields in EXPECTED.items():
            for field in fields: translated['runtime']['notifications']['templates'][event].pop(field)
        _, render = renderer(catalog, translated)
        for event, fields in EXPECTED.items():
            for field in fields:
                if field not in ('title', 'body'):
                    continue
                self.assertEqual(render(event, {'category': 'disk'}, 'it')[field],
                                 render(event, {'category': 'disk'}, 'en')[field])
        translated['runtime']['notifications']['templates']['error_resolved']['title'] = 'Synthetic observation: {category}'
        _, render = renderer(catalog, translated)
        self.assertEqual(render('error_resolved', {'category': 'disk'}, 'it')['title'], 'Synthetic observation: disk')

    def test_rich_backup_icon_tracks_outcome_and_digest_default_is_neutral(self):
        tree = ast.parse((SCRIPTS / 'notification_templates.py').read_text())
        def assign(name):
            return ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)))
        icons = assign('EVENT_EMOJI')
        self.assertNotIn('✅', icons['backup_complete'])
        ns = {'TEMPLATES': assign('TEMPLATES'), 'EVENT_EMOJI': icons,
              'Dict': dict, 'Any': Any,
              'CATEGORY_EMOJI': assign('CATEGORY_EMOJI'), 'SEVERITY_ICONS': assign('SEVERITY_ICONS'),
              'FIELD_EMOJI': assign('FIELD_EMOJI'), '_localized_template_labels': lambda *a: {},
              '_lxc_update_label_icons': lambda *a: {}}
        enrich = extract(SCRIPTS / 'notification_templates.py', 'enrich_with_emojis', namespace=ns)
        for state, icon in [('confirmed', '💾✅'), ('unconfirmed', '💾❔'), ('failed', '💾❌')]:
            with self.subTest(state=state):
                title, body = enrich('backup_complete', 'node-a: Backup', 'Backup report',
                    {'backup_outcome': state, '_notification_language': 'en'})
                self.assertTrue(title.startswith(icon), title)

    def test_uncertain_outcomes_have_no_blanket_success_icon(self):
        tree = ast.parse((SCRIPTS / 'notification_templates.py').read_text())
        icon_map = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == 'EVENT_EMOJI' for t in n.targets)))
        for event in ('error_resolved', 'system_restore_completed'):
            self.assertNotIn('✅', icon_map[event], event)
        self.assertNotIn('✅', icon_map['backup_complete'])  # buffered digest has no outcome metadata


if __name__ == '__main__': unittest.main()
