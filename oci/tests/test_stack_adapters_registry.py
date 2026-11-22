"""Every dedicated stack adapter is declared once, completely, and the engine
finds everything it needs for it in that one table."""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))
sys.path.insert(0, str(ROOT / "src"))

import oci_stack_adapters as adapters
import oci_stack_modify
import oci_stack_native


class RegistryTests(unittest.TestCase):
    def test_every_adapter_declares_what_the_engine_asks(self):
        for script, adapter in adapters.ADAPTERS.items():
            with self.subTest(script=script):
                for key in ("record", "menu_ready", "prerequisites"):
                    self.assertTrue(callable(adapter[key]), key)
                self.assertTrue(adapter["application_paths"])
                self.assertTrue(adapter["label"] and adapter["healthcheck"])
                self.assertNotIn(adapter["main_role"], adapter["dependencies"])
        self.assertTrue(callable(oci_stack_native.adapter_plan))

    def test_the_engine_tables_come_from_the_registry(self):
        self.assertEqual(oci_stack_modify.CONVERTERS, adapters.converters())
        self.assertEqual(adapters.REPLAY_FLAGS,
                         tuple(f"{adapter['name']}_replay" for adapter in adapters.ADAPTERS.values()))

    def test_a_flagged_plan_names_its_adapter(self):
        self.assertIs(adapters.flagged({"tandoor_replay": True}), adapters.ADAPTERS["install_tandoor_stack.sh"])
        self.assertIsNone(adapters.flagged({}))

    def test_no_engine_module_keeps_its_own_list_of_adapters(self):
        # A check of one adapter is its own behavior; two adapters named close
        # together are a list that belongs in the registry.
        name = re.compile(r"install_(?:nextcloud|paperless|tandoor|immich)_stack\.sh|"
                          r"(?:nextcloud|paperless|tandoor|immich)_(?:replay|menu_ready|record|plan)\b")
        for path in (ROOT / "remote/oci_stack_modify.py", ROOT / "remote/oci_stack_native.py",
                     ROOT / "remote/oci_instance_transaction.py",
                     ROOT / "src/proxmenux_oci/management.py", ROOT / "src/proxmenux_oci/stack_recreation.py"):
            with self.subTest(path=path.name):
                found = [(m.start(), m.group(0).split('_')[1] if m.group(0).startswith('install_')
                          else m.group(0).split('_')[0]) for m in name.finditer(path.read_text())]
                close = [(a, b) for (pa, a), (pb, b) in zip(found, found[1:]) if a != b and pb - pa < 160]
                self.assertEqual(close, [])


if __name__ == "__main__":
    unittest.main()
