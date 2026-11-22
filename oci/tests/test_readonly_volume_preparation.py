"""Run the installer's volume preparation loop against filesystem fixtures.

Write doubles reject every mutation of the protected directory, including
lost+found removal. Writable paths keep ordinary directories and run real chmod; chown is recorded
without requiring root. These tests never invoke Proxmox or touch a container.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "remote/install_oci.sh"


def preparation_loop():
    source = INSTALLER.read_text()
    start = source.index("  if (( failed == 0 )) && [[ $(jq -r '.stack_managed")
    end = source.index("\n  if (( failed == 0 && tls_count == 1 )); then", start)
    return source[start:end]


def preparation(target):
    return {
        "container_path": target,
        "remove_lost_found": True,
        "owner_strategy": "mapped-application-user",
        "mode": "0750",
    }


class ReadOnlyVolumePreparationTests(unittest.TestCase):
    def run_case(self, mounts, *, target="/run/secrets", read_only=True,
                 preparations=None):
        preparations = preparations if preparations is not None else [preparation(target)]
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            rootfs = fixture / "rootfs"
            for item in preparations:
                path = rootfs / item["container_path"].lstrip("/")
                path.mkdir(parents=True, exist_ok=True)
                (path / "lost+found").mkdir(exist_ok=True)
            protected = rootfs / target.lstrip("/")
            protected.mkdir(parents=True, exist_ok=True)
            sentinel = protected / "sentinel"
            sentinel.write_bytes(b"existing secret\n")
            sentinel.chmod(0o600)
            protected.chmod(0o700)
            before = sentinel.stat()
            template = {"proxmox": {"installer_profile": {
                "volume_preparations": preparations,
            }}}
            (fixture / "template.json").write_text(json.dumps(template))
            (fixture / "deployment.json").write_text(json.dumps({"mounts": mounts}))
            script = r'''set -Eeuo pipefail
rootfs="$FIXTURE/rootfs"
TEMPLATE_FILE="$FIXTURE/template.json"
DEPLOYMENT_FILE="$FIXTURE/deployment.json"
HOST_BIND_UID=110001; HOST_BIND_GID=110001
HOST_ROOT_UID=100000; HOST_ROOT_GID=100000
SCRIPT_DIR="$REMOTE"
oci_quiet() { printf "WRITE cleanup %s\n" "${!#}"; "$@"; }
failed=0; volumes_prepared=0
oci_log() { printf 'log %s\n' "$*"; }
write_op() {
  local operation=$1
  shift
  local path=${!#}
  printf 'WRITE %s %s\n' "$operation" "$path"
  if [[ -n $PROTECTED && ( $path == "$PROTECTED" || $path == "$PROTECTED/"* ) ]]; then
    printf 'Read-only file system\n' >&2
    return 1
  fi
  case "$operation" in
    rm|chmod) command "$operation" "$@" ;;
    chown) return 0 ;;
  esac
}
chown() { write_op chown "$@"; }
chmod() { write_op chmod "$@"; }
rm() { write_op rm "$@"; }
''' + preparation_loop() + r'''
printf 'failed=%s prepared=%s\n' "$failed" "$volumes_prepared"
test "$failed" = 0
'''
            result = subprocess.run(
                ["bash", "-c", script], capture_output=True, text=True,
                env=dict(os.environ, FIXTURE=str(fixture), REMOTE=str(ROOT / "remote"),
                         PROTECTED=str(protected) if read_only else ""),
                timeout=15,
            )
            self.assertEqual(sentinel.read_bytes(), b"existing secret\n")
            after = sentinel.stat()
            self.assertEqual(
                (before.st_ino, before.st_uid, before.st_gid, before.st_mode, before.st_mtime_ns),
                (after.st_ino, after.st_uid, after.st_gid, after.st_mode, after.st_mtime_ns),
            )
            if read_only:
                self.assertEqual(protected.stat().st_mode & 0o777, 0o700)
                self.assertTrue((protected / "lost+found").is_dir())
            elif "prepared=1" in result.stdout:
                self.assertEqual(protected.stat().st_mode & 0o777, 0o750)
                self.assertTrue((protected / "lost+found").is_dir())
            return result

    def assert_skipped(self, result):
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn("WRITE ", result.stdout)
        self.assertIn("Skipping preparation of read-only volume", result.stdout)
        self.assertIn("prepared=0", result.stdout)

    def assert_prepared(self, result):
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        for operation in ("cleanup", "chown", "chmod"):
            self.assertIn(f"WRITE {operation} ", result.stdout)
        self.assertIn("prepared=1", result.stdout)

    def test_read_only_managed_and_bind_volumes_receive_no_writes(self):
        for mount_type in ("managed-volume", "host-bind"):
            with self.subTest(mount_type=mount_type):
                self.assert_skipped(self.run_case([
                    {"container_path": "/run/secrets", "type": mount_type, "read_only": True},
                ]))

    def test_read_only_parent_protects_nested_preparation(self):
        self.assert_skipped(self.run_case([
            {"container_path": "/run", "read_only": True},
        ]))

    def test_writable_child_overrides_read_only_parent_regardless_of_order(self):
        mounts = [
            {"container_path": "/run", "read_only": True},
            {"container_path": "/run/secrets", "read_only": False},
        ]
        for ordered in (mounts, mounts[::-1]):
            with self.subTest(mounts=ordered):
                self.assert_prepared(self.run_case(ordered, read_only=False))

    def test_child_without_read_only_flag_overrides_read_only_parent(self):
        self.assert_prepared(self.run_case([
            {"container_path": "/run", "read_only": True},
            {"container_path": "/run/secrets"},
        ], read_only=False))

    def test_read_only_child_overrides_writable_parent_regardless_of_order(self):
        mounts = [
            {"container_path": "/run/secrets", "read_only": True},
            {"container_path": "/run", "read_only": False},
        ]
        for ordered in (mounts, mounts[::-1]):
            with self.subTest(mounts=ordered):
                self.assert_skipped(self.run_case(ordered))

    def test_writable_volume_is_still_prepared(self):
        self.assert_prepared(self.run_case([
            {"container_path": "/data", "read_only": False},
        ], target="/data", read_only=False))

    def test_missing_read_only_flag_defaults_to_writable(self):
        self.assert_prepared(self.run_case([
            {"container_path": "/data"},
        ], target="/data", read_only=False))

    def test_unrelated_mount_with_similar_prefix_does_not_skip_preparation(self):
        self.assert_prepared(self.run_case([
            {"container_path": "/run/secret", "read_only": True},
        ], read_only=False))

    def test_directory_outside_mounts_is_still_prepared(self):
        self.assert_prepared(self.run_case([], read_only=False))

    def test_skipping_read_only_volume_does_not_skip_following_writable_volume(self):
        result = self.run_case([
            {"container_path": "/run/secrets", "read_only": True},
            {"container_path": "/data", "read_only": False},
        ], preparations=[preparation("/run/secrets"), preparation("/data")])
        self.assert_prepared(result)
        self.assertIn("Skipping preparation of read-only volume: /run/secrets", result.stdout)
        for line in result.stdout.splitlines():
            if line.startswith("WRITE "):
                self.assertTrue(line.endswith("/data") or line.endswith("/data/lost+found"), line)


if __name__ == "__main__":
    unittest.main()
