"""AI explains evidence, while backup inventories stay authoritative."""
import sys
import io
import json
import tempfile
import urllib.error
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import notification_manager as manager_module
import notification_templates as templates
from notification_manager import NotificationManager
from notification_channels import EmailChannel
from ai_context_enrichment import get_backup_error_context
from ai_providers.openai_provider import OpenAIProvider
from ai_providers.base import AIProviderError


CONFIG = {
    'ai_enabled': 'true', 'ai_allow_suggestions': 'true',
    'ai_provider': 'ollama', 'ai_ollama_url': 'http://localhost:11434',
    'ai_model': 'test-only', 'ai_language': 'es', 'channel_type': 'telegram',
}
EXPLANATION = ('VM 110: el destino PBS rechazó la escritura por superar una cuota.\n'
               '108 y 9000: el código 255 no indica la causa concreta.\n'
               'Revisa la cuota del destino y el log completo de esas tareas.')


def report(count=11):
    ids = list(range(100, 109)) + [110, 9000]
    if count > 11:
        ids += list(range(200, 200 + count - 11))
    fmt = '{:<8}{:<22}{:<10}{:<10}{:<14}{}'
    rows = [fmt.format('VMID', 'Name', 'Status', 'Time', 'Size', 'Filename')]
    for vmid in ids:
        failed = vmid in (108, 110, 9000)
        rows.append(fmt.format(str(vmid), f'guest-{vmid}', 'ERROR' if failed else 'OK',
                               '00:00:12', '0 B' if failed else '1.25 GiB',
                               'null' if failed else f'ct/{vmid}/2026-11-01T06:00:00Z'))
    return ('Proxmox vzdump report\n' + '\n'.join(rows)
            + '\nTotal running time: 00:14:47\nTotal size: 110.487 GiB\n'
            + '108: 2026-11-01 07:10:47 INFO: Starting Backup of VM 108 (lxc)\n'
            + '110: 2026-11-01 07:14:47 INFO: Starting Backup of VM 110 (qemu)\n'
            + '9000: 2026-11-01 07:14:48 INFO: Starting Backup of VM 9000 (lxc)\n'
            + "108: 2026-11-01 07:14:47 ERROR: Backup of VM 108 failed - command '/usr/bin/proxmox-backup-client backup root.pxar:/mnt/vzsnap0' failed: exit code 255\n"
            + "110: 2026-11-01 07:14:48 ERROR: VM 110 qmp command 'backup' failed - backup connect failed: command error: Disk quota exceeded (os error 122)\n"
            + "9000: 2026-11-01 07:14:53 ERROR: Backup of VM 9000 failed - command 'lxc-usernsexec -- proxmox-backup-client backup' failed: exit code 255\n")


def render(count=11):
    data = {'hostname': 'test-node', 'storage': 'PBS-Cloud',
            'pve_message': report(count), 'backup_outcome': 'failed',
            '_notification_language': 'es'}
    rendered = templates.render_template('backup_fail', data, language='es')
    data['_backup_analysis'] = rendered['backup_analysis']
    return data, rendered


class CapturingChannel:
    def __init__(self):
        self.calls = []

    def send(self, *args):
        self.calls.append(args)
        return {'success': True}


class BackupAIDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        with templates._AI_CACHE_LOCK:
            templates._AI_CACHE.clear()
        self.prompts = []
        prompts = self.prompts
        class Provider:
            def generate(self, system, user, max_tokens):
                prompts.append((system, user, max_tokens))
                return '[TITLE]\nInvented title\n[BODY]\n' + EXPLANATION
        self.provider = Provider()
        def initialize(enhancer):
            enhancer._provider = self.provider
        self.provider_patch = patch.object(templates.AIEnhancer, '_init_provider', initialize)
        self.provider_patch.start()
        self.addCleanup(self.provider_patch.stop)

    def explain(self, data, rendered, **config):
        return templates.format_backup_diagnostics_with_ai(
            rendered['title'], rendered['body'], 'CRITICAL', {**CONFIG, **config},
            event_type='backup_fail', data=data)

    def test_suggestions_setting_reaches_all_runtime_rewriters(self):
        manager = NotificationManager()
        manager._config = {'ai_allow_suggestions': 'true'}
        self.assertEqual(manager._build_ai_config()['ai_allow_suggestions'], 'true')
        manager._config = {}
        self.assertEqual(manager._build_ai_config()['ai_allow_suggestions'], 'false')

    def test_api_quota_exhaustion_is_distinct_from_rate_limit_and_never_retried(self):
        for classification in ({'code': 'insufficient_quota'},
                               {'code': 'unknown-code', 'type': 'insufficient_quota'},
                               {'code': 'credit_balance_exhausted'},
                               {'code': 'project_spend_limit_exceeded'}):
            with self.subTest(classification=classification):
                payload = json.dumps({'error': {**classification, 'message': 'private-prompt-do-not-log'}}).encode()
                error = urllib.error.HTTPError('https://example.invalid', 429, 'Too Many Requests', {}, io.BytesIO(payload))
                provider = OpenAIProvider(api_key='test-only', model='test-only')
                with patch('urllib.request.urlopen', side_effect=error) as request, patch('time.sleep') as sleep:
                    with self.assertRaisesRegex(AIProviderError, 'quota exhausted') as failure:
                        provider._make_request('https://example.invalid', {}, {})
                self.assertEqual(request.call_count, 1)
                sleep.assert_not_called()
                self.assertNotIn('private-prompt', str(failure.exception))

    def test_temporary_api_rate_limit_keeps_retry_behavior(self):
        error = urllib.error.HTTPError('https://example.invalid', 429, 'Too Many Requests', {},
                                      io.BytesIO(b'{"error":{"type":"rate_limit_exceeded"}}'))
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok":true}'
        provider = OpenAIProvider(api_key='test-only', model='test-only')
        with patch('urllib.request.urlopen', side_effect=[error, response]) as request, patch('time.sleep') as sleep:
            result = provider._make_request('https://example.invalid', {}, {})
        self.assertTrue(result['ok'])
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_low_level_context_requires_the_exact_run_and_ignores_other_guests(self):
        anchor = '2026-11-01 07:14:47 ERROR: Backup of VM 108 failed - exit code 255'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'lxc-108.log').write_text(
                '2026-11-01 07:10:47 INFO: Starting Backup of VM 108 (lxc)\n'
                '2026-11-01 07:14:45 INFO: Error: inserting chunk failed: EDQUOT: Quota exceeded\n'
                + anchor + '\n')
            (root / 'lxc-109.log').write_text('Unrelated secret log')
            context = get_backup_error_context('108: ' + anchor, root)
            self.assertIn('CT 108:', context)
            self.assertIn('EDQUOT', context)
            self.assertNotIn('Unrelated', context)
            self.assertEqual(get_backup_error_context(anchor.replace('07:14:47', '08:14:47'), root), '')
            self.assertEqual(get_backup_error_context(anchor.replace('255', '254'), root), '')

    def test_current_job_context_does_not_include_previous_job_errors(self):
        anchor = '2026-11-01 07:14:47 ERROR: Backup of VM 108 failed - exit code 255'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'lxc-108.log').write_text(
                '2026-10-31 07:14:45 ERROR: OLD unrelated error\n'
                '2026-11-01 07:10:47 INFO: Starting Backup of VM 108 (lxc)\n'
                '2026-11-01 07:14:45 INFO: Error: EDQUOT: Quota exceeded\n' + anchor + '\n')
            context = get_backup_error_context(anchor, root)
            self.assertIn('EDQUOT', context)
            self.assertNotIn('OLD', context)

    def test_verified_local_causes_reach_the_ai_without_rewriting_inventory(self):
        data, rendered = render()
        with patch('ai_context_enrichment.get_backup_error_context', return_value='CT 108: EDQUOT: Quota exceeded'):
            result = self.explain(data, rendered)
        self.assertIn('CT 108: EDQUOT', self.prompts[0][1])
        self.assertTrue(result['body'].startswith(data['_backup_analysis']['inventory_body']))

    def test_only_diagnostics_reach_the_model_and_all_49_guests_are_preserved(self):
        data, rendered = render(49)
        result = self.explain(data, rendered)
        self.assertEqual(result['title'], rendered['title'])
        self.assertTrue(result['body'].startswith(data['_backup_analysis']['inventory_body']))
        for vmid in list(range(100, 109)) + [110, 9000] + list(range(200, 238)):
            self.assertEqual(result['body'].count(f'guest-{vmid} ({vmid})'), 1)
        self.assertIn('49 backups', result['body'])
        self.assertIn('110.487 GiB', result['body'])
        self.assertIn(EXPLANATION, result['body'])
        self.assertNotIn(': null', result['body'])
        self.assertNotIn('/usr/bin/proxmox-backup-client', result['body'])
        system, user, _ = self.prompts[0]
        self.assertIn('Spanish', system)
        self.assertIn('Exit code 255 alone', system)
        self.assertIn('Disk quota exceeded', user)
        self.assertIn('9000:', user)
        self.assertNotIn('guest-100', user)
        self.assertNotIn('ct/100/', user)

    def test_disabled_suggestions_or_ai_never_call_a_provider(self):
        data, rendered = render()
        for config in ({'ai_allow_suggestions': 'false'}, {'ai_enabled': 'false'}):
            self.assertEqual(self.explain(data, rendered, **config),
                             {'title': rendered['title'], 'body': rendered['body']})
        self.assertEqual(self.prompts, [])

    def test_ai_guest_type_is_corrected_using_authoritative_inventory(self):
        data, rendered = render()
        self.assertEqual(data['_backup_analysis']['guest_types'],
                         {'108': 'CT', '110': 'VM', '9000': 'CT'})
        with patch.object(self.provider, 'generate', return_value=(
                '[TITLE]\nIgnored\n[BODY]\nCT 110: cuota excedida. VM 108: falta causa.')) as generate:
            result = self.explain(data, rendered)
        explanation = result['body'][len(data['_backup_analysis']['inventory_body']):]
        self.assertIn('VM 110: cuota excedida', explanation)
        self.assertIn('CT 108: falta causa', explanation)
        self.assertIn('Guest identities: CT 108, VM 110, CT 9000', generate.call_args.args[1])

    def test_ai_cannot_introduce_a_failed_guest_outside_the_report(self):
        data, rendered = render()
        with patch.object(self.provider, 'generate', return_value=(
                '[TITLE]\nIgnored\n[BODY]\nVM 999: backup failed.')):
            result = self.explain(data, rendered)
        self.assertNotIn('999', result['body'])
        self.assertIn('Copias 110:', result['body'])

    def test_unknown_guest_type_is_neutral_in_ai_explanation(self):
        data, rendered = render()
        data['_backup_analysis']['guest_types'].pop('110')
        result = self.explain(data, rendered)
        explanation = result['body'][len(data['_backup_analysis']['inventory_body']):]
        self.assertIn('ID 110:', explanation)

    def test_missing_credentials_use_evidenced_quota_fallback(self):
        data, rendered = render()
        result = self.explain(data, rendered, ai_provider='openai', ai_api_key='')
        self.assertIn('Copias 110:', result['body'])
        self.assertIn('Copias 108, 9000: el resumen no indica la causa', result['body'])
        self.assertNotIn('ERROR:', result['body'])
        self.assertEqual(self.prompts, [])

    def test_provider_failure_uses_evidenced_quota_fallback(self):
        data, rendered = render()
        with patch.object(self.provider, 'generate', return_value=None):
            result = self.explain(data, rendered)
        self.assertIn('Copias 110:', result['body'])
        self.assertIn('PBS-Cloud', result['body'])
        self.assertNotIn('ERROR:', result['body'])

    def test_unknown_failure_without_quota_keeps_original_on_provider_failure(self):
        data, rendered = render()
        data['_backup_analysis']['diagnostics'] = '108: command failed: exit code 255'
        with patch.object(self.provider, 'generate', return_value=None):
            result = self.explain(data, rendered)
        self.assertEqual(result['body'], rendered['body'])

    def test_stale_or_missing_metadata_never_replaces_a_custom_message(self):
        data, rendered = render()
        rendered['body'] = 'A custom backup report'
        self.assertEqual(self.explain(data, rendered)['body'], rendered['body'])
        self.assertEqual(self.prompts, [])

    def test_direct_send_renders_metadata_and_applies_suggestions(self):
        data, rendered = render()
        del data['_backup_analysis']
        manager = NotificationManager()
        channel = CapturingChannel()
        manager._channels = {'telegram': channel}
        with patch.object(manager, '_build_ai_config', return_value=CONFIG), patch.object(manager, '_record_history'):
            result = manager.send_notification('backup_fail', 'CRITICAL', '', '', data=data,
                                                skip_toggle_check=True)
        self.assertTrue(result['success'])
        title, body, _, _ = channel.calls[0]
        self.assertEqual(title, rendered['title'])
        self.assertIn(EXPLANATION, body)

    def test_queued_dispatch_preserves_inventory_and_explains_errors(self):
        data, rendered = render()
        manager = NotificationManager()
        channel = CapturingChannel()
        manager._channels = {'telegram': channel}
        with patch.object(manager, '_build_ai_config', return_value=CONFIG), patch.object(manager, '_record_history'):
            self.assertTrue(manager._dispatch_to_channels(rendered['title'], rendered['body'],
                            'CRITICAL', 'backup_fail', data, 'test'))
        self.assertIn(EXPLANATION, channel.calls[0][1])
        self.assertNotIn('ERROR:', channel.calls[0][1])

    def test_timeout_uses_evidenced_fallback_and_still_delivers(self):
        data, rendered = render()
        manager = NotificationManager()
        channel = CapturingChannel()
        manager._channels = {'telegram': channel}
        with patch.object(manager, '_build_ai_config', return_value=CONFIG), \
             patch.object(manager, '_record_history'), \
             patch.object(manager_module, '_format_with_ai_bounded', return_value=None):
            self.assertTrue(manager._dispatch_to_channels(rendered['title'], rendered['body'],
                            'CRITICAL', 'backup_fail', data, 'test'))
        self.assertTrue(channel.calls[0][1].startswith(data['_backup_analysis']['inventory_body']))
        self.assertIn('Copias 110:', channel.calls[0][1])
        self.assertNotIn('ERROR:', channel.calls[0][1])

    def test_fallback_with_verified_quota_for_every_failure_is_precise(self):
        data, rendered = render()
        with patch.object(self.provider, 'generate', return_value=None), \
             patch('ai_context_enrichment.get_backup_error_context',
                   return_value='CT 108: EDQUOT: Quota exceeded\nCT 9000: Error: Disk quota exceeded'):
            result = self.explain(data, rendered)
        self.assertIn('Copias 108, 110, 9000:', result['body'])
        self.assertNotIn('no indica la causa', result['body'])

    def test_evidenced_fallback_is_localized_in_every_monitor_language(self):
        data, rendered = render()
        with patch.object(self.provider, 'generate', return_value=None):
            for language in ('en', 'es', 'de', 'fr', 'it', 'pt', 'sk', 'sv'):
                with self.subTest(language=language):
                    result = self.explain(data, rendered, ai_language=language)
                    expected = templates.runtime_message('backup.quotaAffected', language, ids='110')
                    self.assertTrue(expected)
                    self.assertIn(expected, result['body'])

    def test_generic_diagnostic_alerts_receive_suggestions_and_cache_respects_toggle(self):
        manager = NotificationManager()
        manager._config = {**CONFIG}
        ai = manager._build_ai_config()
        templates.format_with_ai_full('test: Error', 'A service failed.', 'CRITICAL', ai)
        self.assertIn('AI SUGGESTIONS MODE (ENABLED)', self.prompts[-1][0])
        manager._config['ai_allow_suggestions'] = 'false'
        templates.format_with_ai_full('test: Error', 'A service failed.', 'CRITICAL', manager._build_ai_config())
        self.assertEqual(len(self.prompts), 2)
        self.assertNotIn('AI SUGGESTIONS MODE (ENABLED)', self.prompts[-1][0])

    def test_update_announcements_keep_intentional_no_suggestions_policy(self):
        manager = NotificationManager()
        channel = CapturingChannel()
        manager._channels = {'telegram': channel}
        manager._config = {'telegram.event.update_available': 'true'}
        with patch.object(manager, '_build_ai_config', return_value=CONFIG), \
             patch.object(manager, '_record_history'), \
             patch.object(manager_module, 'enrich_context_for_ai', return_value=''):
            manager._dispatch_to_channels('test: Updates', 'Two package updates.',
                                          'INFO', 'update_available', {}, 'test')
        self.assertNotIn('AI SUGGESTIONS MODE (ENABLED)', self.prompts[0][0])

    def test_direct_update_announcements_also_keep_no_suggestions_policy(self):
        manager = NotificationManager()
        channel = CapturingChannel()
        manager._channels = {'telegram': channel}
        with patch.object(manager, '_build_ai_config', return_value=CONFIG), patch.object(manager, '_record_history'):
            manager.send_notification('update_available', 'INFO', 'test: Updates',
                                      'Two package updates.', skip_toggle_check=True)
        self.assertNotIn('AI SUGGESTIONS MODE (ENABLED)', self.prompts[0][0])

    def test_email_standard_explains_without_raw_commands_and_detailed_retains_evidence(self):
        data, rendered = render()
        result = self.explain(data, rendered, channel_type='email')
        html = EmailChannel({})._format_html(result['title'], result['body'], 'CRITICAL',
                                             {**data, '_event_type': 'backup_fail', '_group': 'backup'})
        self.assertIn('cuota', html)
        self.assertNotIn('/usr/bin/proxmox-backup-client', html)
        detailed = templates.format_backup_diagnostics_with_ai(
            rendered['title'], rendered['body'], 'CRITICAL', {**CONFIG, 'channel_type': 'email'},
            event_type='backup_fail', data=data, detail_level='detailed')
        self.assertIn('/usr/bin/proxmox-backup-client', detailed['body'])


if __name__ == '__main__':
    unittest.main()
