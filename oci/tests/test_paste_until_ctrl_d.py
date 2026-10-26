"""A pasted definition ends with one Ctrl+D, also when it is pressed at the
end of the last line instead of on an empty one."""

import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci import custom


def read_pasted(limit):
    with patch.object(custom.console, "show_logo"), patch.object(custom.console, "msg_title"), \
            patch.object(custom.console, "msg_info2"), patch("builtins.print"):
        return custom._read_pasted(None, limit=limit)

COMPOSE = "services:\n  app:\n    image: nginx:latest\n"


@unittest.skipUnless(hasattr(os, "openpty"), "needs a pseudo terminal")
class PasteUntilCtrlDTests(unittest.TestCase):
    def read(self, typed: bytes, limit: int = 1024) -> str:
        controller, terminal = os.openpty()
        with os.fdopen(terminal, "r") as stdin, patch("sys.stdin", stdin):
            os.write(controller, typed)
            try:
                return read_pasted(limit)
            finally:
                os.close(controller)

    def test_ctrl_d_on_an_empty_line(self):
        self.assertEqual(self.read(COMPOSE.encode() + b"\x04"), COMPOSE)

    def test_ctrl_d_at_the_end_of_the_last_line(self):
        self.assertEqual(self.read(COMPOSE.rstrip("\n").encode() + b"\x04"), COMPOSE.rstrip("\n"))

    def test_reading_stops_past_the_limit(self):
        text = self.read(b"a: 1\n" * 20 + b"\x04", limit=10)
        self.assertGreater(len(text), 10)
        self.assertLess(len(text), 100)


class PastedFromAPipeTests(unittest.TestCase):
    def test_a_pipe_is_read_to_its_end(self):
        with patch("sys.stdin", io.StringIO(COMPOSE)):
            self.assertEqual(read_pasted(1024), COMPOSE)


if __name__ == "__main__":
    unittest.main()
