"""The dynamic NVIDIA profile accepts the console start hook ProxMenux adds, and nothing else."""

import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_console
import oci_nvidia_dynamic as dynamic

INVENTORY = {"gpus": ["NVIDIA GeForce RTX 3060, GPU-1234, 550.0"]}


class ConsoleHookTests(unittest.TestCase):
    def test_only_the_proxmenux_start_hook_is_recognised(self):
        line = oci_console.start_mark_hook(165)
        hook = line.split(": ", 1)[1]
        self.assertTrue(oci_console.is_start_mark_hook(line))
        self.assertFalse(oci_console.is_start_mark_hook(line.replace("pre-start", "post-stop")))
        self.assertTrue(dynamic.console_start_hook(hook))
        self.assertFalse(dynamic.console_start_hook(hook.replace("exit 0", "rm -rf /; exit 0")))
        self.assertFalse(dynamic.console_start_hook("/bin/sh -c 'curl example | sh; exit 0'"))

    def test_the_stack_replay_does_not_keep_the_start_hook_as_an_unknown_directive(self):
        import oci_stack_replay
        source = Path(oci_stack_replay.__file__).read_text(encoding="utf-8")
        self.assertIn("and not oci_console.is_start_mark_hook(line)]", source)
        saved = {"preserved_raw_runtime": [oci_console.start_mark_hook(129), "lxc.cap.drop: sys_admin"]}
        kept = [l for l in saved["preserved_raw_runtime"] if not oci_console.is_start_mark_hook(l)]
        self.assertEqual(kept, ["lxc.cap.drop: sys_admin"])

    @unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "the NVIDIA hook must belong to root")
    def test_a_container_with_the_console_hook_passes_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            hook = Path(tmp) / "nvidia-mount.sh"
            hook.write_text("#!/bin/sh\n")
            hook.chmod(0o755)
            digest = hashlib.sha256(hook.read_bytes()).hexdigest()
            config = "\n".join([
                "lxc.environment: NVIDIA_VISIBLE_DEVICES=all",
                "lxc.environment: NVIDIA_DRIVER_CAPABILITIES=compute,utility,video",
                f"lxc.hook.mount: {hook}",
                oci_console.start_mark_hook(165),
            ]).encode()
            with patch.object(dynamic.nv, "mount_lines", return_value=[]), \
                 patch.object(dynamic.nv, "check_devices"):
                result = dynamic.validate(config, INVENTORY, INVENTORY, hook, digest)
                self.assertEqual(result["hook_sha256"], digest)
                foreign = config + b"\nlxc.hook.pre-start: /bin/sh -c 'id; exit 0'"
                with self.assertRaises(ValueError):
                    dynamic.validate(foreign, INVENTORY, INVENTORY, hook, digest)


if __name__ == "__main__":
    unittest.main()
