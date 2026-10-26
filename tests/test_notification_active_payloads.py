"""Inert actual-function tests for active notification payloads; no app imports."""
import ast
import copy
import html
import json
import math
import re
import sys
import time
import types
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'AppImage/scripts'
MESSAGES = ROOT / 'AppImage/messages'


def extracted(path, name, cls=None, namespace=None):
    tree = ast.parse((SCRIPTS / path).read_text())
    nodes = tree.body
    if cls:
        nodes = next(n for n in nodes if isinstance(n, ast.ClassDef) and n.name == cls).body
    node = next(n for n in nodes if isinstance(n, ast.FunctionDef) and n.name == name)
    # Never execute module code or decorators; no operational module imports.
    node = copy.deepcopy(node)
    node.decorator_list = []
    scope = namespace if namespace is not None else {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 '<extracted ' + name + '>', 'exec'), scope)
    return scope[name]


def render_fixture(language='en', overlays=None, missing=(), translations=None):
    catalogs = {lang: json.loads((MESSAGES / lang / 'common.json').read_text())['runtime']['notifications']
                for lang in ('en', 'de', 'es', 'fr', 'it', 'pt', 'sk', 'sv')}
    if language == 'synthetic':
        catalogs[language] = {'templates': {'temp_high': {
            'title': 'Synthetic {value}°C', 'body': 'Synthetic {threshold}°C\n{details}'}}}
    if translations:
        catalogs[language].update(translations)
    for key in missing:
        section, leaf = key.split('.', 1)
        catalogs[language].get(section, {}).pop(leaf, None)
    if overlays:
        for lang, title, body in overlays:
            catalogs[lang]['templates']['temp_high'].update(title=title, body=body)
    def lookup(lang, key):
        value = catalogs.get(lang, {})
        for segment in key.split('.'):
            value = value.get(segment) if isinstance(value, dict) else None
        return value if isinstance(value, str) and value else None

    src = ast.parse((SCRIPTS / 'notification_templates.py').read_text())
    definition = next(n for n in src.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'TEMPLATES' for t in n.targets))
    templates = ast.literal_eval(definition.value)
    cpu_pattern = next(n for n in src.body if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == '_CPU_SUSTAINED_REASON'
                               for t in n.targets))
    assert isinstance(cpu_pattern.value, ast.Call)
    assert isinstance(cpu_pattern.value.func, ast.Attribute) and cpu_pattern.value.func.attr == 'compile'
    assert len(cpu_pattern.value.args) == 1
    scope = {'TEMPLATES': templates, '_load_runtime_catalog': lambda lang: catalogs.get(lang, {}),
             '_get_hostname': lambda: 'node.example',
             'time': time, 'html': html, 're': re, 'Dict': dict, 'Any': object,
             'Optional': __import__('typing').Optional, 'Tuple': tuple,
             '_CPU_SUSTAINED_REASON': re.compile(ast.literal_eval(cpu_pattern.value.args[0]))}
    safe_dict = next(n for n in src.body if isinstance(n, ast.ClassDef) and n.name == '_SafeFormatDict')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[safe_dict], type_ignores=[])),
                 '<safe formatting>', 'exec'), scope)
    extracted('notification_templates.py', '_catalog_value', namespace=scope)
    extracted('notification_templates.py', 'runtime_message', namespace=scope)
    extracted('notification_templates.py', '_format_health_degraded', namespace=scope)
    render = extracted('notification_templates.py', 'render_template', namespace=scope)
    return lambda kind, data: render(kind, data, language=language)


def temperature_case(history, reading=89., active=False):
    class Persistence:
        emitted = []
        resolved = []
        def record_error(self, **kw): self.emitted.append(kw)
        def is_error_active(self, *a, **kw): return active
        def resolve_error(self, *a, **kw): self.resolved.append((a, kw))
    db = Persistence()
    env = {'time': types.SimpleNamespace(time=lambda: 100000),
           'subprocess': types.SimpleNamespace(run=lambda *a, **kw: types.SimpleNamespace(
               returncode=0, stdout=f'temp1_input: {reading:.3f}\ntemp2_input: 45.000\n')),
           'health_persistence': db, 'Optional': __import__('typing').Optional,
           'Dict': dict, 'Any': object}
    check = extracted('health_monitor.py', '_check_cpu_temperature', 'HealthMonitor', env)
    monitor = types.SimpleNamespace(last_check_times={}, cached_results={}, state_history=defaultdict(list))
    monitor.state_history['cpu_temp_history'] = list(history)
    result = check(monitor)
    return result, db


def produced_temperature():
    result, db = temperature_case([
        {'value': 89., 'time': 99900 + n * 5} for n in range(17)])
    assert result['status'] == 'WARNING' and len(db.emitted) == 1
    return db.emitted[0]


def polled_event(entry):
    raw_row = {'error_key': entry['error_key'], 'category': entry['category'],
               'severity': entry['severity'], 'reason': entry['reason'],
               'details': json.dumps(entry['details']), 'last_seen': '',
               'first_seen': '', 'acknowledged': 0}
    class Cursor:
        def execute(self, *a): pass
        def fetchall(self): return [raw_row]
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return Cursor()
    typing = __import__('typing')
    get_active = extracted('health_persistence.py', 'get_active_errors', 'HealthPersistence',
        {'json': json, 'Optional': typing.Optional, 'List': typing.List,
         'Dict': typing.Dict, 'Any': typing.Any})
    persisted = get_active(types.SimpleNamespace(_db_connection=lambda **kw: Connection()))
    assert len(persisted) == 1 and persisted[0]['details'] == entry['details']
    class Persistence:
        def get_active_errors(self): return persisted
    class Event:
        def __init__(self, event_type, severity, data, **kw):
            self.event_type, self.severity, self.data = event_type, severity, data
    q = types.SimpleNamespace(items=[], put=lambda event: q.items.append(event))
    tree = ast.parse((SCRIPTS / 'notification_events.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PollingCollector')
    maps = {target.id: ast.literal_eval(n.value) for n in cls.body if isinstance(n, ast.Assign)
            for target in n.targets if isinstance(target, ast.Name) and target.id in
            ('_CATEGORY_TO_EVENT_TYPE', '_ENTITY_MAP', '_CATEGORY_COOLDOWNS')}
    collector = types.SimpleNamespace(_CATEGORY_TO_EVENT_TYPE=maps['_CATEGORY_TO_EVENT_TYPE'],
        _ENTITY_MAP=maps['_ENTITY_MAP'], _CATEGORY_COOLDOWNS=maps['_CATEGORY_COOLDOWNS'],
        DIGEST_INTERVAL=86400, SAME_ERROR_COOLDOWN=86400, _queue=q, _hostname='node.example',
        _first_poll_done=True, _known_errors={}, _last_notified={}, _notified_severity={},
        _is_usb_cache={}, _get_cooldown_from_db=lambda _: None,
        _persist_last_notified=lambda *a: None, _save_known_errors_meta=lambda: None)
    old = sys.modules.get('health_persistence')
    sys.modules['health_persistence'] = types.SimpleNamespace(health_persistence=Persistence())
    try:
        poll = extracted('notification_events.py', '_check_persistent_health', 'PollingCollector',
            {'time': types.SimpleNamespace(time=lambda: 100000), 'json': json,
             'startup_grace': types.SimpleNamespace(should_suppress_category=lambda _: False),
             'NotificationEvent': Event, 'Dict': dict})
        poll(collector)
    finally:
        if old is None: sys.modules.pop('health_persistence', None)
        else: sys.modules['health_persistence'] = old
    assert len(q.items) == 1
    return q.items[0]


class ActivePayloadTests(unittest.TestCase):
    def test_temperature_sampling_boundaries_and_recovery_policy(self):
        # These characterize the existing threshold/guard, not new policy.
        highs = [{'value': 89., 'time': 99900 + n * 5} for n in range(17)]
        below, db = temperature_case(highs[:-1])  # current sample makes 17
        self.assertEqual(below['status'], 'OK')
        self.assertEqual((db.emitted, db.resolved), ([], []))
        warning, db = temperature_case(highs)  # current sample makes 18
        self.assertEqual(warning['status'], 'WARNING')
        self.assertEqual(len(db.emitted), 1)
        self.assertEqual(db.emitted[0]['details']['duration'], 100)
        self.assertEqual((db.emitted[0]['category'], db.emitted[0]['severity'],
                          db.emitted[0]['details']['dismissable']), ('temperature', 'WARNING', True))
        low = [{'value': 79., 'time': t} for t in (99980, 99990)]
        pending, db = temperature_case(low[:1], reading=79., active=True)
        self.assertEqual(pending['status'], 'WARNING')
        self.assertEqual((db.emitted, db.resolved), ([], []))
        recovered, db = temperature_case(low, reading=79., active=True)
        self.assertEqual(recovered['status'], 'OK')
        self.assertEqual(db.emitted, [])
        self.assertEqual(db.resolved[0][0][0], 'cpu_temperature')

    def test_temperature_record_queue_and_english_render_use_measured_sensor(self):
        record = produced_temperature()
        self.assertIn('sensor', record['reason'].lower())
        self.assertEqual(record['details']['temperature'], 89.)
        self.assertTrue(record['details']['dismissable'])
        event = polled_event(record)
        self.assertEqual((event.event_type, event.severity), ('temp_high', 'WARNING'))
        self.assertEqual(event.data['value'], 89.)
        self.assertEqual(event.data['threshold'], 80)
        self.assertEqual(event.data['duration'], record['details']['duration'])
        self.assertIn('High samples span', event.data['details'])
        rendered = render_fixture()('temp_high', event.data)
        self.assertIn('sensor temperature', rendered['title'].lower())
        self.assertIn('89', rendered['title'])
        self.assertIn('80', rendered['body'])
        self.assertNotIn('CPU', rendered['title'] + rendered['body'])

    def test_missing_temperature_measurement_never_renders_blank_celsius_claim(self):
        event = polled_event({'error_key': 'cpu_temperature', 'category': 'temperature',
                              'severity': 'WARNING', 'reason': 'legacy raw reason',
                              'details': {'duration': 90}})
        for lang in ('en', 'de', 'es', 'fr', 'it', 'pt', 'sk', 'sv'):
            out = render_fixture(lang)('temp_high', event.data)
            self.assertNotIn('°C', out['title'] + out['body'])
            self.assertNotIn('CPU', out['title'] + out['body'])
            expected = json.loads((MESSAGES / lang / 'common.json').read_text())['runtime']['notifications']['fallback']['temperatureAlertTitle']
            self.assertIn(expected.replace('{hostname}', 'node.example'), out['title'])

    def test_nonfinite_temperature_payload_is_not_presented_as_a_reading(self):
        render = render_fixture()
        for value, threshold in ((math.nan, 80), (math.inf, 80), (89, math.inf),
                                 (True, 80), (10**400, 80), (89, 10**400)):
            with self.subTest(value=value, threshold=threshold):
                out = render('temp_high', {'value': value, 'threshold': threshold})
                self.assertNotIn('°C', out['title'] + out['body'])

    def test_numeric_strings_from_manual_payloads_retain_finite_readings(self):
        out = render_fixture()('temp_high', {'value': '89.0', 'threshold': '80'})
        self.assertIn('89.0°C', out['title'])
        self.assertIn('80°C', out['body'])
        for bad in ('', 'NaN', 'Infinity', '1e999', 'eighty', '  ', object()):
            with self.subTest(value=repr(bad)):
                out = render_fixture()('temp_high', {'value': bad, 'threshold': '80'})
                self.assertNotIn('°C', out['title'] + out['body'])

    def test_incomplete_measurement_preserves_recorded_context_once(self):
        render = render_fixture()
        for data, fragments in (
            ({'reason': 'CPU temperature 89°C >80°C sustained for 2m'},
             ('Recorded reason: CPU temperature 89°C >80°C sustained for 2m',)),
            ({'value': 89, 'details': 'High samples span 2m.'},
             ('Recorded details: High samples span 2m.',)),
            ({'value': 89, 'reason': 'old raw text', 'details': 'old raw text'},
             ('Recorded reason: old raw text',)),
        ):
            with self.subTest(data=data):
                out = render('temp_high', data)
                self.assertNotIn('°C', out['title'] + out['body'].split('\n')[0])
                self.assertIn('without a complete measurement', out['body'])
                for fragment in fragments:
                    self.assertIn(fragment, out['body'])
                if data.get('reason') == data.get('details'):
                    self.assertEqual(out['body'].count('old raw text'), 1)
        self.assertNotIn('Recorded', render('temp_high', {})['body'])

    def test_incomplete_title_keeps_raw_brace_bearing_hostname_in_every_locale(self):
        for lang in ('en', 'de', 'es', 'fr', 'it', 'pt', 'sk', 'sv'):
            fallback = json.loads((MESSAGES / lang / 'common.json').read_text())['runtime']['notifications']['fallback']['temperatureAlertTitle']
            for hostname in ('host{value}', 'host{value.__class__}'):
                with self.subTest(lang=lang, hostname=hostname):
                    out = render_fixture(lang)('temp_high', {'hostname': hostname})
                    self.assertEqual(out['title'], fallback.replace('{hostname}', hostname))
                    self.assertNotIn('°C', out['title'])

    def test_incomplete_measurement_keeps_literal_braces_in_raw_context(self):
        out = render_fixture()('temp_high', {
            'reason': 'legacy {value} at {unknown}', 'details': 'sensor {threshold}',
        })
        self.assertIn('Recorded reason: legacy {value} at {unknown}', out['body'])
        self.assertIn('Recorded details: sensor {threshold}', out['body'])

    def test_shipped_locales_use_sensor_wording_and_localized_sample_span(self):
        event = polled_event(produced_temperature())
        for lang in ('en', 'de', 'es', 'fr', 'it', 'pt', 'sk', 'sv'):
            with self.subTest(lang=lang):
                out = render_fixture(lang)('temp_high', event.data)
                self.assertNotIn('CPU', out['title'] + out['body'])
                self.assertNotIn('High samples span', out['body'] if lang != 'en' else '')
                self.assertIn('89', out['title'])
                self.assertIn('80', out['body'])
                expected = json.loads((MESSAGES / lang / 'common.json').read_text())['runtime']['notifications']['temperature']['sampleSpan'].replace('{duration}', '1m 40s')
                self.assertIn(expected, out['body'])

    def test_structured_span_does_not_replace_unrelated_or_unmarked_details(self):
        producer = polled_event(produced_temperature()).data
        for changed in ({'temperature_detail_kind': None}, {'details': 'Manual {duration} remains'},
                        {'duration': 'Infinity'}, {'duration': 10**400}, {'duration': -1},
                        {'duration': True}, {'duration': 1.5}):
            with self.subTest(changed=changed):
                data = {**producer, **changed}
                out = render_fixture('it')('temp_high', data)
                self.assertIn(data['details'], out['body'])
        raw = render_fixture('it')('temp_high', {'value': 89, 'threshold': 80,
            'duration': 100, 'details': 'Manual {duration} remains'})
        self.assertIn('Manual {duration} remains', raw['body'])

    def test_synthetic_locale_and_missing_key_fallback_for_every_temperature_key(self):
        keys = ('fallback.temperatureAlertTitle', 'fallback.temperatureAlertBody',
                'fallback.recordedReason', 'fallback.recordedDetails', 'temperature.sampleSpan')
        producer = polled_event(produced_temperature()).data
        synthetic = render_fixture('synthetic')
        for key in keys:
            with self.subTest(key=key):
                data = producer if key.endswith('sampleSpan') else {'reason': 'raw R', 'details': 'raw D'}
                output = synthetic('temp_high', data)
                english = render_fixture('en')('temp_high', data)
                if key.endswith('sampleSpan'):
                    self.assertIn('High samples span 1m 40s.', output['body'])
                else:
                    self.assertEqual(output['body'] if not key.endswith('Title') else output['title'],
                                     english['body'] if not key.endswith('Title') else english['title'])
        for key in keys:
            # Exercise actual fallback per missing key even after catalog migration.
            with self.subTest(missing=key):
                if key.endswith('sampleSpan'):
                    self.assertIn('High samples span 1m 40s.',
                        render_fixture('it', missing=[key])('temp_high', producer)['body'])
                else:
                    data = {'reason': 'raw R', 'details': 'raw D'}
                    result = render_fixture('it', missing=[key])('temp_high', data)
                    en_value = json.loads((MESSAGES / 'en' / 'common.json').read_text())['runtime']['notifications']
                    self.assertIn(en_value['fallback'][key.split('.')[1]].format(
                        hostname='node.example', reason='raw R', details='raw D'),
                        result['title'] if key.endswith('Title') else result['body'])
        # A synthetic translated value proves the runtime consumer uses lookup.
        translated = render_fixture('synthetic', overlays=[('synthetic', 'Translated {value}°C',
            'Translated {threshold}°C\n{details}')])('temp_high', producer)
        self.assertIn('Translated', translated['title'])
        custom = render_fixture('synthetic', translations={
            'fallback': {'temperatureAlertTitle': 'CUSTOM {hostname}',
                         'temperatureAlertBody': 'CUSTOM incomplete.',
                         'recordedReason': 'CUSTOM R {reason}',
                         'recordedDetails': 'CUSTOM D {details}'},
            'temperature': {'sampleSpan': 'CUSTOM span {duration}.'},
        })
        complete = custom('temp_high', producer)
        self.assertIn('CUSTOM span 1m 40s.', complete['body'])
        incomplete = custom('temp_high', {'reason': 'raw R', 'details': 'raw D'})
        self.assertIn('CUSTOM node.example', incomplete['title'])
        for fragment in ('CUSTOM incomplete.', 'CUSTOM R raw R', 'CUSTOM D raw D'):
            self.assertIn(fragment, incomplete['body'])

    def test_email_contains_complete_and_incomplete_localized_temperature_body(self):
        # The actual channel formats structured fields; the temperature body
        # must not disappear merely because those rows exist.
        import importlib.util
        spec = importlib.util.spec_from_file_location('notification_channels_fixture',
                                                     SCRIPTS / 'notification_channels.py')
        channels = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(channels)
        old = sys.path[:]
        sys.path.insert(0, str(SCRIPTS))
        try:
            channel = object.__new__(channels.EmailChannel)
            channel.subject_prefix = '[ProxMenux]'
            produced = polled_event(produced_temperature()).data
            for lang in ('en', 'de', 'es', 'fr', 'it', 'pt', 'sk', 'sv'):
                for name, data in (('complete', produced), ('incomplete', {
                    'hostname': 'node.example', 'reason': 'legacy {token}',
                    'details': 'raw {details}', 'value': 89,
                })):
                    with self.subTest(lang=lang, name=name):
                        rendered = render_fixture(lang)('temp_high', data)
                        message = channel._format_html(rendered['title'], rendered['body'],
                            'WARNING', {**data, '_notification_language': lang,
                                        '_event_type': 'temp_high', '_group': rendered['group']})
                        # HTML escaping may replace apostrophes/angle brackets.
                        for line in rendered['body'].splitlines():
                            if ':' in line and len(line.partition(':')[0]) < 40:
                                label, _, value = line.partition(':')
                                self.assertIn(html.escape(label.strip()), message)
                                self.assertIn(html.escape(value.strip()), message)
                            else:
                                self.assertIn(html.escape(line), message)
                        if name == 'incomplete':
                            self.assertNotIn('89C', message)
        finally:
            sys.path[:] = old

    def test_long_reason_email_once_if_temperature_body_already_contains_it(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('notification_channels_fixture',
                                                     SCRIPTS / 'notification_channels.py')
        channels = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(channels)
        old = sys.path[:]
        sys.path.insert(0, str(SCRIPTS))
        try:
            channel = object.__new__(channels.EmailChannel)
            channel.subject_prefix = '[ProxMenux]'
            reason = 'Recorded observation ' + 'R' * 90 + ' <i> & {value}'
            escaped = html.escape(reason)
            for lang in ('en', 'de', 'es', 'fr', 'it', 'pt', 'sk', 'sv'):
                render = render_fixture(lang)
                for kind, fields in (('incomplete', {'details': 'raw {details}'}),
                                     ('complete', {'value': 89, 'threshold': 80})):
                    with self.subTest(lang=lang, kind=kind):
                        data = {'hostname': 'host{value.__class__}', 'reason': reason, **fields}
                        rendered = render('temp_high', data)
                        message = channel._format_html(rendered['title'], rendered['body'],
                            'WARNING', {**data, '_notification_language': lang,
                                        '_event_type': 'temp_high', '_group': rendered['group']})
                        self.assertEqual(message.count(escaped), 1)
                        self.assertNotIn('<i>', message)
                        self.assertIn(html.escape(rendered['title']), message)
                        if kind == 'incomplete':
                            self.assertIn(reason, rendered['body'])
                            self.assertIn('raw {details}', rendered['body'])
                        else:
                            self.assertNotIn(reason, rendered['body'])
                            self.assertIn('89', message)
            # An unrelated event retains its existing long-reason block.
            other = channel._format_html('Other alert', reason, 'WARNING',
                {'reason': reason, '_event_type': 'other', '_group': 'other'})
            self.assertEqual(other.count(escaped), 2)
        finally:
            sys.path[:] = old

    def test_collector_schema_categories_and_cpu_reason_are_localized(self):
        # Execute actual collector-to-formatter path against inert per-cycle inputs.
        class Stop(Exception): pass
        class Clock:
            count = 0
            def time(self): return 1.
            def sleep(self, _):
                self.count += 1
                if self.count > 1: raise Stop
        class Manager:
            _enabled = True
            _config = {}
            events = []
            def is_event_enabled(self, *_): return True
            def emit_event(self, **kw): self.events.append(kw)
        manager = Manager()
        scope = {'notification_manager': manager, 'time': Clock(),
                 'startup_grace': types.SimpleNamespace(should_suppress_category=lambda *_: False),
                 '_capture_health_journal_context': lambda *_: '',
                 'resolve_notification_hostname': lambda name, *_: name,
                 'health_monitor': types.SimpleNamespace(get_detailed_status=lambda: {
                     'hostname': 'node.example', 'details': {'cpu': {'status': 'WARNING',
                         'reason': 'CPU >85% sustained for 300s'}}, 'overall': 'WARNING', 'summary': 'x'},
                     cached_results={}, last_check_times={})}
        # Remove only infrastructure imports from the extracted function.
        tree = ast.parse((SCRIPTS / 'flask_server.py').read_text())
        fn = copy.deepcopy(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_health_collector_loop'))
        for node in ast.walk(fn):
            for field, value in ast.iter_fields(node):
                if isinstance(value, list):
                    setattr(node, field, [child for child in value if not (
                        isinstance(child, ast.ImportFrom) and child.module == 'health_monitor'
                        or isinstance(child, ast.Import) and any(a.name == 'startup_grace' for a in child.names))])
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<collector>', 'exec'), scope)
        with self.assertRaises(Stop): scope['_health_collector_loop']()
        self.assertEqual(len(manager.events), 1)
        payload = manager.events[0]['data']
        item = payload['health_degraded']['categories'][0]
        self.assertEqual(item['cat_key'], 'cpu')
        out = render_fixture('it')('health_degraded', {**payload, 'severity': 'WARNING'})
        self.assertIn('Utilizzo e temperatura CPU', out['title'])
        self.assertEqual(out['body'], 'Utilizzo della CPU oltre 85% per 300 s.')

    def test_legacy_key_and_unknown_reason_remain_honest(self):
        render = render_fixture('it')
        def payload(item):
            return {'hostname': 'node.example', 'health_degraded': {'categories': [item]}}
        legacy = render('health_degraded', payload({'key': 'cpu', 'status': 'WARNING',
                  'reason': 'CPU >85% sustained for 300s'}))
        self.assertIn('Utilizzo e temperatura CPU', legacy['title'])
        self.assertIn('Utilizzo della CPU', legacy['body'])
        raw = render('health_degraded', payload({'cat_key': 'services', 'category': 'PVE Services',
                     'status': 'CRITICAL', 'reason': 'Services inactive: pvedaemon', 'entity': 'pvedaemon'}))
        self.assertIn('Servizi PVE', raw['title'])
        self.assertIn('pvedaemon', raw['title'])
        self.assertEqual(raw['body'], 'Services inactive: pvedaemon')
        unknown = render('health_degraded', payload({'cat_key': 'other', 'category': 'External category',
                         'reason': 'raw unknown', 'status': 'WARNING'}))
        self.assertIn('External category', unknown['title'])
        self.assertEqual(unknown['body'], 'raw unknown')

        conflicting = render('health_degraded', payload({'key': 'memory', 'cat_key': 'cpu',
            'status': 'WARNING', 'reason': 'CPU >85% sustained for 300s'}))
        self.assertIn('Memoria e swap', conflicting['title'])
        self.assertEqual(conflicting['body'], 'CPU >85% sustained for 300s')
        multi = render('health_degraded', {'hostname': 'node.example',
            'health_degraded': {'categories': [
                {'cat_key': 'cpu', 'status': 'WARNING', 'reason': 'CPU >85% sustained for 300s'},
                {'cat_key': 'services', 'status': 'CRITICAL', 'reason': 'Services inactive: pvedaemon'}]}})
        self.assertIn('Utilizzo e temperatura CPU', multi['body'])
        self.assertIn('Servizi PVE', multi['body'])
        self.assertIn('Services inactive: pvedaemon', multi['body'])


if __name__ == '__main__':
    unittest.main()
