"""The Rallly entry runs the upstream two-service Compose deployment."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from proxmenux_oci.stack import assess, ordered_services

APPS_PATH = ROOT / "catalog/apps/rallly.json"
CURATED_PATH = ROOT / "catalog/curated/rallly.json"
START = "export SUPPORT_EMAIL="


class RalllyRecipeTests(unittest.TestCase):
    def setUp(self):
        self.recipe = json.loads(APPS_PATH.read_text(encoding="utf-8"))
        self.command = self.recipe["proxmox"]["stack_command_overrides"]["rallly"]

    def test_curated_copy_matches_and_compose_hash_is_current(self):
        self.assertEqual(APPS_PATH.read_bytes(), CURATED_PATH.read_bytes())
        compose = self.recipe["container_contract"]["original_compose"]
        self.assertEqual(hashlib.sha256(compose.encode()).hexdigest(), self.recipe["source"]["compose_sha256"])

    def test_stack_is_accepted_and_only_the_application_command_changes(self):
        self.assertEqual(assess(self.recipe), [])
        services = {service["name"]: service for service in ordered_services(self.recipe)}
        self.assertEqual([s["name"] for s in ordered_services(self.recipe)], ["db", "rallly"])
        self.assertEqual(services["rallly"]["compose"]["command"], self.command)
        declared = {s["name"]: s for s in self.recipe["compose_stack"]["services"]}
        self.assertEqual(services["db"], declared["db"])
        self.assertNotIn("command", services["db"]["compose"])

    def test_optional_settings_are_reserved_empty_in_the_compose(self):
        names = [field["name"]
                 for group in self.recipe["proxmox"]["stack_optional_environment"]
                 for field in group["fields"]]
        self.assertIn("REGISTRATION_ENABLED", names)
        self.assertIn("SMTP_SECURE", names)
        stack_env = next(s for s in self.recipe["compose_stack"]["services"]
                         if s["name"] == "rallly")["compose"]["environment"]
        compose_env = yaml.safe_load(self.recipe["container_contract"]["original_compose"])[
            "services"]["rallly"]["environment"]
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(stack_env[name], "")
                self.assertEqual(compose_env[name], "")

    def test_boolean_settings_are_checked_before_the_upstream_start(self):
        self.assertEqual(self.command[:2], ["/bin/sh", "-ec"])
        script = self.command[2]
        # Proxmox stores the command single-quoted and LXC does not unescape a quote inside it.
        self.assertNotIn("'", script)
        self.assertTrue(script.endswith('setsid ./docker-start.sh & app_pid=$!; wait "$app_pid"'))
        check = script[:script.index(START)] + 'printf "%s|%s" "$REGISTRATION_ENABLED" "$SMTP_SECURE"'
        cases = {"": "|", "true": "true|true", "True": "true|true", "TRUE": "true|true",
                 "false": "false|false", "False": "false|false"}
        for value, expected in cases.items():
            with self.subTest(value=value):
                result = subprocess.run(["sh", "-ec", check], capture_output=True, text=True, timeout=5,
                                        env={"PATH": "/usr/bin:/bin", "REGISTRATION_ENABLED": value,
                                             "SMTP_SECURE": value})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)
        for name in ("REGISTRATION_ENABLED", "SMTP_SECURE"):
            for value in ("yes", "1", "true; id", " true"):
                with self.subTest(name=name, value=value):
                    result = subprocess.run(["sh", "-ec", check], capture_output=True, text=True, timeout=5,
                                            env={"PATH": "/usr/bin:/bin", name: value})
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(result.stderr.strip(), f"{name} must be true or false")


if __name__ == "__main__":
    unittest.main()
