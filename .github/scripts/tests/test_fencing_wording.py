"""Inert fencing wording contract: execute extracted producers and template renderer."""
import ast
import json
import re
import time
import unittest
from typing import Any
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVENTS = ROOT / 'AppImage/scripts/notification_events.py'
TEMPLATES = ROOT / 'AppImage/scripts/notification_templates.py'
MESSAGES = ROOT / 'AppImage/messages'
FIELDS = ('title', 'body', 'label')


def extract_method(path, owner, method, namespace):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner)
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method)
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[method]


def notification_renderer(catalogs):
    tree = ast.parse(TEMPLATES.read_text(encoding='utf-8'))
    templates = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
                                      and any(isinstance(t, ast.Name) and t.id == 'TEMPLATES' for t in n.targets)))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'render_template')

    def lookup(obj, dotted):
        for part in dotted.split('.'):
            obj = obj.get(part) if isinstance(obj, dict) else None
        return obj

    namespace = {'TEMPLATES': templates, 'Dict': dict, 'Any': object,
                 '_get_hostname': lambda: 'node-a',
                 '_load_runtime_catalog': lambda lang: catalogs[lang]['runtime']['notifications'],
                 '_catalog_value': lookup, 'runtime_message': lambda key, lang, **kw: key,
                 'time': time, 're': re}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(TEMPLATES), 'exec'), namespace)
    return templates, namespace['render_template']


class FencingWordingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogs = {p.parent.name: json.loads(p.read_text(encoding='utf-8'))
                        for p in MESSAGES.glob('*/common.json')}
        cls.templates, render = notification_renderer(cls.catalogs)
        cls.render = staticmethod(render)

    def test_webhook_fencing_renders_without_split_brain_or_quorum_diagnosis(self):
        namespace: dict[str, Any] = {'re': re}
        classify = extract_method(EVENTS, 'ProxmoxHookWatcher', '_classify_pve', namespace)
        severity = extract_method(EVENTS, 'ProxmoxHookWatcher', '_map_severity', namespace)
        namespace['capture_journal_context'] = lambda **kw: ''
        class Event:
            def __init__(self, **kw):
                self.__dict__.update(kw)
                self.event_id = 'inert-id'
        class Queue:
            def __init__(self): self.items = []
            def put(self, item): self.items.append(item)
        namespace['NotificationEvent'] = Event
        webhook = extract_method(EVENTS, 'ProxmoxHookWatcher', 'process_webhook', namespace)
        class Receiver:
            _hostname = 'node-a'
            _classify_pve = classify
            _map_severity = staticmethod(severity)
            def __init__(self): self._queue = Queue()
        receiver = Receiver()
        for fields in ({'type': 'fencing'}, {'type': 'fencing', 'quorum': 'lost'}):
            result = webhook(receiver, {'fields': fields, 'severity': 'warning',
                                        'title': 'Fence requested', 'message': 'Check node state'})
            self.assertEqual(result['event_type'], 'split_brain')
            event = receiver._queue.items.pop()
            self.assertEqual(event.severity, 'WARNING')
            self.assertNotIn('quorum', event.data)
            for lang, catalog in self.catalogs.items():
                rendered = self.render(event.event_type, event.data, lang)
                expected = catalog['runtime']['notifications']['templates']['split_brain']
                self.assertEqual(rendered['title'], expected['title'].format(hostname='node-a'), lang)
                self.assertEqual(rendered['body'], expected['body'], lang)
                self.assertNotIn('split-brain', '\n'.join((rendered['title'], rendered['body'])).lower(), lang)
                self.assertNotIn('quorum', rendered['body'].lower(), lang)
        self.assertEqual(webhook(receiver, {'type': 'fencing', 'severity': 'warning',
                                            'title': 'Unclassified', 'message': 'Other'})['event_type'], 'system_problem')
        self.assertEqual(self.templates['split_brain']['group'], 'cluster')
        self.assertIs(self.templates['split_brain']['default_enabled'], True)

    def test_journal_family_uses_same_truthful_wording(self):
        tree = ast.parse(EVENTS.read_text(encoding='utf-8'))
        owner = next(n.name for n in tree.body if isinstance(n, ast.ClassDef)
                     and any(isinstance(m, ast.FunctionDef) and m.name == '_check_cluster_events' for m in n.body))
        namespace: dict[str, Any] = {'re': re}
        method = extract_method(EVENTS, owner, '_check_cluster_events', namespace)
        class Journal:
            _hostname = 'node-a'
            def __init__(self): self.events = []
            def _emit(self, *args, **kwargs): self.events.append((args, kwargs))
        for message in ('fencing required for node', 'cluster partition suspected', 'split-brain reported'):
            journal = Journal()
            method(journal, message, 'syslog')
            args, _ = journal.events[0]
            self.assertEqual(args[0], 'split_brain')
            for lang, catalog in self.catalogs.items():
                rendered = self.render(args[0], args[2], lang)
                self.assertEqual(rendered['body'], catalog['runtime']['notifications']['templates']['split_brain']['body'], lang)
        journal = Journal()
        method(journal, 'quorum lost', 'syslog')
        self.assertEqual(journal.events[0][0][0], 'node_disconnect')

    def test_english_family_and_settings_label_align_without_changing_key(self):
        en = self.catalogs['en']
        self.assertEqual(self.templates['split_brain']['label'], 'Cluster event')
        self.assertEqual(en['runtime']['notifications']['templates']['split_brain']['label'], 'Cluster event')
        self.assertEqual(en['settings']['notifications']['eventTypes']['split_brain'], 'Cluster events')
        settings = (ROOT / 'AppImage/components/notification-settings.tsx').read_text(encoding='utf-8')
        self.assertIn('settings.notifications.eventTypes.${evt.type}', settings)
        self.assertIn('evt.title : translated', settings)
        for field in FIELDS:
            self.assertEqual(en['runtime']['notifications']['templates']['split_brain'][field],
                             self.templates['split_brain'][field])

    def test_every_shipped_locale_renders_cluster_event_without_diagnosis(self):
        expected = {
            'de': ('{hostname}: Clusterereignis gemeldet', 'Ein Clusterereignis wurde gemeldet. Prüfen Sie den Clusterstatus und das ursprüngliche Ereignis für weitere Informationen.', 'Clusterereignis', 'Clusterereignisse'),
            'es': ('{hostname}: evento del clúster notificado', 'Se ha notificado un evento del clúster. Consulta el estado del clúster y el evento original para obtener más detalles.', 'Evento del clúster', 'Eventos del clúster'),
            'fr': ('{hostname}\u00a0: événement du cluster signalé', 'Un événement du cluster a été signalé. Vérifiez l’état du cluster et l’événement d’origine pour plus de détails.', 'Événement du cluster', 'Événements du cluster'),
            'it': ('{hostname}: evento del cluster segnalato', "È stato segnalato un evento del cluster. Controlla lo stato del cluster e l'evento originale per maggiori dettagli.", 'Evento del cluster', 'Eventi del cluster'),
            'pt': ('{hostname}: evento do cluster comunicado', 'Foi comunicado um evento do cluster. Verifique o estado do cluster e o evento original para obter mais detalhes.', 'Evento do cluster', 'Eventos do cluster'),
            'sk': ('{hostname}: hlásená udalosť klastra', 'Bola hlásená udalosť klastra. Skontrolujte stav klastra a pôvodnú udalosť, kde nájdete ďalšie podrobnosti.', 'Udalosť klastra', 'Udalosti klastra'),
            'sv': ('{hostname}: klusterhändelse rapporterad', 'En klusterhändelse har rapporterats. Kontrollera klusterstatus och den ursprungliga händelsen för mer information.', 'Klusterhändelse', 'Klusterhändelser'),
        }
        self.assertEqual(set(self.catalogs), {'en', *expected})
        for lang, (title, body, label, settings) in expected.items():
            with self.subTest(lang=lang):
                leaves = self.catalogs[lang]['runtime']['notifications']['templates']['split_brain']
                self.assertEqual((leaves['title'], leaves['body'], leaves['label'],
                                  self.catalogs[lang]['settings']['notifications']['eventTypes']['split_brain']),
                                 (title, body, label, settings))
                result = self.render('split_brain', {}, lang)
                self.assertEqual(result['title'], title.format(hostname='node-a'))
                self.assertEqual(result['body'], body)
                self.assertNotIn('quorum', result['body'].lower())

    def test_fallback_and_translated_lookup_are_real_for_missing_and_synthetic_values(self):
        import copy
        catalogs = copy.deepcopy(self.catalogs)
        for field in FIELDS:
            catalogs['it']['runtime']['notifications']['templates']['split_brain'].pop(field)
        _, render = notification_renderer(catalogs)
        self.assertEqual(render('split_brain', {}, 'it')['body'],
                         'A cluster event was reported. Review cluster status and the source event for details.')
        catalogs['it']['runtime']['notifications']['templates']['split_brain']['body'] = 'Evento del cluster segnalato.'
        _, render = notification_renderer(catalogs)
        self.assertEqual(render('split_brain', {}, 'it')['body'], 'Evento del cluster segnalato.')
        for lang, catalog in self.catalogs.items():
            if lang == 'en': continue
            leaves = catalog['runtime']['notifications']['templates']['split_brain']
            self.assertTrue(all(leaves[field] for field in FIELDS), lang)
            self.assertTrue(catalog['settings']['notifications']['eventTypes']['split_brain'], lang)
            self.assertNotEqual(leaves['body'], self.catalogs['en']['runtime']['notifications']['templates']['split_brain']['body'], lang)


if __name__ == '__main__':
    unittest.main()
