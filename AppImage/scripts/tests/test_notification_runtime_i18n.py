import json
import re
import sqlite3
import string
import sys
import tempfile
import unittest
from datetime import datetime
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
    RUNTIME_LANGUAGES = ("en", "de", "es", "fr", "it", "pt", "sk", "sv")

    @classmethod
    def setUpClass(cls):
        cls.catalogs = {}
        for language in cls.RUNTIME_LANGUAGES:
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
        for language, catalog in self.catalogs.items():
            translated = flatten(catalog)
            self.assertEqual(set(translated), set(en), language)
            for key in en:
                self.assertEqual(_placeholders(translated[key]), _placeholders(en[key]), f"{language}:{key}")

    def test_notification_language_ui_keys_exist_in_both_catalogs(self):
        required = {
            "notificationLanguage",
            "selectNotificationLanguage",
            "notificationLanguageHint",
        }
        for language in self.RUNTIME_LANGUAGES:
            path = APPIMAGE_DIR / "messages" / language / "common.json"
            common = json.loads(path.read_text(encoding="utf-8"))
            ui = common["settings"]["notifications"]["ui"]
            self.assertTrue(required.issubset(ui), language)
            for key in required:
                self.assertIsInstance(ui[key], str)
                self.assertTrue(ui[key].strip(), f"{language}:{key}")

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

    def test_lxc_update_result_and_details_render_in_slovak(self):
        data = {
            "hostname": "homelab",
            "ct_name": "iventoy",
            "vmid": "105",
            "result": "succeeded",
            "details": "Source: Manual",
            "lxc_update": {
                "status": "success",
                "source": "manual",
                "targets": ["app:iventoy"],
                "labels": ["iVentoy"],
                "duration": "16s",
                "before": {
                    "apps": {"iventoy": {"name": "iVentoy", "installed_version": "1.0.42"}},
                },
                "after": {
                    "apps": {"iventoy": {"name": "iVentoy", "installed_version": "1.0.43"}},
                },
                "verification_pending": False,
                "verification_errors": [],
                "reboot_required": False,
            },
        }
        rendered = notification_templates.render_template("lxc_update_applied", data, language="sk")
        self.assertEqual(rendered["title"], "homelab: LXC iventoy (105) aktualizácia úspešne dokončená")
        self.assertIn("Zdroj: Manuálne", rendered["body"])
        self.assertIn("Ciele: iVentoy", rendered["body"])
        self.assertIn("Aplikácie: iVentoy: 1.0.42 → 1.0.43", rendered["body"])
        self.assertIn("Vyžaduje sa reštart: nie", rendered["body"])
        self.assertIn("Trvanie: 16s", rendered["body"])
        self.assertNotIn("Source:", rendered["body"])
        self.assertNotIn("succeeded", rendered["title"])

        _title, enriched_body = notification_templates.enrich_with_emojis(
            "lxc_update_applied", rendered["title"], rendered["body"],
            {**data, "_notification_language": "sk", "severity": "INFO"},
        )
        self.assertIn("🧭 Zdroj: Manuálne", enriched_body)
        self.assertIn("🎯 Ciele: iVentoy", enriched_body)
        self.assertIn("🧩 Aplikácie: iVentoy: 1.0.42 → 1.0.43", enriched_body)
        self.assertIn("🔄 Vyžaduje sa reštart: nie", enriched_body)
        self.assertIn("⏱️ Trvanie: 16s", enriched_body)

        for language in self.RUNTIME_LANGUAGES:
            rendered_locale = notification_templates.render_template(
                "lxc_update_applied", data, language=language,
            )
            _title, body_locale = notification_templates.enrich_with_emojis(
                "lxc_update_applied", rendered_locale["title"], rendered_locale["body"],
                {**data, "_notification_language": language, "severity": "INFO"},
            )
            self.assertIn("🧭", body_locale, language)
            self.assertIn("⏱️", body_locale, language)

    def test_update_summary_body_icons_follow_the_selected_language(self):
        data = {
            "hostname": "pve01", "total_count": "2", "security_count": "0",
            "pve_count": "1", "kernel_count": "0", "important_list": "none",
            "severity": "INFO", "_notification_language": "sk",
        }
        rendered = notification_templates.render_template("update_summary", data, language="sk")
        _title, enriched_body = notification_templates.enrich_with_emojis(
            "update_summary", rendered["title"], rendered["body"], data,
        )
        self.assertIn("📦 Aktualizácie spolu: 2", enriched_body)
        self.assertIn("🛡️ Bezpečnostné aktualizácie: 0", enriched_body)
        self.assertIn("⚙️ Aktualizácie jadra: 0", enriched_body)
        self.assertIn("📋 Dôležité balíky:", enriched_body)
        self.assertIn("žiadne", enriched_body)
        self.assertNotIn("\nnone", enriched_body)

        for language in self.RUNTIME_LANGUAGES:
            locale_data = {**data, "_notification_language": language}
            rendered_locale = notification_templates.render_template(
                "update_summary", locale_data, language=language,
            )
            _title, body_locale = notification_templates.enrich_with_emojis(
                "update_summary", rendered_locale["title"], rendered_locale["body"], locale_data,
            )
            total_label = notification_templates._localized_template_labels(
                "update_summary", language,
            )["total_count"][0]
            self.assertIn(f"📦 {total_label}: 2", body_locale, language)

    def test_docker_update_body_icons_preserve_localized_container_label(self):
        data = {
            "hostname": "pve01", "vmid": "210", "ct_name": "repopulse-labs-test",
            "count": "1", "details": "• Docker Engine: 29.8.0 → 29.8.1",
            "severity": "INFO", "_notification_language": "sk",
        }
        rendered = notification_templates.render_template(
            "docker_stack_update_available", data, language="sk",
        )
        _title, enriched_body = notification_templates.enrich_with_emojis(
            "docker_stack_update_available", rendered["title"], rendered["body"], data,
        )
        self.assertIn("📦 Kontajner repopulse-labs-test (CT 210) má 1 aktualizácií Docker:", enriched_body)
        self.assertIn("🐳 • Docker Engine: 29.8.0 → 29.8.1", enriched_body)

    def test_app_and_proxmox_update_body_icons_cover_versions(self):
        app_data = {
            "hostname": "HomeLAB_1", "app_name": "Uptime Kuma", "vmid": "108",
            "ct_name": "uptime-kuma", "installed": "2.5.4", "latest": "2.5.5",
            "severity": "INFO", "_notification_language": "sk",
        }
        app = notification_templates.render_template(
            "app_update_available", app_data, language="sk",
        )
        _title, app_body = notification_templates.enrich_with_emojis(
            "app_update_available", app["title"], app["body"], app_data,
        )
        self.assertIn("📦 Aplikácia Uptime Kuma na CT 108 (uptime-kuma) má novú verziu:", app_body)
        self.assertIn("🔄 2.5.4 → 2.5.5", app_body)

        pve_data = {
            "hostname": "HomeLAB_1", "current_version": "9.2.18",
            "new_version": "9.2.20", "details": "pve-manager 9.2.18 → 9.2.20",
            "severity": "INFO", "_notification_language": "sk",
        }
        pve = notification_templates.render_template("pve_update", pve_data, language="sk")
        _title, pve_body = notification_templates.enrich_with_emojis(
            "pve_update", pve["title"], pve["body"], pve_data,
        )
        self.assertIn("📦 Aktuálna: 9.2.18", pve_body)
        self.assertIn("🆕 Nová: 9.2.20", pve_body)
        self.assertIn("🔧 pve-manager 9.2.18 → 9.2.20", pve_body)

        for language in self.RUNTIME_LANGUAGES:
            locale_data = {**pve_data, "_notification_language": language}
            locale = notification_templates.render_template(
                "pve_update", locale_data, language=language,
            )
            _title, locale_body = notification_templates.enrich_with_emojis(
                "pve_update", locale["title"], locale["body"], locale_data,
            )
            label = notification_templates._localized_template_labels(
                "pve_update", language,
            )["new_version"][0]
            self.assertIn(f"🆕 {label}: 9.2.20", locale_body, language)

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
        rich_digest = manager._compose_digest_body(rows, use_icons=True)
        self.assertIn("📊 Zdroje: 1", rich_digest)
        self.assertIn("• 🔥 01:00  Vysoké využitie CPU", rich_digest)
        title, body, caption = manager._build_test_message(False, False, "groq / sk")
        self.assertEqual(title, "Test ProxMenux")
        self.assertIn("Vitajte", body)
        self.assertIn("profilovú fotografiu", caption)

    def test_monitor_generated_cpu_health_degradation_is_slovak(self):
        data = {
            "hostname": "HomeLAB_2",
            "severity": "CRITICAL",
            "title": "HomeLAB_2: Health CRITICAL - CPU Usage & Temperature",
            "reason": "CPU >95.0% sustained for 296s",
            "health_degraded": {
                "categories": [{
                    "key": "cpu",
                    "status": "CRITICAL",
                    "reason": "CPU >95.0% sustained for 296s",
                    "entity": "",
                }],
            },
        }
        rendered = notification_templates.render_template(
            "health_degraded", data, language="sk",
        )
        self.assertEqual(
            rendered["title"],
            "HomeLAB_2: Kritický stav – Využitie CPU a teplota",
        )
        self.assertEqual(rendered["body"], "CPU je nad 95.0 % už 296 s.")
        self.assertNotIn("Health CRITICAL", rendered["title"])
        self.assertNotIn("sustained", rendered["body"])

        enriched_title, _body = notification_templates.enrich_with_emojis(
            "health_degraded", rendered["title"], rendered["body"],
            {**data, "_notification_language": "sk"},
        )
        self.assertTrue(enriched_title.startswith("⚠️ "))

    def test_batch_app_updates_render_from_every_runtime_catalog(self):
        data = {
            "hostname": "HOST-ŽILINA",
            "updates": [
                {"vmid": 100, "app_name": "AdGuard Home", "installed": "1.0", "latest": "1.1"},
                {"vmid": 115, "app_name": "Redis", "installed": "7.0", "latest": "8.1"},
            ],
        }
        for language in self.RUNTIME_LANGUAGES:
            rendered = notification_templates.render_template(
                "app_update_available", data, language=language,
            )
            self.assertEqual(
                rendered["title"],
                notification_templates.runtime_message(
                    "appUpdates.batchTitle", language,
                    hostname="HOST-ŽILINA", count=2,
                ),
                language,
            )
            self.assertIn("CT 100", rendered["body"], language)
            self.assertIn("• Redis: 7.0 → 8.1", rendered["body"], language)

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

    def test_display_name_replaces_only_the_local_runtime_hostname(self):
        config = {"hostname": "HomeLAB_2"}
        with mock.patch.object(notification_manager.socket, "gethostname", return_value="homelab-2"), \
                mock.patch.object(notification_manager.socket, "getfqdn", return_value="homelab-2.home.lab"):
            self.assertEqual(
                notification_manager.resolve_notification_hostname("homelab-2", config),
                "HomeLAB_2",
            )
            self.assertEqual(
                notification_manager.resolve_notification_hostname("remote-pve", config),
                "remote-pve",
            )

        class RecordingChannel:
            def __init__(self):
                self.payload = None

            def send(self, title, body, severity, data=None):
                self.payload = (title, body, severity, data)
                return {"success": True}

        manager = notification_manager.NotificationManager()
        channel = RecordingChannel()
        manager._channels = {"telegram": channel}
        manager._config = {
            "notification_language": "sk",
            "hostname": "HomeLAB_2",
            "ai_enabled": "false",
            "telegram.rich_format": "false",
        }
        with mock.patch.object(notification_manager.socket, "gethostname", return_value="homelab-2"), \
                mock.patch.object(notification_manager.socket, "getfqdn", return_value="homelab-2.home.lab"), \
                mock.patch.object(manager, "_record_history"):
            result = manager.send_notification(
                "docker_stack_update_available", "INFO", "", "",
                data={"hostname": "homelab-2", "vmid": "210", "ct_name": "repopulse", "count": "1", "details": "Docker Engine"},
                skip_toggle_check=True,
            )

        self.assertTrue(result["success"])
        self.assertIn("HomeLAB_2: Na CT 210 sú dostupné aktualizácie Docker", channel.payload[0])
        self.assertNotIn("homelab-2:", channel.payload[0])

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
        self.assertIn("Server:", html)
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

    def test_future_digest_time_change_resets_only_the_digest_guard(self):
        class FixedDatetime:
            @classmethod
            def now(cls):
                return datetime(2026, 9, 17, 13, 30)

        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "settings.db"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE user_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT, updated_at TEXT)")
            conn.commit()
            conn.close()

            manager = notification_manager.NotificationManager()
            manager._config = {
                "telegram.digest_enabled": "true",
                "telegram.digest_time": "13:20",
                "telegram.digest_last_at": "2026-09-17T13:20:25",
            }
            with mock.patch.object(notification_manager, "DB_PATH", db_path), \
                    mock.patch.object(notification_manager, "datetime", FixedDatetime):
                result = manager.save_settings({
                    "telegram.digest_enabled": "true",
                    "telegram.digest_time": "13:40",
                })

            self.assertTrue(result["success"], result)
            self.assertEqual(manager._config["telegram.digest_last_at"], "")
            conn = sqlite3.connect(db_path)
            stored = conn.execute(
                "SELECT setting_value FROM user_settings WHERE setting_key = ?",
                ("notification.telegram.digest_last_at",),
            ).fetchone()
            conn.close()
            self.assertEqual(stored[0], "")

        manager = notification_manager.NotificationManager()
        manager._config = {
            "telegram.digest_enabled": "true",
            "telegram.digest_time": "13:40",
            "telegram.digest_last_at": "2026-09-17T13:20:25",
        }
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "settings.db"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE user_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT, updated_at TEXT)")
            conn.commit()
            conn.close()
            with mock.patch.object(notification_manager, "DB_PATH", db_path), \
                    mock.patch.object(notification_manager, "datetime", FixedDatetime):
                result = manager.save_settings({
                    "telegram.digest_enabled": "true",
                    "telegram.digest_time": "13:40",
                })
        self.assertTrue(result["success"], result)
        self.assertEqual(manager._config["telegram.digest_last_at"], "2026-09-17T13:20:25")

    def test_ai_language_is_independent_from_runtime_notification_language(self):
        manager = notification_manager.NotificationManager()
        manager._config = {
            "notification_language": "sk",
            "ai_language": "de",
            "ai_provider": "groq",
        }
        self.assertEqual(manager._notification_language(), "sk")
        self.assertEqual(manager._build_ai_config()["ai_language"], "de")

    def test_legacy_runtime_capable_ai_language_is_preserved(self):
        manager = notification_manager.NotificationManager()
        manager._config = {"ai_language": "de"}
        self.assertEqual(manager._notification_language(), "de")
        self.assertEqual(manager.get_settings()["config"]["notification_language"], "de")

        manager._config = {"notification_language": "invalid", "ai_language": "sk"}
        self.assertEqual(manager._notification_language(), "sk")
        manager._config = {"notification_language": "invalid", "ai_language": "de"}
        self.assertEqual(manager._notification_language(), "de")

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

    def test_digest_buffer_coalesces_lxc_results_despite_detail_changes(self):
        manager = notification_manager.NotificationManager()
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "settings.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE digest_pending ("
                "id INTEGER PRIMARY KEY, channel TEXT, event_type TEXT, "
                "event_group TEXT, severity TEXT, ts INTEGER, title TEXT, body TEXT)"
            )
            conn.commit()
            conn.close()

            with mock.patch.object(notification_manager, "DB_PATH", db_path), \
                    mock.patch.object(notification_manager.time, "time", side_effect=(1000, 1060, 1070, 1080, 1301)):
                manager._buffer_digest_event(
                    "telegram", "lxc_update_applied", "vm_ct", "INFO",
                    "pve01: LXC wireguard (101) update completed", "Source: Manual",
                )
                # An adjacent collector can report the same completion with
                # a different source or duration. It must not appear twice.
                manager._buffer_digest_event(
                    "telegram", "lxc_update_applied", "vm_ct", "INFO",
                    "pve01: LXC wireguard (101) update completed", "Source: Scheduled",
                )
                # Other event types still require the full message to match.
                manager._buffer_digest_event(
                    "telegram", "app_update_available", "applications", "INFO",
                    "pve01: Update available", "Version: 1.0 → 1.1",
                )
                manager._buffer_digest_event(
                    "telegram", "app_update_available", "applications", "INFO",
                    "pve01: Update available", "Version: 1.0 → 1.2",
                )
                # The same result is allowed again outside the short window.
                manager._buffer_digest_event(
                    "telegram", "lxc_update_applied", "vm_ct", "INFO",
                    "pve01: LXC wireguard (101) update completed", "Source: Manual",
                )

            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                "SELECT ts, body FROM digest_pending ORDER BY id"
            ).fetchall()
            conn.close()

        self.assertEqual(
            rows,
            [
                (1000, "Source: Manual"),
                (1070, "Version: 1.0 → 1.1"),
                (1080, "Version: 1.0 → 1.2"),
                (1301, "Source: Manual"),
            ],
        )

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
        for language in self.RUNTIME_LANGUAGES:
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
        for language in self.RUNTIME_LANGUAGES:
            self.assertIn(language, build)
        self.assertIn('$APP_DIR/usr/share/proxmenux/messages', build)

    def test_missing_event_type_names_exist_in_both_ui_catalogs(self):
        for language in self.RUNTIME_LANGUAGES:
            path = APPIMAGE_DIR / "messages" / language / "common.json"
            event_types = json.loads(path.read_text(encoding="utf-8"))["settings"]["notifications"]["eventTypes"]
            self.assertIn("lxc_update_applied", event_types)
            self.assertIn("docker_stack_update_available", event_types)


if __name__ == "__main__":
    unittest.main()
