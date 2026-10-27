"""Log2RAM keeps /var/log in RAM while the journal and the task logs of
Proxmox VE and Proxmox Backup Server stay on disk behind a link. An update keeps the size
and interval the host already has."""

import os
from pathlib import Path
import shutil
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

    def run_script(self, revert=False):
        env = dict(os.environ, PMX_L2R_ROOT=str(self.root), PMX_L2R_REVERT="1" if revert else "0")
        return subprocess.run(["bash", str(KEEP)], env=env, capture_output=True, text=True)

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
                                    capture_output=True, text=True)
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

    def test_the_release_is_pinned_to_a_verified_commit(self):
        text = SETUP.read_text()
        self.assertIn('PMX_L2R_TAG="1.7.2"', text)
        self.assertIn('PMX_L2R_COMMIT="f171449530f8984374c8f69fff3c92af813a694b"', text)
        self.assertNotIn("install.sh", text.split("_pmx_log2ram_install_release() {", 1)[1].split("\n}\n", 1)[0])


if __name__ == "__main__":
    unittest.main()
