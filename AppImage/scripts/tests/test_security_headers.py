import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import security_headers


class SecurityHeadersTests(unittest.TestCase):
    def test_default_csp_blocks_all_frame_ancestors_and_keeps_xfo(self):
        frame_ancestors = security_headers.get_allowed_frame_ancestors({})

        csp = security_headers.build_content_security_policy(frame_ancestors)

        self.assertIn("frame-ancestors 'none'", csp)
        self.assertTrue(security_headers.should_emit_x_frame_options(frame_ancestors))

    def test_primary_env_allows_exact_http_and_https_origins(self):
        frame_ancestors = security_headers.get_allowed_frame_ancestors({
            "PROXMENUX_ALLOWED_FRAME_ANCESTORS": (
                "https://dashboard.example.test, "
                "http://raspberrypi.local:8080 http://10.0.0.5"
            ),
        })

        self.assertEqual(
            frame_ancestors,
            [
                "https://dashboard.example.test",
                "http://raspberrypi.local:8080",
                "http://10.0.0.5",
            ],
        )
        self.assertIn(
            "frame-ancestors https://dashboard.example.test "
            "http://raspberrypi.local:8080 http://10.0.0.5",
            security_headers.build_content_security_policy(frame_ancestors),
        )
        self.assertFalse(security_headers.should_emit_x_frame_options(frame_ancestors))

    def test_compat_env_is_used_when_primary_env_is_empty(self):
        frame_ancestors = security_headers.get_allowed_frame_ancestors({
            "ALLOWED_FRAME_ANCESTORS": "https://legacy.example.test",
        })

        self.assertEqual(frame_ancestors, ["https://legacy.example.test"])

    def test_primary_env_takes_precedence_over_compat_env(self):
        frame_ancestors = security_headers.get_allowed_frame_ancestors({
            "PROXMENUX_ALLOWED_FRAME_ANCESTORS": "https://primary.example.test",
            "ALLOWED_FRAME_ANCESTORS": "https://compat.example.test",
        })

        self.assertEqual(frame_ancestors, ["https://primary.example.test"])

    def test_invalid_and_overly_broad_sources_are_rejected(self):
        frame_ancestors = security_headers.get_allowed_frame_ancestors({
            "PROXMENUX_ALLOWED_FRAME_ANCESTORS": (
                "* https: http://valid.example.test "
                "https://with-path.example.test/app "
                "javascript:alert(1) "
                "https://evil.example.test;frame-src * "
                "https://user:pass@example.test "
                "https://invalid-port.example.test:nope "
                "example.test"
            ),
        })

        self.assertEqual(frame_ancestors, ["http://valid.example.test"])

    def test_self_keyword_is_normalized_and_sources_are_deduplicated(self):
        frame_ancestors = security_headers.get_allowed_frame_ancestors({
            "PROXMENUX_ALLOWED_FRAME_ANCESTORS": (
                "self 'self' HTTPS://Dashboard.Example.Test "
                "https://dashboard.example.test/"
            ),
        })

        self.assertEqual(frame_ancestors, ["'self'", "https://dashboard.example.test"])


if __name__ == "__main__":
    unittest.main()
