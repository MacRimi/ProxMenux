"""Offline regression tests: execute extracted functions, never source the upgrade.

PATH contains only grep/tee wrappers; apt and repository mutations are shell
fixtures. This is a reviewed fixture, not a security sandbox for arbitrary code.
Run: python3 -m unittest discover -s tests -v
"""
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "scripts/utilities/upgrade_pve8_to_pve9.sh"


def extract(name):
    matches = re.findall(r"^" + re.escape(name) + r"\(\) \{\n.*?^\}",
                         SOURCE.read_text(), re.M | re.S)
    assert len(matches) == 1, name
    return matches[0]


class AptTests(unittest.TestCase):
    def run_fixture(self, entry="apt_update_with_repo_fallback", *, first=100,
                    output="E: network unavailable", retry=0, mode="no-subscription",
                    assume="1", confirm=0, pipefail=False, errexit=False,
                    conditional=False, tee_failure=False):
        with tempfile.TemporaryDirectory(prefix="proxmenux-apt-test-") as tmp:
            root = Path(tmp)
            bindir = root / "bin"
            bindir.mkdir()
            for command in ("grep", "tee"):
                executable = shutil.which(command)
                self.assertIsNotNone(executable)
                wrapper = "#!/bin/bash\n"
                if command == "tee":
                    wrapper += '[[ "$1" == -a && "$2" == "$LOG" && "$#" == 2 ]] || exit 98\n'
                    if tee_failure:
                        wrapper += "exit 1\n"
                wrapper += "exec " + shlex.quote(executable) + ' "$@"\n'
                (bindir / command).write_text(wrapper)
                (bindir / command).chmod(0o700)
            functions = "\n".join(extract(n) for n in (
                "apt_update_with_repo_fallback", "simulate_would_remove_proxmox_ve",
                "guard_against_proxmox_ve_removal"))
            host_path = "/etc/apt/sources.list.d/ceph.sources"
            self.assertEqual(functions.count(host_path), 1)
            functions = functions.replace(host_path, str(root / "ceph.sources"))
            prelude = r'''
translate() { printf '%s' "$1"; }
msg_ok2() { printf 'OK:%s\n' "$*"; }
msg_ok() { msg_ok2 "$@"; }
msg_error() { printf 'ERROR:%s\n' "$*"; }
msg_info() { :; }
msg_warn() { :; }
confirm() { printf 'confirm\n' >> "$EVENTS"; return "$CONFIRM"; }
disable_enterprise_repo_if_present() { printf 'disable\n' >> "$EVENTS"; }
create_pve_repo_nosub_if_missing() { printf 'create\n' >> "$EVENTS"; }
create_ceph_repo_nosub_if_missing() { printf 'ceph\n' >> "$EVENTS"; }
proxmox_repo_candidate_ok() { return 0; }
apt-get() {
  case "$*" in update|'-s dist-upgrade') ;; *) return 97;; esac
  printf '%s\n' "$*" >> "$CALLS"
  if [[ -f "$SEEN" ]]; then
    printf 'retry stdout\n'; printf 'retry stderr\n' >&2
    return "$RETRY"
  fi
  : > "$SEEN"
  local diagnostic
  diagnostic=$(< "$OUTPUT_FILE")
  printf '%s\n' "$diagnostic"
  printf 'first stderr\n' >&2
  return "$FIRST"
}
'''
            call = entry + '\nprintf "CONTINUED:%s\\n" "$REPO_MODE"\n'
            if conditional:
                call = 'if ' + entry + '; then printf "CONTINUED:%s\\n" "$REPO_MODE"; else exit 90; fi\n'
            options = ("set -o pipefail\n" if pipefail else "") + ("set -e\n" if errexit else "")
            # Use a file so large diagnostics do not hit exec's per-variable limit.
            (root / "output").write_text(output)
            env = {"PATH": str(bindir), "LC_ALL": "C", "HOME": tmp,
                   "LOG": str(root / "apt.log"), "EVENTS": str(root / "events"),
                   "CALLS": str(root / "calls"), "SEEN": str(root / "seen"),
                   "FIRST": str(first), "OUTPUT_FILE": str(root / "output"), "RETRY": str(retry),
                   "REPO_MODE": mode, "ASSUME_YES": assume, "CONFIRM": str(confirm)}
            result = subprocess.run(["/bin/bash", "--noprofile", "--norc", "-c",
                                     options + prelude + functions + "\n" + call],
                                    env=env, cwd=tmp, text=True, capture_output=True, timeout=10)
            read = lambda name: (root / name).read_text() if (root / name).exists() else ""
            return result, read("apt.log"), read("events"), read("calls")

    def test_failed_update_is_logged_and_blocks_continuation(self):
        for pipefail in (False, True):
            with self.subTest(pipefail=pipefail):
                result, log, events, calls = self.run_fixture(pipefail=pipefail)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("E: network unavailable", log)
                self.assertIn("first stderr", log)
                self.assertNotIn("CONTINUED", result.stdout)
                self.assertNotIn("OK:", result.stdout)
                self.assertEqual(events, "")
                self.assertEqual(calls, "update\n")

    def test_enterprise_fallback_logs_both_attempts(self):
        for retry in (0, 100):
            with self.subTest(retry=retry):
                result, log, events, calls = self.run_fixture(
                    mode="enterprise", output="401 Unauthorized enterprise.proxmox.com", retry=retry)
                self.assertEqual(result.returncode, 0 if retry == 0 else 1)
                self.assertEqual(events, "disable\ncreate\n")
                self.assertEqual(calls, "update\nupdate\n")
                self.assertIn("401 Unauthorized enterprise.proxmox.com", log)
                self.assertIn("retry stdout", log)
                self.assertIn("retry stderr", log)
                self.assertEqual("CONTINUED:no-subscription" in result.stdout, retry == 0)
                self.assertEqual("OK:APT indexes updated" in result.stdout, retry == 0)

    def test_large_enterprise_diagnostic_still_triggers_fallback(self):
        for diagnostic in ("401 Unauthorized", "enterprise.proxmox.com"):
            for pipefail in (False, True):
                with self.subTest(diagnostic=diagnostic, pipefail=pipefail):
                    result, log, events, calls = self.run_fixture(
                        mode="enterprise", pipefail=pipefail,
                        output=diagnostic + "\n" + "Hit: unrelated repository\n" * 25000)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(events, "disable\ncreate\n")
                    self.assertEqual(calls, "update\nupdate\n")
                    self.assertIn(diagnostic, log)
                    self.assertEqual(log.count("Hit: unrelated repository"), 25000)
                    self.assertIn("first stderr", log)
                    self.assertIn("retry stdout", log)
                    self.assertIn("retry stderr", log)
                    self.assertIn("CONTINUED:no-subscription", result.stdout)
                    self.assertIn("OK:APT indexes updated", result.stdout)

    def test_simulated_removal_blocks_upgrade(self):
        for pipefail in (False, True):
            with self.subTest(pipefail=pipefail):
                result, _, _, calls = self.run_fixture(
                    "guard_against_proxmox_ve_removal", first=0,
                    output="Remv proxmox-ve [8.0]", pipefail=pipefail)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("would be REMOVED", result.stdout)
                self.assertNotIn("simulation passed", result.stdout)
                self.assertNotIn("CONTINUED", result.stdout)
                self.assertEqual(calls, "-s dist-upgrade\n")

    def test_simulation_error_is_not_a_safe_plan(self):
        for pipefail in (False, True):
            for output in ("E: solver failed", "Remv proxmox-ve [8.0]\nE: solver failed"):
                with self.subTest(pipefail=pipefail, output=output):
                    result, log, _, calls = self.run_fixture(
                        "guard_against_proxmox_ve_removal", output=output, pipefail=pipefail)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn("simulation failed", result.stdout)
                    self.assertNotIn("simulation passed", result.stdout)
                    self.assertNotIn("CONTINUED", result.stdout)
                    self.assertIn("E: solver failed", log)
                    self.assertIn("first stderr", log)
                    self.assertEqual(calls, "-s dist-upgrade\n")

    # Characterization/edge coverage; these require no further production changes.
    def test_successful_update_is_logged_without_fallback(self):
        for pipefail in (False, True):
            result, log, events, calls = self.run_fixture(first=0, output="Hit: fixture", pipefail=pipefail)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Hit: fixture", log)
            self.assertIn("first stderr", log)
            self.assertIn("OK:APT indexes updated", result.stdout)
            self.assertNotIn("Hit: fixture", result.stdout)
            self.assertEqual(events, "")
            self.assertEqual(calls, "update\n")

    def test_enterprise_fallback_acceptance_and_decline(self):
        for confirm in (0, 1):
            result, log, events, calls = self.run_fixture(
                mode="enterprise", output="401 Unauthorized", assume="0", confirm=confirm)
            self.assertEqual(result.returncode, confirm)
            self.assertEqual(events, "confirm\n" + ("disable\ncreate\n" if confirm == 0 else ""))
            self.assertEqual(calls, "update\n" * (2 if confirm == 0 else 1))
            self.assertIn("401 Unauthorized", log)
            if confirm:
                self.assertIn("fallback declined", result.stdout)
                self.assertNotIn("CONTINUED", result.stdout)

    def test_unrelated_enterprise_error_does_not_switch_repositories(self):
        result, _, events, calls = self.run_fixture(mode="enterprise")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(events, "")
        self.assertEqual(calls, "update\n")

    def test_nonremoval_plans_pass(self):
        for output in ("Inst proxmox-ve [8.0] (9.0)", "Remv unrelated [1.0]", ""):
            result, log, _, calls = self.run_fixture(
                "guard_against_proxmox_ve_removal", first=0, output=output)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("simulation passed", result.stdout)
            self.assertIn("CONTINUED", result.stdout)
            self.assertIn("first stderr", log)
            self.assertEqual(calls, "-s dist-upgrade\n")

    def test_large_removal_output_cannot_hide_behind_sigpipe(self):
        result, log, _, _ = self.run_fixture(
            "guard_against_proxmox_ve_removal", first=0, pipefail=True,
            output="Remv proxmox-ve [8.0]\n" + "Inst other [1.0]\n" * 4096)
        self.assertEqual(result.returncode, 1)
        self.assertIn("would be REMOVED", result.stdout)
        self.assertEqual(log.count("Inst other [1.0]"), 4096)

    def test_logging_failure_blocks_update_and_simulation(self):
        for entry in ("apt_update_with_repo_fallback", "guard_against_proxmox_ve_removal"):
            result, _, _, _ = self.run_fixture(entry, first=0, tee_failure=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertNotIn("CONTINUED", result.stdout)
            self.assertNotIn("simulation passed", result.stdout)
            self.assertNotIn("OK:APT indexes updated", result.stdout)

    def test_errexit_and_conditional_callers_preserve_failure_handling(self):
        for conditional in (False, True):
            for pipefail in (False, True):
                with self.subTest(conditional=conditional, pipefail=pipefail):
                    result, log, events, _ = self.run_fixture(
                        mode="enterprise", output="401 Unauthorized", errexit=True,
                        conditional=conditional, pipefail=pipefail)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(events, "disable\ncreate\n")
                    self.assertIn("retry stderr", log)
                    result, log, _, _ = self.run_fixture(
                        "guard_against_proxmox_ve_removal", errexit=True,
                        conditional=conditional, pipefail=pipefail)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("simulation failed", result.stdout)
                    self.assertNotIn("CONTINUED", result.stdout)


if __name__ == "__main__":
    unittest.main()
