"""Backup-only maintainer contract at actual render/dispatch/email seams.

Scope-approved seams: receiver, template lookup, rich enrichment, inert queued
and manual delivery with an email capture sink. No host operations or sends.
"""
import unittest
from notification_fixture import templates, LANGUAGES
from notification_final_fixture import deliver


class BackupSplitTests(unittest.TestCase):
    def test_recovery_default_is_upstream_resolved_without_proof(self):
        for language in LANGUAGES:
            data = {'hostname': 'alias', 'category': 'temperature',
                    'reason': 'Temperature high (recovered)', 'duration': '2m',
                    'original_severity': 'WARNING'}
            rendered = templates.render_template('error_resolved', data, language)
            expected = templates.runtime_message('templates.error_resolved.title', language,
                hostname='alias', category='temperature', entity_suffix='')
            self.assertEqual(rendered['title'], expected)
            rich, _ = templates.enrich_with_emojis('error_resolved', rendered['title'], rendered['body'], data)
            self.assertTrue(rich.startswith('✅ '))
            result = deliver('error_resolved', data, 'OK', language)
            self.assertIn('background:#f0fdf4;', result['html'])

    def test_pre_guest_native_subject_keeps_only_cause_once_with_display_alias(self):
        from notification_fixture import receive
        raw_host = 'pve-production.internal.example'
        message = ('Details\n=======\nVMID    Name    Status    Time     Size     Filename\n'
                   '\nTotal running time: 0s\nTotal size: 0 B')
        for raw in (message, 'ERROR: unable to activate storage PBS\n' + message):
            event = receive(raw, 'error', 'vzdump backup status (' + raw_host +
                            '): backup failed: unable to activate storage PBS')
            event.data['hostname'] = 'display-alias {rack.location}'
            for language in LANGUAGES:
                for manual in (False, True):
                    result = deliver(event.event_type, event.data, event.severity, language, manual=manual)
                    self.assertNotIn(raw_host, result['text'])
                    self.assertNotIn('vzdump backup status', result['text'])
                    self.assertEqual(result['text'].count('unable to activate storage PBS'), 1)
                    self.assertIn('display-alias {rack.location}', result['title'])
                    self.assertEqual(result['data']['pve_title'], event.data['pve_title'])
                    self.assertEqual(result['data']['pve_message'], raw)
        # No global hostname or guest-name substitution: actual diagnostics are
        # authoritative, even when they happen to contain the original hostname.
        event = receive(message, 'error', 'vzdump backup status (' + raw_host +
                        '): backup failed: cannot connect to ' + raw_host)
        result = deliver(event.event_type, {**event.data, 'hostname': 'alias'}, event.severity)
        self.assertEqual(result['body'].count('cannot connect to ' + raw_host), 1)
        self.assertNotIn('vzdump backup status', result['body'])

    def test_backup_legacy_keys_keep_meaning_and_unknown_uses_new_keys(self):
        # Frozen upstream contract; no Git history required in shipped tests.
        legacy = {'en': {'title': '{hostname} → {storage}: Backup complete — {vmname} ({vmid})', 'body': 'Backup of {vmname} (ID: {vmid}) completed successfully on {storage}.\nSize: {size}', 'label': 'Backup complete'}, 'de': {'title': '{hostname} → {storage}: Sicherung abgeschlossen – {vmname} ({vmid})', 'body': 'Die Sicherung von {vmname} (ID: {vmid}) wurde am {storage} erfolgreich abgeschlossen.\nGröße: {size}', 'label': 'Sicherung abgeschlossen'}, 'es': {'title': '{hostname} → {storage}: Backup completado — {vmname} ({vmid})', 'body': 'El backup de {vmname} (ID: {vmid}) se ha completado correctamente en {storage}.\nTamaño: {size}', 'label': 'Backup completado'}, 'fr': {'title': '{hostname} → {storage}\xa0: Sauvegarde terminée — {vmname} ({vmid})', 'body': "La sauvegarde de {vmname} (ID\xa0: {vmid}) s'est terminée avec succès le {storage}.\nTaille\xa0: {size}", 'label': 'Sauvegarde terminée'}, 'it': {'title': '{hostname} → {storage}: Backup completato — {vmname} ({vmid})', 'body': 'Backup di {vmname} (ID: {vmid}) completato con successo su {storage}.\nTaglia: {size}', 'label': 'Backup completato'}, 'pt': {'title': '{hostname} → {storage}: Backup concluído — {vmname} ({vmid})', 'body': 'Backup de {vmname} (ID: {vmid}) concluído com sucesso em {storage}.\nTamanho: {size}', 'label': 'Backup concluído'}, 'sk': {'title': '{hostname} → {storage}: Záloha dokončená — {vmname} ({vmid})', 'body': 'Záloha {vmname} (ID: {vmid}) na úložisku {storage} bola úspešne dokončená.\nVeľkosť: {size}', 'label': 'Záloha bola dokončená'}, 'sv': {'title': '{hostname} → {storage}: Säkerhetskopiering klar — {vmname} ({vmid})', 'body': 'Säkerhetskopiering av {vmname} (ID: {vmid}) slutfördes framgångsrikt på {storage}.\nStorlek: {size}', 'label': 'Säkerhetskopieringen är klar'}}
        for language, expected in legacy.items():
            self.assertEqual(templates._load_runtime_catalog(language)['templates']['backup_complete'], expected)
            result = templates.render_template('backup_complete', {'hostname': 'alias {rack.location}'}, language)
            self.assertIn('alias {rack.location}', result['title'])
            self.assertNotIn('()', result['title'])
            new_title = templates.runtime_message('backup.unconfirmedTitle', language, hostname='alias {rack.location}')
            self.assertTrue(new_title)
            self.assertEqual(result['title'], new_title)
            self.assertIn(templates.runtime_message('backup.unconfirmedBody', language), result['body'])
        # Absent/blank/non-string translation uses English per-key fallback.
        from unittest.mock import patch
        english = templates._load_runtime_catalog('en')
        for value in (None, '', {}, []):
            missing = {'backup': {'unconfirmedTitle': value, 'unconfirmedBody': value}}
            with patch.object(templates, '_load_runtime_catalog', side_effect=lambda lang: english if lang == 'en' else missing):
                result = templates.render_template('backup_complete', {'hostname': 'alias'}, 'it')
                self.assertEqual(result['title'], 'alias: Backup outcome unconfirmed')
                self.assertEqual(result['body'], 'The backup outcome is not confirmed.')
        # Both catalogs missing: new outcome text still has explicit EN defaults.
        with patch.object(templates, '_load_runtime_catalog', return_value={}):
            result = templates.render_template('backup_complete', {'hostname': 'alias'}, 'it')
            self.assertEqual(result['title'], 'alias: Backup outcome unconfirmed')
            self.assertEqual(result['body'], 'The backup outcome is not confirmed.')

    def test_restore_keeps_original_ready_line_and_success_icon_with_warnings(self):
        from notification_final_fixture import restore_event
        ready = {'en': 'The node is now fully ready to use.', 'de': 'Der Knoten ist nun vollständig einsatzbereit.', 'es': 'El nodo está listo para usarse.', 'fr': 'Le nœud est maintenant entièrement prêt à être utilisé.', 'it': "Il nodo è ora completamente pronto per l'uso.", 'pt': 'O nó agora está totalmente pronto para uso.', 'sk': 'Uzol je teraz úplne pripravený na použitie.', 'sv': 'Noden är nu helt redo att användas.'}
        for warning in ('', 'missing module zfs'):
            event = restore_event(warning)
            for language in LANGUAGES:
                result = deliver(event['event_type'], event['data'], event['severity'], language)
                self.assertTrue(result['title'].startswith('✅ '))
                self.assertIn(ready[language], result['body'])
                self.assertIn(ready[language], result['text'])
                self.assertIn('2m', result['text'])
                if warning:
                    self.assertIn(warning, result['text'])
                quiet = deliver(event['event_type'], event['data'], event['severity'], language, quiet=True)
                self.assertIn('✅', quiet['body'])
                self.assertIn('    ' + ready[language], quiet['body'])
                self.assertIn('white-space:pre-wrap;', quiet['html'])

    def test_spanish_outcome_and_restore_titles_are_capitalized_and_failure_is_exact(self):
        expected = {'confirmed': 'Backup completado', 'completed_with_warnings': 'Backup completado con advertencias',
                    'unconfirmed': 'Resultado del backup sin confirmar', 'failed': 'Backup fallido'}
        for outcome, title in expected.items():
            result = templates.render_template('backup_complete', {'hostname': 'alias', 'backup_outcome': outcome}, 'es')
            self.assertEqual(result['title'], 'alias: ' + title)
        failure = templates.render_template('backup_fail', {'hostname': 'alias'}, 'es')
        self.assertEqual(failure['title'], 'alias: Backup fallido')
        restore = templates.render_template('system_restore_completed', {'hostname': 'alias'}, 'es')
        self.assertEqual(restore['title'], 'alias: Restauración del host finalizada')

    def test_recovery_only_quiet_release_keeps_upstream_summary_contract(self):
        result = deliver('error_resolved', {'hostname': 'alias', 'category': 'temperature',
                         'reason': 'old (recovered)', 'duration': '2m'}, 'OK', quiet=True)
        self.assertIn(templates.runtime_message('digest.lead', 'en', count=1).strip(), result['body'])
        self.assertIn(templates.runtime_message('digest.footer', 'en'), result['body'])
        self.assertIn('✅', result['body'])


if __name__ == '__main__': unittest.main()
