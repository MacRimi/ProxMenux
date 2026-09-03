import json
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import lxc_apps

GENERATOR_PATH = Path(__file__).resolve().parents[3] / ".github" / "scripts" / "generate_app_tracking_catalog.py"
GENERATOR_SPEC = importlib.util.spec_from_file_location("app_tracking_generator_under_test", GENERATOR_PATH)
app_tracking_generator = importlib.util.module_from_spec(GENERATOR_SPEC)
sys.modules[GENERATOR_SPEC.name] = app_tracking_generator
GENERATOR_SPEC.loader.exec_module(app_tracking_generator)


VERSION_RE = r"(?i)(?:v|release[-_/]?)?(\d+(?:\.\d+){1,3}(?:[-+._][0-9A-Za-z.-]+)?)"
TRAEFIK_LIVE_RE = r"(?m)^Version:\s*(\d+(?:\.\d+){1,3}(?:[-+._][0-9A-Za-z.-]+)?)"


class LiveVersionDetectionTests(unittest.TestCase):
    def test_runtime_override_wins_over_stale_remote_helper_marker(self):
        """A live detector must survive an older remote catalog entry."""
        stale_remote = {
            "traefik": {
                "installed_via": "file",
                "file_path": "/root/.traefik",
                "file_regex": VERSION_RE,
                "repo": "traefik/traefik",
                "tag_regex": VERSION_RE,
            }
        }
        overrides = {
            "traefik": {
                "operational": True,
                "detector": {
                    "installed_via": "binary",
                    "binary_path": "/usr/bin/traefik",
                    "binary_args": ["version"],
                    "installed_regex": TRAEFIK_LIVE_RE,
                    "repo": "traefik/traefik",
                    "tag_regex": VERSION_RE,
                },
            }
        }

        result = lxc_apps._apply_runtime_verified_overrides(stale_remote, overrides)

        self.assertEqual(result["traefik"]["installed_via"], "binary")
        self.assertEqual(result["traefik"]["binary_path"], "/usr/bin/traefik")
        self.assertNotIn("file_path", result["traefik"])
        self.assertEqual(
            result["traefik"]["file_fallbacks"],
            [{"path": "/root/.traefik", "regex": VERSION_RE, "source": "helper_marker"}],
        )

    def test_fetch_applies_runtime_override_after_remote_catalog_merge(self):
        """The actual fetch path must not let a remote stale entry win."""
        remote = {
            "traefik": {
                "installed_via": "file",
                "file_path": "/root/.traefik",
                "file_regex": VERSION_RE,
            },
            "another-app": {"installed_via": "manual"},
        }
        bundled = {
            "traefik": {
                "installed_via": "binary",
                "binary_path": "/usr/bin/traefik",
                "binary_args": ["version"],
                "installed_regex": TRAEFIK_LIVE_RE,
            }
        }
        overrides = {
            "traefik": {
                "operational": True,
                "detector": dict(bundled["traefik"]),
            }
        }
        response = mock.MagicMock()
        response.read.return_value = json.dumps(remote).encode("utf-8")
        response.__enter__.return_value = response

        previous_cache = lxc_apps._tracking_hints_cache
        previous_ts = lxc_apps._tracking_hints_ts
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                with (
                mock.patch.object(lxc_apps, "_TRACKING_HINTS_DISK", str(Path(temp_dir) / "hints.json")),
                mock.patch.object(lxc_apps, "_load_bundled_hints", return_value=bundled),
                mock.patch.object(lxc_apps, "_load_runtime_verified_overrides", return_value=overrides),
                mock.patch.object(lxc_apps.urllib.request, "urlopen", return_value=response),
                ):
                    lxc_apps._tracking_hints_cache = None
                    lxc_apps._tracking_hints_ts = 0
                    result = lxc_apps._fetch_tracking_hints()
        finally:
            lxc_apps._tracking_hints_cache = previous_cache
            lxc_apps._tracking_hints_ts = previous_ts

        self.assertEqual(result["traefik"]["installed_via"], "binary")
        self.assertEqual(result["traefik"]["binary_path"], "/usr/bin/traefik")
        self.assertNotIn("file_path", result["traefik"])

    def test_runtime_override_promotes_live_detector_and_preserves_helper_marker(self):
        catalog = {
            "traefik": {
                "installed_via": "file",
                "file_path": "/root/.traefik",
                "file_regex": VERSION_RE,
            }
        }
        v2 = {
            "apps": {
                "traefik": {
                    "detectors": [
                        {
                            "installed_via": "file",
                            "file_path": "/root/.traefik",
                            "file_regex": VERSION_RE,
                        }
                    ]
                }
            }
        }
        overrides = {
            "apps": {
                "traefik": {
                    "operational": True,
                    "detector": {
                        "installed_via": "binary",
                        "binary_path": "/usr/bin/traefik",
                        "binary_args": ["version"],
                        "installed_regex": TRAEFIK_LIVE_RE,
                        "repo": "traefik/traefik",
                        "tag_regex": VERSION_RE,
                    },
                }
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "overrides.json"
            path.write_text(__import__("json").dumps(overrides), encoding="utf-8")
            result = app_tracking_generator.apply_runtime_overrides(catalog, v2, path)

        self.assertEqual(result["promoted_to_v1"], ["traefik"])
        self.assertEqual(catalog["traefik"]["installed_via"], "binary")
        self.assertEqual(catalog["traefik"]["binary_path"], "/usr/bin/traefik")
        self.assertEqual(
            catalog["traefik"]["file_fallbacks"],
            [{"path": "/root/.traefik", "regex": VERSION_RE, "source": "helper_marker"}],
        )

    def test_old_helper_marker_migrates_to_new_live_catalog_detector(self):
        """A catalog upgrade repairs already-saved helper sidecars too."""
        app = {
            "id": "app-traefik",
            "name": "Traefik",
            "helper_slug": "traefik",
            "installed_via": "file",
            "file_path": "/root/.traefik",
            "file_regex": VERSION_RE,
            "repo": "traefik/traefik",
            "tag_regex": VERSION_RE,
            "update_command": "custom updater owned by the operator",
            "ports": [{"port": 8080}],
        }
        hint = {
            "installed_via": "binary",
            "binary_path": "/usr/bin/traefik",
            "binary_args": ["version"],
            "installed_regex": TRAEFIK_LIVE_RE,
            "repo": "traefik/traefik",
            "tag_regex": VERSION_RE,
            "file_fallbacks": [{"path": "/root/.traefik", "regex": VERSION_RE}],
        }

        with (
            mock.patch.object(lxc_apps, "_fetch_tracking_hints", return_value={"traefik": hint}),
            mock.patch.object(
                lxc_apps,
                "_pct_exec",
                return_value=(0, "Version:      3.7.12\n", ""),
            ) as run,
        ):
            installed, error, healed = lxc_apps._detect_with_alt_healing(117, app)

        self.assertEqual(installed, "3.7.12")
        self.assertIsNone(error)
        self.assertTrue(healed)
        self.assertEqual(app["installed_via"], "binary")
        self.assertEqual(app["binary_path"], "/usr/bin/traefik")
        self.assertNotIn("file_path", app)
        self.assertEqual(app["update_command"], "custom updater owned by the operator")
        run.assert_called_once_with(117, ["/usr/bin/traefik", "version"])

    def test_helper_marker_remains_safe_fallback_when_live_probe_is_missing(self):
        app = {
            "helper_slug": "example",
            "installed_via": "file",
            "file_path": "/root/.example",
            "file_regex": VERSION_RE,
        }
        hint = {
            "installed_via": "binary",
            "binary_path": "/usr/bin/example",
            "binary_args": ["version"],
            "installed_regex": TRAEFIK_LIVE_RE,
            "file_fallbacks": [{"path": "/root/.example", "regex": VERSION_RE}],
        }

        def probe(_vmid, argv, **_kwargs):
            if argv[0] == "/usr/bin/example":
                return 127, "", "not found"
            self.assertEqual(argv, ["cat", "/root/.example"])
            return 0, "1.2.3\n", ""

        with (
            mock.patch.object(lxc_apps, "_fetch_tracking_hints", return_value={"example": hint}),
            mock.patch.object(lxc_apps, "_pct_exec", side_effect=probe),
        ):
            installed, error, healed = lxc_apps._detect_with_alt_healing(117, app)

        self.assertEqual(installed, "1.2.3")
        self.assertIsNone(error)
        self.assertFalse(healed)
        self.assertEqual(app["installed_via"], "file")

    def test_successful_custom_update_invalidates_only_its_manual_version_claim(self):
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            lxc_apps, "_APPS_DIR", temp_dir
        ):
            sidecar = {
                "vmid": 210,
                "apps": [
                    {
                        "id": "manual-app",
                        "installed_via": "manual",
                        "installed_version": "0.9.0",
                        "state": {},
                    },
                    {
                        "id": "binary-app",
                        "installed_via": "binary",
                        "binary_path": "/usr/bin/example",
                        "state": {},
                    },
                ],
            }
            self.assertTrue(lxc_apps._write_sidecar(210, sidecar))

            self.assertEqual(lxc_apps.mark_manual_versions_unverified(210, ["manual-app"]), 1)
            persisted = lxc_apps._read_sidecar(210)
            manual = persisted["apps"][0]
            binary = persisted["apps"][1]
            self.assertTrue(manual["manual_version_needs_confirmation"])
            self.assertNotIn("manual_version_needs_confirmation", binary)

            with mock.patch.object(lxc_apps, "_fetch_tracking_hints", return_value={}):
                installed, error, healed = lxc_apps._detect_with_alt_healing(210, manual)
            self.assertIsNone(installed)
            self.assertIsNone(error)
            self.assertFalse(healed)


if __name__ == "__main__":
    unittest.main()
