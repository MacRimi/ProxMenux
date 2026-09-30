"""Native initializer, measurement methods, SQL writers/readers and collector."""
import unittest
from notification_recovery_fixture import case, Clock, BASE, cpu, sql, poll

class RecoveryCorrectionTests(unittest.TestCase):
    def test_supported_low_warning_current_violation_is_neutral(self):
        with case() as store:
            Clock.epoch = BASE - 600
            initial = cpu(store, 80, [{'value':80, 'time':Clock.epoch-i*5} for i in range(1,26)], warning=50)
            self.assertEqual(initial['status'], 'WARNING')
            first = sql(store, 'SELECT first_seen FROM errors')[0][0]
            Clock.epoch = BASE
            result = cpu(store, 60, [{'value':60, 'time':BASE-i*5} for i in range(1,26)], warning=50)
            events, _ = poll(store, first, reason=initial['reason'])
            # Preserve operational clear/hysteresis behavior, not its factual claim.
            self.assertEqual(result['status'], 'OK')
            self.assertFalse(events[0]['is_recovery'], events)
            self.assertIsNone(store.get_recovery_evidence('cpu_usage', first))

    def test_original_policy_survives_repeated_native_updates(self):
        import json
        for later_warning in (85, 40):
            with self.subTest(later_warning=later_warning), case() as store:
                Clock.epoch = BASE - 600
                cpu(store, 80, [{'value':80, 'time':Clock.epoch-i*5} for i in range(1,26)], warning=50)
                first = sql(store, 'SELECT first_seen FROM errors')[0][0]
                for step in (400, 200):
                    Clock.epoch = BASE-step
                    cpu(store, 90, [{'value':90, 'time':Clock.epoch-i*5} for i in range(1,26)], warning=later_warning)
                original = json.loads(sql(store, 'SELECT details FROM errors')[0][0])['cpu_policy']
                self.assertEqual(original['warning'], 50)
                Clock.epoch = BASE
                cpu(store, 20, warning=later_warning)
                self.assertIsNone(store.get_recovery_evidence('cpu_usage', first))
                self.assertFalse(poll(store, first)[0][0]['is_recovery'])

    def test_clock_rollback_new_row_generic_clear_cannot_inherit_old_proof(self):
        for rollback, reuse_first in ((True,False),(False,False),(True,True)):
            with self.subTest(rollback=rollback,reuse_first=reuse_first),case() as store:
                Clock.epoch = BASE-600
                cpu(store, 90, [{'value':90, 'time':Clock.epoch-i*5} for i in range(1,26)])
                first = sql(store, 'SELECT first_seen FROM errors')[0][0]
                Clock.epoch = BASE; Clock.tick = .001
                try: cpu(store)
                finally: Clock.tick = 0
                self.assertTrue(store.get_recovery_evidence('cpu_usage', first))
                store.acknowledge_error('cpu_usage', suppression_hours=-1)
                store.clear_error('cpu_usage')
                Clock.epoch = BASE-100 if rollback else BASE+1
                store.record_error('cpu_usage','cpu','WARNING','new incident after clock step',{})
                second = sql(store, 'SELECT first_seen FROM errors')[0][0]
                self.assertNotEqual(first, second)
                if reuse_first:
                    # Restored malformed snapshot with reused wall-clock identity;
                    # native row id and latest closure still prevent replay.
                    sql(store,'UPDATE errors SET first_seen=?',(first,));second=first
                Clock.epoch = BASE+.0005 if rollback else BASE+2
                store.clear_error('cpu_usage'); Clock.epoch = BASE+3
                self.assertIsNone(store.get_recovery_evidence('cpu_usage', second))
                self.assertFalse(poll(store, second)[0][0]['is_recovery'])

    def test_malformed_native_and_manual_proof_is_neutral_at_all_consumers(self):
        import copy, json, time
        from unittest.mock import patch
        from notification_fixture import LANGUAGES
        from notification_final_fixture import deliver
        with case() as store:
            Clock.epoch = BASE-600
            cpu(store, 90, [{'value':90,'time':Clock.epoch-i*5} for i in range(1,26)])
            first = sql(store,'SELECT first_seen FROM errors')[0][0]
            Clock.epoch = BASE; cpu(store)
            event_data = json.loads(sql(store,"SELECT data FROM events WHERE event_type='resolved'")[0][0])
            data = poll(store,first)[0][0]
            for field, bad in [('checked_at','bad'),('checked_at',True),('checked_at',float('inf')),
                               ('checked_at',10**400),('value',60),('max_sample',float('nan')),
                               ('normal_samples',True),('normal_samples',9),('checked_at',BASE+1),('checked_at',BASE-7201),
                               ('policy',{'warning':False,'critical':95,'recovery':75}),
                               ('policy',{'warning':96,'critical':95,'recovery':75}),
                               ('policy',{'warning':85,'critical':95}),
                               ('policy',{'warning':85,'critical':95,'recovery':float('nan')}),
                               ('policy',{'warning':85,'critical':95,'recovery':75,'extra':0})]:
                broken = copy.deepcopy(event_data)
                broken['check_evidence'][field] = bad
                if field == 'value': broken['check_evidence']['policy']['warning'] = 50
                sql(store,"UPDATE events SET data=? WHERE event_type='resolved'",(json.dumps(broken),))
                with self.subTest(field=field,bad=str(bad)),patch('health_recovery.time.time',return_value=BASE):
                    self.assertIsNone(store.get_recovery_evidence('cpu_usage',first))
                    for language in LANGUAGES:
                        for manual in (False,True):
                            result = deliver('error_resolved',{**data,'check_evidence':broken['check_evidence']},'OK',language,manual=manual)
                            self.assertNotIn('background:#f0fdf4;', result['html'])
            # Caller content is trusted, not authenticated native proof; even
            # well-shaped assertions require a valid time/type/numeric contract.
            for proof in ({'check':'cpu_usage'}, {'check':'cpu_usage','checked_at':time.time()+1}):
                self.assertNotIn('background:#f0fdf4;', deliver('error_resolved',{**data,'check_evidence':proof},'OK',manual=True)['html'])

    def test_exact_service_active_native_clear_reaches_recovery_consumers(self):
        from unittest.mock import patch
        from notification_recovery_fixture import service
        from notification_fixture import LANGUAGES
        from notification_final_fixture import deliver
        with case() as store:
            Clock.epoch = BASE-600
            service(store,3,'inactive\n')
            first = sql(store,'SELECT first_seen FROM errors')[0][0]
            Clock.epoch = BASE
            result, calls = service(store)
            self.assertEqual(result['status'],'OK')
            self.assertEqual(calls,[(['systemctl','is-active','pvedaemon'], {'capture_output':True,'text':True,'timeout':2})])
            proof = store.get_recovery_evidence('pve_service_pvedaemon',first)
            self.assertTrue(proof)
            data = poll(store,first,'pve_service_pvedaemon','pve_services','PVE service pvedaemon is inactive',details={'service':'pvedaemon'})[0][0]
            self.assertTrue(data['is_recovery'])
            with patch('health_recovery.time.time',return_value=BASE):
                for language in LANGUAGES:
                    for manual in (False,True):
                        rendered = deliver('error_resolved',data,'OK',language,manual=manual)
                        self.assertIn('background:#f0fdf4;',rendered['html'])
                        self.assertIn('pvedaemon', rendered['text'])

    def test_cpu_positive_default_low_policy_and_neutral_history_controls(self):
        from notification_recovery_fixture import record
        for warning,current,history,legacy,expected in (
            (85,20,None,False,True), (50,20,None,False,True),
            (85,20,None,True,False), (85,99,[],False,False),
            (85,20,[],False,False),
            (85,20,[{'value':20,'time':BASE+i*5} for i in range(1,10)],False,False),
            (85,20,[{'value':20,'time':BASE-121-i} for i in range(12)],False,False),
            (85,99,None,False,False),
            (85,float('nan'),None,False,False), (85,float('inf'),None,False,False),
            (85,True,None,False,False), (85,10**400,None,False,False)):
            with self.subTest(warning=warning,current=str(current),legacy=legacy), case() as store:
                if legacy: first = record(store)
                else:
                    Clock.epoch=BASE-600
                    cpu(store,90,[{'value':90,'time':Clock.epoch-i*5} for i in range(1,26)],warning=warning)
                    first=sql(store,'SELECT first_seen FROM errors')[0][0]
                Clock.epoch=BASE; cpu(store,current,history,warning=warning)
                self.assertEqual(bool(store.get_recovery_evidence('cpu_usage',first)),expected)

    def test_service_unavailable_removed_overall_ok_and_ack_controls(self):
        from notification_recovery_fixture import service, record
        for rc,stdout,raised in ((3,'inactive\n',False),(4,'unknown\n',False),(0,'active extra\n',False),(1,'active\n',False),(0,'',True)):
            with self.subTest(rc=rc,stdout=stdout,raised=raised),case() as store:
                Clock.epoch=BASE-600; service(store,3,'inactive\n')
                first=sql(store,'SELECT first_seen FROM errors')[0][0]
                Clock.epoch=BASE; service(store,rc,stdout,raised)
                self.assertIsNone(store.get_recovery_evidence('pve_service_pvedaemon',first))
                self.assertFalse(poll(store,first,'pve_service_pvedaemon','pve_services')[0])
        for removed in ('pvedaemon','corosync'):
            with self.subTest(removed=removed),case() as store:
                first=record(store,'pve_service_'+removed,'pve_services','service inactive',{'service':removed})
                result,calls=service(store,services=(),clustered=False)
                self.assertEqual(result['status'],'OK'); self.assertEqual(calls,[])
                store.clear_error('pve_service_'+removed)
                self.assertFalse(poll(store,first,'pve_service_'+removed,'pve_services')[0][0]['is_recovery'])
        with case() as store:
            first=record(store,'pve_service_corosync','pve_services','corosync inactive',{'service':'corosync'})
            result,calls=service(store,services=('pvedaemon',),clustered=False)
            self.assertEqual(result['status'],'OK')
            self.assertEqual([c[0][-1] for c in calls],['pvedaemon'])
            self.assertTrue(store.is_error_active('pve_service_corosync'))
            self.assertIsNone(store.get_recovery_evidence('pve_service_corosync',first))
        with case() as store:
            first=record(store,'pve_service_pvedaemon','pve_services','service inactive')
            store.acknowledge_error('pve_service_pvedaemon',suppression_hours=-1)
            store.clear_error('pve_service_pvedaemon',check_evidence={'check':'pve_service_pvedaemon','checked_at':BASE,'service':'pvedaemon','state':'active','returncode':0})
            self.assertEqual(sql(store,'SELECT id FROM errors'),[])
            self.assertIsNone(store.get_recovery_evidence('pve_service_pvedaemon',first))

    def test_native_binding_latest_closure_rollbacks_and_consistent_ack_read(self):
        import contextlib, json, sqlite3
        for mutation in ('row_id','first_seen','closure','last_seen','latest_clear','latest_resolve','ack','event_insert_failure','ack_before_join'):
            with self.subTest(mutation=mutation),case() as store:
                Clock.epoch=BASE-600
                cpu(store,90,[{'value':90,'time':Clock.epoch-i*5} for i in range(1,26)])
                first=sql(store,'SELECT first_seen FROM errors')[0][0]
                Clock.epoch=BASE
                if mutation=='event_insert_failure':
                    sql(store,"CREATE TRIGGER fail_resolve BEFORE INSERT ON events WHEN NEW.event_type='resolved' BEGIN SELECT RAISE(ABORT,'fixture'); END")
                    self.assertEqual(cpu(store)['status'],'UNKNOWN')
                    self.assertIsNone(sql(store,'SELECT resolved_at FROM errors')[0][0])
                    continue
                cpu(store); self.assertTrue(store.get_recovery_evidence('cpu_usage',first))
                if mutation in ('row_id','first_seen','closure'):
                    data=json.loads(sql(store,"SELECT data FROM events WHERE event_type='resolved'")[0][0])
                    field={'row_id':'id','first_seen':'first_seen','closure':'resolved_at'}[mutation]
                    data['incident'][field]='wrong'
                    sql(store,"UPDATE events SET data=? WHERE event_type='resolved'",(json.dumps(data),))
                elif mutation=='last_seen': sql(store,'UPDATE errors SET last_seen=?',(Clock.fromtimestamp(BASE+1).isoformat(),))
                elif mutation.startswith('latest_'):
                    sql(store,"INSERT INTO events(event_type,error_key,timestamp,data) VALUES(?,'cpu_usage',?,'{}')",('cleared' if mutation=='latest_clear' else 'resolved',Clock.now().isoformat()))
                elif mutation=='ack': store.acknowledge_error('cpu_usage',suppression_hours=-1)
                else:
                    original=store._db_connection; triggered=[]
                    class Proxy:
                        def __init__(self,connection):self.connection=connection
                        def __getattr__(self,name):return getattr(self.connection,name)
                        def execute(self,query,args=()):
                            if 'FROM errors e JOIN events' in query and not triggered:
                                triggered.append(True)
                                store.acknowledge_error('cpu_usage',suppression_hours=-1)
                            return self.connection.execute(query,args)
                    @contextlib.contextmanager
                    def interleaved(**kw):
                        with original(**kw) as conn: yield Proxy(conn)
                    store._db_connection=interleaved
                self.assertIsNone(store.get_recovery_evidence('cpu_usage',first))
                if mutation=='ack_before_join': self.assertTrue(triggered)
        with case() as store:
            sql(store,"INSERT INTO errors(error_key,category,severity,reason,first_seen,last_seen) VALUES('cpu_usage','cpu','WARNING','fixture','x','x')")
            with self.assertRaises(sqlite3.IntegrityError):
                sql(store,"INSERT INTO errors(error_key,category,severity,reason,first_seen,last_seen) VALUES('cpu_usage','cpu','WARNING','duplicate','x','x')")

    def test_malformed_history_declines_proof_without_changing_operational_clear(self):
        with case() as store:
            Clock.epoch=BASE-600
            cpu(store,90,[{'value':90,'time':Clock.epoch-i*5} for i in range(1,26)])
            first=sql(store,'SELECT first_seen FROM errors')[0][0]
            Clock.epoch=BASE
            result=cpu(store,20,[{'value':10**400,'time':BASE-i*5} for i in range(1,10)])
            self.assertEqual(result['status'],'OK')
            self.assertIsNone(store.get_recovery_evidence('cpu_usage',first))

if __name__ == '__main__': unittest.main()
