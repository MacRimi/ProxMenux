import hashlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci.catalog import Catalog


class MediaAppRecipesTest(unittest.TestCase):
    def test_curated_recipes_match_the_shipped_compose(self):
        catalog = Catalog(ROOT)
        for name in ("jellystat", "tunarr"):
            with self.subTest(name=name):
                curated = json.loads((ROOT / "catalog" / "curated" / f"{name}.json").read_text())
                shipped = catalog.compose(name)
                compose = shipped["container_contract"]["original_compose"]
                self.assertEqual(compose, curated["container_contract"]["original_compose"])
                self.assertEqual(hashlib.sha256(compose.encode()).hexdigest(), shipped["source"]["compose_sha256"])
                self.assertEqual(catalog.find_item(name)["icon"], shipped["catalog_ui"]["icon"])
                self.assertTrue(shipped["compatibility"]["automatic_install_candidate"])
                self.assertTrue(shipped["proxmox"]["defaults"]["unprivileged"])

    def test_tunarr_points_the_database_at_its_managed_volume(self):
        recipe = Catalog(ROOT).compose("tunarr")
        runtime = recipe["proxmox"]["installer_profile"]["runtime"]
        service = next(item for item in recipe["compose_stack"]["services"] if item["is_main"])
        self.assertEqual(runtime["command"], ["server", "--database", "/config/tunarr"])
        self.assertEqual(service["compose"]["command"], runtime["command"])
        self.assertTrue(any(volume["container_path"] == "/config/tunarr"
                            for volume in recipe["container_contract"]["volumes"]))

    def test_jellystat_forwards_the_container_stop_signal(self):
        recipe = Catalog(ROOT).compose("jellystat")
        service = next(item for item in recipe["compose_stack"]["services"] if item["is_main"])
        with tempfile.TemporaryDirectory() as tmp:
            node = Path(tmp) / "node"
            node.write_text("#!/bin/sh\ntrap 'printf stopped; exit 0' TERM\necho ready\nwhile :; do sleep 0.1; done\n")
            node.chmod(0o755)
            env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}"}
            with subprocess.Popen(service["compose"]["command"], env=env, text=True, start_new_session=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) as running:
                try:
                    ready, _, _ = select.select([running.stdout], [], [], 5)
                    self.assertTrue(ready, "Jellystat startup did not launch the server")
                    self.assertEqual(running.stdout.readline().strip(), "ready")
                    running.terminate()
                    out, err = running.communicate(timeout=5)
                    self.assertEqual(running.returncode, 0, err)
                    self.assertEqual(out, "stopped")
                finally:
                    if running.poll() is None:
                        os.killpg(running.pid, signal.SIGKILL)

    def test_jellystat_database_is_private_and_uses_a_shared_generated_password(self):
        recipe = Catalog(ROOT).compose("jellystat")
        stack = recipe["compose_stack"]
        services = {service["name"]: service for service in stack["services"]}
        postgres = services["postgres"]
        self.assertFalse(postgres["frontend_network"])
        self.assertTrue(postgres["private_network"])
        self.assertFalse(postgres["compose"].get("ports"))
        self.assertEqual(services["jellystat"]["depends_on"], ["postgres"])
        self.assertEqual(services["jellystat"]["compose"]["environment"]["POSTGRES_IP"], postgres["name"])

        secrets = {
            secret["id"]: {(binding["service"], binding["environment_variable"]) for binding in secret["bindings"]}
            for secret in stack["installer_inputs"]["generated_secrets"]
        }
        self.assertEqual(secrets["db-password"], {
            ("jellystat", "POSTGRES_PASSWORD"), ("postgres", "POSTGRES_PASSWORD"),
        })
        self.assertEqual(secrets["jwt-secret"], {("jellystat", "JWT_SECRET")})


if __name__ == "__main__":
    unittest.main()
