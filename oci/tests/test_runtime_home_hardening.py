"""Exercise HOME resolution without reading image symlinks or changing guests."""

from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))
import oci_runtime


class HomeHardeningTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "etc").mkdir()
        self.passwd = self.root / "etc/passwd"
        self.passwd.write_text("root:x:0:0:root:/root:/bin/sh\n", encoding="utf-8")

    def cli(self, uid="1234"):
        output, error = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["oci_runtime.py", "--home", str(self.passwd), uid]), \
             redirect_stdout(output), redirect_stderr(error):
            status = oci_runtime.main()
        return status, output.getvalue(), error.getvalue()

    def assert_rejected_without_read(self):
        with patch.object(os, "fdopen", side_effect=AssertionError("unsafe file read")):
            status, output, _ = self.cli()
        self.assertEqual(status, 1)
        self.assertEqual(output, "")

    def test_unknown_uid_uses_root_only_after_reading_a_regular_database(self):
        self.assertEqual(self.cli(), (0, "/\n", ""))

    def test_empty_regular_database_uses_root(self):
        self.passwd.write_text("")
        self.assertEqual(self.cli(), (0, "/\n", ""))

    def test_final_symlink_is_rejected_without_reading_its_target(self):
        target = self.root / "outside"
        target.write_text("app:x:1234:1234::/host-secret:/bin/sh\n")
        self.passwd.unlink()
        self.passwd.symlink_to(target)
        self.assert_rejected_without_read()
        self.assertEqual(target.read_text(), "app:x:1234:1234::/host-secret:/bin/sh\n")

    def test_symlinked_etc_is_rejected_without_reading_its_target(self):
        directory = self.root / "etc"
        directory.rename(self.root / "outside-etc")
        directory.symlink_to(self.root / "outside-etc", target_is_directory=True)
        self.assert_rejected_without_read()
        self.assertEqual(self.cli("0")[:2], (1, ""))

    def test_pinned_etc_does_not_follow_a_later_directory_replacement(self):
        original_open = os.open
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "passwd").write_text("root:x:0:0::/outside:/bin/sh\n")
        replaced = []
        def replace(path, flags, *args, **kwargs):
            if str(path) == "passwd":
                (self.root / "etc").rename(self.root / "original-etc")
                (self.root / "etc").symlink_to(outside, target_is_directory=True)
                replaced.append(True)
            return original_open(path, flags, *args, **kwargs)
        with patch.object(os, "open", side_effect=replace):
            self.assertEqual(self.cli("0"), (0, "/root\n", ""))
        self.assertEqual(replaced, [True])

    def test_directory_is_rejected_without_reading(self):
        self.passwd.unlink()
        self.passwd.mkdir()
        self.assert_rejected_without_read()

    def test_fifo_is_rejected_without_reading_or_waiting_for_a_writer(self):
        self.passwd.unlink()
        os.mkfifo(self.passwd)
        done = subprocess.run(
            [sys.executable, "-B", str(ROOT / "remote/oci_runtime.py"), "--home", str(self.passwd), "0"],
            capture_output=True, text=True, timeout=3,
        )
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout, "")
        self.assert_rejected_without_read()

    def test_missing_database_does_not_masquerade_as_unknown_uid(self):
        self.passwd.unlink()
        self.assert_rejected_without_read()

    def test_permission_failure_does_not_masquerade_as_unknown_uid(self):
        with patch.object(os, "open", side_effect=PermissionError("denied")):
            self.assert_rejected_without_read()

    def test_invalid_encoding_does_not_produce_a_fallback(self):
        self.passwd.write_bytes(b"\xff\xfe")
        status, output, _ = self.cli()
        self.assertEqual((status, output), (1, ""))

    def test_partial_matching_record_does_not_produce_a_fallback(self):
        self.passwd.write_text("app:x:1234:1234\n")
        self.assertEqual(self.cli()[:2], (1, ""))

    def test_read_error_closes_both_descriptors_without_a_fallback(self):
        descriptors = []
        original_open = os.open
        def opened(*args, **kwargs):
            fd = original_open(*args, **kwargs)
            descriptors.append(fd)
            return fd
        with patch.object(os, "open", side_effect=opened), \
             patch.object(os, "fdopen", side_effect=OSError("read failed")):
            self.assertEqual(self.cli()[:2], (1, ""))
        self.assertEqual(len(descriptors), 2)
        for fd in descriptors:
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_matching_unsafe_home_is_not_replaced_with_root(self):
        for value in ("", "relative", "/bad\tvalue", "/bad\x00value", "/bad\x7fvalue"):
            with self.subTest(value=repr(value)):
                self.passwd.write_text(f"app:x:1234:1234::{value}:/bin/sh\n")
                self.assertEqual(self.cli()[:2], (1, ""))

    def test_invalid_uid_does_not_open_the_database(self):
        for uid in ("-1", "nobody"):
            with self.subTest(uid=uid), patch.object(os, "open") as opened:
                self.assertEqual(self.cli(uid)[:2], (1, ""))
                opened.assert_not_called()

    def test_symlink_replacement_between_check_and_open_is_not_read(self):
        original_open = os.open
        outside = self.root / "outside"
        outside.write_text("app:x:1234:1234::/outside:/bin/sh\n")
        def replace(path, flags, *args, **kwargs):
            if str(path) == "passwd":
                self.passwd.unlink()
                self.passwd.symlink_to(outside)
            return original_open(path, flags, *args, **kwargs)
        with patch.object(os, "open", side_effect=replace):
            self.assert_rejected_without_read()

    def test_fifo_replacement_between_check_and_open_is_not_read(self):
        original_open = os.open
        def replace(path, flags, *args, **kwargs):
            if str(path) == "passwd":
                self.passwd.unlink()
                os.mkfifo(self.passwd)
            return original_open(path, flags, *args, **kwargs)
        with patch.object(os, "open", side_effect=replace):
            self.assert_rejected_without_read()


class HomeInstallerExecutionTests(unittest.TestCase):
    """Run the real shell HOME function and Python CLI with fake mount boundaries."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "etc").mkdir()
        self.passwd = self.root / "etc/passwd"
        self.passwd.write_text("root:x:0:0:root:/root:/bin/sh\napp:x:1001:1001::/srv/app:/bin/sh\n")
        self.conf = self.root / "guest.conf"
        self.trace = self.root / "trace"
        self.source = (ROOT / "remote/install_oci.sh").read_text()

    def run_home(self, config="unrelated: keep\n", unmount_status=0, mount_status=0):
        self.conf.write_text(config)
        self.trace.write_text("")
        functions = []
        for name in ("ensure_runtime_home", "set_runtime_environment"):
            found = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", self.source, re.M | re.S)
            self.assertIsNotNone(found, name)
            functions.append(found.group(0))
        script = r'''
set -euo pipefail
CONF=$1
FIXTURE_ROOT=$2
TRACE=$3
OCI_RUNTIME_RESOLVER=$4
PYTHON=$5
UNMOUNT_STATUS=$6
MOUNT_STATUS=$7
OCI_LOG="$FIXTURE_ROOT/resolver.log"
VMID=123456789
translate() { printf '%s' "$1"; }
die() { printf '%s\n' "$*" >&2; exit 1; }
mount_ct_rootfs() {
  printf 'mount\n' >> "$TRACE"
  [ "$MOUNT_STATUS" = 0 ] || die 'mount failed'
  rootfs=$FIXTURE_ROOT
  passwd_file="$rootfs/etc/passwd"
}
oci_quiet() { printf '%s\n' "$*" >> "$TRACE"; return "$UNMOUNT_STATUS"; }
python3() { printf 'resolve\n' >> "$TRACE"; command "$PYTHON" -B "$@"; }
'''
        done = subprocess.run(
            ["bash", "-c", script + "\n".join(functions) + "\nensure_runtime_home\nprintf 'continued\\n'\n",
             "bash", str(self.conf), str(self.root), str(self.trace), str(ROOT / "remote/oci_runtime.py"),
             sys.executable, str(unmount_status), str(mount_status)],
            capture_output=True, text=True, timeout=5,
        )
        return done, self.conf.read_text(), self.trace.read_text().splitlines()

    def test_explicit_home_including_empty_never_mounts_or_resolves(self):
        for home in ("/custom", ""):
            config = f"unrelated: keep\nlxc.environment.runtime: HOME={home}\n"
            done, after, trace = self.run_home(config)
            self.assertEqual((done.returncode, after, trace), (0, config, []))

    def test_default_and_effective_uid_write_the_resolved_home_after_unmount(self):
        for uid, expected in ((None, "/root"), (1001, "/srv/app"), (9999, "/")):
            config = "unrelated: keep\n" + (f"lxc.init.uid: {uid}\n" if uid is not None else "")
            done, after, trace = self.run_home(config)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(after, config + f"lxc.environment.runtime: HOME={expected}\n")
            self.assertEqual(trace, ["mount", "resolve", "pct unmount 123456789"])

    def test_invalid_uid_leaves_config_unchanged_without_mount(self):
        config = "lxc.init.uid: not-a-uid\n"
        done, after, trace = self.run_home(config)
        self.assertEqual((done.returncode, after, trace), (0, config, []))

    def test_rejected_input_unmounts_and_preserves_config(self):
        self.passwd.unlink()
        self.passwd.symlink_to(self.root / "missing")
        config = "unrelated: keep\n"
        done, after, trace = self.run_home(config)
        self.assertEqual((done.returncode, after), (0, config))
        self.assertEqual(trace, ["mount", "resolve", "pct unmount 123456789"])

    def test_failed_unmount_stops_before_config_write_for_success_and_failure(self):
        for valid in (True, False):
            if not valid:
                self.passwd.unlink()
            config = "unrelated: keep\n"
            done, after, trace = self.run_home(config, unmount_status=1)
            self.assertNotEqual(done.returncode, 0)
            self.assertEqual(after, config)
            self.assertNotIn("continued", done.stdout)
            self.assertEqual(trace, ["mount", "resolve", "pct unmount 123456789"])

    def test_failed_mount_never_reads_or_writes(self):
        config = "unrelated: keep\n"
        done, after, trace = self.run_home(config, mount_status=1)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(after, config)
        self.assertEqual(trace, ["mount"])


if __name__ == "__main__":
    unittest.main()
