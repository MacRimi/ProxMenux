"""Log2RAM syncs only the archived journal files, so the active file it found
on disk when it was installed stays there and is restored at every boot.
journald then continues an old sequence and deletes its newest archives first.
The post-install makes the sync remove that file from the disk copy."""

from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
SHARED = ROOT / "scripts/global/utils-install-functions.sh"
FLOWS = {"auto_post_install.sh": "install_log2ram_auto", "customizable_post_install.sh": "configure_log2ram"}

# The sync of Log2RAM in its journald-aware mode, as its project ships it.
JOURNALD_AWARE = '''#!/usr/bin/env bash
sync_to_disk() {
    is_safe

    local optional_params=()

    if journald_logrotate; then
        optional_params+=("--include=journal/*/*@*.journal")
        optional_params+=("--exclude=journal/*/*")
    fi

    rsync -aXv --no-acls --delete-after "${optional_params[@]}" "${RAM_LOG}"/ "${HDD_LOG}"/
}
'''
NOT_AWARE = '''#!/usr/bin/env bash
sync_to_disk() {
    rsync -aXv --delete-after "${RAM_LOG}"/ "${HDD_LOG}"/
}
'''


def gnu_sed():
    return shutil.which("bash") and subprocess.run(["sed", "--version"], capture_output=True).returncode == 0


@unittest.skipUnless(gnu_sed(), "bash and GNU sed are needed")
class Log2ramJournalSyncTests(unittest.TestCase):
    def correct(self, folder, content, times=1):
        script = Path(folder) / "log2ram"
        script.write_text(content)
        script.chmod(0o755)
        calls = "; ".join(['pmx_log2ram_drop_stale_journal "$1"; echo "rc=$?"'] * times)
        # As the change journal does, the new content is read whole before it is written.
        write = 'pmx_write_file() { local content; content="$(cat)"; printf "%s\\n" "$content" > "$1"; }'
        run = subprocess.run(["bash", "-c", f'source "{SHARED}"; {write}; {calls}',
                              "bash", str(script)], capture_output=True, text=True, check=False)
        return script, run.stdout.split()

    def test_the_sync_removes_what_it_does_not_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            script, results = self.correct(folder, JOURNALD_AWARE)
            lines = script.read_text().splitlines()
            position = lines.index('        optional_params+=("--exclude=journal/*/*")')
            self.assertEqual(lines[position + 1], '        optional_params+=("--delete-excluded")')
            self.assertEqual(lines[position + 2], "    fi")
            self.assertEqual(results, ["rc=0"])
            self.assertEqual(subprocess.run(["bash", "-n", str(script)]).returncode, 0)
            self.assertTrue(script.stat().st_mode & stat.S_IXUSR)
            self.assertEqual(Path(str(script) + ".proxmenux.bak").read_text(), JOURNALD_AWARE)

    def test_it_is_applied_once(self):
        with tempfile.TemporaryDirectory() as folder:
            script, results = self.correct(folder, JOURNALD_AWARE, times=2)
            self.assertEqual(results, ["rc=0", "rc=1"])
            self.assertEqual(script.read_text().count("--delete-excluded"), 1)

    def test_a_sync_that_copies_every_file_is_left_as_it_is(self):
        with tempfile.TemporaryDirectory() as folder:
            script, results = self.correct(folder, NOT_AWARE)
            self.assertEqual(results, ["rc=1"])
            self.assertEqual(script.read_text(), NOT_AWARE)
            self.assertFalse(Path(str(script) + ".proxmenux.bak").exists())

    def test_both_flows_apply_it_to_new_and_existing_installations(self):
        for name, function in FLOWS.items():
            with self.subTest(flow=name):
                text = (ROOT / "scripts/post_install" / name).read_text()
                self.assertEqual(text.count("pmx_log2ram_drop_stale_journal"), 2)
                # An existing installation is told that it needs a reboot.
                self.assertIn('if pmx_log2ram_drop_stale_journal "$log2ram_bin"; then\n        NECESSARY_REBOOT=1', text)
                # The version is what offers the update to existing installations.
                version = re.search(rf'{function}\(\) {{\n    local FUNC_VERSION="([0-9.]+)"', text)
                self.assertIsNotNone(version)
                self.assertGreaterEqual(tuple(map(int, version.group(1).split("."))), (1, 7))

    def test_rotated_logs_are_compressed_at_once_on_a_tmpfs_var_log(self):
        # A rotated log kept uncompressed filled the 128M Log2RAM of a PBS.
        for name, function in FLOWS.items():
            with self.subTest(flow=name):
                text = (ROOT / "scripts/post_install" / name).read_text()
                self.assertNotIn("delaycompress", text)
                version = re.search(rf'{function}\(\) {{\n    local FUNC_VERSION="([0-9.]+)"', text)
                self.assertGreaterEqual(tuple(map(int, version.group(1).split("."))), (1, 8))


if __name__ == "__main__":
    unittest.main()
