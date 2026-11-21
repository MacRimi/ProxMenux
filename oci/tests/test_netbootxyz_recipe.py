import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class NetbootXYZRecipeTests(unittest.TestCase):
    def run_startup(self, *, cached_menu=False, pinned_version="", network_recovers=True):
        catalog = Path(__file__).resolve().parents[1] / "catalog"
        profiles = [
            json.loads((catalog / name / "netbootxyz.json").read_text())["proxmox"]["installer_profile"]
            for name in ("apps", "curated")
        ]
        self.assertEqual(profiles[0], profiles[1])
        generated = profiles[0]["generated_files"][0]
        self.assertEqual(profiles[0]["runtime"]["entrypoint"], generated["container_path"])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            menu = config / "menus" / "remote" / "menu.ipxe"
            menu.parent.mkdir(parents=True)
            (config / "menuversion.txt").touch()
            if cached_menu:
                menu.write_text("#!ipxe\n")
            (root / "start.sh").write_text('#!/bin/sh\nprintf "Started with %s\\n" "$MENU_VERSION"\n')
            (root / "sleep").write_text("#!/bin/sh\nexit 0\n")
            (root / "curl").write_text(
                '#!/bin/sh\n'
                'url=""\n'
                'for arg do url=$arg; done\n'
                'printf "%s\\n" "$url" >> "$REQUESTS"\n'
                '[ "$NETWORK_RECOVERS" = 1 ] || exit 6\n'
                '[ "$(wc -l < "$REQUESTS")" -gt 1 ] || exit 6\n'
                'case "$url" in *releases/latest) printf \'{"tag_name":"3.0.3"}\\n\';; esac\n'
            )
            for name in ("curl", "sleep", "start.sh"):
                (root / name).chmod(0o755)

            startup = generated["content"].replace("/config/", f"{config}/").replace("/start.sh", str(root / "start.sh"))
            log = root / "requests"
            env = {
                **os.environ,
                "PATH": f"{root}:{os.environ['PATH']}",
                "MENU_VERSION": pinned_version,
                "NETWORK_RECOVERS": str(int(network_recovers)),
                "REQUESTS": str(log),
            }
            result = subprocess.run(["sh", "-c", startup], env=env, capture_output=True, text=True, timeout=10)
            requests = log.read_text().splitlines() if log.exists() else []
        return result, requests

    def test_retries_dns_and_recovers_an_empty_version_file(self):
        result, requests = self.run_startup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Started with 3.0.3", result.stdout)
        self.assertEqual(len(requests), 3)
        self.assertTrue(requests[-1].endswith("/3.0.3/menus.tar.gz"))

    def test_preserves_explicit_menu_version(self):
        result, requests = self.run_startup(pinned_version="2.0.84")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Started with 2.0.84", result.stdout)
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(url.endswith("/2.0.84/menus.tar.gz") for url in requests))

    def test_existing_menu_starts_without_network(self):
        result, requests = self.run_startup(cached_menu=True, network_recovers=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Started with", result.stdout)
        self.assertEqual(requests, [])

    def test_unavailable_network_fails_after_bounded_retries(self):
        result, requests = self.run_startup(network_recovers=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Could not reach the GitHub menu release", result.stderr)
        self.assertNotIn("Started with", result.stdout)
        self.assertEqual(len(requests), 12)
