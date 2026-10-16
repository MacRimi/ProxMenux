"""Terminal smoke tests and pure controller tests for the console TUI."""

import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import sys
import tempfile
import termios
import time
import unittest
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "console"
sys.path.insert(0, str(SCRIPTS))

import console_tui  # noqa: E402


def guest(vmid=101, node="p3-01", uptime=30, **counters):
    return {"type": "qemu", "vmid": vmid, "node": node, "uptime": uptime,
            "netin": counters.get("netin", 100),
            "netout": counters.get("netout", 200),
            "diskread": counters.get("diskread", 300),
            "diskwrite": counters.get("diskwrite", 400)}


class GuestRateTests(unittest.TestCase):
    def test_rates_require_advanced_observation_and_stable_guest(self):
        rates = console_tui.GuestRates()
        first = rates.update([guest()], 10)
        self.assertNotIn("net_rx_bps", first[0])
        second = rates.update([guest(uptime=35, netin=150, netout=220,
                                     diskread=340, diskwrite=440)], 15)
        self.assertEqual({key: second[0][key] for key in
                          ("net_rx_bps", "net_tx_bps", "disk_read_bps", "disk_write_bps")},
                         {"net_rx_bps": 10, "net_tx_bps": 4,
                          "disk_read_bps": 8, "disk_write_bps": 8})
        self.assertNotIn("net_rx_bps", rates.update([guest(netin=999)], 15)[0])
        self.assertNotIn("net_rx_bps", rates.update([guest(node="p3-02")], 20)[0])
        self.assertNotIn("net_rx_bps", rates.update([guest(node="p3-02", uptime=1)], 25)[0])
        self.assertNotIn("net_rx_bps", rates.update([guest(node="p3-02", uptime=2,
                                                            netin=1)], 30)[0])

    def test_missing_counter_resets_its_rate(self):
        rates = console_tui.GuestRates()
        rates.update([guest(diskread=None)], 10)
        result = rates.update([guest(uptime=35, netin=120, diskread=400)], 12)[0]
        self.assertEqual(result["net_rx_bps"], 10)
        self.assertNotIn("disk_read_bps", result)

    def test_decreased_counter_resets_all_rates(self):
        rates = console_tui.GuestRates()
        rates.update([guest()], 10)
        result = rates.update([guest(uptime=35, netin=120, netout=100)], 12)[0]
        self.assertNotIn("net_rx_bps", result)
        next_result = rates.update([guest(uptime=36, netin=140,
                                          netout=120)], 14)[0]
        self.assertEqual(next_result["net_rx_bps"], 10)


class TranslationTests(unittest.TestCase):
    def test_language_key_english_and_raw_key_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            appdir = Path(temp)
            folder = appdir / "usr/share/proxmenux/messages"
            for language, values in (("en", {"runtime": {"consoleTui": {
                    "title": "English title", "onlyEnglish": "English fallback"}}}),
                                     ("es", {"runtime": {"consoleTui": {
                    "title": "Título"}}})):
                target = folder / language / "common.json"
                target.parent.mkdir(parents=True)
                target.write_text(json.dumps(values), encoding="utf-8")
            with mock.patch.dict(os.environ, {"APPDIR": str(appdir)}):
                catalog = console_tui.Translator()
                catalog.set_language("es")
                self.assertEqual(catalog("runtime.consoleTui.title"), "Título")
                self.assertEqual(catalog("runtime.consoleTui.onlyEnglish"), "English fallback")
                self.assertEqual(catalog("runtime.consoleTui.missing"),
                                 "runtime.consoleTui.missing")
                catalog.set_language("fr")
                self.assertEqual(catalog("runtime.consoleTui.title"), "English title")

    def test_packaged_layout_resolves_catalog_from_appdir(self):
        with tempfile.TemporaryDirectory() as temp:
            appdir = Path(temp) / "AppDir"
            module = appdir / "usr/bin/console_tui.py"
            module.parent.mkdir(parents=True)
            module.write_text("", encoding="utf-8")
            target = appdir / "usr/share/proxmenux/messages/en/common.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps({"runtime": {"consoleTui": {"title": "PACKAGED"}}}),
                              encoding="utf-8")
            with mock.patch.dict(os.environ):
                os.environ.pop("APPDIR", None)
                catalog = console_tui.Translator(module_file=str(module))
                self.assertEqual(catalog("runtime.consoleTui.title"), "PACKAGED")


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
                                ("proc/uptime", "30.0 10.0\n")):
            path = self.proc_root / target
            path.write_text(content, encoding="utf-8")
        self.snapshot = self.root / "snapshot.json"
        self.state_dir = self.root / "state"
        self.other_cwd = self.root / "elsewhere"
        self.other_cwd.mkdir()

    def write_snapshot(self):
        document = {"schema": 1, "generator": {"name": "monitor", "version": "1"},
                    "observed_at": time.time(), "publish_interval_s": 5,
                    "language": "en", "node": {"status": "ok", "name": "p3-01"},
                    "cluster": {"status": "ok", "members": [], "is_cluster": False},
                    "resources": {"status": "ok", "observed_at": time.time(),
                                  "nodes": [], "guests": [], "storages": []}}
        self.snapshot.write_text(json.dumps(document), encoding="utf-8")

    def spawn(self, once=False):
        child, master = pty.fork()
        if child == 0:
            fcntl.ioctl(1, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
            os.chdir(self.other_cwd)
            os.environ["TERM"] = "linux"
            os.environ.pop("APPDIR", None)
            args = [sys.executable, "-I", str(SCRIPTS / "console_tui.py")]
            if once:
                args.append("--once")
            args.extend(("--snapshot", str(self.snapshot), "--proc-root",
                         str(self.proc_root), "--state-dir", str(self.state_dir)))
            os.execv(sys.executable, args)
        self.addCleanup(self._stop, child, master)
        return child, master

    @staticmethod
    def _stop(child, master):
        try:
            os.kill(child, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(child, os.WNOHANG)
        except ChildProcessError:
            pass
        os.close(master)

    def collect(self, child, master, timeout=2, wanted=None):
        output = bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            readable, _, _ = select.select([master], [], [], 0.05)
            if readable:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    pass
            if wanted is not None and wanted in output:
                return bytes(output), None
            ended, status = os.waitpid(child, os.WNOHANG)
            if ended:
                while select.select([master], [], [], 0)[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output.extend(chunk)
                return bytes(output), os.waitstatus_to_exitcode(status)
        self.fail("TUI did not respond before deadline")

    def test_once_with_snapshot_from_different_cwd_under_isolated_python(self):
        self.write_snapshot()
        child, master = self.spawn(once=True)
        output, code = self.collect(child, master)
        self.assertEqual(code, 0, output.decode("ascii", "replace"))
        self.assertIn(b"PROXMENUX MONITOR", output)

    def test_q_exits_interactive_loop_within_two_seconds(self):
        self.write_snapshot()
        child, master = self.spawn()
        output, _ = self.collect(child, master, wanted=b"PROXMENUX MONITOR")
        self.assertIn(b"PROXMENUX MONITOR", output)
        os.write(master, b"q")
        _, code = self.collect(child, master)
        self.assertEqual(code, 0)

    def test_once_without_snapshot_shows_local_panels_and_starting(self):
        child, master = self.spawn(once=True)
        output, code = self.collect(child, master)
        self.assertEqual(code, 0, output.decode("ascii", "replace"))
        self.assertIn(b"CPU", output)
        self.assertIn(b"MEMORY", output)
        self.assertIn(b"Monitor starting", output)

    def test_once_without_snapshot_after_boot_shows_unavailable(self):
        (self.proc_root / "proc/uptime").write_text("180.0 10.0\n", encoding="utf-8")
        child, master = self.spawn(once=True)
        output, code = self.collect(child, master)
        self.assertEqual(code, 0, output.decode("ascii", "replace"))
        self.assertIn(b"MONITOR UNAVAILABLE", output)

    def test_sigterm_restores_terminal_and_exits_zero(self):
        child, master = self.spawn()
        self.collect(child, master, wanted=b"PROXMENUX MONITOR")
        os.kill(child, signal.SIGTERM)
        output, code = self.collect(child, master)
        self.assertEqual(code, 0)
        self.assertTrue(b"\x1b[?25h" in output or b"\x0f" in output)


if __name__ == "__main__":
    unittest.main()
