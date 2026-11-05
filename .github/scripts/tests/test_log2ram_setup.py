"""Log2RAM keeps /var/log in RAM while the journal and the task logs of
Proxmox VE and Proxmox Backup Server stay on disk behind a link. An update keeps the size
and interval the host already has."""

import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
KEEP = ROOT / "scripts/global/log2ram_keep_on_disk.sh"
SETUP = ROOT / "scripts/global/log2ram_setup.sh"


@unittest.skipUnless(shutil.which("bash"), "bash is needed")
class KeepOnDiskTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.log = self.root / "var/log"
        (self.log / "journal/abc").mkdir(parents=True)
        (self.log / "journal/abc/system.journal").write_text("entries")
        (self.log / "pveproxy").mkdir()
        (self.log / "pveproxy/access.log").write_text("GET /")
        self.config = self.root / "etc/log2ram.conf"
        self.config.parent.mkdir()
        self.config.write_text("SIZE=128M\nJOURNALD_AWARE=true\nNOTIFICATION=true\n")

    def run_setup(self, edit_failure=False):
        # Extract only the shared setup function, never an administrative caller.
        body = SETUP.read_text().split("pmx_log2ram_setup() {", 1)[1].split("\n}\n", 1)[0]
        body = body.replace("/etc/", str(self.root / "etc") + "/")
        for directory in ("cron.d", "tmpfiles.d"):
            (self.root / "etc" / directory).mkdir(exist_ok=True)
        stubs = r'''
translate() { printf '%s' "$1"; }
msg_info() { :; }
msg_ok() { :; }
pmx_install_pkg() { :; }
_pmx_log2ram_install_release() { :; }
_pmx_log2ram_pbs_logrotate() { :; }
_pmx_log2ram_remove_legacy() { :; }
pmx_edit_file() { local file="$1"; shift; sed -i "$@" "$file"; }
pmx_append_file() { cat >> "$1"; }
pmx_write_file() { cat > "$1"; }
pmx_remove_file() { rm -f "$1"; }
pmx_apply_setting() { :; }
systemctl() { printf '%s\n' "$*" >> "$SYSTEMCTL_TRACE"; }
'''
        if edit_failure:
            # A failed configuration writer must be handled even by root runners.
            stubs += "\npmx_edit_file() { return 1; }\n"
        script = (stubs + "\npmx_log2ram_setup() {" + body + "\n}\n"
                  + "pmx_log2ram_setup 256 3 false\n")
        env = dict(os.environ, SYSTEMCTL_TRACE=str(self.root / "systemctl.trace"),
                   PMX_L2R_TAG="1.7.2", PMX_L2R_SCRIPTS=str(KEEP.parent),
                   PMX_L2R_REVERT_UNIT=str(self.root / "etc/revert.service"))
        return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=10)

    def test_setup_keeps_journal_aware_syncing_until_boot(self):
        self.config.write_text("SIZE=128M\nJOURNALD_AWARE=false\nNOTIFICATION=true\n")
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("JOURNALD_AWARE=true\n", self.config.read_text())
        self.assertIn("SIZE=256M\n", self.config.read_text())
        self.assertFalse((self.log / "journal").is_symlink())
        self.assertEqual((self.root / "systemctl.trace").read_text(), "daemon-reload\n")

    def test_boot_disables_journal_aware_syncing_after_relocation(self):
        self.assertEqual(self.run_setup().returncode, 0)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(os.readlink(self.log / "journal"), "/var/hdd.journal")
        self.assertEqual((self.root / "var/hdd.journal/abc/system.journal").read_text(), "entries")
        self.assertIn("JOURNALD_AWARE=false\n", self.config.read_text())
        self.assertIn("SIZE=256M\n", self.config.read_text())
        # Reapplying the repair to an already-relocated installation is safe.
        self.assertEqual(self.run_setup().returncode, 0)
        self.assertEqual(self.run_script().returncode, 0)
        self.assertIn("JOURNALD_AWARE=false\n", self.config.read_text())
        self.assertEqual(sorted(p.name for p in (self.root / "var/hdd.journal").iterdir()), ["abc"])

    def test_boot_migration_failure_is_not_ignored_by_startup(self):
        self.assertEqual(self.run_setup().returncode, 0)
        # A non-directory destination causes a real copy failure, without mounts.
        conflict = self.root / "var/hdd.journal"
        conflict.write_text("blocked")
        unit = self.root / "etc/systemd/system/log2ram.service.d/proxmenux.conf"
        command = next(line.split("=", 1)[1] for line in unit.read_text().splitlines()
                       if line.startswith("ExecStartPre="))
        result = subprocess.run(["bash", *shlex.split(command.lstrip("-"))],
                                env=dict(os.environ, PMX_L2R_ROOT=str(self.root)),
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("JOURNALD_AWARE=true\n", self.config.read_text())
        self.assertFalse(command.startswith("-"), "systemd must not ignore the helper's failure")
        conflict.unlink()
        self.assertEqual(self.run_script().returncode, 0)
        self.assertIn("JOURNALD_AWARE=false\n", self.config.read_text())

    def test_setup_adds_journal_aware_setting_when_missing(self):
        self.config.write_text("SIZE=128M\n#JOURNALD_AWARE=false\n")
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("\nJOURNALD_AWARE=true\n", self.config.read_text())
        self.assertEqual(self.run_script().returncode, 0)
        self.assertIn("\nJOURNALD_AWARE=false\n", self.config.read_text())

    def check_missing_setting_without_final_newline(self, content):
        self.config.write_text(content)
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in ("true", "false"):
            with self.subTest(journal_aware=expected):
                # Read shell semantics in a fresh Bash, not a substring match.
                sourced = subprocess.run(
                    ["bash", "--noprofile", "--norc", "-c",
                     'unset JOURNALD_AWARE NOTIFICATION; source "$1"; '
                     'printf "%s\\n%s\\n" "${JOURNALD_AWARE-UNSET}" "${NOTIFICATION-UNSET}"',
                     "fixture", str(self.config)],
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(sourced.returncode, 0, sourced.stderr)
                self.assertEqual(sourced.stdout, expected + "\nfalse\n")

            if expected == "true":
                self.assertFalse((self.log / "journal").is_symlink())
                self.assertEqual((self.log / "journal/abc/system.journal").read_text(), "entries")
                result = self.run_script()
                self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(os.readlink(self.log / "journal"), "/var/hdd.journal")
        self.assertEqual((self.root / "var/hdd.journal/abc/system.journal").read_text(), "entries")

    def test_missing_setting_after_comment_without_final_newline(self):
        self.check_missing_setting_without_final_newline(
            "SIZE=128M\nNOTIFICATION=false\n#JOURNALD_AWARE=false")

    def test_missing_setting_after_assignment_without_final_newline(self):
        self.check_missing_setting_without_final_newline("SIZE=128M\nNOTIFICATION=false")

    def test_setup_reports_configuration_edit_failure(self):
        self.config.write_text("SIZE=128M\nJOURNALD_AWARE=false\nNOTIFICATION=false\n")
        result = self.run_setup(edit_failure=True)
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("JOURNALD_AWARE=false\n", self.config.read_text())

    def test_an_existing_link_with_an_unusable_disk_target_fails(self):
        self.assertEqual(self.run_script().returncode, 0)
        self.config.write_text("JOURNALD_AWARE=true\n")
        disk = self.root / "var/hdd.journal"
        shutil.rmtree(disk)
        disk.write_text("blocked")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.config.read_text(), "JOURNALD_AWARE=true\n")

    def test_an_unexpected_journal_link_does_not_complete_migration(self):
        shutil.rmtree(self.log / "journal")
        (self.log / "journal").symlink_to("pveproxy")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertEqual(os.readlink(self.log / "journal"), "pveproxy")
        self.assertIn("JOURNALD_AWARE=true\n", self.config.read_text())

    def test_a_missing_journal_with_an_unusable_disk_target_fails(self):
        shutil.rmtree(self.log / "journal")
        (self.root / "var/hdd.journal").write_text("blocked")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("JOURNALD_AWARE=true\n", self.config.read_text())
        self.assertFalse((self.log / "journal").is_symlink())

    def test_failed_source_removal_does_not_complete_migration(self):
        (self.root / "var/hdd.journal").mkdir()
        result = subprocess.run(
            ["bash", "-c", 'rm() { return 1; }; export -f rm; exec bash "$1"', "fixture", str(KEEP)],
            env=dict(os.environ, PMX_L2R_ROOT=str(self.root)), capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("JOURNALD_AWARE=true\n", self.config.read_text())
        self.assertTrue((self.log / "journal/abc/system.journal").is_file())

    def test_boot_configuration_failure_is_reported_and_can_be_retried(self):
        self.config.unlink()
        self.config.mkdir()
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertEqual(os.readlink(self.log / "journal"), "/var/hdd.journal")
        self.config.rmdir()
        self.config.write_text("JOURNALD_AWARE=true\n")
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.config.read_text(), "JOURNALD_AWARE=false\n")

    def run_script(self, revert=False):
        env = dict(os.environ, PMX_L2R_ROOT=str(self.root), PMX_L2R_REVERT="1" if revert else "0")
        return subprocess.run(["bash", str(KEEP)], env=env, capture_output=True, text=True, timeout=10)

    def test_the_journal_moves_to_disk_behind_a_link(self):
        self.assertEqual(self.run_script().returncode, 0)
        journal = self.log / "journal"
        self.assertTrue(journal.is_symlink())
        self.assertEqual(os.readlink(journal), "/var/hdd.journal")
        self.assertEqual((self.root / "var/hdd.journal/abc/system.journal").read_text(), "entries")
        self.assertTrue((self.log / "pveproxy/access.log").exists())
        self.assertFalse((self.root / "var/hdd.proxmox-backup").exists())

    def test_running_again_changes_nothing(self):
        self.run_script()
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(os.readlink(self.log / "journal"), "/var/hdd.journal")
        self.assertEqual(sorted(p.name for p in (self.root / "var/hdd.journal").iterdir()), ["abc"])

    def test_the_task_logs_of_backup_server_stay_on_disk_too(self):
        (self.log / "proxmox-backup/tasks").mkdir(parents=True)
        (self.log / "proxmox-backup/tasks/active").write_text("task")
        self.run_script()
        self.assertEqual(os.readlink(self.log / "proxmox-backup"), "/var/hdd.proxmox-backup")
        self.assertEqual((self.root / "var/hdd.proxmox-backup/tasks/active").read_text(), "task")

    def test_files_written_back_to_the_folder_join_the_copy_on_disk(self):
        self.run_script()
        (self.log / "journal").unlink()
        (self.log / "journal/def").mkdir(parents=True)
        (self.log / "journal/def/system.journal").write_text("later")
        self.run_script()
        disk = self.root / "var/hdd.journal"
        self.assertEqual(sorted(p.name for p in disk.iterdir()), ["abc", "def"])
        self.assertTrue((self.log / "journal").is_symlink())

    def test_a_host_without_a_journal_folder_gets_one_on_disk(self):
        shutil.rmtree(self.log / "journal")
        self.run_script()
        self.assertTrue((self.root / "var/hdd.journal").is_dir())
        self.assertTrue((self.log / "journal").is_symlink())

    def test_the_task_logs_of_proxmox_ve_stay_on_disk(self):
        (self.log / "pve/tasks").mkdir(parents=True)
        (self.log / "pve/tasks/index").write_text("UPID")
        self.run_script()
        self.assertEqual(os.readlink(self.log / "pve"), "/var/hdd.pve")
        self.assertEqual((self.root / "var/hdd.pve/tasks/index").read_text(), "UPID")

    def test_removing_log2ram_puts_the_folders_back(self):
        (self.log / "proxmox-backup").mkdir()
        self.run_script()
        self.config.unlink()  # Revert must not require or rewrite Log2RAM settings.
        self.assertEqual(self.run_script(revert=True).returncode, 0)
        for name in ("journal", "proxmox-backup"):
            self.assertFalse((self.log / name).is_symlink(), name)
            self.assertTrue((self.log / name).is_dir(), name)
            self.assertFalse((self.root / f"var/hdd.{name}").exists(), name)
        self.assertEqual((self.log / "journal/abc/system.journal").read_text(), "entries")


@unittest.skipUnless(shutil.which("bash"), "bash is needed")
class KeptSettingsTests(unittest.TestCase):
    def read(self, function, files):
        with tempfile.TemporaryDirectory() as folder:
            script = SETUP.read_text()
            for path, content in files.items():
                target = Path(folder) / path.lstrip("/")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
                script = script.replace(path, str(target))
            library = Path(folder) / "setup.sh"
            library.write_text(script)
            result = subprocess.run(["bash", "-c", f'source "{library}"; {function}'],
                                    capture_output=True, text=True, timeout=10)
            return result.stdout.strip()

    def test_the_size_comes_from_the_installed_configuration(self):
        self.assertEqual(self.read("pmx_log2ram_current_size", {"/etc/log2ram.conf": "SIZE=256M\n"}), "256")

    def test_the_interval_comes_from_the_timer_of_this_version(self):
        timer = "[Timer]\nOnCalendar=\nOnCalendar=*-*-* 00/6:55:00\n"
        self.assertEqual(self.read("pmx_log2ram_current_hours",
                                   {"/etc/systemd/system/log2ram-daily.timer.d/proxmenux.conf": timer}), "6")

    def test_the_interval_of_an_earlier_version_is_kept(self):
        cron = "MAILTO=\"\"\n0 */3 * * * root /usr/local/bin/log2ram write >/dev/null 2>&1\n"
        self.assertEqual(self.read("pmx_log2ram_current_hours", {"/etc/cron.d/log2ram": cron}), "3")

    def test_both_modes_offer_a_repair_to_version_2_0_installs(self):
        for filename, function, updater in (
            ("auto_post_install.sh", "install_log2ram_auto", "_update_existing_log2ram_auto"),
            ("customizable_post_install.sh", "configure_log2ram", "_update_existing_log2ram_custom"),
        ):
            with self.subTest(mode=filename), tempfile.TemporaryDirectory() as folder:
                config = Path(folder) / "log2ram.conf"
                config.write_text("JOURNALD_AWARE=false\n")
                source = (ROOT / "scripts/post_install" / filename).read_text()
                body = source.split(function + "() {", 1)[1].split("\n}\n", 1)[0]
                body = body.replace("/etc/log2ram.conf", str(config))
                script = ("pmx_journal_context() { :; }\n"
                          + updater + "() { printf '%s\\n' \"$1\"; }\n"
                          + function + "() {" + body + "\n}\n" + function)
                result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "2.1")

    def test_the_release_is_pinned_to_a_verified_commit(self):
        text = SETUP.read_text()
        self.assertIn('PMX_L2R_TAG="1.7.2"', text)
        self.assertIn('PMX_L2R_COMMIT="f171449530f8984374c8f69fff3c92af813a694b"', text)
        self.assertNotIn("install.sh", text.split("_pmx_log2ram_install_release() {", 1)[1].split("\n}\n", 1)[0])


if __name__ == "__main__":
    unittest.main()
