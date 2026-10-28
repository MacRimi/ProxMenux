"""Exercise only the update confirmation widget in a disposable terminal.

No update script is sourced or executed: the shared confirmation function
receives synthetic package names. Requires whiptail; skips without it.
"""

import errno
import fcntl
import os
from pathlib import Path
import pty
import re
import select
import shutil
import signal
import struct
import termios
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
UPDATERS = (
    "update-pve8.sh",
    "update-pve9_2.sh",
    "update-pve-safe.sh",
)


COMMON = ROOT / "scripts/global/common-functions.sh"


def confirmation_function():
    match = re.search(r"^pmx_confirm_update\(\) \{\n.*?^\}\n", COMMON.read_text(),
                      re.MULTILINE | re.DOTALL)
    if not match:
        raise AssertionError("pmx_confirm_update not found")
    return match.group(0)


def confirmation_command():
    """The shared confirmation as an updater calls it; the package list comes
    from UPDATE_CONFIRMATION_TEXT, formatted as pmx_format_upgradable writes it."""
    return (confirmation_function() + 'pmx_confirm_update "Proxmox Update" '
            '"System Update Information\\n\\n" "$UPDATE_CONFIRMATION_TEXT" '
            '"Do you want to proceed with the system update?"')


def run_widget(command, text, keys):
    child, terminal = pty.fork()
    if child == 0:
        fcntl.ioctl(1, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
        environment = dict(os.environ, TERM="xterm-256color", LC_ALL="C",
                           DIALOGRC="/dev/null", UPDATE_CONFIRMATION_TEXT=text)
        # Exit-code overrides must not leak into this isolated test.
        for key in list(environment):
            if key.startswith("DIALOG_"):
                environment.pop(key)
        script = 'translate() { printf "%s" "$1"; }\n' + command
        os.execve("/bin/bash", ["bash", "-c", script], environment)

    output = bytearray()
    sent = False
    status = None
    deadline = time.monotonic() + 8
    try:
        while time.monotonic() < deadline:
            if select.select([terminal], [], [], 0.1)[0]:
                try:
                    chunk = os.read(terminal, 65536)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    chunk = b""
                output.extend(chunk)
            # The widget is ready once both buttons have been drawn.
            plain = re.sub(rb"\x1b(?:\[[0-?]*[ -/]*[@-~]|[()][A-Za-z0-9]|.)", b"", output)
            if not sent and b"Yes" in plain and b"No" in plain:
                os.write(terminal, keys)
                sent = True
            finished, result = os.waitpid(child, os.WNOHANG)
            if finished:
                status = os.waitstatus_to_exitcode(result)
                break
        if status is None:
            raise AssertionError("Confirmation did not respond to keyboard input: " + repr(bytes(output[-2000:])))
        return status, bytes(output)
    finally:
        if status is None:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(child, 0)
        os.close(terminal)


def packages(count, long_every=0):
    """Formatted list lines; every `long_every`-th package spans three lines."""
    lines = []
    for i in range(count):
        if long_every and i % long_every == 0:
            lines += ["  libsamba-{:03d}".format(i), "      2:2.11.0+samba4.22.10+dfsg-0+deb13u1",
                      "    → 2:2.11.0+samba4.22.11+dfsg-0+deb13u1"]
        else:
            lines.append("  package-{:03d}                    1.0 → 2.0".format(i))
    return "\n".join(lines)


@unittest.skipUnless(shutil.which("whiptail"), "whiptail is not installed")
class UpdateConfirmationTest(unittest.TestCase):
    def test_enter_confirms_yes_without_tab_for_short_and_long_lists(self):
        for count in (1, 80, 200):
            with self.subTest(packages=count):
                status, output = run_widget(confirmation_command(), packages(count, 7), b"\r")
                self.assertEqual(status, 0, output)

    def test_tab_can_select_no_and_escape_can_cancel(self):
        for keys, expected in ((b"\t\r", 1), (b"\x1b", 255)):
            with self.subTest(keys=keys):
                status, output = run_widget(confirmation_command(), packages(80), keys)
                self.assertEqual(status, expected, output)

    def test_a_long_list_fits_and_counts_the_packages_left_out(self):
        status, output = run_widget(confirmation_command(), packages(200, 7), b"\r")
        self.assertEqual(status, 0, output)
        plain = re.sub(rb"\x1b(?:\[[0-?]*[ -/]*[@-~]|[()][A-Za-z0-9]|.)", b"", output)
        self.assertIn(b"more packages; the full list is in the update log", plain)
        # A package is shown whole or counted, never cut after its name.
        self.assertNotRegex(plain, rb"libsamba-\d{3}\s+\.\.\.")

    def test_every_updater_asks_through_the_shared_confirmation(self):
        for updater in UPDATERS + ("update-pbs.sh",):
            with self.subTest(updater=updater):
                source = (ROOT / "scripts/global" / updater).read_text()
                self.assertIn("pmx_confirm_update ", source)
                self.assertNotIn("--scrolltext --yesno", source)
                self.assertNotIn("dialog --keep-tite", source)


if __name__ == "__main__":
    unittest.main()
