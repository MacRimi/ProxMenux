"""The process of a container reaches LXC as lxc.init.cmd, which LXC splits on
its own terms: a word is bare or wrapped whole in one kind of quote, with no
escapes. Each argument of the Compose command arrives as it was written."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_runtime  # noqa: E402


def lxc_split(text):
    """The splitting of lxc_string_split_quoted() in LXC's string_utils.c."""
    words, state, start = [], " ", 0
    for index, char in enumerate(text):
        if state == " ":
            if char.isspace():
                continue
            start, state = index, char if char in "'\"" else "a"
        elif state == "a":
            if char.isspace():
                words.append(text[start:index])
                state = " "
        elif char == state:
            words.append(text[start + 1:index])
            state = " "
    if state == "a":
        words.append(text[start:])
    return words


class LxcInitCommandTests(unittest.TestCase):
    def entrypoint(self, command, entrypoint):
        with patch.object(oci_runtime, "image_entrypoint", return_value=[]):
            return oci_runtime.effective_entrypoint(Path("image.tar"), command, entrypoint)

    def test_a_shell_command_with_single_quotes_reaches_sh_whole(self):
        command = ["IP=$(ip -4 -o addr show eth0 | awk '{print $4}'); echo $IP; exec sleep infinity"]
        line = self.entrypoint(command, ["/bin/sh", "-c"])
        self.assertEqual(lxc_split(line), ["/bin/sh", "-c", command[0]])

    def test_plain_spaced_empty_and_double_quoted_arguments_survive(self):
        process = ["/app/run", "--name", "two words", "", 'say "hi"', "a'b", "--flag=x"]
        line = self.entrypoint(process[1:], process[:1])
        self.assertEqual(lxc_split(line), process)
        self.assertTrue(line.startswith("/app/run --name 'two words'"))

    def test_an_argument_with_both_quotes_is_refused_by_name(self):
        with self.assertRaises(oci_runtime.RuntimeResolutionError) as raised:
            self.entrypoint(["echo \"it's\""], ["/bin/sh", "-c"])
        self.assertIn("echo \"it's\"", str(raised.exception))


class StartWithoutHealthcheckTests(unittest.TestCase):
    def test_the_installer_checks_the_application_stays_up_without_a_health_check(self):
        text = (ROOT / "remote" / "install_oci.sh").read_text(encoding="utf-8")
        block = text[text.index('detect_container_ipv4 "$(translate "Container started")"'):]
        block = block[:block.index('case "$PASSWORD_STATE" in')]
        self.assertIn("HAS_STARTUP_HEALTHCHECK == 0", block)
        self.assertIn("container_is_running", block)
        self.assertIn('translate "The application stopped during its first start:"', block)


if __name__ == "__main__":
    unittest.main()
