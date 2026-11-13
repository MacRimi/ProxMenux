"""The context prompt sent with each string never reaches the translation."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "build_translation_cache", ROOT / ".github/scripts/build_translation_cache.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ContextCleanupTests(unittest.TestCase):
    def test_every_locale_drops_the_translated_context_prompt(self):
        returned = {
            "ru": "Контекст: Техническое сообщение для Proxmox и ИТ.Перевести: обнаружена сборка (PXVIRT)",
            "es": "Contexto: Mensaje técnico para Proxmox y TI. Traducir: compilación detectada",
            "sk": "Kontext: Technická správa pre Proxmox a IT. Preložiť: zistená zostava",
            "sv": "Sammanhang: Tekniskt meddelande för Proxmox och IT. Översätt: version upptäckt",
        }
        for lang, value in returned.items():
            with self.subTest(lang=lang):
                cleaned = builder.clean_translation(value)
                self.assertNotIn(":", cleaned.split("(")[0])
                self.assertNotIn("Proxmox и ИТ", cleaned)

    def test_leading_capital_follows_the_source(self):
        self.assertEqual(builder.restore_leading_capital("Downstream build", "compilação downstream"),
                         "Compilação downstream")
        self.assertEqual(builder.restore_leading_capital("pct exec failed", "pct exec falló"), "pct exec falló")
        self.assertEqual(builder.restore_leading_capital("Docker", ""), "")


if __name__ == "__main__":
    unittest.main()
