"""Exercise only the update confirmation widget in a disposable terminal.

No update script is sourced or executed: the isolated UI command receives
synthetic package names. Requires dialog; skips on systems without it.
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


def confirmation_command(name):
    source = (ROOT / "scripts/global" / name).read_text()
    match = re.search(
        r'^\s*if (?:! )?((?:dialog|whiptail) --(?:keep-tite --)?title '
        r'"\$\(translate "Proxmox Update"\)"[^;]+); then',
        source,
        re.MULTILINE,
    )
    if not match:
        raise AssertionError("Update confirmation not found: " + name)
    return match.group(1)


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
        script = ('translate() { printf "%s" "$1"; }\n'
                  'menu_text=$UPDATE_CONFIRMATION_TEXT\n' + command)
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


@unittest.skipUnless(shutil.which("dialog"), "dialog is not installed")
class UpdateConfirmationTest(unittest.TestCase):
    def test_enter_confirms_yes_without_tab_for_short_and_long_lists(self):
        for updater in UPDATERS:
            for count in (1, 80):
                with self.subTest(updater=updater, packages=count):
                    text = "System Update Information\\n\\n" + "\\n".join(
                        "  package-{:02d}  1.0 -> 2.0".format(i)
                        for i in range(count)
                    ) + "\\n\\nDo you want to proceed with the system update?"
                    status, output = run_widget(confirmation_command(updater), text, b"\r")
                    self.assertEqual(status, 0, output)

    def test_tab_can_select_no_and_escape_can_cancel(self):
        for updater in UPDATERS:
            for keys, expected in ((b"\t\r", 1), (b"\x1b", 255)):
                with self.subTest(updater=updater, keys=keys):
                    status, output = run_widget(confirmation_command(updater), "Confirm update?", keys)
                    self.assertEqual(status, expected, output)

    def test_full_list_remains_scrollable_with_yes_focused(self):
        text = "\\n".join("package-{:03d}".format(i) for i in range(80))
        for updater in UPDATERS:
            with self.subTest(updater=updater):
                # G scrolls to the end of the yes/no text without moving focus.
                status, output = run_widget(confirmation_command(updater), text, b"G\r")
                self.assertEqual(status, 0, output)
                # Curses may repaint only changed digits rather than emit a
                # complete final line. Its 100% indicator confirms the end.
                self.assertIn(b"100%", output)


if __name__ == "__main__":
    unittest.main()
