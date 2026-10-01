"""Durable native observation order, not wall-clock row identity, admits proof."""
import datetime
import json
import re
import sys
import types
import typing
import unittest
from unittest.mock import patch
from notification_recovery_fixture import case, Clock, BASE, cpu, service, sql, extract, scripts, TIME
from notification_fixture import LANGUAGES
from notification_final_fixture import deliver


def collector(store):
    events = []
    target = types.SimpleNamespace(_hostname='alias {rack.location}',
        _ENTITY_MAP={'cpu':('node',''), 'pve_services':('node','')}, _first_poll_done=False,
        _known_errors={}, _notified_severity={}, _last_notified={}, SAME_ERROR_COOLDOWN=86400,
        _get_cooldown_from_db=lambda *a:BASE-1, _queue=types.SimpleNamespace(put=events.append),
        _save_known_errors_meta=lambda:None)
    ns = dict(vars(typing), time=TIME, json=json, re=re,
        NotificationEvent=lambda *a, **kw:types.SimpleNamespace(event_type=a[0], severity=a[1], data=a[2], **kw),
        startup_grace=types.SimpleNamespace(should_suppress_category=lambda *a:False))
    target._guest_storage_error_is_now_foreign = extract(scripts/'notification_events.py',
        '_guest_storage_error_is_now_foreign', 'PollingCollector', ns)
    poll = extract(scripts/'notification_events.py', '_check_persistent_health', 'PollingCollector', ns)
    def tick():
        with patch.dict(sys.modules, {'health_persistence':types.SimpleNamespace(health_persistence=store),
                'datetime':types.SimpleNamespace(**{**vars(datetime), 'datetime':Clock})}):
            poll(target)
    return target, events, tick


def abnormal(store, kind, value=99):
    if kind == 'cpu':
        return cpu(store, value, [{'value':value, 'time':Clock.epoch-i*5} for i in range(1,26)])
    return service(store,3,'inactive\n')[0]


def normal(store, kind):
    return cpu(store) if kind == 'cpu' else service(store)[0]


def initial_closure(store, kind):
    key = 'cpu_usage' if kind == 'cpu' else 'pve_service_pvedaemon'
    Clock.epoch = BASE-600
    abnormal(store,kind,90)
    target, events, tick = collector(store)
    tick()
    assert target._first_poll_done and key in target._known_errors and not events
    snapshot = json.loads(json.dumps(target._known_errors))
    Clock.epoch = BASE
    assert normal(store,kind)['status'] == 'OK'
    first = snapshot[key]['first_seen']
    assert store.get_recovery_evidence(key,first)
    return key, first, snapshot, target, events, tick


class RecoveryOrderTests(unittest.TestCase):
    def assert_consumers(self, data, expected):
        with patch('health_recovery.time.time', return_value=Clock.epoch):
            for language in LANGUAGES:
                for manual in (False,True):
                    with self.subTest(language=language, manual=manual):
                        result = deliver('error_resolved',data,'OK',language,manual=manual)
                        self.assertEqual('background:#f0fdf4;' in result['html'],expected)
                        self.assertIn('alias {rack.location}',result['text'])
                quiet = deliver('error_resolved',data,'OK',language,quiet=True)
                self.assertEqual(len(quiet['buffered']),1)
                # The existing quiet digest stores the rendered title, not
                # health body/proof metadata. Assert its exact outcome label.
                from notification_fixture import templates
                label = templates.render_template('error_resolved',data,language)['title'].split(': ',1)[-1]
                self.assertIn(label, quiet['body'])
                self.assertIn(label, quiet['buffered'][0][2])

    def assert_superseded(self, kind):
        for offset in (-100,0,1):
            for value in ((90,99) if kind == 'cpu' else (99,)):
                with self.subTest(kind=kind, offset=offset, value=value), case() as store:
                    key, first, snapshot, target, events, tick = initial_closure(store,kind)
                    oldrow = sql(store,'SELECT id,first_seen,resolved_at FROM errors')[0]
                    prior = sql(store,'SELECT id,event_type FROM events ORDER BY id')
                    Clock.epoch = BASE+offset
                    renewed = abnormal(store,kind,value)
                    self.assertEqual(renewed['status'],'WARNING' if kind == 'cpu' and value == 90 else 'CRITICAL')
                    self.assertEqual(sql(store,'SELECT id,first_seen,resolved_at FROM errors')[0],oldrow)
                    later = sql(store,'SELECT id,event_type FROM events ORDER BY id')[-1]
                    self.assertGreater(later[0],prior[-1][0])
                    self.assertEqual(later[1],'escalated' if kind == 'cpu' and value == 99 else 'updated')
                    if kind == 'cpu':
                        policy=json.loads(sql(store,'SELECT details FROM errors')[0][0])['cpu_policy']
                        self.assertEqual(policy,{'warning':85,'critical':95,'recovery':75})
                    Clock.epoch = BASE+2
                    tick()
                    self.assertEqual(len(events),1)
                    data = events[0].data
                    self.assertFalse(data['is_recovery'])
                    self.assertIsNone(store.get_recovery_evidence(key,first))
                    self.assert_consumers(data,False)
                    # Existing operations do not rearm the resolved row, so a
                    # later normal check cannot establish a NEW native closure.
                    before = sql(store,'SELECT id FROM events ORDER BY id')
                    Clock.epoch = BASE+3
                    self.assertEqual(normal(store,kind)['status'],'OK')
                    self.assertEqual(sql(store,'SELECT id FROM events ORDER BY id'),before)
                    self.assertIsNone(store.get_recovery_evidence(key,first))

    def test_cpu_superseded_same_row_is_neutral_at_all_consumers(self):
        self.assert_superseded('cpu')

    def test_service_superseded_same_row_is_neutral_at_all_consumers(self):
        self.assert_superseded('service')

    def test_fresh_closure_and_repeated_noop_clear_keep_genuine_proof(self):
        for kind in ('cpu','service'):
            with self.subTest(kind=kind),case() as store:
                key, first, snapshot, target, events, tick = initial_closure(store,kind)
                before = sql(store,'SELECT id,event_type FROM events ORDER BY id')
                Clock.epoch = BASE+1
                for _ in range(3):
                    store.clear_error(key)
                    store.resolve_error(key,'generic repeat')
                    normal(store,kind)
                self.assertEqual(sql(store,'SELECT id,event_type FROM events ORDER BY id'),before)
                self.assertTrue(store.get_recovery_evidence(key,first))
                tick()
                self.assertEqual(len(events),1)
                self.assertTrue(events[0].data['is_recovery'])
                self.assert_consumers(events[0].data,True)
                tick()
                self.assertEqual(len(events),1)

    def test_later_actual_generic_closure_blocks_older_proof_even_clock_rollback(self):
        for kind in ('cpu','service'):
            with self.subTest(kind=kind),case() as store:
                key, first, *_ = initial_closure(store,kind)
                Clock.epoch = BASE-100
                with store._db_connection() as conn:
                    store._record_event(conn.cursor(),'cleared',key,{'reason':'generic actual closure','check_evidence':None})
                    conn.commit()
                self.assertIsNone(store.get_recovery_evidence(key,first))

    def test_explicit_acknowledged_row_suppresses_native_proof(self):
        for kind in ('cpu','service'):
            with self.subTest(kind=kind),case() as store:
                key, first, snapshot, target, events, tick = initial_closure(store,kind)
                store.acknowledge_error(key,suppression_hours=-1)
                self.assertEqual(sql(store,'SELECT acknowledged FROM errors')[0][0],1)
                self.assertIsNone(store.get_recovery_evidence(key,first))
                tick()
                self.assertEqual(events,[])

    def test_new_incarnation_abnormal_order_blocks_previous_closure(self):
        for kind in ('cpu','service'):
            with self.subTest(kind=kind),case() as store:
                key, first, *_ = initial_closure(store,kind)
                old_id = sql(store,'SELECT id FROM errors')[0][0]
                store.acknowledge_error(key,suppression_hours=-1)
                store.clear_error(key)
                Clock.epoch = BASE-100
                abnormal(store,kind,99)
                self.assertGreater(sql(store,'SELECT id FROM errors')[0][0],old_id)
                self.assertEqual(sql(store,'SELECT event_type FROM events ORDER BY id DESC')[0][0],'new')
                self.assertIsNone(store.get_recovery_evidence(key,first))


if __name__ == '__main__':
    unittest.main()
