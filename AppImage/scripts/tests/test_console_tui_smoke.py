"""Terminal smoke tests of the console TUI: a real pty and real curses.

Run on a QA host (they need a pty, ncurses and a few seconds each). The
output is fed to a small terminal model, so the tests look at the screen the
operator would see, not at raw bytes that curses only sends when a cell
changes.
"""

import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import sys
import tempfile
import termios
import time
import unittest


SCRIPTS = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "console"
# Characters of bar and graph cells in every glyph mode, as a terminal shows them.
GLYPH_CHARS = set("_#█▒·~:")
CLEAR = (b"\x1b[2J", b"\x1b[H\x1b[J")
GARBAGE = "\u00a4"  # never drawn by the console
SETAF = re.compile(rb"\x1b\[3[0-7]m")


class Terminal:
    """Enough of a VT100/linux console to rebuild the screen from curses output.

    Each cell keeps ``(char, reverse, alternate charset)``.
    """

    def __init__(self, rows, cols):
        self.rows, self.cols = rows, cols
        self.cells = [[(" ", False, False)] * cols for _ in range(rows)]
        self.y = self.x = 0
        self.wrap = False
        self.reverse = self.acs = False
        self.saved = (0, 0)
        self.top, self.bottom = 0, rows - 1
        self.rest = b""

    def text(self, row):
        return "".join(cell[0] for cell in self.cells[row])

    def screen(self):
        return [self.text(row) for row in range(self.rows)]

    def contains(self, text):
        return any(text in line for line in self.screen())

    def _blank(self):
        return (" ", self.reverse, False)

    def _scroll(self, count=1):
        for _ in range(count):
            del self.cells[self.top]
            self.cells.insert(self.bottom, [self._blank()] * self.cols)

    def _linefeed(self):
        if self.y == self.bottom:
            self._scroll()
        else:
            self.y = min(self.rows - 1, self.y + 1)

    def _put(self, char):
        if self.wrap:
            self.x, self.wrap = 0, False
            self._linefeed()
        self.cells[self.y][self.x] = (char, self.reverse, self.acs)
        if self.x == self.cols - 1:
            self.wrap = True
        else:
            self.x += 1

    def _move(self, y=None, x=None):
        if y is not None:
            self.y = max(0, min(self.rows - 1, y))
        if x is not None:
            self.x = max(0, min(self.cols - 1, x))
        self.wrap = False

    def _csi(self, params, final):
        if params.startswith(("?", ">", "=")):
            return
        values = [int(value) if value.isdigit() else None for value in params.split(";")]
        first = values[0] if values[0] is not None else 0
        count = first or 1
        row = self.cells[self.y]
        if final in "Hf":
            column = values[1] if len(values) > 1 and values[1] else 1
            self._move(count - 1, column - 1)
        elif final == "A":
            self._move(self.y - count)
        elif final == "B":
            self._move(self.y + count)
        elif final == "C":
            self._move(x=self.x + count)
        elif final == "D":
            self._move(x=self.x - count)
        elif final in "G`":
            self._move(x=count - 1)
        elif final == "d":
            self._move(count - 1)
        elif final == "K":
            span = {0: range(self.x, self.cols), 1: range(0, self.x + 1)}.get(
                first, range(self.cols))
            for column in span:
                row[column] = self._blank()
        elif final == "J":
            if first == 0:
                rows = range(self.y + 1, self.rows)
                for column in range(self.x, self.cols):
                    row[column] = self._blank()
            elif first == 1:
                rows = range(0, self.y)
                for column in range(0, self.x + 1):
                    row[column] = self._blank()
            else:
                rows = range(self.rows)
            for index in rows:
                self.cells[index] = [self._blank()] * self.cols
        elif final == "X":
            for column in range(self.x, min(self.cols, self.x + count)):
                row[column] = self._blank()
        elif final == "@":
            row[self.x:] = ([self._blank()] * count + row[self.x:])[:self.cols - self.x]
        elif final == "P":
            row[self.x:] = (row[self.x + count:] + [self._blank()] * count)[:self.cols - self.x]
        elif final in "LM":
            for _ in range(count):
                if final == "L":
                    del self.cells[self.bottom]
                    self.cells.insert(self.y, [self._blank()] * self.cols)
                else:
                    del self.cells[self.y]
                    self.cells.insert(self.bottom, [self._blank()] * self.cols)
        elif final == "r":
            top = (values[0] or 1) - 1
            bottom = (values[1] if len(values) > 1 and values[1] else self.rows) - 1
            self.top, self.bottom = top, bottom
            self._move(0, 0)
        elif final == "S":
            self._scroll(count)
        elif final == "m":
            for value in values:
                value = value or 0
                if value in (0, 27):
                    self.reverse = False
                elif value == 7:
                    self.reverse = True

    def feed(self, data):
        data = self.rest + data
        index = 0
        while index < len(data):
            byte = data[index]
            if byte == 0x1b:
                if index + 1 >= len(data):
                    break
                kind = data[index + 1]
                if kind == ord("["):
                    end = index + 2
                    while end < len(data) and not 0x40 <= data[end] <= 0x7e:
                        end += 1
                    if end >= len(data):
                        break
                    self._csi(data[index + 2:end].decode("latin-1"), chr(data[end]))
                    index = end + 1
                    continue
                if kind in b"()#":
                    if index + 2 >= len(data):
                        break
                    index += 3
                    continue
                if kind == ord("7"):
                    self.saved = (self.y, self.x)
                elif kind == ord("8"):
                    self._move(*self.saved)
                elif kind == ord("M"):
                    self._move(self.y - 1)
                elif kind == ord("D"):
                    self._linefeed()
                elif kind == ord("c"):
                    self.__init__(self.rows, self.cols)
                index += 2
                continue
            if byte >= 0x80:
                length = 2 if byte >> 5 == 6 else 3 if byte >> 4 == 14 else 4 if byte >> 3 == 30 else 1
                if index + length > len(data):
                    break
                self._put(data[index:index + length].decode("utf-8", "replace"))
                index += length
                continue
            if byte == 0x0e:
                self.acs = True
            elif byte == 0x0f:
                self.acs = False
            elif byte == 0x0d:
                self._move(x=0)
            elif byte == 0x0a:
                self.wrap = False
                self._linefeed()
            elif byte == 0x08:
                self._move(x=self.x - 1)
            elif byte == 0x09:
                self._move(x=(self.x // 8 + 1) * 8)
            elif 0x20 <= byte < 0x7f:
                self._put(chr(byte))
            index += 1
        self.rest = data[index:]


class Session:
    """The TUI on a pty of ``rows`` × ``cols`` with ``TERM=term``."""

    def __init__(self, test, args, rows=24, cols=80, term="linux"):
        self.terminal = Terminal(rows, cols)
        self.raw = bytearray()
        self.code = None
        self.closed = False
        child, master = pty.fork()
        if child == 0:
            try:
                fcntl.ioctl(1, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
                os.chdir(test.other_cwd)
                os.environ["TERM"] = term
                os.environ["LANG"] = "C.UTF-8"
                for name in ("APPDIR", "LC_ALL", "LC_CTYPE"):
                    os.environ.pop(name, None)
                os.execv(sys.executable, [sys.executable, "-I", str(SCRIPTS / "console_tui.py"),
                                          *args])
            finally:
                os._exit(127)
        self.child, self.master = child, master
        test.addCleanup(self.stop)

    def stop(self):
        if self.code is None:
            try:
                os.kill(self.child, signal.SIGKILL)
                os.waitpid(self.child, 0)
            except (ProcessLookupError, ChildProcessError):
                pass
        os.close(self.master)

    def _read(self, timeout):
        if self.closed:
            time.sleep(timeout)
            return False
        readable, _, _ = select.select([self.master], [], [], timeout)
        if not readable:
            return False
        try:
            chunk = os.read(self.master, 65536)
        except OSError:
            chunk = b""
        if not chunk:
            self.closed = True
            return False
        self.raw.extend(chunk)
        self.terminal.feed(chunk)
        return True

    def _reap(self):
        if self.code is None:
            ended, status = os.waitpid(self.child, os.WNOHANG)
            if ended:
                self.code = os.waitstatus_to_exitcode(status)
        return self.code

    def pump(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self._read(0.05)
            if self._reap() is not None:
                while self._read(0.05):
                    pass
                return

    def wait_for(self, text, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.terminal.contains(text):
                return
            self._read(0.05)
            if self._reap() is not None and not self._read(0.05):
                break
        raise AssertionError(f"{text!r} not on screen:\n" + "\n".join(self.terminal.screen()))

    def settle(self, quiet=0.3, timeout=3):
        """Read until no output arrives for ``quiet`` seconds (a frame is done)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._read(quiet):
                return

    def send(self, data):
        os.write(self.master, data)

    def wait_exit(self, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._read(0.05)
            if self._reap() is not None:
                while self._read(0.05):
                    pass
                return self.code
        raise AssertionError("TUI still running:\n" + "\n".join(self.terminal.screen()))

    def alive(self, seconds=1.0):
        self.pump(seconds)
        return self._reap() is None


class TerminalSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.proc_root = self.root / "machine"
        for target, fixture in (("proc/stat", "proc_stat_1"),
                                ("proc/net/dev", "proc_net_1"),
                                ("proc/diskstats", "proc_disk_1")):
            path = self.proc_root / target
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((FIXTURES / fixture).read_bytes())
        for target, content in (("proc/meminfo", "MemTotal: 1000000 kB\n"
                                 "MemAvailable: 500000 kB\n"),
                                ("proc/loadavg", "0.25 0.50 0.75 1/10 1\n"),
                                ("proc/uptime", "30.0 10.0\n"),
                                ("proc/sys/kernel/osrelease", "6.14.11-4-pve\n")):
            path = self.proc_root / target
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self.snapshot = self.root / "snapshot.json"
        self.state_dir = self.root / "state"
        self.other_cwd = self.root / "elsewhere"
        self.other_cwd.mkdir()

    def write_snapshot(self):
        now = time.time()
        document = {"schema": 1, "generator": {"name": "monitor", "version": "1"},
                    "observed_at": now, "publish_interval_s": 10,
                    "language": "en", "node": {"status": "ok", "name": "pve-01"},
                    "cluster": {"status": "ok", "members": [], "is_cluster": False},
                    "resources": {"status": "ok", "observed_at": now,
                                  "nodes": [], "guests": [], "storages": []}}
        self.snapshot.write_text(json.dumps(document), encoding="utf-8")

    def write_hot_cluster(self):
        """Three nodes at 95 % CPU and 92 % memory for the last hour."""
        now = time.time()
        t_end = int(now // 60 * 60 - 60)
        names = ("pve01", "pve02", "pve03")
        memory = 64 * 2 ** 30
        document = {
            "schema": 1, "generator": {"name": "monitor", "version": "1"},
            "observed_at": now, "publish_interval_s": 10, "language": "en",
            "node": {"status": "ok", "name": "pve01", "pve_version": "pve-manager/9.0.3/x"},
            "cluster": {"status": "ok", "observed_at": now, "is_cluster": True, "name": "lab",
                        "quorate": True, "nodes_total": 3, "nodes_online": 3,
                        "members": [{"name": name, "nodeid": index + 1, "online": True,
                                     "local": index == 0, "ip": f"10.0.0.{index + 1}"}
                                    for index, name in enumerate(names)]},
            "resources": {"status": "ok", "observed_at": now, "storages": [],
                          "nodes": [{"name": name, "status": "online", "cpu": 0.95,
                                     "maxcpu": 16, "mem": 0.92 * memory, "maxmem": memory,
                                     "disk": 40 * 2 ** 30, "maxdisk": 100 * 2 ** 30,
                                     "uptime": 86400} for name in names],
                          "guests": [{"vmid": 100 + index, "type": "qemu",
                                      "name": f"guest{index}", "node": name,
                                      "status": "running", "cpu": 0.95, "maxcpu": 4,
                                      "mem": 7 * 2 ** 30, "maxmem": 8 * 2 ** 30,
                                      "uptime": 3600}
                                     for index, name in enumerate(names)]},
            "history": {"status": "ok", "observed_at": now, "source": "rrddata",
                        "step_s": 60, "points": 60, "error": None,
                        "nodes": {name: {"status": "ok", "observed_at": now, "t_end": t_end,
                                         "maxcpu": 16, "memtotal": memory,
                                         "cpu": [0.95] * 60, "mem": [0.92] * 60,
                                         "load1": [3.0] * 60} for name in names}}}
        self.snapshot.write_text(json.dumps(document), encoding="utf-8")

    def start(self, *extra, once=False, rows=24, cols=80, term="linux"):
        args = (["--once"] if once else []) + [
            "--snapshot", str(self.snapshot), "--proc-root", str(self.proc_root),
            "--state-dir", str(self.state_dir), *extra]
        return Session(self, args, rows, cols, term)

    def interactive(self, *extra, **options):
        session = self.start(*extra, **options)
        session.wait_for("PROXMENUX MONITOR")
        session.settle()
        return session

    # ------------------------------------------------------------ start and stop

    def test_once_with_snapshot_from_different_cwd_under_isolated_python(self):
        self.write_snapshot()
        session = self.start(once=True)
        self.assertEqual(session.wait_exit(), 0, bytes(session.raw).decode("utf-8", "replace"))
        self.assertIn(b"PROXMENUX MONITOR", session.raw)

    def test_q_exits_interactive_loop_within_two_seconds_and_renews_the_lease(self):
        self.write_snapshot()
        session = self.interactive()
        lease = self.state_dir / "client" / "lease"
        self.assertTrue(lease.is_file())
        self.assertLess(time.time() - lease.stat().st_mtime, 5)
        session.send(b"q")
        self.assertEqual(session.wait_exit(2), 0)

    def test_once_without_snapshot_shows_local_panels_and_starting(self):
        session = self.start(once=True)
        self.assertEqual(session.wait_exit(), 0)
        self.assertTrue(session.terminal.contains("CPU"))
        self.assertTrue(session.terminal.contains("MEMORY"))
        self.assertTrue(session.terminal.contains("Monitor starting"))

    def test_once_without_snapshot_after_boot_shows_unavailable(self):
        (self.proc_root / "proc/uptime").write_text("180.0 10.0\n", encoding="utf-8")
        session = self.start(once=True)
        self.assertEqual(session.wait_exit(), 0)
        self.assertTrue(session.terminal.contains("MONITOR UNAVAILABLE"))

    def test_sigterm_restores_terminal_and_exits_zero(self):
        session = self.interactive()
        os.kill(session.child, signal.SIGTERM)
        self.assertEqual(session.wait_exit(), 0)
        self.assertTrue(b"\x1b[?25h" in session.raw or b"\x0f" in session.raw)

    def test_sighup_and_ctrl_c_exit_zero(self):
        for name, stop in (("SIGHUP", lambda s: os.kill(s.child, signal.SIGHUP)),
                           ("Ctrl+C", lambda s: s.send(b"\x03"))):
            with self.subTest(name):
                session = self.interactive()
                stop(session)
                self.assertEqual(session.wait_exit(), 0)

    def test_ctrl_z_is_ignored(self):
        session = self.interactive()
        session.send(b"\x1a")
        self.assertTrue(session.alive(1.5))
        session.send(b"q")
        self.assertEqual(session.wait_exit(), 0)

    # ------------------------------------------------------------ text size

    def test_text_size_keys_exit_10_and_11_after_restoring_the_terminal(self):
        for key, code in ((b"+", 10), (b"=", 10), (b"-", 11)):
            with self.subTest(key=key):
                session = self.interactive("--zoom", "3/8", rows=30, cols=100)
                self.assertIn("+/- text (3/8)", session.terminal.text(29))
                session.send(key)
                self.assertEqual(session.wait_exit(2), code)
                self.assertIn(b"\x1b[?25h", session.raw)

    def test_text_size_keys_are_ignored_at_the_ends_and_without_zoom(self):
        for zoom, keys in ((("--zoom", "8/8"), b"+="), (("--zoom", "1/8"), b"-"),
                           ((), b"+=-")):
            with self.subTest(zoom=zoom):
                session = self.interactive(*zoom)
                session.send(keys)
                self.assertTrue(session.alive(1.5))
                session.send(b"q")
                self.assertEqual(session.wait_exit(), 0)

    def test_invalid_arguments_exit_64(self):
        for argv in (("--zoom", "9/8"), ("--view", "tree"), ("--no-such-flag",)):
            with self.subTest(argv=argv):
                session = self.start(*argv)
                self.assertEqual(session.wait_exit(), 64)
                self.assertIn(b"error", session.raw)

    # ------------------------------------------------------------ views and brand

    def test_view_flag_starts_in_the_cluster_view(self):
        self.write_hot_cluster()
        session = self.start("--view", "cluster", once=True, rows=30, cols=100)
        self.assertEqual(session.wait_exit(), 0)
        self.assertIn("[Cluster]", session.terminal.text(0))
        self.assertTrue(session.terminal.contains("pve03"))
        self.assertTrue(session.terminal.contains("95%"))
        # acs glyphs in a UTF-8 locale: solid U+2588, never ncurses' U+25AE.
        self.assertTrue(session.terminal.contains("\u2588" * 5))
        self.assertFalse(session.terminal.contains("\u25ae"))

    def test_brand_badge_and_rejected_brand(self):
        self.write_snapshot()
        # The header status has priority: at 100 columns it leaves no room.
        session = self.start("--brand", "HOMELAB", once=True, rows=45, cols=160)
        self.assertEqual(session.wait_exit(), 0)
        self.assertIn(" HOMELAB ", session.terminal.text(0))
        session = self.start("--brand", "<bad>", once=True, rows=45, cols=160)
        self.assertEqual(session.wait_exit(), 0)
        self.assertIn(b"--brand ignored", session.raw)
        self.assertNotIn("bad", session.terminal.text(0))

    def test_brand_art_where_rows_are_free(self):
        if os.geteuid() != 0:
            self.skipTest("the art file must be owned by root")
        self.write_snapshot()
        art_dir = self.root / "art"
        art_dir.mkdir(mode=0o755)
        art = art_dir / "brand.txt"
        art.write_text("+---------+\n| HOMELAB |\n+---------+\n", encoding="utf-8")
        art.chmod(0o644)
        session = self.start("--brand-art", str(art), once=True, rows=45, cols=160)
        self.assertEqual(session.wait_exit(), 0)
        self.assertTrue(session.terminal.contains("| HOMELAB |"))
        session = self.start("--brand-art", str(art), once=True, rows=30, cols=100)
        self.assertEqual(session.wait_exit(), 0)
        self.assertFalse(session.terminal.contains("HOMELAB"))

    # ------------------------------------------------------------ colours

    def test_mono_sends_no_colour(self):
        self.write_hot_cluster()
        colour = self.start("--view", "cluster", once=True, rows=30, cols=100)
        self.assertEqual(colour.wait_exit(), 0)
        self.assertRegex(bytes(colour.raw), SETAF)
        mono = self.start("--view", "cluster", "--mono", once=True, rows=30, cols=100)
        self.assertEqual(mono.wait_exit(), 0)
        self.assertNotRegex(bytes(mono.raw), SETAF)
        self.assertTrue(mono.terminal.contains("95%"))

    def test_monochrome_terminal_never_reverses_bar_or_graph_cells(self):
        self.write_hot_cluster()
        for extra, term in ((("--mono",), "linux"), ((), "vt100")):
            with self.subTest(term=term):
                session = self.start("--view", "cluster", *extra, once=True, rows=30,
                                     cols=100, term=term)
                self.assertEqual(session.wait_exit(), 0)
                cells = [cell for row in session.terminal.cells for cell in row]
                reversed_cells = [cell for cell in cells if cell[1]]
                self.assertTrue(any(char != " " for char, _, _ in reversed_cells))
                self.assertGreater(sum(1 for char, _, acs in cells
                                       if acs or char in GLYPH_CHARS), 100)
                for char, _, acs in reversed_cells:
                    self.assertFalse(acs or char in GLYPH_CHARS, char)

    # ------------------------------------------------------------ loop (R3-T5)

    def test_periodic_redraw_repairs_the_screen_without_clearing_it(self):
        self.write_snapshot()
        session = self.interactive()
        start = len(session.raw)
        # What a kernel message does to the console: cells curses believes are
        # right now show something else, the static title and blank rows too.
        # The bottom-right cell is never written (it would scroll the screen).
        terminal = session.terminal
        for row in range(terminal.rows):
            terminal.cells[row] = [(GARBAGE, False, False)] * terminal.cols
        terminal.cells[-1][-1] = (" ", False, False)
        session.pump(7)
        self.assertIsNone(session.code)
        later = bytes(session.raw[start:])
        for clear in CLEAR:
            self.assertNotIn(clear, later)
        screen = session.terminal.screen()
        self.assertFalse([line for line in screen if GARBAGE in line], "\n".join(screen))
        self.assertIn("PROXMENUX MONITOR", screen[0])
        self.assertIn(b"PROXMENUX MONITOR", later)

    def test_cursor_is_parked_at_the_origin_after_each_frame(self):
        self.write_snapshot()
        session = self.interactive()
        for _ in range(3):
            self.assertEqual((session.terminal.y, session.terminal.x), (0, 0))
            session.pump(1.0)
            session.settle()

    def test_w_switches_the_graph_window(self):
        self.write_snapshot()
        session = self.interactive()
        self.assertTrue(session.terminal.contains("live 1m"))
        session.send(b"w")
        session.wait_for("live 5m", timeout=3)
        session.send(b"w")
        session.wait_for("live 1m", timeout=3)

    def test_refresh_key_clears_the_screen(self):
        self.write_snapshot()
        session = self.interactive()
        start = len(session.raw)
        session.send(b"r")
        session.pump(1.5)
        self.assertTrue(any(clear in bytes(session.raw[start:]) for clear in CLEAR))
        session.wait_for("PROXMENUX MONITOR")


if __name__ == "__main__":
    unittest.main()
