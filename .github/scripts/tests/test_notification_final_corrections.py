"""Final review contracts at actual locale/manual/queued/quiet email seams.
All operational dependencies are inert; no manager or route module import.
"""
import ast
import copy
import html
import unittest
from unittest.mock import patch
from notification_fixture import templates, SCRIPTS, LANGUAGES, receive
from notification_final_fixture import deliver, restore_event

# Literal native send_notification body, produced by pinned PVE Perl helpers.
NATIVE_REPORT = 'Details\n=======\n' + '''VMID    Name    Status    Time     Size     Filename
100     web     ok        1m 1s    1 GiB    vm/100/2026-09-29T17:00:00Z

Total running time: 1m 1s
Total size: 1 GiB

Logs
====
vzdump --all 1 --storage PBS --mode snapshot

100: no log available
'''



class FinalCorrectionsTests(unittest.TestCase):
    def test_runtime_backup_assertions_accept_generated_and_missing_slovak_title(self):
        path = SCRIPTS / 'tests/test_notification_runtime_i18n.py'
        tree = ast.parse(path.read_text())
        owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'RuntimeCatalogTests')
        method = next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == 'test_special_formatters_digest_and_test_message_are_slovak')
        start = next(i for i,n in enumerate(method.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='backup' for t in n.targets))
        stop = next(i for i,n in enumerate(method.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='manager' for t in n.targets))
        block = ast.Module(body=method.body[start:stop], type_ignores=[])
        english = templates._load_runtime_catalog('en')
        for title in (None, '{hostname}: GENERATED_SK potvrdené'):
            sk = copy.deepcopy(templates._load_runtime_catalog('sk'))
            if title is not None: sk.setdefault('backup', {})['confirmedTitle'] = title
            else: sk.get('backup', {}).pop('confirmedTitle', None)
            with patch.object(templates, '_load_runtime_catalog', side_effect=lambda lang: english if lang == 'en' else sk):
                exec(compile(block,str(path),'exec'), {'self':self, 'notification_templates':templates})


    def test_native_multiline_failure_diagnostics_survive_receiver_dispatch_once(self):
        subject = 'vzdump backup status (node-a): backup failed: multiple problems'
        for diagnostic, report in (
            ('external provider job cleanup failed\njob-abort hook permission denied', NATIVE_REPORT),
            ('job interrupted\njob-abort hook permission denied', NATIVE_REPORT.replace('ok        ', 'todo      ')),
            ('unable to initialize external provider\njob-abort hook permission denied', NATIVE_REPORT.replace('100     web     ok        1m 1s    1 GiB    vm/100/2026-09-29T17:00:00Z\n', '')),
        ):
            event = receive(diagnostic + '\n' + report, 'error', subject)
            self.assertEqual((event.event_type, event.severity), ('backup_fail', 'CRITICAL'))
            for language in LANGUAGES:
                result = deliver(event.event_type, event.data, event.severity, language)
                for line in diagnostic.splitlines():
                    self.assertEqual(result['body'].count(line), 1)
                    self.assertEqual(result['text'].count(line), 1)
                if 'ok        ' in report:
                    self.assertIn('✅ VM web (100)', result['body'])


    def test_restore_endpoint_quiet_release_keeps_warning_counts_and_truthful_footer(self):
        reason = 'missing module zfs <raw> & {literal}'
        event = restore_event(reason)
        self.assertEqual(event['severity'], 'WARNING')
        for language in LANGUAGES:
            result = deliver(event['event_type'], event['data'], event['severity'], language, quiet=True)
            self.assertEqual(result['severity'], 'INFO')
            buffered_body = result['buffered'][0][3]
            self.assertEqual(result['text'].count(reason), 1)
            for line in buffered_body.splitlines():
                if line.strip(): self.assertIn(line.strip(), result['text'])
            self.assertIn('2m', result['text'])
            self.assertNotIn(templates.runtime_message('digest.footer', language), result['body'])
            self.assertNotIn('script', result['tags'])


    def test_long_disappearance_reason_is_present_once_in_actual_dispatch(self):
        reason = 'Temperature exceeded configured limit; the source stopped reporting this observation after expiry.'
        for language in LANGUAGES:
            for manual in (False, True):
                result = deliver('error_resolved', {'hostname':'node-a','category':'temperature',
                    'reason':reason,'duration':'3d 2h','original_severity':'WARNING'}, 'OK', language, manual=manual)
                self.assertEqual(result['text'].count(reason), 1)
                self.assertNotIn('>OK</span>', result['html'])
                self.assertNotIn('>RESOLVED</span>', result['html'])


    def test_raw_restore_and_observation_cells_use_event_scoped_mail_wrapping(self):
        token = 'b' * 64
        event = restore_event('Boot check: recorded token ' + token + '; verification pending')
        for language in LANGUAGES:
            results = [deliver(event['event_type'],event['data'],event['severity'],language,quiet=quiet) for quiet in (False,True)]
            results.append(deliver('error_resolved',{'hostname':'node-a','reason':token,'category':'temperature','duration':'3d 2h'},'OK',language))
            for result in results:
                self.assertIn('table-layout:fixed;', result['html'])
                self.assertIn('word-wrap:break-word;', result['html'])
                self.assertIn('overflow-wrap:break-word;', result['html'])
                self.assertEqual(result['text'].count(token), 1)
        unrelated = deliver('node_reconnect', {'hostname':'node-a'}, 'OK')
        self.assertNotIn('table-layout:fixed;', unrelated['html'])


    def test_manual_failed_and_unconfirmed_backup_keep_short_actionable_reason(self):
        for outcome, reason in (('failed','PBS permission denied for datastore remote'),
                                ('unconfirmed','Task status unavailable: upstream API timed out')):
            for language in LANGUAGES:
                result = deliver('backup_complete',{'hostname':'node-a','vmid':'100','vmname':'web',
                    'storage':'PBS','backup_outcome':outcome,'reason':reason},'INFO',language,manual=True)
                self.assertEqual(result['text'].count(reason), 1)
                self.assertNotIn('>COMPLETED</span>', result['html'])


    def test_backup_reason_threshold_and_raw_body_deduplication(self):
        for event in ('backup_complete', 'backup_fail'):
            for length in (79, 80, 81, 120):
                prefix = '<raw> & {rack.location} '
                reason = prefix + 'b' * (length - len(prefix))
                self.assertEqual(len(reason), length)
                for raw in ('', reason):
                    data = {'hostname':'node-a','backup_outcome':'failed','reason':reason,'pve_message':raw}
                    for manual in (False, True):
                        result = deliver(event,data,'INFO','en',manual=manual)
                        self.assertEqual(result['text'].count(reason), 1, (event,length,raw,manual))
                        self.assertNotIn('raw', result['tags'])


    def test_quiet_restore_after_preview_limit_is_not_omitted_or_called_info(self):
        event = restore_event('missing module zfs')
        earlier = [dict(event_type='service_fail',severity='WARNING',data={'hostname':'node-a','service_name':f'unit-{i}','reason':'recorded'}) for i in range(8)]
        result = deliver(event['event_type'],event['data'],event['severity'],quiet=True,quiet_before=earlier)
        self.assertEqual(result['text'].count('missing module zfs'), 1)
        self.assertNotIn(templates.runtime_message('digest.lead','en',count=9), result['body'])
        self.assertEqual(result['data']['_count'], 9)


    def test_native_error_block_does_not_deduplicate_a_substring_of_inventory(self):
        event = receive('web\nexternal provider job cleanup failed\n' + NATIVE_REPORT,
                        'error','vzdump backup status (node-a): backup failed: multiple problems')
        result = deliver(event.event_type,event.data,event.severity)
        self.assertEqual(result['body'].splitlines().count('web'), 1)


if __name__ == '__main__': unittest.main()
