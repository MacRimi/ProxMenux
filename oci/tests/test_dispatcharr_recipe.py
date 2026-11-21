import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci.catalog import Catalog


class DispatcharrRecipeTest(unittest.TestCase):
    def test_curated_recipes_match_the_shipped_compose(self):
        catalog = Catalog(ROOT)
        for name in ("dispatcharr",):
            with self.subTest(name=name):
                curated = json.loads((ROOT / "catalog" / "curated" / f"{name}.json").read_text())
                shipped = catalog.compose(name)
                compose = shipped["container_contract"]["original_compose"]
                self.assertEqual(compose, curated["container_contract"]["original_compose"])
                self.assertEqual(hashlib.sha256(compose.encode()).hexdigest(), shipped["source"]["compose_sha256"])
                self.assertEqual(catalog.find_item(name)["icon"], shipped["catalog_ui"]["icon"])
                self.assertTrue(shipped["compatibility"]["automatic_install_candidate"])
                self.assertTrue(shipped["proxmox"]["defaults"]["unprivileged"])

    def test_dispatcharr_limits_bundled_services_before_launch(self):
        recipe = Catalog(ROOT).compose("dispatcharr")
        profile = recipe["proxmox"]["installer_profile"]
        generated = profile["generated_files"][0]
        self.assertEqual(generated["container_path"], profile["runtime"]["entrypoint"])
        self.assertEqual(profile["generated_sensitive_environment"]["POSTGRES_PASSWORD"]["bytes"], 32)

        with tempfile.TemporaryDirectory() as tmp:
            entrypoint = Path(tmp) / "entrypoint.sh"
            uwsgi = Path(tmp) / "uwsgi.ini"
            entrypoint.write_text("#!/bin/sh\n# -o '-c port=${POSTGRES_PORT}'\nprintf started\n")
            entrypoint.chmod(0o755)
            uwsgi.write_text(
                "attach-daemon = redis-server --timeout 300\n"
                "attach-daemon = daphne -b 0.0.0.0 -p 8001 example\n"
            )
            script = generated["content"].replace("/app/docker/entrypoint.sh", str(entrypoint))
            script = script.replace("/app/docker/uwsgi.ini", str(uwsgi))
            command = [sys.executable, "-c", script]

            for _ in range(2):
                completed = subprocess.run(command, capture_output=True, text=True, timeout=5)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(completed.stdout, "started")
                self.assertIn("listen_addresses=127.0.0.1", entrypoint.read_text())
                self.assertIn("redis-server --bind 127.0.0.1", uwsgi.read_text())
                self.assertIn("daphne -b 127.0.0.1", uwsgi.read_text())

            uwsgi.write_text("daphne config changed upstream\n")
            refused = subprocess.run(command, capture_output=True, text=True, timeout=5)
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual(refused.stdout, "")
            self.assertIn("no longer matches the loopback profile", refused.stderr)



if __name__ == "__main__":
    unittest.main()
