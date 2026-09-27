"""Regression checks for the Slovak wording in the OCI Manager journey."""
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SLOVAK = ROOT / "lang" / "sk.json"


class SlovakOCIWordingTests(unittest.TestCase):
    def test_wizard_and_removal_copy_is_clear(self):
        text = json.loads(SLOVAK.read_text(encoding="utf-8"))
        self.assertEqual(text["Start with Proxmox"], "Spúšťať spolu so spustením Proxmoxu")
        self.assertEqual(text["Start"], "Spustenie")
        self.assertEqual(text["Starting"], "Spúšťanie")
        self.assertEqual(text["Containers that are removed:"], "Kontajnery, ktoré sa odstránia:")
        self.assertEqual(text["The application was removed"], "Aplikácia bola odstránená")


if __name__ == "__main__":
    unittest.main()
