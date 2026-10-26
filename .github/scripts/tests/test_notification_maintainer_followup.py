"""Maintainer acceptance at inert actual notification consumers."""
import unittest
from notification_fixture import templates, receive, LANGUAGES, SCRIPTS, extract
from notification_final_fixture import deliver

NATIVE_REPORT = '''Details
=======
VMID    Name    Status    Time     Size     Filename
100     web     ok        1m 1s    1 GiB    vm/100/2026-09-29T17:00:00Z

Total running time: 1m 1s
Total size: 1 GiB

Logs
====
vzdump --all 1 --storage PBS --mode snapshot

100: 2026-09-29 17:00:00 INFO: Starting Backup of VM 100 (qemu)
100: 2026-09-29 17:01:01 INFO: Finished Backup of VM 100 (00:01:01)
'''

class MaintainerFollowupTests(unittest.TestCase):
    def test_completed_with_warnings_requires_independent_completion(self):
        warning = '\n100: 2026-09-29 17:00:01 WARN: file changed during backup'
        event = receive(NATIVE_REPORT + warning)
        self.assertEqual(event.data['backup_outcome'], 'completed_with_warnings')
        self.assertEqual((event.event_type,event.severity), ('backup_complete','INFO'))
        for manual in (False,True):
            for lang in LANGUAGES:
                result = deliver(event.event_type,event.data,event.severity,lang,manual=manual)
                label = templates.runtime_message('backup.warningTitle',lang,hostname='node-a')
                self.assertIn(label,result['title'])
                status = templates.runtime_message('channels.email.status.completed_with_warnings',lang)
                self.assertIn(status,result['text'])
                self.assertIn('file changed during backup',result['text'])
                # Manual sends intentionally skip channel emoji enrichment.
                if not manual: self.assertTrue(result['title'].startswith('💾⚠️'))
                rich, _ = templates.enrich_with_emojis(event.event_type,result['title'],result['body'],event.data)
                self.assertTrue(rich.startswith('💾⚠️'))
        self.assertEqual(receive('WARN: file changed during backup').data['backup_outcome'],'unconfirmed')
        self.assertEqual(receive(NATIVE_REPORT.split('Total running time:')[0]+warning).data['backup_outcome'],'unconfirmed')
        self.assertEqual(receive(NATIVE_REPORT+warning+'\nERROR: cleanup failed').data['backup_outcome'],'failed')
        self.assertEqual(receive(NATIVE_REPORT+warning,'warning').data['backup_outcome'],'completed_with_warnings')
        self.assertEqual(receive('INFO: Starting Backup of VM 100 (qemu)\nINFO: Finished Backup of VM 100 (00:01:01)'+warning).data['backup_outcome'],'completed_with_warnings')
        self.assertEqual(receive(NATIVE_REPORT+warning,kind='').data['backup_outcome'],'unconfirmed')

    def test_null_filename_failed_guest_uses_own_start_identity(self):
        report = NATIVE_REPORT.replace('100     web     ok        1m 1s    1 GiB    vm/100/2026-09-29T17:00:00Z',
                                       '100     web     err       1m 1s    0 B      null')
        for kind, prefix in (('qemu','VM'),('lxc','CT')):
            own = report.replace('VM 100 (qemu)',f'VM 100 ({kind})')
            # Unrelated guest appears first and must never supply the failed type.
            message = f'INFO: Starting Backup of VM 999 ({"lxc" if kind == "qemu" else "qemu"})\n' + own
            event = receive(message,'error','vzdump backup status (raw-node): backup failed')
            parsed = templates._parse_vzdump_message(message)
            self.assertEqual(parsed['vms'][0]['type'],kind)
            result = deliver(event.event_type,event.data,event.severity)
            self.assertIn(f'{prefix} web (100)',result['title'])
            self.assertIn(f'❌ {prefix} web (100)',result['body'])
        for message in (report.replace('Starting Backup of VM 100','Starting Backup of VM 999'),
                        report+'\nINFO: Starting Backup of VM 100 (lxc)'):
            self.assertEqual(templates._parse_vzdump_message(message)['vms'][0]['type'],'')

    def test_native_subject_keeps_cause_without_host_envelope(self):
        subject = 'vzdump backup status (raw-host): backup failed: multiple problems'
        event = receive('ERROR: archive write failed\n'+NATIVE_REPORT,'error',subject)
        event.data['hostname']='configured-alias'
        for lang in LANGUAGES:
            result=deliver(event.event_type,event.data,event.severity,lang)
            self.assertNotIn(subject,result['text'])
            self.assertEqual(result['text'].count('ERROR: archive write failed'),1)
            self.assertIn('configured-alias',result['title'])
        setup=receive('Details\n=======\nVMID    Name    Status    Time     Size     Filename\n\nTotal running time: 0s\nTotal size: 0 B','error',subject.replace('multiple problems','unable to open storage'))
        result=deliver(setup.event_type,setup.data,setup.severity)
        self.assertEqual(result['text'].count('unable to open storage'),1)
        self.assertNotIn(setup.data['pve_title'],result['text'])
        unique=receive(NATIVE_REPORT,'error',subject.replace('multiple problems','job-end hook denied'))
        result=deliver(unique.event_type,unique.data,unique.severity)
        self.assertIn('job-end hook denied',result['body'])
        self.assertNotIn('vzdump backup status',result['body'])

    def test_backup_diagnostics_are_bounded_with_principal_cause_and_notice(self):
        raw = NATIVE_REPORT + '\n' + '\n'.join(f'WARN: repeated warning {i}' for i in range(80)) + '\nERROR: principal archive write failure'
        event=receive(raw)
        for lang in LANGUAGES:
            result=deliver(event.event_type,event.data,event.severity,lang)
            self.assertIn('ERROR: principal archive write failure',result['body'])
            self.assertLessEqual(len('\n'.join(line for line in result['body'].splitlines() if line.startswith(('WARN:','ERROR:')))),1024)
            self.assertLessEqual(sum(line.startswith(('WARN:','ERROR:')) for line in result['body'].splitlines()),8)
            notice=templates.runtime_message('backup.diagnosticsOmitted',lang,count=73)
            self.assertIn(notice,result['body'])
            self.assertEqual(event.data['pve_message'],raw)
        long=receive('ERROR: '+ 'b'*5000,'error','vzdump backup status (node): backup failed')
        result=deliver(long.event_type,long.data,long.severity)
        self.assertLess(len(result['body']),1400)
        self.assertIn('ERROR: '+ 'b'*100,result['body'])
        self.assertIn(templates.runtime_message('backup.diagnosticsOmitted','en',count=1),result['body'])

    def test_real_quiet_digest_retains_each_backup_outcome_icon(self):
        samples=[(NATIVE_REPORT,'confirmed','💾✅'),(NATIVE_REPORT+'\nWARN: changed file','completed_with_warnings','💾⚠️'),(NATIVE_REPORT+'\nERROR: write failed','failed','💾❌'),('INFO: Starting Backup of VM 100 (qemu)','unconfirmed','💾❔')]
        for raw,outcome,icon in samples:
            event=receive(raw)
            self.assertEqual(event.data['backup_outcome'],outcome)
            for lang in LANGUAGES:
                result=deliver(event.event_type,event.data,event.severity,lang,quiet=True)
                self.assertIn(icon,result['body'])
                self.assertNotIn('💾❔',result['body']) if outcome!='unconfirmed' else None
        import types,datetime
        ns={'datetime':datetime.datetime,'runtime_message':templates.runtime_message,'EVENT_EMOJI':templates.EVENT_EMOJI,'CATEGORY_EMOJI':templates.CATEGORY_EMOJI}
        compose=extract(SCRIPTS/'notification_manager.py','_compose_digest_body','NotificationManager',ns)
        target=types.SimpleNamespace(_notification_language=lambda:'en')
        rows=[(i,'backup_complete','backup',1,icon+' node: Backup','') for i,(_,_,icon) in enumerate(samples)]
        body=compose(target,rows,use_icons=True)
        for _,_,icon in samples:self.assertIn(icon,body)
        plain=compose(target,rows,use_icons=False)
        for _,_,icon in samples:self.assertNotIn(icon,plain)
        should=extract(SCRIPTS/'notification_manager.py','_should_buffer_for_digest','NotificationManager',{})
        self.assertFalse(should(types.SimpleNamespace(_DIGEST_EXEMPT_EVENTS={'backup_complete'},_config={'email.digest_enabled':'true'}),'email','INFO','backup_complete'))

    def test_quiet_restore_details_are_subordinate_in_text_and_email(self):
        from notification_final_fixture import restore_event
        event=restore_event('missing module zfs')
        for lang in LANGUAGES:
            result=deliver(event['event_type'],event['data'],event['severity'],lang,quiet=True)
            body_lines=result['buffered'][0][3].splitlines()
            for line in body_lines:
                if line.strip():
                    self.assertIn('    '+line.strip(),result['body'])
                    self.assertIn('    '+__import__('html').escape(line.strip()),result['html'])
            self.assertIn('white-space:pre-wrap;',result['html'])
            self.assertNotIn(templates.runtime_message('digest.footer',lang),result['body'])

    def test_concrete_subject_cause_already_in_error_log_is_not_repeated(self):
        event=receive(NATIVE_REPORT+'\n100: ERROR: job-end hook denied','error',
                      'vzdump backup status (raw-host): backup failed: job-end hook denied')
        for lang in LANGUAGES:
            result=deliver(event.event_type,event.data,event.severity,lang)
            self.assertEqual(result['text'].count('job-end hook denied'),1)
            self.assertIn('100: ERROR: job-end hook denied',result['body'])

    def test_job_level_subject_cause_survives_warning_cap(self):
        raw=NATIVE_REPORT+'\n'+'\n'.join('WARN: repeated diagnostic '+str(i) for i in range(80))
        event=receive(raw,'error','vzdump backup status (raw-host): backup failed: job-end hook denied')
        for lang in LANGUAGES:
            result=deliver(event.event_type,event.data,event.severity,lang)
            self.assertEqual(result['body'].count('job-end hook denied'),1)
            self.assertNotIn('vzdump backup status',result['body'])
            self.assertIn(templates.runtime_message('backup.diagnosticsOmitted',lang,count=73),result['body'])

    def test_backup_quiet_email_uses_event_scoped_wrapping(self):
        event=receive(NATIVE_REPORT+'\nWARN: changed file')
        result=deliver(event.event_type,event.data,event.severity,'sv',quiet=True)
        self.assertTrue(result['data'].get('_backup_summary'))
        self.assertIn('table-layout:fixed;',result['html'])
        self.assertIn('overflow-wrap:break-word;',result['html'])
        unrelated=deliver('node_reconnect',{'hostname':'node-a'},'OK')
        self.assertNotIn('table-layout:fixed;',unrelated['html'])

if __name__ == '__main__': unittest.main()
