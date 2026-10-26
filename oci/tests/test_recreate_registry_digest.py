"""A Recreate pins the registry/index digest while downloading a platform manifest."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_installation_state as state
import oci_update_current as update


def digest(data):
    return "sha256:" + state.sha(data)


class RecreateRegistryDigestTests(unittest.TestCase):
    def test_candidate_keeps_the_multi_arch_registry_digest_separate_from_platform_manifest(self):
        platform = json.dumps({
            "schemaVersion": 2,
            "config": {"digest": "sha256:" + "c" * 64},
            "layers": [],
        }).encode()
        index = json.dumps({
            "schemaVersion": 2,
            "manifests": [{"digest": digest(platform),
                           "platform": {"architecture": "amd64", "os": "linux"}}],
        }).encode()
        config = json.dumps({"architecture": "amd64", "os": "linux",
                             "config": {"Labels": {}, "Env": []}}).encode()
        with patch.object(state, "command", side_effect=[index, platform, config]):
            candidate = state.resolve_candidate("postgres@" + digest(index), "amd64")

        self.assertEqual(candidate["registry_digest"], digest(index))
        self.assertEqual(candidate["manifest_digest"], digest(platform))

    def test_recreate_accepts_saved_index_digest_and_returns_platform_manifest(self):
        index_digest = "sha256:" + "a" * 64
        platform_digest = "sha256:" + "b" * 64
        candidate = {"registry_digest": index_digest, "manifest_digest": platform_digest,
                     "layers": [], "created": "2026-10-05T00:00:00Z"}
        desired = {"template": {"container_contract": {"image": {"reference": "postgres:latest"}}},
                   "deployment": {"template_storage": "local"}}
        with patch.object(update, "run_quiet", return_value=json.dumps(candidate)) as query:
            archive, digest_value = update.resolve_archive(
                desired, b"arch: amd64\n", current={"manifest_digest": platform_digest},
                required_digest=index_digest)

        self.assertIsNone(archive)
        self.assertEqual(digest_value, platform_digest)
        self.assertIn("postgres@" + index_digest, query.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
