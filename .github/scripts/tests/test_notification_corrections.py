"""Whole-PR outcome corrections, inert producer/actual email consumers."""
import html
import unittest
from notification_fixture import templates, receive, email, LANGUAGES

REPORT = """Details
=======
VMID    Name    Status    Time     Size     Filename
100     web     ok        1m 1s    1 GiB    vm/100/2026-09-29T17:00:00Z

Total running time: 1m 1s
Total size: 1 GiB
"""

class CorrectionTests(unittest.TestCase):
    def test_reversed_finish_is_not_completion_evidence(self):
        event = receive('INFO: Finished Backup of VM 100 (00:01:01)\nINFO: Starting Backup of VM 100 (qemu)')
        self.assertEqual(event.data['backup_outcome'], 'unconfirmed')


    def test_interleaved_complete_logs_keep_both_finished_guests(self):
        message = ('INFO: Starting Backup of VM 100 (qemu)\nINFO: VM Name: web\n'
                   'INFO: Starting Backup of VM 101 (lxc)\nINFO: CT Name: db\n'
                   'INFO: Finished Backup of VM 100 (00:01:01)\nINFO: Finished Backup of VM 101 (00:01:02)')
        event = receive(message)
        self.assertEqual(event.data['backup_outcome'], 'confirmed')
        result, markup = email(event.event_type, event.data, event.severity)
        self.assertIn('✅ VM web (100)', result['body'])
        self.assertIn('✅ CT db (101)', result['body'])
        self.assertNotIn('❔', result['body'])
        self.assertIn('00:01:01', result['body'])


    def test_backup_identity_has_event_scoped_mail_compatible_wrapping(self):
        result, markup = email('backup_complete', {'hostname': 'n' * 64,
            'backup_outcome': 'confirmed', 'pve_message': 'INFO: Starting Backup of VM 100 (qemu)\nINFO: VM Name: customerproductionpostgresqlreplicaeuropewestdatacenter01\nINFO: Finished Backup of VM 100 (00:01:01)'})
        self.assertIn('table-layout:fixed;', markup)
        title_tag = markup.split('<h2 style="', 1)[1].split('"', 1)[0]
        self.assertIn('overflow-wrap:break-word;', title_tag)
        self.assertIn('word-wrap:break-word;', title_tag)
        _, unrelated = email('node_reconnect', {'hostname': 'node-a'}, 'OK')
        self.assertNotIn('table-layout:fixed;', unrelated)


    def test_catalog_parity_accepts_eventual_valid_slovak_keys(self):
        from notification_fixture import extract, SCRIPTS
        import copy
        import string
        path = SCRIPTS / 'tests/test_notification_runtime_i18n.py'
        ns = {'string': string}
        ns['_placeholders'] = extract(path, '_placeholders', None, ns)
        parity = extract(path, 'test_runtime_catalog_keys_and_placeholders_match', 'RuntimeCatalogTests', ns)
        probe = unittest.TestCase()
        probe.catalogs = {lang: copy.deepcopy(templates._load_runtime_catalog(lang)) for lang in LANGUAGES}
        parity(probe)  # shipped missing keys remain allowed
        probe.catalogs['sk']['backup'] = copy.deepcopy(probe.catalogs['en']['backup'])
        for key in ('observation',):
            probe.catalogs['sk']['channels']['email']['severity'][key] = probe.catalogs['en']['channels']['email']['severity'][key]
        probe.catalogs['sk']['channels']['email']['status']['unconfirmed'] = probe.catalogs['en']['channels']['email']['status']['unconfirmed']
        parity(probe)  # generation of exactly the pending keys is legal
        probe.catalogs['sk']['backup']['confirmedTitle'] = 'Missing hostname token'
        with self.assertRaises(AssertionError): parity(probe)


    def test_actual_neutral_style_is_not_success_green(self):
        for event, severity, data in (('error_resolved', 'OK', {}),
                                      ('backup_complete', 'INFO', {'backup_outcome': 'unconfirmed'})):
            result, markup = email(event, data, severity)
            self.assertIn('background:#f9fafb;', markup)
            self.assertNotIn('background:#f0fdf4;', markup)


    def test_actual_manual_caller_carries_event_presentation_context(self):
        from notification_fixture import extract, SCRIPTS, EmailChannel
        from typing import Optional, Dict, Any
        from threading import Lock
        captured = []
        channel = object.__new__(EmailChannel)
        channel.subject_prefix = '[ProxMenux]'
        class Sink:
            def send(self, title, body, severity, data):
                captured.append((data, channel._format_html(title, body, severity, data)))
                return {'success': True}
        ns = {'Optional': Optional, 'Dict': Dict, 'Any': Any, 'TEMPLATES': templates.TEMPLATES,
              'resolve_notification_hostname': lambda host, config: host or 'node-a',
              'render_template': templates.render_template, '_should_bypass_ai': lambda event: True}
        send = extract(SCRIPTS / 'notification_manager.py', 'send_notification', 'NotificationManager', ns)
        class Manager:
            _channels = {'email': Sink()}
            _config = {}
            _lock = Lock()
            def _notification_language(self): return 'en'
            def is_event_enabled(self, event): return True
            def _build_ai_config(self): return {}
            def _record_history(self, *args): pass
        data = {'category': 'temperature', 'reason': 'old', 'duration': '3d', 'original_severity': 'WARNING',
                '_event_type': 'node_reconnect', '_group': 'cluster'}
        result = send(Manager(), 'error_resolved', 'OK', '', '', data)
        self.assertTrue(result['success'])
        context, markup = captured[0]
        self.assertEqual(context['_event_type'], 'error_resolved')
        self.assertEqual(context['_group'], 'health')
        self.assertIn('NO LONGER REPORTED', markup)
        self.assertNotIn('>RESOLVED</span>', markup)
        self.assertNotIn('color:#16a34a', markup)
        self.assertEqual(data['_event_type'], 'node_reconnect')  # caller not mutated


    def test_disappearance_body_keeps_observation_age_not_green_severity(self):
        data = {'hostname': 'node-a', 'category': 'temperature', 'reason': 'old observation',
                'duration': '3d 2h', 'original_severity': 'WARNING', 'severity': 'OK'}
        for language in LANGUAGES:
            result, markup = email('error_resolved', data, 'OK', language)
            for line in result['body'].splitlines():
                if line.strip(): self.assertIn(line.strip(), html.unescape(markup))
            self.assertNotIn('>OK</span>', markup)
            self.assertNotIn('color:#16a34a', markup)
            self.assertNotIn('>RESOLVED</span>', markup)


    def test_actual_restore_endpoint_warnings_and_counts_reach_email(self):
        from notification_fixture import extract, SCRIPTS
        from types import SimpleNamespace
        for warnings in ('', 'missing module zfs'):
            events = []
            ns = {'request': SimpleNamespace(remote_addr='127.0.0.1', get_json=lambda **kw: {
                'hostname': 'node-a', 'guests': '3', 'stubs': '1', 'stale_nodes': '0',
                'components': '2', 'duration': '2m', 'warnings': warnings}),
                'notification_manager': SimpleNamespace(emit_event=lambda **kw: events.append(kw)),
                'jsonify': lambda value: value}
            handler = extract(SCRIPTS / 'flask_notification_routes.py', 'internal_restore_event', None, ns)
            response, status = handler()
            self.assertEqual(status, 200)
            event = events[0]
            for language in LANGUAGES:
                result, markup = email(event['event_type'], event['data'], event['severity'], language)
                self.assertIn('2m', markup)
                for line in result['body'].splitlines():
                    if line.strip(): self.assertIn(line.strip(), html.unescape(markup))
                if warnings: self.assertIn(warnings, markup)


    def test_raw_display_hostname_is_substituted_exactly_once(self):
        for event_type, outcome in (('backup_complete', 'confirmed'), ('backup_complete', 'failed'), ('backup_fail', 'failed')):
            for hostname in ('Sala {rack} – Zürich', 'node-{vmid}', 'Sala {rack.location}'):
                for language in LANGUAGES:
                    result, markup = email(event_type, {'hostname': hostname,
                        'backup_outcome': outcome, 'pve_message': REPORT}, language=language)
                    self.assertIn(hostname, result['title'])
                    self.assertIn(hostname, html.unescape(markup))


    def test_malformed_numeric_report_is_queued_uncertain_and_renderable(self):
        for size in ('1..5 GiB', '..5 GiB'):
            message = REPORT.replace('1 GiB    ', size.ljust(9)).split('Total size:')[0]
            event = receive(message)
            self.assertEqual(event.data['backup_outcome'], 'unconfirmed')
            result, markup = email(event.event_type, event.data, event.severity)
            self.assertIn(size, result['body'])


    def test_unknown_backup_type_keeps_explicit_err_but_cannot_certify_ok(self):
        event = receive(REPORT.replace('ok        ', 'err       '), kind='')
        self.assertEqual(event.event_type, 'backup_complete')
        self.assertEqual(event.severity, 'INFO')
        self.assertEqual(event.data['backup_outcome'], 'failed')
        result, markup = email(event.event_type, event.data, event.severity)
        self.assertIn('FAILED', markup)
        self.assertEqual(receive(REPORT, kind='').data['backup_outcome'], 'unconfirmed')


    def test_confirmed_metadata_only_context_is_retained(self):
        data = {'hostname': 'node-a', 'backup_outcome': 'confirmed',
                'vmid': '100', 'vmname': 'web {literal}', 'storage': 'PBS', 'size': '1 GiB'}
        for language in LANGUAGES:
            result, markup = email('backup_complete', data, language=language)
            self.assertIn('web {literal} (100)', result['title'])
            self.assertIn('1 GiB', result['body'])
            self.assertIn('1 GiB', markup)


    def test_explicit_guest_failure_overrides_only_the_linked_ok_row(self):
        other = '101     db      ok        1m 1s    1 GiB    ct/101/2026-09-29T17:00:00Z'
        message = REPORT.replace('\n\nTotal', '\n' + other + '\n\nTotal')
        diagnostic = '100: 2026-09-29 17:00:00 ERROR: Backup of VM 100 failed - archive write failed'
        for severity in ('info', 'error'):
            event = receive(message + '\n' + diagnostic, severity)
            self.assertEqual(event.data.get('vmid'), '100')
            for language in LANGUAGES:
                result, markup = email(event.event_type, event.data, event.severity, language)
                self.assertIn('❌ VM web (100)', result['body'])
                self.assertNotIn('✅ VM web (100)', markup)
                self.assertIn('✅ CT db (101)', result['body'])
                self.assertIn('web (100)', result['title'])


    def test_official_week_month_year_durations_stay_confirmed(self):
        for duration in ('1w', '1w 1m 1s', '1M', '1y'):
            # Fixed-column widths are unchanged for these bounded values.
            message = REPORT.replace('1m 1s    ', duration.ljust(9))
            event = receive(message)
            self.assertEqual(event.data['backup_outcome'], 'confirmed', duration)
            result, markup = email(event.event_type, event.data, event.severity)
            self.assertIn(duration, result['body'])


    def test_prefixed_error_diagnostics_survive_both_source_severities(self):
        diagnostic = '100: 2026-09-29 17:00:00 ERROR: archive write failed: permission denied'
        for severity in ('info', 'error'):
            event = receive(REPORT + '\n' + diagnostic, severity)
            self.assertEqual(event.data['backup_outcome'], 'failed')
            for language in LANGUAGES:
                result, markup = email(event.event_type, event.data, event.severity, language)
                self.assertIn(diagnostic, result['body'])
                self.assertIn(diagnostic, html.unescape(markup))
                # A job-level error must not invent a failed guest.
                self.assertIn('✅ VM web (100)', result['body'])


    def test_official_completed_report_warning_is_distinct_and_retained(self):
        warning = '100: 2026-09-29 17:00:00 WARN: unable to add notes - permission denied'
        event = receive(REPORT + '\n' + warning)
        self.assertEqual(event.data['backup_outcome'], 'completed_with_warnings')
        for language in LANGUAGES:
            result, markup = email(event.event_type, event.data, event.severity, language)
            self.assertIn(warning, result['body'])
            self.assertIn(warning, html.unescape(markup))

    def test_batch_and_abort_failure_titles_have_no_empty_guest_slot(self):
        failed = REPORT.replace('ok        ', 'err       ')
        failed = failed.replace('\n\nTotal', '\n101     db      err       1m 1s    0 B      null\n\nTotal')
        for message in (failed, REPORT.replace('ok        ', 'todo      '),
                        REPORT.split('100     web')[0] + '\nTotal running time: 0s'):
            event = receive(message + '\nINFO: vzdump --storage PBS', 'error')
            for language in LANGUAGES:
                result, markup = email(event.event_type, event.data, event.severity, language)
                self.assertNotIn('()', result['title'])
                self.assertIn('PBS', result['title'])
                self.assertNotIn('web (100)', result['title'])

    def test_subject_only_setup_failure_survives_actual_email(self):
        reason = 'unable to activate storage PBS'
        title = 'vzdump backup status (node-a): backup failed: ' + reason
        message = REPORT.split('100     web')[0] + '\nTotal running time: 0s\nTotal size: 0 B'
        event = receive(message, 'error', title)
        for language in LANGUAGES:
            result, markup = email(event.event_type, event.data, event.severity, language)
            self.assertIn(reason, result['body'])
            self.assertIn(reason, html.unescape(markup))

if __name__ == '__main__': unittest.main()
