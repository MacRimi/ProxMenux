"""Exercise the Cloud-Init menu without network access or guest creation."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
SELECTOR = ROOT / "scripts/vm/select_linux_iso.sh"


class CloudInitLauncherTests(unittest.TestCase):
    def run_menu(self, selection="2", body=None, curl_exit=0, dialog_exit=0,
                 installer_exit=0, stdin="\n"):
        source = SELECTOR.read_text(encoding="utf-8")
        match = re.search(r"(?ms)^function select_linux_cloudinit\(\) \{.*?^\}", source)
        assert match is not None, "Cloud-Init menu function not found"
        with tempfile.TemporaryDirectory(prefix="cloudinit-launcher-") as temporary:
            work = Path(temporary)
            (work / "menus").mkdir()
            (work / "menus/create_vm_menu.sh").write_text(
                'printf "menu-returned\\n" >> "$ACTION_LOG"\n', encoding="utf-8")
            environment = os.environ.copy()
            environment.update({
                "LOCAL_SCRIPTS": str(work), "SELECTION": selection,
                "DIALOG_EXIT": str(dialog_exit), "CURL_EXIT": str(curl_exit),
                "INSTALLER_EXIT": str(installer_exit),
                "CURL_BODY": body if body is not None else
                    'printf "helper-executed\\n" >> "$ACTION_LOG"\nexit "$INSTALLER_EXIT"\n',
                "ACTION_LOG": str(work / "actions"),
                "CURL_ARGS": str(work / "curl-args"),
                "DIALOG_LOG": str(work / "dialog-args"),
            })
            prelude = r'''
translate() { printf '%s' "$1"; }
msg_success() { printf 'continue-prompt\n' >> "$ACTION_LOG"; }
whiptail() { printf 'website-prompt\n' >> "$ACTION_LOG"; }
dialog() {
  printf '%s\n' "$@" >> "$DIALOG_LOG"
  if [[ " $* " == *" --menu "* ]]; then
    printf '%s' "$SELECTION" >&2
    return "$DIALOG_EXIT"
  fi
}
curl() {
  printf '%s\n' "$@" > "$CURL_ARGS"
  printf '%s' "$CURL_BODY"
  return "$CURL_EXIT"
}
'''
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-c",
                 prelude + match.group() + "\nselect_linux_cloudinit\n"],
                input=stdin, capture_output=True, text=True, env=environment,
                timeout=5)
            def contents(name):
                path = work / name
                return path.read_text(encoding="utf-8") if path.exists() else ""
            return result, contents("curl-args"), contents("dialog-args"), contents("actions")

    def test_debian_uses_the_maintained_generic_installer(self):
        result, curl_args, _, actions = self.run_menu()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(curl_args.splitlines()[-1],
                         "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/vm/debian-vm.sh")
        self.assertIn("helper-executed", actions)


    def test_ubuntu_uses_one_generic_entry_without_obsolete_release_labels(self):
        result, curl_args, menu, actions = self.run_menu(selection="3")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(curl_args.splitlines()[-1],
                         "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/vm/ubuntu-vm.sh")
        self.assertIn("helper-executed", actions)
        self.assertEqual(menu.count("(Cloud-Init automated)"), 3)
        for obsolete in ("Debian 13", "Debian 12", "Ubuntu 22.04", "Ubuntu 24.04",
                         "Ubuntu 24.10", "Ubuntu 25.04"):
            self.assertNotIn(obsolete, menu)


    def test_failed_or_empty_download_never_runs_a_script(self):
        for body, exit_code in (("404: Not Found", 22),
                                ('printf "helper-executed\\n" >> "$ACTION_LOG"', 28),
                                ("", 0), (" \n\t", 0)):
            with self.subTest(body=body, exit_code=exit_code):
                result, _, messages, actions = self.run_menu(body=body, curl_exit=exit_code)
                self.assertNotIn("helper-executed", actions)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Error: Failed to download the script.", messages)
                self.assertNotIn("menu-returned", actions)


    def test_installer_failure_returns_its_status_without_success_navigation(self):
        result, _, _, actions = self.run_menu(installer_exit=17)
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertIn("helper-executed", actions)
        self.assertNotIn("continue-prompt", actions)
        self.assertNotIn("website-prompt", actions)
        self.assertNotIn("menu-returned", actions)


    def test_arch_and_successful_menu_navigation_are_preserved(self):
        result, curl_args, _, actions = self.run_menu(selection="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(curl_args.splitlines()[-1],
                         "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/vm/archlinux-vm.sh")
        self.assertEqual(actions.splitlines(),
                         ["helper-executed", "continue-prompt", "website-prompt", "menu-returned"])
        arguments = curl_args.splitlines()
        self.assertIn("-fsSL", arguments)
        self.assertEqual(arguments[arguments.index("--connect-timeout") + 1], "5")
        self.assertEqual(arguments[arguments.index("--max-time") + 1], "60")

    def test_return_and_cancel_do_not_download_or_execute(self):
        for selection, status, expected in (("4", 0, 1), ("2", 1, 0), ("2", 255, 0)):
            with self.subTest(selection=selection, status=status):
                result, curl_args, _, actions = self.run_menu(
                    selection=selection, dialog_exit=status)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(curl_args, "")
                self.assertEqual(actions, "")

    def test_unknown_selection_is_rejected(self):
        result, curl_args, _, actions = self.run_menu(selection="999")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(curl_args, "")
        self.assertEqual(actions, "")

    def test_installer_keeps_interactive_standard_input(self):
        body = 'IFS= read -r answer; printf "input:%s\\n" "$answer" >> "$ACTION_LOG"\n'
        result, _, _, actions = self.run_menu(body=body, stdin="answer with spaces\n\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("input:answer with spaces\n", actions)
        self.assertIn("menu-returned", actions)


if __name__ == "__main__":
    unittest.main()
