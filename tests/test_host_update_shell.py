"""Actual wrapper + worker, with every machine effect replaced by local fixtures.

Only fixed filesystem locations are redirected. Package commands and reboot
are inert executables which record calls; no root, network or host update.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HostUpdateShell(unittest.TestCase):
    def test_packaging_copies_required_modules_with_no_host_probe_on_import(self):
        source = (ROOT / 'AppImage/scripts/build_appimage.sh').read_text().splitlines()
        copies = [f'cp "$SCRIPT_DIR/{name}.py" "$APP_DIR/usr/bin/"'
                  for name in ('host_update_jobs', 'kernel_reboot')]
        for line in copies:
            self.assertIn(line, source)
        app = self.folder / 'AppDir'
        (app / 'usr/bin').mkdir(parents=True)
        result = subprocess.run(['/bin/bash', '-c', '\n'.join(copies)],
                                env=dict(os.environ, SCRIPT_DIR=str(ROOT / 'AppImage/scripts'), APP_DIR=str(app)),
                                capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        code = ('import sys; from unittest.mock import patch; sys.path.insert(0,sys.argv[1]); '
                'guard=patch("subprocess.Popen",side_effect=AssertionError("forbidden probe")); '
                'guard.start(); import host_update_jobs,kernel_reboot; '
                'assert host_update_jobs.list_jobs()==[]')
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(app / 'usr/bin')],
                                capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='host-update-shell-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.bin = self.folder / 'bin'
        self.bin.mkdir()
        scripts = self.folder / 'scripts'
        (scripts / 'utilities').mkdir(parents=True)
        (scripts / 'global').mkdir()
        self.calls = self.folder / 'calls'
        self.calls.touch()
        self.lock = self.folder / 'update.lock'
        for name in ('utilities/proxmox_update.sh', 'global/update-pve-safe.sh'):
            text = (ROOT / 'scripts' / name).read_text()
            text = text.replace('/usr/local/share/proxmenux', str(self.folder))
            text = text.replace('/run/proxmenux-host-update.lock', str(self.lock))
            text = text.replace('/var/run/proxmenux-update-', str(self.folder / 'marker-'))
            text = text.replace('/var/run/reboot-required', str(self.folder / 'reboot-required'))
            text = text.replace('/var/log/proxmox-update-', str(self.folder / 'update-'))
            text = text.replace('/tmp/proxmenux_screen_capture_', str(self.folder / 'capture-'))
            (scripts / name).write_text(text)
        (self.folder / 'utils.sh').write_text('''
load_language() { :; }
initialize_cache() { :; }
translate() { printf '%s' "$1"; }
msg_error() { echo "$*"; }
msg_warn() { echo "$*"; }
msg_info() { echo "$*"; }
msg_info2() { echo "$*"; }
msg_ok() { echo "$*"; }
msg_title() { echo "$*"; }
msg_success() { echo "$*"; }
show_proxmenux_logo() { :; }
LOCAL_SCRIPTS="$FIXTURE/scripts"
''')
        # Keep the real confirmation contract added upstream; stub only the
        # package/host effects, not the updater's shared decision helper.
        confirmation = re.search(r'^pmx_confirm_update\(\) \{\n.*?^\}\n',
                                 (ROOT / 'scripts/global/common-functions.sh').read_text(),
                                 re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(confirmation)
        (scripts / 'global/common-functions.sh').write_text('''
pmx_format_upgradable() { cat; }
pmx_dpkg_changes_since() { echo 'package changes fixture'; }
lvm_repair_check() { echo lvm-poststep >> "$CALLS"; }
pmx_rebuild_dkms_after_kernel() { echo dkms-poststep >> "$CALLS"; }
''' + confirmation.group(0))
        (scripts / 'global/utils-install-functions.sh').write_text('ensure_repositories() { return 0; }\n')
        commands = {
            'pveversion': "echo 'pve-manager/9.2.24/test (running kernel: 7.0.14-25-pve)'",
            'df': "printf 'Filesystem 1K-blocks Used Available Use%% Mounted\\nfixture 9999999 1 9999999 1%% /\\n'",
            'uname': "echo 7.0.14-25-pve",
            'dpkg-query': "printf 'install ok installed\\tproxmox-kernel-7.0.14-26-pve-signed\\n'",
            'apt-cache': "echo 'Candidate: 9.2.24'",
            'apt-get': 'echo "apt-get $*" >> "$CALLS"; exit 0',
            'apt': '''echo "apt $*" >> "$CALLS"
if [[ "$1" == list ]]; then
  printf 'Listing...\\npve-manager/stable 9.2.24 amd64 [upgradable from: 9.2.21]\\n'
else
  touch "$FIXTURE/upgrade-started"
  while [[ ! -e "$FIXTURE/release" ]]; do sleep .02; done
  exit "${UPGRADE_EXIT:-0}"
fi''',
            'dialog': 'echo dialog >> "$CALLS"; exit "${CONFIRM_EXIT:-0}"',
            'whiptail': '''echo "whiptail $*" >> "$CALLS"
if [[ "$1" == --title && "$2" == "Proxmox Update" ]]; then exit "${CONFIRM_EXIT:-0}"; fi
exit 1''',
            'reboot': 'echo FORBIDDEN-REBOOT >> "$CALLS"; exit 99',
            'clear': ':',
        }
        for name, body in commands.items():
            path = self.bin / name
            path.write_text('#!/bin/bash\n' + body + '\n')
            path.chmod(0o700)
        self.env = dict(os.environ, PATH=str(self.bin)+':'+os.environ['PATH'],
                        FIXTURE=str(self.folder), CALLS=str(self.calls),
                        EXECUTION_MODE='web', PROXMENUX_HOST_UPDATE_JOB='1')
        self.wrapper = scripts / 'utilities/proxmox_update.sh'
        self.procs = []
        self.addCleanup(self.finish)

    def finish(self):
        (self.folder / 'release').touch()
        for proc in self.procs:
            if proc.poll() is None:
                proc.communicate('\n', timeout=8)

    def start(self, **env):
        proc = subprocess.Popen(['/bin/bash', str(self.wrapper)], env=dict(self.env, **env),
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        self.procs.append(proc)
        return proc

    def wait_upgrade(self):
        until = time.monotonic() + 5
        while not (self.folder / 'upgrade-started').exists():
            self.assertLess(time.monotonic(), until, 'inert upgrade did not start')
            time.sleep(.01)

    def test_web_full_flow_finishes_poststeps_and_footer_without_reboot_or_keypress(self):
        proc = self.start()
        self.wait_upgrade()
        (self.folder / 'release').touch()
        output, _ = proc.communicate(timeout=8)
        self.assertEqual(proc.returncode, 0, output)
        calls = self.calls.read_text()
        self.assertIn('lvm-poststep', calls)
        self.assertIn('dkms-poststep', calls)
        self.assertIn('apt-get -y autoremove', calls)
        self.assertIn('apt-get -y autoclean', calls)
        self.assertNotIn('FORBIDDEN-REBOOT', calls)
        self.assertIn('whiptail --title Proxmox Update --yesno', calls)
        self.assertNotIn('whiptail --title Reboot Required', calls)
        self.assertIn('Reboot Required', output)
        self.assertIn('You can reboot later manually.', output)
        self.assertFalse((self.folder / 'marker-in-progress').exists())
        self.assertTrue((self.folder / 'marker-just-finished').exists())
        log = next(self.folder.glob('update-*.log')).read_text()
        self.assertIn('--- Packages changed (exit 0) ---', log)
        self.assertIn('Finished:', log)

    def test_cancel_before_upgrade_has_no_upgrade_cleanup_or_reboot(self):
        proc = self.start(CONFIRM_EXIT='1')
        output, _ = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 130, output)
        calls = self.calls.read_text()
        for forbidden in ('full-upgrade', 'autoremove', 'autoclean', 'REBOOT', 'poststep'):
            self.assertNotIn(forbidden, calls)

    def test_failure_keeps_failure_and_never_offers_reboot(self):
        (self.folder / 'release').touch()
        proc = self.start(UPGRADE_EXIT='1')
        output, _ = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 1, output)
        for forbidden in ('autoremove', 'autoclean', 'REBOOT', 'poststep', 'whiptail --title Reboot Required'):
            self.assertNotIn(forbidden, self.calls.read_text())

    def test_old_menu_cli_contract_retains_explicit_reboot_prompt(self):
        (self.folder / 'release').touch()
        proc = self.start(PROXMENUX_HOST_UPDATE_JOB='', EXECUTION_MODE='cli')
        output, _ = proc.communicate('\n', timeout=5)
        self.assertEqual(proc.returncode, 0, output)
        self.assertIn('whiptail --title Reboot Required --yesno', self.calls.read_text())
        self.assertNotIn('FORBIDDEN-REBOOT', self.calls.read_text())

    def test_shared_lock_rejects_second_legacy_or_web_caller_before_any_package_call(self):
        first = self.start()
        self.wait_upgrade()
        before = self.calls.read_text()
        for mode in ('cli', 'web'):
            second = self.start(EXECUTION_MODE=mode)
            output, _ = second.communicate(timeout=3)
            self.assertEqual(second.returncode, 75, output)
            self.assertEqual(self.calls.read_text(), before)
            self.assertIn('already running', output)
        self.assertIsNone(first.poll())

    def test_lock_does_not_follow_symlink_or_truncate_existing_file(self):
        target = self.folder / 'protected'
        target.write_text('preserve')
        self.lock.symlink_to(target)
        proc = self.start()
        output, _ = proc.communicate(timeout=3)
        self.assertEqual(proc.returncode, 75, output)
        self.assertEqual(target.read_text(), 'preserve')
        self.assertEqual(self.calls.read_text(), '')
        self.lock.unlink()
        self.lock.write_text('existing metadata')
        proc = self.start(CONFIRM_EXIT='1')
        proc.communicate(timeout=5)
        self.assertEqual(self.lock.read_text(), 'existing metadata')


if __name__ == '__main__':
    unittest.main(verbosity=2)
