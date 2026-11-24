import sys
import unittest
from pathlib import Path

# Add AppImage/scripts to path regardless of location
current = Path(__file__).resolve()
if current.parent.name == 'tests' and current.parents[1].name == 'scripts':
    SCRIPTS_DIR = current.parents[1]
else:
    SCRIPTS_DIR = current.parents[1] / 'AppImage' / 'scripts'

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from notification_channels import create_channel, CHANNEL_TYPES, TelegramChannel


class TestTelegramRichMessages(unittest.TestCase):
    """Comprehensive test suite for Telegram Rich Message formatting, i18n, validation and delivery."""

    def setUp(self):
        self.config = {
            'bot_token': '123456789:ABCdefGHIjklMNOpqrsTUVwxyz',
            'chat_id': '1234567890',
            'icons_enabled': True,
            'ai_enabled': False,
            'rich_format': True,
            '_notification_language': 'en'
        }
        self.channel = create_channel('telegram', self.config)

    def test_telegram_channel_registered(self):
        """Verify telegram is in CHANNEL_TYPES and config_keys only contains credentials."""
        self.assertIn('telegram', CHANNEL_TYPES)
        self.assertIsInstance(self.channel, TelegramChannel)
        # Verify rich_format is not in config_keys (avoids boolean-to-string coercion bug)
        self.assertNotIn('rich_format', CHANNEL_TYPES['telegram']['config_keys'])

    def test_escape_html(self):
        """Verify HTML special characters are properly escaped."""
        raw = '<b>Test & "quote" <tag>\'</b>'
        escaped = TelegramChannel._escape_html(raw)
        self.assertNotIn('<tag>', escaped)
        self.assertNotIn('<b>', escaped)
        self.assertIn('&amp;', escaped)
        self.assertIn('&lt;', escaped)
        self.assertIn('&gt;', escaped)

    def test_format_html_text_preserves_newlines(self):
        """Verify that text newlines are converted to <br> tags."""
        text = "Línea 1\nLínea 2\n\nLínea 3"
        formatted = TelegramChannel._format_html_text(text)
        self.assertIn("<br>", formatted)
        self.assertIn("<br><br>", formatted)
        self.assertIn("Línea 1", formatted)

    def test_accordion_under_8_items_is_open(self):
        """Lists with 8 or fewer items must have <details open>."""
        items = [{'name': f'item_{i}', 'status': 'OK'} for i in range(5)]
        data = {
            '_event_type': 'status_summary',
            'items': items,
            'message': 'Summary'
        }
        rich_html, keyboard = self.channel._build_rich_content(
            title="System Status",
            message="Summary",
            severity="INFO",
            data=data
        )
        self.assertIn('<details open>', rich_html)
        self.assertNotIn('<details>', rich_html.replace('<details open>', ''))
        # Buttons should be None (no rigid buttons)
        self.assertIsNone(keyboard)

    def test_accordion_over_8_items_is_collapsed(self):
        """Lists with more than 8 items must have collapsed <details> without data loss."""
        items = [{'name': f'vm_{i}', 'status': 'running'} for i in range(12)]
        data = {
            '_event_type': 'vms_status',
            'items': items,
            'message': 'Virtual machines'
        }
        rich_html, _ = self.channel._build_rich_content(
            title="VM List",
            message="Virtual machines",
            severity="INFO",
            data=data
        )
        self.assertIn('<details>', rich_html)
        self.assertNotIn('<details open>', rich_html)
        for i in range(12):
            self.assertIn(f'vm_{i}', rich_html)

    def test_rich_format_disabled_falls_back_to_send_message(self):
        """When rich_format is False, standard message keeps title in bold without icon."""
        cfg = dict(self.config)
        cfg['rich_format'] = False
        ch = create_channel('telegram', cfg)
        self.assertFalse(ch.rich_format)

        sent_messages = []
        ch._send_with_retry = lambda fn: sent_messages.append(fn()) or {'success': True, 'error': None}
        ch._post_message = lambda payload: payload

        ch.send("Test Title", "Test Message Body", "INFO")
        self.assertEqual(len(sent_messages), 1)
        self.assertIn("<b>Test Title</b>\n\nTest Message Body", sent_messages[0])

    def test_rich_cards_toggle_configuration(self):
        """Verify rich_cards defaults to False and can be configured independently of rich_format."""
        # Default behavior: rich_cards is False, rich_format is True
        ch_default = create_channel('telegram', self.config)
        self.assertTrue(ch_default.rich_format)
        self.assertFalse(ch_default.rich_cards)

        cfg = dict(self.config)
        cfg['rich_format'] = True
        cfg['rich_cards'] = False
        ch = create_channel('telegram', cfg)
        self.assertTrue(ch.rich_format)
        self.assertFalse(ch.rich_cards)

        cfg2 = dict(self.config)
        cfg2['rich_format'] = False
        cfg2['rich_cards'] = True
        ch2 = create_channel('telegram', cfg2)
        self.assertFalse(ch2.rich_format)
        self.assertTrue(ch2.rich_cards)

    def test_progress_bar_calculation(self):
        """Test progress bar visual rendering across different percentages."""
        bar_0 = TelegramChannel._format_progress_bar(0)
        self.assertIn('░░░░░░░░░░', bar_0)
        self.assertIn('0.0%', bar_0)

        bar_50 = TelegramChannel._format_progress_bar(50)
        self.assertIn('█████░░░░░', bar_50)
        self.assertIn('50.0%', bar_50)

        bar_100 = TelegramChannel._format_progress_bar(100)
        self.assertIn('██████████', bar_100)
        self.assertIn('100.0%', bar_100)

    def test_smart_test_failed_is_not_treated_as_test_event(self):
        """Verify that smart_test_failed event with 'test' in title is routed to storage, NOT test card."""
        data = {
            '_event_type': 'smart_test_failed',
            '_group': 'storage',
            'device': 'sda',
            'test_type': 'Short self-test',
            'result': 'Completed with read failure',
            'reason': 'Read failure on LBA 482910',
            'message': 'SMART Short self-test on /dev/sda has failed.\nResult: Completed with read failure'
        }
        rich_html, keyboard = self.channel._build_rich_content(
            title="proxmox: SMART test FAILED — sda",
            message=data['message'],
            severity="CRITICAL",
            data=data
        )
        self.assertNotIn("Welcome to ProxMenux Monitor", rich_html)
        self.assertNotIn("Bienvenido", rich_html)
        self.assertIn("sda", rich_html)
        self.assertIsNone(keyboard)

    def test_i18n_german_and_slovak_labels(self):
        """Verify card labels respect _notification_language for German and Slovak users."""
        data_de = {
            '_event_type': 'cpu_high',
            '_group': 'resources',
            '_notification_language': 'de',
            'metric': 'CPU',
            'value': '88%'
        }
        html_de, _ = self.channel._build_rich_content("CPU Alert", "CPU at 88%", "WARNING", data_de)
        self.assertIn("Gastgeber:", html_de)
        self.assertIn("Warnung", html_de)
        self.assertIn("Details", html_de)

        data_sk = {
            '_event_type': 'disk_full',
            '_group': 'storage',
            '_notification_language': 'sk',
            'device': 'sdb',
        }
        html_sk, _ = self.channel._build_rich_content("Disk Alert", "Disk full", "CRITICAL", data_sk)
        self.assertIn("Server:", html_sk)
        self.assertIn("Kritické", html_sk)
        self.assertIn("Podrobnosti", html_sk)

        # Test card in German has 'Kanal'
        data_test_de = {
            '_event_type': 'test',
            '_group': 'other',
            '_notification_language': 'de'
        }
        html_test_de, _ = self.channel._build_rich_content("Test", "Prüfung", "INFO", data_test_de)
        self.assertIn("Kanal", html_test_de)

    def test_no_synthetic_or_guessed_values(self):
        """Verify that missing percentage does not invent 90%, temperature is not called RAM, and values are not parsed from title/body."""
        # Temperature event without percentage
        data_temp = {
            '_event_type': 'temperature_high',
            '_group': 'resources',
            '_notification_language': 'en',
            'value': '75°C'
        }
        html_temp, _ = self.channel._build_rich_content("Temp Alert", "CPU Package at 75°C", "WARNING", data_temp)
        # Must not show progress bar
        self.assertNotIn("█████████", html_temp)
        self.assertNotIn("90.0%", html_temp)
        # Must not be labelled as Memory/RAM
        self.assertNotIn("Memory", html_temp)
        self.assertIn("Temperature", html_temp)
        self.assertIn("75°C", html_temp)

        # Title containing 'SMART test failed' must NOT extract 'test' as device
        data_smart = {
            '_event_type': 'smart_test_failed',
            '_group': 'storage',
            '_notification_language': 'en'
        }
        html_smart, _ = self.channel._build_rich_content("SMART test failed", "Self-test completed with read failure", "ERROR", data_smart)
        self.assertNotIn("<code>test</code>", html_smart)

        # Message with arbitrary NN% must NOT trigger progress bar unless in data['value']
        data_res_nompct = {
            '_event_type': 'cpu_high',
            '_group': 'resources',
            '_notification_language': 'en'
        }
        html_res, _ = self.channel._build_rich_content("CPU Notice", "Threshold exceeded during 50% fan operation", "WARNING", data_res_nompct)
        self.assertNotIn("█████", html_res)

        # Storage card icon follows severity (🟢 for OK, 🟡 for WARNING, 🔴 for ERROR)
        html_ok, _ = self.channel._build_rich_content("SMART test passed", "All self tests passed", "OK", data_smart)
        self.assertIn("<b>🟢", html_ok)
        self.assertNotIn("<b>🔴", html_ok)

        html_err, _ = self.channel._build_rich_content("SMART test failed", "Self-test failed", "ERROR", data_smart)
        self.assertIn("<b>🔴", html_err)

    def test_backup_card_with_failed_guests_and_language_agnostic_units(self):
        """Verify backup cards capture failed guests (❌) and parse sizes/durations using native parser."""
        backup_log = (
            "INFO: Starting Backup of VM 101 (qemu)\n"
            "INFO: VM Name: web\n"
            "INFO: transferred 15.2 GiB in 45 seconds\n"
            "INFO: Finished Backup of VM 101 (00:00:45)\n"
            "INFO: Starting Backup of VM 102 (lxc)\n"
            "INFO: CT Name: db\n"
            "INFO: ERROR: Backup of CT 102 failed - storage offline\n"
            "INFO: Starting Backup of VM 103 (qemu)\n"
            "INFO: VM Name: mail\n"
            "INFO: transferred 2.4 GiB in 12 seconds\n"
            "INFO: Finished Backup of VM 103 (00:12:00)\n"
        )
        data = {
            '_event_type': 'backup_complete',
            '_group': 'backup',
            '_notification_language': 'en',
            'failed_vms': ['102'],
            'storage': 'PBS-Backup',
            'pve_message': backup_log
        }
        html_bk, _ = self.channel._build_rich_content("Backup Report", "Backup completed with errors", "WARNING", data)
        # Failed CT 102 must have failure icon
        self.assertIn("❌", html_bk)
        self.assertIn("102", html_bk)
        # Check size & duration extracted via native parser
        self.assertIn("15.2 GiB", html_bk)
        self.assertIn("PBS-Backup", html_bk)
        self.assertIn('<th align="center">Status</th>', html_bk)

    def test_backup_card_multiline_real_format(self):
        """Verify PBS vzdump messages correctly parse name, id, size, and duration into table with localized header."""
        pve_msg = (
            "INFO: Starting Backup of VM 100 (lxc)\n"
            "INFO: CT Name: adguard\n"
            "INFO: root.pxar: had to backup 2.567 GiB of 2.567 GiB\n"
            "INFO: creating ct/100/2026-11-23T07:00:04Z archive\n"
            "INFO: Finished Backup of VM 100 (00:01:23)\n"
            "INFO: Starting Backup of VM 101 (lxc)\n"
            "INFO: CT Name: dockhand\n"
            "INFO: root.pxar: had to backup 2.79 GiB of 2.79 GiB\n"
            "INFO: creating ct/101/2026-11-23T07:01:28Z archive\n"
            "INFO: Finished Backup of VM 101 (00:01:20)\n"
        )
        data = {
            '_event_type': 'backup_complete',
            '_group': 'backup',
            '_notification_language': 'es',
            'storage': 'Tuxis-PBS',
            'hostname': 'proxmox',
            'pve_message': pve_msg
        }
        html_bk, _ = self.channel._build_rich_content("Proxmox: Backup completado — Tuxis-PBS", "Backup terminado", "INFO", data)
        self.assertIn("Tuxis-PBS", html_bk)
        self.assertIn("adguard", html_bk)
        self.assertIn("2.567 GiB", html_bk)
        self.assertIn("00:01:23", html_bk)
        self.assertIn("dockhand", html_bk)
        self.assertIn("2.79 GiB", html_bk)
        self.assertIn("Estado", html_bk)
        self.assertNotIn("ct/100/2026-11-23T07:00:04Z", html_bk)

    def test_backup_card_labels_follow_language_and_unknown_status_is_neutral(self):
        """Backup labels come from the catalog in every language, and a guest without a result shows no tick."""
        pve_msg = (
            "INFO: Starting Backup of VM 100 (lxc)\n"
            "INFO: CT Name: adguard\n"
            "INFO: Finished Backup of VM 100 (00:01:23)\n"
            "INFO: Starting Backup of VM 101 (qemu)\n"
            "INFO: VM Name: web\n"
        )
        data = {'_event_type': 'backup_complete', '_group': 'backup', '_notification_language': 'fr',
                'storage': 'local', 'pve_message': pve_msg}
        html_bk, _ = self.channel._build_rich_content("Backup", "Backup", "INFO", data)
        for fixed in ("Backups", "processed", "Respaldos", "procesados", "Desglose"):
            self.assertNotIn(fixed, html_bk)
        self.assertIn("Sauvegarde", html_bk)
        rows = [line for line in html_bk.splitlines() if "<td" in line and ">10" in line]
        self.assertTrue(any("✅" in r and ">100<" in r for r in rows))
        self.assertTrue(any(">101<" in r and "✅" not in r and "❌" not in r for r in rows))

    def test_title_is_bold_text_and_grouped_guest_events_have_no_guest_row(self):
        """The title keeps the font of the plain message, and an event without a guest shows no guest row."""
        data = {'_event_type': 'lxc_updates_available', '_group': 'vm_ct', '_notification_language': 'es', 'hostname': 'amd'}
        html_ct, _ = self.channel._build_rich_content("amd: 1 LXC(s) con actualizaciones", "detalle", "INFO", data)
        self.assertNotIn("<h3>", html_ct)
        self.assertNotIn("<h4>", html_ct)
        self.assertTrue(html_ct.startswith("<b>"))
        self.assertNotIn("Guest", html_ct)
        data.update({'vmid': 113, 'vmname': 'ubuntu', '_event_type': 'ct_start'})
        html_one, _ = self.channel._build_rich_content("amd: CT ubuntu arrancado", "detalle", "INFO", data)
        self.assertIn("ubuntu (113)", html_one)

    def test_backup_card_unparseable_fallback(self):
        """Verify that when vzdump format cannot be parsed, card falls back cleanly to details text."""
        data = {
            '_event_type': 'backup_complete',
            '_group': 'backup',
            '_notification_language': 'en',
            'storage': 'Local-NFS'
        }
        msg = "Simple backup plain text notification without vzdump structure."
        html_bk, _ = self.channel._build_rich_content("Backup Report", msg, "INFO", data)
        self.assertIn("Local-NFS", html_bk)
        self.assertIn("<details open>", html_bk)
        self.assertIn(msg, html_bk)

    def test_digest_card_without_rows_falls_back_to_details(self):
        """Verify digest without _rows falls back cleanly to details block."""
        data = {
            '_digest': True,
            '_notification_language': 'en',
            '_rows': []
        }
        msg = "No events were buffered."
        html_dg, _ = self.channel._build_rich_content("Daily Digest", msg, "INFO", data)
        self.assertIn("Daily Digest", html_dg)
        self.assertIn("<details open>", html_dg)
        self.assertIn(msg, html_dg)

    def test_digest_card_with_rows(self):
        """Verify digest with _rows groups by category and formats time rows."""
        import time
        now = int(time.time())
        data = {
            '_digest': True,
            '_notification_language': 'en',
            '_rows': [
                (1, 'vm_started', 'vm_ct', now, 'VM 100 started', 'Details'),
                (2, 'backup_ok', 'backup', now + 60, 'Backup OK', 'Details')
            ]
        }
        html_dg, _ = self.channel._build_rich_content("Daily Digest", "Digest body", "INFO", data)
        self.assertIn("Daily Digest", html_dg)
        self.assertIn("Virtual Machine / Container", html_dg)
        self.assertIn("Backup &amp; Snapshot", html_dg)

    def test_xss_injection_resilience(self):
        """Verify HTML/Script injection attacks inside event fields are neutralized."""
        malicious_message = '<script>alert("hacked")</script><img src="x" onerror="steal()">'
        data = {
            '_event_type': 'security_alert',
            '_group': 'security',
            'ip': '10.0.0.1',
            'target': '<iframe src="evil.com">',
            'message': malicious_message
        }
        rich_html, _ = self.channel._build_rich_content(
            title="<b onmouseover=alert(1)>Alerta</b>",
            message=malicious_message,
            severity="WARNING",
            data=data
        )
        self.assertNotIn('<script>', rich_html)
        self.assertNotIn('<iframe', rich_html)
        self.assertNotIn('<img', rich_html)
        self.assertIn('&lt;script&gt;', rich_html)

    def test_robustness_with_empty_or_broken_data(self):
        """Verify that missing fields or malformed data dictionaries do not raise exceptions."""
        try:
            res1, _ = self.channel._build_rich_content("", "", "", {})
            self.assertIsInstance(res1, str)
            res2, _ = self.channel._build_rich_content(None, None, None, None)
            self.assertIsInstance(res2, str)
            res3, _ = self.channel._build_rich_content("Title", "Msg", "CRITICAL", {'invalid': None})
            self.assertIsInstance(res3, str)
        except Exception as e:
            self.fail(f"_build_rich_content raised unexpected exception: {e}")

    def test_all_severities_handled(self):
        """Ensure all severity levels have assigned icons/styles without error."""
        severities = ['INFO', 'SUCCESS', 'WARNING', 'ERROR', 'CRITICAL', 'UNKNOWN']
        for sev in severities:
            content, kb = self.channel._build_rich_content(
                title=f"Test {sev}",
                message="Severity check",
                severity=sev,
                data={'_event_type': 'test'}
            )
            self.assertIsInstance(content, str)
            self.assertTrue(len(content) > 0)
            self.assertIsNone(kb)


if __name__ == '__main__':
    unittest.main()
