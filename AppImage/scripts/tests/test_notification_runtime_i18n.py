import json
import re
import sqlite3
import string
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
APPIMAGE_DIR = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import notification_manager
import notification_templates
import notification_channels


def _placeholders(value):
    return {
        field_name
        for _literal, field_name, _format_spec, _conversion
        in string.Formatter().parse(value)
        if field_name
    }


class RuntimeCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogs = {}
        for language in ("en", "sk"):
            path = APPIMAGE_DIR / "messages" / language / "common.json"
            cls.catalogs[language] = json.loads(path.read_text(encoding="utf-8"))["runtime"]["notifications"]

    def test_runtime_catalog_covers_every_template_dynamically(self):
        expected = set(notification_templates.TEMPLATES)
        for language, catalog in self.catalogs.items():
            templates = catalog["templates"]
            self.assertEqual(set(templates), expected, language)
            for event_type, source in notification_templates.TEMPLATES.items():
                self.assertEqual(set(templates[event_type]), {"title", "body", "label"})
                for field in ("title", "body", "label"):
                    self.assertIsInstance(templates[event_type][field], str)
                    self.assertTrue(templates[event_type][field])
                    if field in source:
                        self.assertEqual(
                            _placeholders(templates[event_type][field]),
                            _placeholders(source[field]),
                            f"{language}:{event_type}:{field}",
                        )

    def test_runtime_catalog_keys_and_placeholders_match(self):
        def flatten(value, prefix=""):
            result = {}
            for key, child in value.items():
                dotted = f"{prefix}.{key}" if prefix else key
                if isinstance(child, dict):
                    result.update(flatten(child, dotted))
                else:
                    result[dotted] = child
            return result

        en = flatten(self.catalogs["en"])
        sk = flatten(self.catalogs["sk"])
        self.assertEqual(set(sk), set(en))
        for key in en:
            self.assertEqual(_placeholders(sk[key]), _placeholders(en[key]), key)

    def test_slovak_catalog_preserves_placeholders_and_translates_static_text(self):
        en = self.catalogs["en"]["templates"]
        sk = self.catalogs["sk"]["templates"]
        for event_type, source in notification_templates.TEMPLATES.items():
            for field in ("title", "body", "label"):
                static_text = source.get(field, "")
                for placeholder in _placeholders(static_text):
                    static_text = static_text.replace("{" + placeholder + "}", "")
                if any(ch.isalpha() for ch in static_text):
                    self.assertNotEqual(sk[event_type][field], en[event_type][field], f"{event_type}:{field}")

    def test_every_template_renders_in_slovak_and_preserves_dynamic_values(self):
        values = {
            name: f"DYNAMIC_{name.upper()}"
            for template in notification_templates.TEMPLATES.values()
            for field in ("title", "body")
            for name in _placeholders(template.get(field, ""))
        }
        values.update({"hostname": "HOST-ŽILINA", "severity": "WARNING"})
        with mock.patch.object(notification_templates, "_get_hostname", return_value="HOST-ŽILINA"):
            for event_type in notification_templates.TEMPLATES:
                rendered = notification_templates.render_template(event_type, values, language="sk")
                combined = rendered["title"] + "\n" + rendered["body"]
                if notification_templates.TEMPLATES[event_type].get("formatter"):
                    continue
                for name in _placeholders(
                    notification_templates.TEMPLATES[event_type]["title"]
                    + notification_templates.TEMPLATES[event_type]["body"]
                ):
                    if name not in {"entity_suffix", "title_or_default"}:
                        self.assertIn(str(values[name]), combined, f"{event_type}:{name}")

    def test_missing_slovak_key_falls_back_to_english(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "en").mkdir()
            (root / "sk").mkdir()
            (root / "en" / "common.json").write_text(
                json.dumps({"runtime": {"notifications": {"fallback": {"unknownTitle": "{hostname}: {event_type}"}}}}),
                encoding="utf-8",
            )
            (root / "sk" / "common.json").write_text(
                json.dumps({"runtime": {"notifications": {}}}), encoding="utf-8"
            )
            with mock.patch.object(notification_templates, "RUNTIME_CATALOG_DIR", root):
                notification_templates._load_runtime_catalog.cache_clear()
                self.assertEqual(
                    notification_templates.runtime_message(
                        "fallback.unknownTitle", "sk", hostname="pve01", event_type="vendor_event"
                    ),
                    "pve01: vendor_event",
                )
        notification_templates._load_runtime_catalog.cache_clear()

    def test_special_formatters_digest_and_test_message_are_slovak(self):
        startup = notification_templates.render_template(
            "system_startup",
            {"hostname": "pve01", "has_issues": False, "vms_started": [{"name": "alpha", "vmid": 100}]},
            language="sk",
        )
        self.assertIn("Spustenie systému", startup["title"])
        self.assertIn("Všetky systémy sú funkčné", startup["body"])
        self.assertIn("alpha", startup["body"])

        app = notification_templates.render_template(
            "app_update_available",
            {"hostname": "pve01", "app_name": "Redis", "vmid": 115, "ct_name": "cache", "installed": "7.0", "latest": "8.1"},
            language="sk",
        )
        self.assertIn("dostupná aktualizácia", app["title"])
        self.assertIn("Redis", app["body"])
        self.assertIn("7.0 → 8.1", app["body"])

        backup = notification_templates.render_template(
            "backup_complete",
            {
                "hostname": "pve01", "storage": "pbs-main", "vmname": "alpha", "vmid": "100",
                "pve_title": "Backup job finished",
                "pve_message": (
                    "INFO: Starting Backup of VM 100 (qemu)\n"
                    "INFO: VM Name: alpha\n"
                    "INFO: transferred 1.5 GiB in 10 seconds\n"
                    "INFO: Finished Backup of VM 100 (00:00:10)"
                ),
            },
            language="sk",
        )
        self.assertIn("Záloha dokončená", backup["title"])
        self.assertNotIn("Backup job finished", backup["title"])
        self.assertIn("Veľkosť: 1.5 GiB", backup["body"])
        self.assertIn("Trvanie: 00:00:10", backup["body"])

        manager = notification_manager.NotificationManager()
        manager._config = {"notification_language": "sk"}
        rows = [(1, "cpu_high", "resources", 0, "pve01: Vysoké využitie CPU", "body")]
        digest = manager._compose_digest_body(rows)
        self.assertIn("udalostí INFO zoskupených podľa kategórie", digest)
        self.assertIn("Zdroje", digest)
        title, body, caption = manager._build_test_message(False, False, "groq / sk")
        self.assertEqual(title, "Test ProxMenux")
        self.assertIn("Vitajte", body)
        self.assertIn("profilovú fotografiu", caption)

    def test_ai_disabled_telegram_receives_deterministic_slovak(self):
        class RecordingTelegram:
            def __init__(self):
                self.payload = None

            def send(self, title, body, severity, data=None):
                self.payload = (title, body, severity, data)
                return {"success": True, "error": ""}

        channel = RecordingTelegram()
        manager = notification_manager.NotificationManager()
        manager._channels = {"telegram": channel}
        manager._config = {
            "notification_language": "sk",
            "ai_enabled": "false",
            "telegram.rich_format": "false",
        }
        with mock.patch.object(manager, "_record_history"):
            result = manager.send_notification(
                "vm_start", "INFO", "", "",
                data={"hostname": "pve01", "vmname": "účtovníctvo", "vmid": "123"},
                skip_toggle_check=True,
            )
        self.assertTrue(result["success"])
        self.assertIn("spustený", channel.payload[0])
        self.assertIn("účtovníctvo", channel.payload[1])
        self.assertNotIn("is now running", channel.payload[1])

    def test_email_channel_chrome_uses_the_runtime_catalog(self):
        channel = object.__new__(notification_channels.EmailChannel)
        channel.subject_prefix = "[ProxMenux]"
        html = channel._format_html(
            "[ProxMenux] pve01: Vysoké využitie CPU",
            "Využitie CPU dosiahlo 95 %.",
            "WARNING",
            {
                "_notification_language": "sk", "_event_type": "cpu_high",
                "_group": "resources", "hostname": "pve01", "value": "95",
                "threshold": "90", "cores": "8",
            },
        )
        self.assertIn("Systémové zdroje", html)
        self.assertIn("UPOZORNENIE", html)
        self.assertIn("Hostiteľ:", html)
        self.assertIn("Aktuálna hodnota", html)
        self.assertNotIn(">Details<", html)
        self.assertNotIn("System Resources Report", html)

        vm_html = channel._format_html(
            "pve01: VM účtovníctvo (123) spustený",
            "Virtuálny stroj účtovníctvo (ID: 123) je spustený.",
            "INFO",
            {
                "_notification_language": "sk", "_event_type": "vm_start",
                "_group": "vm_ct", "hostname": "pve01", "vmid": "123",
                "vmname": "účtovníctvo",
            },
        )
        self.assertIn("VM bola spustená", vm_html)

    def test_notification_language_precedence_and_roundtrip(self):
        manager = notification_manager.NotificationManager()
        manager._config = {"notification_language": "sk", "ai_language": "de"}
        self.assertEqual(manager._notification_language(), "sk")
        manager._config = {"ai_language": "sk"}
        self.assertEqual(manager._notification_language(), "sk")
        manager._config = {}
        self.assertEqual(manager._notification_language(), "en")

        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "settings.db"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE user_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT, updated_at TEXT)")
            conn.commit()
            conn.close()
            with mock.patch.object(notification_manager, "DB_PATH", db_path):
                saved = manager.save_settings({"notification_language": "sk", "ai_language": "de"})
                self.assertTrue(saved["success"])
                loaded = notification_manager.NotificationManager()
                loaded._load_config()
                self.assertEqual(loaded.get_settings()["config"]["notification_language"], "sk")
                self.assertEqual(loaded.get_settings()["config"]["ai_language"], "de")

    def test_ai_language_is_independent_from_runtime_notification_language(self):
        manager = notification_manager.NotificationManager()
        manager._config = {
            "notification_language": "sk",
            "ai_language": "de",
            "ai_provider": "groq",
        }
        self.assertEqual(manager._notification_language(), "sk")
        self.assertEqual(manager._build_ai_config()["ai_language"], "de")

    def test_legacy_non_runtime_ai_language_roundtrips_as_english_runtime(self):
        manager = notification_manager.NotificationManager()
        manager._config = {"ai_language": "de"}
        self.assertEqual(manager._notification_language(), "en")
        self.assertEqual(manager.get_settings()["config"]["notification_language"], "en")

        manager._config = {"notification_language": "invalid", "ai_language": "sk"}
        self.assertEqual(manager._notification_language(), "sk")
        manager._config = {"notification_language": "invalid", "ai_language": "de"}
        self.assertEqual(manager._notification_language(), "en")

        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "settings.db"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE user_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT, updated_at TEXT)")
            conn.commit()
            conn.close()
            with mock.patch.object(notification_manager, "DB_PATH", db_path):
                result = manager.save_settings({
                    "notification_language": manager.get_settings()["config"]["notification_language"],
                    "ai_language": "de",
                })
        self.assertTrue(result["success"], result)

    def test_backup_email_localizes_status_and_important_packages(self):
        channel = object.__new__(notification_channels.EmailChannel)
        channel.subject_prefix = "[ProxMenux]"
        for event_type, localized_status, english_status in (
            ("backup_fail", "Zlyhalo", "Failed"),
            ("backup_complete", "Dokončené", "Completed"),
            ("backup_start", "Spustené", "Started"),
        ):
            backup_html = channel._format_html(
                "pve01: Záloha", "Stav zálohy VM 100.", "WARNING",
                {
                    "_notification_language": "sk", "_event_type": event_type,
                    "_group": "backup", "hostname": "pve01", "vmid": "100",
                    "vmname": "alpha", "storage": "pbs-main",
                },
            )
            self.assertIn(f">{localized_status}<", backup_html)
            self.assertNotIn(f">{english_status}<", backup_html)

        updates_html = channel._format_html(
            "pve01: Aktualizácie", "Dostupné aktualizácie.", "INFO",
            {
                "_notification_language": "sk", "_event_type": "system_updates",
                "_group": "updates", "hostname": "pve01",
                "important_list": "pve-manager\nproxmox-kernel",
            },
        )
        self.assertIn("Dôležité balíky", updates_html)
        self.assertNotIn("Important Packages", updates_html)

    def test_metric_and_system_email_values_are_localized(self):
        channel = object.__new__(notification_channels.EmailChannel)
        channel.subject_prefix = "[ProxMenux]"
        metric_html = channel._format_html(
            "pve01: Vysoké využitie CPU", "CPU dosiahlo 95 %.", "WARNING",
            {
                "_notification_language": "sk", "_event_type": "cpu_high",
                "_group": "resources", "hostname": "pve01", "value": "95",
            },
        )
        self.assertIn("Vysoké využitie CPU", metric_html)
        self.assertNotIn("Cpu High", metric_html)

        system_html = channel._format_html(
            "pve01: Systémový problém", "Zistil sa problém.", "WARNING",
            {
                "_notification_language": "sk", "_event_type": "system_problem",
                "_group": "system", "hostname": "pve01", "reason": "chyba",
            },
        )
        self.assertIn("Prehľad: Systém", system_html)
        self.assertNotIn("Prehľad: </p>", system_html)

    def test_every_ui_ai_language_is_accepted_by_backend(self):
        source = (APPIMAGE_DIR / "components" / "notification-settings.tsx").read_text(encoding="utf-8")
        block = re.search(r"const AI_LANGUAGES = \[(.*?)\n\]", source, re.DOTALL)
        self.assertIsNotNone(block)
        ui_languages = set(re.findall(r'value: "([a-z]+)"', block.group(1)))
        self.assertIn("sv", ui_languages)
        self.assertIn("no", ui_languages)
        self.assertEqual(ui_languages - set(notification_manager.ALLOWED_AI_LANGUAGES), set())

    def test_quiet_hours_digest_localizes_system_group(self):
        class RecordingChannel:
            def __init__(self):
                self.payload = None

            def send(self, title, body, severity, data=None):
                self.payload = (title, body, severity, data)
                return {"success": True}

        manager = notification_manager.NotificationManager()
        manager._config = {"notification_language": "sk", "hostname": "pve01"}
        channel = RecordingChannel()
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "settings.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE quiet_pending ("
                "id INTEGER PRIMARY KEY, channel TEXT, event_type TEXT, event_group TEXT, "
                "ts REAL, title TEXT, body TEXT)"
            )
            conn.execute(
                "INSERT INTO quiet_pending "
                "(channel, event_type, event_group, ts, title, body) VALUES (?, ?, ?, ?, ?, ?)",
                ("telegram", "ai_model_migrated", "system", 0, "pve01: AI model updated", "body"),
            )
            conn.commit()
            conn.close()
            with mock.patch.object(notification_manager, "DB_PATH", db_path), mock.patch.object(
                manager, "_record_history"
            ):
                manager._flush_quiet_for_channel("telegram", channel)

        self.assertIsNotNone(channel.payload)
        self.assertIn("Systém: 1", channel.payload[1])
        self.assertNotIn("System", channel.payload[1])
        self.assertTrue(channel.payload[3]["_quiet_hours_summary"])

    def test_visible_templates_use_known_backend_and_frontend_groups(self):
        visible_groups = {
            template.get("group", "other")
            for template in notification_templates.TEMPLATES.values()
            if not template.get("hidden", False)
        }
        backend_groups = set(notification_templates.EVENT_GROUPS)

        source = (APPIMAGE_DIR / "components" / "notification-settings.tsx").read_text(encoding="utf-8")
        match = re.search(r"const EVENT_CATEGORIES = \[(.*?)\]\.map", source)
        self.assertIsNotNone(match)
        frontend_groups = set(re.findall(r'"([a-z_]+)"', match.group(1)))

        self.assertEqual(visible_groups - backend_groups, set())
        self.assertEqual(visible_groups - frontend_groups, set())
        self.assertEqual(frontend_groups, backend_groups)
        for language in ("en", "sk"):
            catalog = json.loads(
                (APPIMAGE_DIR / "messages" / language / "common.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                set(catalog["settings"]["notifications"]["categories"]),
                frontend_groups,
                language,
            )

    def test_build_bundles_runtime_catalogs(self):
        build = (SCRIPTS_DIR / "build_appimage.sh").read_text(encoding="utf-8")
        self.assertIn('messages/en/common.json', build)
        self.assertIn('messages/sk/common.json', build)
        self.assertIn('$APP_DIR/usr/share/proxmenux/messages', build)

    def test_missing_event_type_names_exist_in_both_ui_catalogs(self):
        for language in ("en", "sk"):
            path = APPIMAGE_DIR / "messages" / language / "common.json"
            event_types = json.loads(path.read_text(encoding="utf-8"))["settings"]["notifications"]["eventTypes"]
            self.assertIn("lxc_update_applied", event_types)
            self.assertIn("docker_stack_update_available", event_types)


if __name__ == "__main__":
    unittest.main()
