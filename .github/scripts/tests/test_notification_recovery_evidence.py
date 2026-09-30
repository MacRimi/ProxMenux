"""Fresh existing-check provenance; extracted consumers, real disposable SQLite."""
import contextlib
import datetime
import json
import os
import sqlite3
import tempfile
import time
import types
import unittest
from unittest.mock import patch
from notification_fixture import extract, SCRIPTS, templates, LANGUAGES
from notification_final_fixture import deliver

class RecoveryEvidenceTests(unittest.TestCase):
    def test_cpu_success_provenance_is_persisted_only_after_normal_samples(self):
        events=[]
        with tempfile.TemporaryDirectory() as scratch:
            db=scratch+'/health.sqlite'
            conn=sqlite3.connect(db)
            conn.execute('CREATE TABLE errors(id INTEGER PRIMARY KEY,error_key TEXT,details TEXT,resolved_at TEXT,resolution_type TEXT,resolution_reason TEXT)')
            conn.execute("INSERT INTO errors(error_key,details) VALUES ('cpu_usage','{}')")
            conn.commit();conn.close()
            @contextlib.contextmanager
            def connection():
                c=sqlite3.connect(db)
                try:yield c
                finally:c.close()
            ns={'datetime':datetime.datetime,'json':json}
            resolve=extract(SCRIPTS/'health_persistence.py','_resolve_error_impl','HealthPersistence',ns)
            store=types.SimpleNamespace(_db_connection=connection,_entity_from_details=lambda details:'',_record_event=lambda cursor,kind,key,data:events.append(data))
            store.resolve_error=lambda key,reason,**kw:resolve(store,key,reason,**kw)
            ns={'Dict':dict,'Any':object,'os':os,'time':time,'health_persistence':store,'psutil':types.SimpleNamespace(cpu_percent=lambda **kw:20,cpu_count=lambda:4)}
            check=extract(SCRIPTS/'health_monitor.py','_check_cpu_with_hysteresis','HealthMonitor',ns)
            target=types.SimpleNamespace(state_history={'cpu_usage':[{'value':20,'time':time.time()-i*10} for i in range(10)]},CPU_CRITICAL=95,CPU_WARNING=85,CPU_RECOVERY=75,CPU_CRITICAL_DURATION=300,CPU_WARNING_DURATION=300,CPU_RECOVERY_DURATION=120,_check_cpu_temperature=lambda:None)
            result=check(target)
            self.assertEqual(result['status'],'OK')
            self.assertTrue(events[-1].get('check_evidence'),events)
            proof=events[-1]['check_evidence']
            self.assertEqual(proof['check'],'cpu_usage')
            self.assertGreaterEqual(proof['checked_at'],time.time()-5)
            # Existing generic resolve callers (cleanup/exclusion) get no proof.
            conn=sqlite3.connect(db);conn.execute('UPDATE errors SET resolved_at=NULL');conn.commit();conn.close()
            resolve(store,'cpu_usage','No longer present')
            self.assertFalse(events[-1].get('check_evidence'))

    def test_recovery_query_requires_fresh_same_incident_proof(self):
        with tempfile.TemporaryDirectory() as scratch:
            db=scratch+'/health.sqlite'
            conn=sqlite3.connect(db)
            conn.execute('CREATE TABLE errors(id INTEGER PRIMARY KEY,error_key TEXT,first_seen TEXT,last_seen TEXT,resolved_at TEXT,acknowledged INTEGER)')
            conn.execute('CREATE TABLE events(id INTEGER PRIMARY KEY,event_type TEXT,error_key TEXT,timestamp TEXT,data TEXT)')
            now=datetime.datetime.now(); first=(now-datetime.timedelta(minutes=10)).isoformat(); last=(now-datetime.timedelta(minutes=1)).isoformat(); resolved=now.isoformat()
            proof={'check':'cpu_usage','checked_at':now.timestamp()}
            conn.execute('INSERT INTO errors VALUES(1,?,?,?,?,0)',('cpu_usage',first,last,resolved))
            conn.execute('INSERT INTO events VALUES(1,?,?,?,?)',('resolved','cpu_usage',resolved,json.dumps({'check_evidence':proof})))
            conn.commit();conn.close()
            @contextlib.contextmanager
            def connection(**kwargs):
                c=sqlite3.connect(db)
                try:yield c
                finally:c.close()
            ns={'datetime':datetime.datetime,'json':json,'time':time}
            tree=(SCRIPTS/'health_persistence.py').read_text()
            query=extract(SCRIPTS/'health_persistence.py','get_recovery_evidence','HealthPersistence',ns) if 'def get_recovery_evidence(' in tree else lambda *args:None
            store=types.SimpleNamespace(_db_connection=connection)
            self.assertEqual(query(store,'cpu_usage',first),proof)
            self.assertIsNone(query(store,'cpu_usage','different incident'))
            for field,value in [('acknowledged',1),('resolved_at',None),('last_seen',(now+datetime.timedelta(seconds=1)).isoformat())]:
                conn=sqlite3.connect(db);conn.execute(f'UPDATE errors SET {field}=?',(value,));conn.commit();conn.close()
                self.assertIsNone(query(store,'cpu_usage',first))
                conn=sqlite3.connect(db);conn.execute('UPDATE errors SET acknowledged=0,resolved_at=?,last_seen=?',(resolved,last));conn.commit();conn.close()
            for bad in (None,{'check':'cpu_usage','checked_at':now.timestamp()-7201},{'check':'storage_removed','checked_at':now.timestamp()},{'check':'cpu_usage','checked_at':float('inf')},{'check':'cpu_usage','checked_at':10**400}):
                conn=sqlite3.connect(db);conn.execute('UPDATE events SET data=?',(json.dumps({'check_evidence':bad}),));conn.commit();conn.close()
                self.assertIsNone(query(store,'cpu_usage',first))

    def test_poller_and_all_consumers_distinguish_proven_recovery_from_disappearance(self):
        import sys
        ns={'time':time,'json':json,'Dict':dict,'NotificationEvent':lambda *a,**kw:types.SimpleNamespace(event_type=a[0],severity=a[1],data=a[2])}
        poll=extract(SCRIPTS/'notification_events.py','_check_persistent_health','PollingCollector',ns)
        for proof in (None,{'check':'cpu_usage','checked_at':time.time()}):
            events=[]
            store=types.SimpleNamespace(get_active_errors=lambda:[],is_error_acknowledged=lambda key:False,get_recovery_evidence=lambda *a:proof)
            collector=types.SimpleNamespace(_hostname='node-a',_ENTITY_MAP={'cpu':('node','')},_first_poll_done=True,_known_errors={'cpu_usage':{'category':'cpu','reason':'CPU high','severity':'WARNING','first_seen':'2026-09-30T00:00:00'}},_notified_severity={'cpu_usage':'WARNING'},_last_notified={'cpu_usage':1},_queue=types.SimpleNamespace(put=events.append),_guest_storage_error_is_now_foreign=lambda *a:False,_save_known_errors_meta=lambda:None)
            with patch.dict(sys.modules,{'health_persistence':types.SimpleNamespace(health_persistence=store)}):poll(collector)
            self.assertEqual(len(events),1)
            event=events[0]
            self.assertEqual(event.data.get('recovery_outcome'),'resolved' if proof else 'no_longer_reported')
            self.assertEqual(event.data['is_recovery'],bool(proof))
            for lang in LANGUAGES:
                for manual in (False,True):
                    result=deliver(event.event_type,event.data,event.severity,lang,manual=manual)
                    if proof:
                        self.assertIn(templates.runtime_message('healthRecovery.title',lang,hostname='node-a',category='cpu',entity_suffix=''),result['title'])
                        self.assertIn('background:#f0fdf4;',result['html'])
                    else:self.assertNotIn('background:#f0fdf4;',result['html'])
                    self.assertEqual(result['text'].count(event.data['reason']),1)

    def test_manual_recovery_flag_alone_is_not_authoritative_evidence(self):
        data={'hostname':'node-a','category':'cpu','reason':'Observation disappeared','duration':'1h','original_severity':'WARNING','recovery_outcome':'resolved'}
        for lang in LANGUAGES:
            for manual in (False,True):
                result=deliver('error_resolved',data,'OK',lang,manual=manual)
                self.assertNotIn('background:#f0fdf4;',result['html'])
                self.assertNotIn(templates.runtime_message('healthRecovery.body',lang,**data),result['body'])

if __name__=='__main__':unittest.main()
