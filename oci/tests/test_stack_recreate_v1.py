"""The coordinated Recreate path must remain distinct from Update."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_stack_native as native


DIGEST = "sha256:" + "a" * 64
MEMBER = {
    "vmid": 138,
    "installation_id": "blinko-installation",
    "template": {"id": "blinko", "container_contract": {"image": {"reference": "blinkospace/blinko:latest"}}},
    "deployment": {"mounts": []},
    "observed": {"config_sha256": "saved-config", "resolved_registry_digest": DIGEST,
                 "image": {"architecture": "amd64", "os": "linux", "defaults": {}}},
    "stack": {"deployment": {"services": [{"vmid": 138, "name": "Blinko",
                                                  "healthcheck": {"type": "running", "timeout_seconds": 120}}]}},
}


class StackRecreateV1Tests(unittest.TestCase):
    def adapter(self):
        plan = {"operation": "recreate", "primary_vmid": 138, "members": [MEMBER]}
        return native.NativeAdapter(Path("/registry"), Path("/journal"), plan)

    def test_prepare_resolves_the_saved_digest_and_builds_an_unchanged_proposal(self):
        adapter = self.adapter()
        image = {"architecture": "amd64", "os": "linux", "defaults": {}}
        with patch.object(native.instances, "read", return_value={}), \
                patch.object(native.instances, "write"), \
                patch.object(native.instances, "location", return_value=Path("/registry/138.json")), \
                patch.object(native.instances, "command", return_value=b"arch: amd64\n"), \
                patch.object(native, "resolve_archive", return_value=(Path("/cache/blinko.tar"), DIGEST)) as resolve, \
                patch.object(native, "image_from_archive", return_value=image):
            prepared = adapter.prepare(MEMBER, "recreate")

        resolve.assert_called_once_with(MEMBER, b"arch: amd64\n", required_digest=DIGEST)
        self.assertEqual(prepared["digest"], DIGEST)
        self.assertEqual(prepared["proposal"]["operation"], "recreate")
        self.assertEqual(prepared["proposal"]["candidate"], MEMBER)
        self.assertEqual(prepared["proposal"]["base_config_sha256"], "saved-config")

    def test_replace_passes_the_recreate_operation_and_proposal_to_every_member(self):
        adapter = self.adapter()
        prepared = {"archive": "/cache/blinko.tar", "digest": DIGEST,
                    "proposal": {"operation": "recreate", "candidate": MEMBER,
                                 "base_config_sha256": "saved-config"}}
        with patch.object(adapter, "validate"), \
                patch.object(adapter, "state", return_value={"backups": {"138": {"archive": "/backup"}}}), \
                patch.object(native, "translate", side_effect=lambda text: text), \
                patch.object(native.member_tx, "apply") as apply:
            adapter.replace(138, prepared, "transaction-id")

        self.assertEqual(apply.call_args.args[3], "recreate")
        self.assertEqual(apply.call_args.kwargs["proposal"], prepared["proposal"])
        self.assertEqual(apply.call_args.kwargs["registry_digest"], DIGEST)
        self.assertIn("Recreating", apply.call_args.kwargs["progress"])

    def test_an_unknown_stack_operation_is_rejected_before_the_stack_is_touched(self):
        with self.assertRaises(ValueError):
            native.run(138, operation="not-a-lifecycle-operation")


if __name__ == "__main__":
    unittest.main()
