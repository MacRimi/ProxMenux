"""Fresh existing-check provenance; native initializer and disposable SQLite."""
import json
import time
import unittest
from unittest.mock import patch
from notification_fixture import templates, LANGUAGES
from notification_final_fixture import deliver
from notification_recovery_fixture import case, Clock, BASE, cpu, sql, poll


def original_cpu(store):
    Clock.epoch = BASE-600
    result = cpu(store, 90, [{'value':90,'time':Clock.epoch-i*5} for i in range(1,26)])
    assert result['status'] == 'WARNING'
    Clock.epoch = BASE
    return sql(store, 'SELECT first_seen FROM errors')[0][0]


class RecoveryEvidenceTests(unittest.TestCase):
    def test_cpu_success_provenance_is_persisted_only_after_normal_samples(self):
        with case() as store:
            first = original_cpu(store)
            self.assertEqual(cpu(store)['status'], 'OK')
            proof = store.get_recovery_evidence('cpu_usage', first)
            self.assertTrue(proof)
            self.assertEqual(proof['check'], 'cpu_usage')
            self.assertEqual(proof['checked_at'], BASE)
            # A generic closure never gains proof; use another actual native row.
            store.record_error('pve_service_test','pve_services','CRITICAL','inactive')
            store.resolve_error('pve_service_test','No longer present')
            self.assertFalse(json.loads(sql(store,"SELECT data FROM events ORDER BY id DESC LIMIT 1")[0][0]).get('check_evidence'))

    def test_recovery_query_requires_fresh_same_incident_proof(self):
        with case() as store:
            first = original_cpu(store); cpu(store)
            proof = store.get_recovery_evidence('cpu_usage',first)
            self.assertTrue(proof)
            self.assertIsNone(store.get_recovery_evidence('cpu_usage','different incident'))
            saved = sql(store,'SELECT last_seen,resolved_at FROM errors')[0]
            for field,value in [('acknowledged',1),('resolved_at',None),('last_seen',Clock.fromtimestamp(BASE+1).isoformat())]:
                sql(store,f'UPDATE errors SET {field}=?',(value,))
                self.assertIsNone(store.get_recovery_evidence('cpu_usage',first))
                sql(store,'UPDATE errors SET acknowledged=0,last_seen=?,resolved_at=?',saved)
            data = json.loads(sql(store,"SELECT data FROM events WHERE event_type='resolved'")[0][0])
            for bad in (None,{'check':'cpu_usage','checked_at':BASE-7201}, {'check':'storage_removed','checked_at':BASE}, {'check':'cpu_usage','checked_at':float('inf')}, {'check':'cpu_usage','checked_at':10**400}):
                sql(store,"UPDATE events SET data=? WHERE event_type='resolved'",(json.dumps({**data,'check_evidence':bad}),))
                self.assertIsNone(store.get_recovery_evidence('cpu_usage',first))

    def test_poller_and_all_consumers_distinguish_proven_recovery_from_disappearance(self):
        for proved in (False,True):
            with case() as store:
                first = original_cpu(store)
                if proved: cpu(store)
                else: store.resolve_error('cpu_usage','No longer present')
                data = poll(store,first,reason='CPU high')[0][0]
                self.assertEqual(data['is_recovery'],proved)
                self.assertEqual(data['recovery_outcome'],'resolved' if proved else 'no_longer_reported')
                with patch('health_recovery.time.time',return_value=BASE):
                    for lang in LANGUAGES:
                        for manual in (False,True):
                            result = deliver('error_resolved',data,'OK',lang,manual=manual)
                            self.assertEqual('background:#f0fdf4;' in result['html'],proved)
                            if proved:
                                self.assertIn(templates.runtime_message('healthRecovery.title',lang,hostname='node-a',category='cpu',entity_suffix=''),result['title'])
                            self.assertEqual(result['text'].count(data['reason']),1)

    def test_manual_recovery_flag_alone_is_not_authoritative_evidence(self):
        data={'hostname':'node-a','category':'cpu','reason':'Observation disappeared','duration':'1h','original_severity':'WARNING','recovery_outcome':'resolved'}
        for lang in LANGUAGES:
            for manual in (False,True):
                result=deliver('error_resolved',data,'OK',lang,manual=manual)
                self.assertNotIn('background:#f0fdf4;',result['html'])
                self.assertNotIn(templates.runtime_message('healthRecovery.body',lang,**data),result['body'])

if __name__=='__main__':unittest.main()
