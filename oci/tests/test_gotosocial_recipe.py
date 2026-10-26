"""Guard GoToSocial's database configuration and persistent SQLite path."""
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GoToSocialRecipeTests(unittest.TestCase):
    def test_sqlite_database_is_configured_in_both_recipes(self):
        for family in ("apps", "curated"):
            with self.subTest(family=family):
                template = json.loads(
                    (ROOT / "catalog" / family / "gotosocial.json")
                    .read_text(encoding="utf-8")
                )
                service = template["compose_stack"]["services"][0]["compose"]
                environment = service["environment"]
                self.assertEqual(environment["GTS_DB_TYPE"], "sqlite")
                self.assertEqual(
                    environment["GTS_DB_ADDRESS"],
                    "/gotosocial/storage/sqlite.db",
                )

                storage_path = "/gotosocial/storage"
                self.assertIn(
                    storage_path,
                    {
                        volume["container_path"]
                        for volume in template["container_contract"]["volumes"]
                    },
                )
                self.assertIn(
                    "./data:/gotosocial/storage",
                    service["volumes"],
                )

                original = template["container_contract"]["original_compose"]
                self.assertIn("GTS_DB_TYPE: sqlite", original)
                self.assertIn(
                    "GTS_DB_ADDRESS: /gotosocial/storage/sqlite.db",
                    original,
                )


if __name__ == "__main__":
    unittest.main()
