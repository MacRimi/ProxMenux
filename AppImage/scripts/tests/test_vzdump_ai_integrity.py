import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import notification_manager
import notification_templates
from notification_channels import EmailChannel, TelegramChannel
from notification_manager import NotificationManager
from notification_templates import render_template


AI_CONFIG = {
    "ai_enabled": "true",
    "ai_provider": "ollama",
    "ai_ollama_url": "http://localhost:11434",
    "ai_model": "test-model",
    "ai_language": "en",
}


def _vzdump_report(count=49, failed=False):
    header = "{:<8}{:<22}{:<10}{:<10}{:<14}{}".format(
        "VMID", "Name", "Status", "Time", "Size", "Filename"
    )
    rows = []
    for index in range(count):
        vmid = 100 + index
        status = "ERROR" if failed and index == count - 1 else "OK"
        rows.append(
            "{:<8}{:<22}{:<10}{:<10}{:<14}{}".format(
                str(vmid),
                f"guest-{vmid}",
                status,
                f"00:00:{index + 10:02d}",
                f"{index + 1}.25 GiB",
                f"/mnt/pve/archive/dump/vzdump-lxc-{vmid}-2026_09_15-01_00_00.tar.zst",
            )
        )
    return (
        "Proxmox vzdump report\n\n"
        + header
        + "\n"
        + "\n".join(rows)
        + "\nTotal running time: 00:49:00\nTotal size: 1225.25 GiB\n"
    )


def _render(event_type, failed=False):
    return render_template(
        event_type,
        {
            "hostname": "pve-a",
            "storage": "archive",
            "vmname": "49 guests",
            "vmid": "batch",
            "size": "1225.25 GiB",
            "reason": "last guest failed" if failed else "",
            "pve_title": "pve-a: vzdump backup status",
            "pve_message": _vzdump_report(failed=failed),
        },
    )


class _CapturingChannel:
    def __init__(self):
        self.calls = []

    def send(self, title, body, severity, data):
        self.calls.append((title, body, severity, data))
        return {"success": True, "error": None}


class _ReplacingEnhancer:
    calls = 0

    def __init__(self, config):
        self.config = config

    def enhance(self, *args, **kwargs):
        type(self).calls += 1
        return {"title": "AI shortened title", "body": "AI kept only one guest."}


class _FailingEnhancer:
    def __init__(self, config):
        self.config = config

    def enhance(self, *args, **kwargs):
        return None


class VzdumpAIIntegrityTests(unittest.TestCase):
    def setUp(self):
        with notification_templates._AI_CACHE_LOCK:
            notification_templates._AI_CACHE.clear()
        _ReplacingEnhancer.calls = 0

    def _dispatch(self, event_type, rendered, enhancer):
        manager = NotificationManager()
        channel = _CapturingChannel()
        manager._channels = {"telegram": channel}
        with (
            patch.object(manager, "_build_ai_config", return_value=dict(AI_CONFIG)),
            patch.object(manager, "_record_history"),
            patch.object(notification_manager, "enrich_context_for_ai", return_value=""),
            patch.object(notification_templates, "AIEnhancer", enhancer),
        ):
            delivered = manager._dispatch_to_channels(
                rendered["title"], rendered["body"],
                "CRITICAL" if event_type == "backup_fail" else "INFO",
                event_type, {}, "test",
            )
        self.assertTrue(delivered)
        self.assertEqual(len(channel.calls), 1)
        return channel.calls[0]

    def _send_public(self, event_type, title, body):
        manager = NotificationManager()
        channel = _CapturingChannel()
        manager._channels = {"telegram": channel}
        manager._config = {"telegram.rich_format": "false"}
        with (
            patch.object(manager, "_build_ai_config", return_value=dict(AI_CONFIG)),
            patch.object(manager, "_record_history"),
            patch.object(notification_templates, "AIEnhancer", _ReplacingEnhancer),
        ):
            result = manager.send_notification(
                event_type,
                "CRITICAL" if event_type == "backup_fail" else "INFO",
                title,
                body,
                source="test",
                skip_toggle_check=True,
            )
        self.assertTrue(result["success"])
        self.assertEqual(len(channel.calls), 1)
        return channel.calls[0]

    def test_public_send_backup_complete_skips_ai_and_keeps_all_49_items(self):
        rendered = _render("backup_complete")

        title, body, _, _ = self._send_public(
            "backup_complete", rendered["title"], rendered["body"]
        )

        self.assertEqual(title, rendered["title"])
        self.assertEqual(body, rendered["body"])
        self.assertEqual(_ReplacingEnhancer.calls, 0)
        self.assertEqual(body.count("✅ CT guest-"), 49)
        self.assertIn("✅ CT guest-100 (100)", body)
        self.assertIn("✅ CT guest-148 (148)", body)

    def test_public_send_backup_fail_skips_ai_and_keeps_all_49_items(self):
        rendered = _render("backup_fail", failed=True)

        title, body, _, _ = self._send_public(
            "backup_fail", rendered["title"], rendered["body"]
        )

        self.assertEqual(title, rendered["title"])
        self.assertEqual(body, rendered["body"])
        self.assertEqual(_ReplacingEnhancer.calls, 0)
        self.assertEqual(body.count("✅ CT guest-") + body.count("❌ CT guest-"), 49)
        self.assertIn("✅ CT guest-100 (100)", body)
        self.assertIn("❌ CT guest-148 (148)", body)

    def test_public_send_non_backup_event_still_uses_ai(self):
        title, body, _, _ = self._send_public(
            "cpu_high", "pve-a: CPU high", "CPU reached 95%."
        )

        self.assertEqual(title, "AI shortened title")
        self.assertEqual(body, "AI kept only one guest.")
        self.assertEqual(_ReplacingEnhancer.calls, 1)

    def test_backup_complete_skips_ai_and_keeps_full_49_item_inventory(self):
        rendered = _render("backup_complete")

        title, body, _, _ = self._dispatch(
            "backup_complete", rendered, _ReplacingEnhancer
        )

        self.assertEqual(title, rendered["title"])
        self.assertEqual(body, rendered["body"])
        self.assertEqual(_ReplacingEnhancer.calls, 0)
        self.assertIn("✅ CT guest-100 (100)", body)
        self.assertIn("📏 Size: 1.25 GiB | ⏱️ Duration: 00:00:10", body)
        self.assertIn("✅ CT guest-148 (148)", body)
        self.assertIn("📏 Size: 49.25 GiB | ⏱️ Duration: 00:00:58", body)
        self.assertIn("📊 49 backups", body)
        self.assertEqual(body.count("✅ CT guest-"), 49)

    def test_backup_fail_skips_ai_and_keeps_inventory_and_failure_details(self):
        rendered = _render("backup_fail", failed=True)

        title, body, _, _ = self._dispatch(
            "backup_fail", rendered, _ReplacingEnhancer
        )

        self.assertEqual(title, rendered["title"])
        self.assertEqual(body, rendered["body"])
        self.assertEqual(_ReplacingEnhancer.calls, 0)
        self.assertIn("✅ CT guest-100 (100)", body)
        self.assertIn("❌ CT guest-148 (148)", body)
        self.assertIn("📏 Size: 49.25 GiB | ⏱️ Duration: 00:00:58", body)
        self.assertIn("📊 49 backups | ❌ 1 failed", body)
        self.assertEqual(body.count("✅ CT guest-"), 48)

    def test_backup_ai_failure_sends_original_title_and_body_unchanged(self):
        rendered = _render("backup_complete")

        title, body, _, _ = self._dispatch(
            "backup_complete", rendered, _FailingEnhancer
        )

        self.assertEqual(title, rendered["title"])
        self.assertEqual(body, rendered["body"])

    def test_non_backup_event_retains_existing_ai_rewrite(self):
        rendered = {"title": "pve-a: CPU high", "body": "CPU reached 95%."}

        title, body, _, _ = self._dispatch(
            "cpu_high", rendered, _ReplacingEnhancer
        )

        self.assertEqual(title, "AI shortened title")
        self.assertEqual(body, "AI kept only one guest.")

    def test_backup_complete_email_html_contains_each_inventory_edge_and_summary_once(self):
        rendered = _render("backup_complete")
        channel = EmailChannel({})
        data = {
            "_event_type": "backup_complete",
            "_group": "backup",
            "hostname": "pve-a",
            "storage": "archive",
            "vmname": "49 guests",
            "vmid": "batch",
            "size": "1225.25 GiB",
        }

        html = channel._format_html(
            "[ProxMenux] [INFO] " + rendered["title"],
            rendered["body"], "INFO", data,
        )

        for vmid in range(100, 149):
            self.assertEqual(html.count(f"guest-{vmid} ({vmid})"), 1, vmid)
        self.assertEqual(html.count("49 backups"), 1)

    def test_backup_fail_email_html_keeps_inventory_and_localized_status_once(self):
        rendered = _render("backup_fail", failed=True)
        channel = EmailChannel({})
        data = {
            "_event_type": "backup_fail",
            "_group": "backup",
            "_notification_language": "sk",
            "hostname": "pve-a",
            "storage": "archive",
            "vmname": "49 guests",
            "vmid": "batch",
            "status": "failed",
            "size": "1225.25 GiB",
            "reason": "last guest failed",
        }

        html = channel._format_html(
            "[ProxMenux] [CRITICAL] " + rendered["title"],
            rendered["body"], "CRITICAL", data,
        )

        for vmid in range(100, 149):
            self.assertEqual(html.count(f"guest-{vmid} ({vmid})"), 1, vmid)
        self.assertEqual(html.count("49 backups"), 1)
        self.assertEqual(html.count("1 failed"), 1)
        self.assertEqual(html.count(">Zlyhalo<"), 1)
        self.assertNotIn(">Failed<", html)
        self.assertLessEqual(html.count("last guest failed"), 1)

    def test_telegram_chunks_preserve_complete_49_item_message(self):
        rendered = _render("backup_complete")
        body = rendered["body"]
        channel = TelegramChannel("123:token", "456")
        html_message = (
            f"<b>🔵 {channel._escape_html(rendered['title'])}</b>\n\n"
            f"{channel._escape_html(body)}"
        )

        chunks = channel._split_message(html_message)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 4096 for chunk in chunks))
        joined = "".join(chunks)
        self.assertIn("guest-100 (100)", joined)
        self.assertIn("guest-148 (148)", joined)
        self.assertIn("49.25 GiB", joined)

    def test_telegram_chunks_do_not_split_entities_or_open_tags(self):
        from html.parser import HTMLParser

        class _BalancedParser(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=False)
                self.stack = []

            def handle_starttag(self, tag, attrs):
                self.stack.append(tag)

            def handle_endtag(self, tag):
                if not self.stack or self.stack.pop() != tag:
                    raise AssertionError(f"unbalanced closing tag: {tag}")

        channel = TelegramChannel("123:token", "456")
        html_message = "<b>" + ("A &amp; B " * 900) + "</b>"

        chunks = channel._split_message(html_message)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 4096 for chunk in chunks))
        for chunk in chunks:
            parser = _BalancedParser()
            parser.feed(chunk)
            parser.close()
            self.assertEqual(parser.stack, [])
            self.assertNotRegex(chunk, r"&(?:amp)?$")
            self.assertNotRegex(chunk, r"^amp;")

    def test_telegram_chunks_bound_an_oversized_entity(self):
        channel = TelegramChannel("123:token", "456")
        chunks = channel._split_message("&" + ("entity" * 900) + ";")

        self.assertTrue(chunks)
        self.assertTrue(all(len(chunk) <= 4096 for chunk in chunks))

    def test_telegram_chunks_bound_an_oversized_tag(self):
        channel = TelegramChannel("123:token", "456")
        html_message = '<b data-value="' + ("x" * 5000) + '">visible text</b>'
        chunks = channel._split_message(html_message)

        self.assertTrue(chunks)
        self.assertTrue(all(len(chunk) <= 4096 for chunk in chunks))
        self.assertIn("visible text", "".join(chunks))

    def test_telegram_chunks_bound_deeply_nested_formatting(self):
        from html.parser import HTMLParser

        class _BalancedParser(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=False)
                self.stack = []

            def handle_starttag(self, tag, attrs):
                self.stack.append(tag)

            def handle_endtag(self, tag):
                if not self.stack or self.stack.pop() != tag:
                    raise AssertionError(f"unbalanced closing tag: {tag}")

        html_message = ("<b>" * 700) + ("A" * 5000) + ("</b>" * 700)
        channel = TelegramChannel("123:token", "456")
        chunks = channel._split_message(html_message)

        self.assertTrue(chunks)
        self.assertTrue(all(len(chunk) <= 4096 for chunk in chunks))
        self.assertEqual("".join(chunks).count("A"), 5000)
        for chunk in chunks:
            parser = _BalancedParser()
            parser.feed(chunk)
            parser.close()
            self.assertEqual(parser.stack, [])


if __name__ == "__main__":
    unittest.main()
