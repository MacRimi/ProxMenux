"""Tests of the console TUI entry point that need no terminal.

The terminal itself (pty, real curses, exit codes after teardown) is covered
by ``test_console_tui_smoke.py`` on a QA host.
"""

import contextlib
import curses
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "console"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import console_metrics  # noqa: E402
import console_render  # noqa: E402
import console_snapshot  # noqa: E402
import console_tui  # noqa: E402
from console_tui import Controls  # noqa: E402


RENDER_ROLES = ("title", "text", "dim", "ok", "warn", "crit", "selected",
                "graph_in", "graph_out", "brand", "brand_badge")


def parse(*argv):
    return console_tui._parse_args(list(argv))


class ArgumentTests(unittest.TestCase):
    def test_defaults(self):
        args = parse()
        self.assertEqual((args.view, args.glyphs, args.mono, args.brand, args.brand_art,
                          args.zoom, args.once), ("node", "acs", False, None, None, None, False))

    def test_new_flags(self):
        args = parse("--view", "cluster", "--mono", "--brand", "HOMELAB", "--brand-art",
                     "/etc/art.txt", "--zoom", "3/8", "--glyphs", "unicode")
        self.assertEqual((args.view, args.mono, args.brand, args.brand_art, args.zoom,
                          args.glyphs),
                         ("cluster", True, "HOMELAB", "/etc/art.txt", (3, 8), "unicode"))
        self.assertEqual(parse("--zoom", "1/1").zoom, (1, 1))
        self.assertEqual(parse("--zoom", "8/8").zoom, (8, 8))

    def test_invalid_arguments_exit_64(self):
        for argv in (["--zoom", "9/8"], ["--zoom", "0/8"], ["--zoom", "3"], ["--zoom", "a/b"],
                     ["--zoom", "3/8x"], ["--zoom", " 3/8"], ["--zoom", "-1/8"],
                     ["--zoom", "65/65"], ["--view", "bogus"], ["--glyphs", "emoji"],
                     ["--bogus"], ["--zoom"]):
            with self.subTest(argv=argv):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
                    parse(*argv)
                self.assertEqual(caught.exception.code, console_tui.EXIT_USAGE)
                self.assertIn("error", stderr.getvalue())

    def test_script_exits_64_before_touching_the_terminal(self):
        result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPTS / "console_tui.py"),
                                 "--zoom", "9/8"], stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 64, result.stderr)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"--zoom", result.stderr)

    def test_help_documents_the_brand_example(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as caught:
            parse("--help")
        self.assertEqual(caught.exception.code, 0)
        text = stdout.getvalue()
        self.assertIn("--brand TEXT", text)
        self.assertIn("e.g. HOMELAB", text)


class ControlTests(unittest.TestCase):
    def test_text_size_keys_exit_10_and_11_inside_the_zoom_range(self):
        controls = Controls(zoom=(3, 8))
        self.assertEqual(controls.press(ord("+")), console_tui.EXIT_BIGGER)
        self.assertEqual(controls.press(ord("=")), 10)
        self.assertEqual(controls.press(ord("-")), console_tui.EXIT_SMALLER)
        self.assertEqual(controls.press(ord("-")), 11)

    def test_text_size_keys_are_ignored_at_the_ends_and_without_zoom(self):
        self.assertIsNone(Controls(zoom=(8, 8)).press(ord("+")))
        self.assertIsNone(Controls(zoom=(8, 8)).press(ord("=")))
        self.assertEqual(Controls(zoom=(8, 8)).press(ord("-")), 11)
        self.assertIsNone(Controls(zoom=(1, 8)).press(ord("-")))
        self.assertEqual(Controls(zoom=(1, 8)).press(ord("+")), 10)
        self.assertIsNone(Controls(zoom=(1, 1)).press(ord("+")))
        self.assertIsNone(Controls(zoom=(1, 1)).press(ord("-")))
        for key in (ord("+"), ord("="), ord("-")):
            controls = Controls()
            self.assertIsNone(controls.press(key))
            self.assertEqual((controls.view, controls.sort, controls.window_s, controls.glyphs),
                             ("node", "cpu", 60, "acs"))

    def test_quit_keys(self):
        for key in (ord("q"), ord("Q"), 3):
            self.assertEqual(Controls(zoom=(3, 8)).press(key), console_tui.EXIT_OK)

    def test_suspend_key_and_unknown_keys_change_nothing(self):
        controls = Controls(view="cluster", glyphs="unicode")
        for key in (26, -1, ord("x"), 27):
            self.assertIsNone(controls.press(key))
        self.assertEqual((controls.view, controls.sort, controls.window_s, controls.glyphs),
                         ("cluster", "cpu", 60, "unicode"))

    def test_views_window_glyphs_and_sort(self):
        controls = Controls(glyphs="auto")
        self.assertEqual(controls.glyphs, "acs")
        controls.press(9)
        self.assertEqual(controls.view, "cluster")
        controls.press(curses.KEY_LEFT)
        self.assertEqual(controls.view, "node")
        controls.press(ord("2"))
        self.assertEqual(controls.view, "cluster")
        controls.press(ord("1"))
        self.assertEqual(controls.view, "node")
        controls.press(ord("m"))
        self.assertEqual(controls.sort, "cpu")  # sort only in the cluster view
        controls.press(ord("2"))
        controls.press(ord("m"))
        self.assertEqual(controls.sort, "mem")
        controls.press(ord("c"))
        self.assertEqual(controls.sort, "cpu")
        self.assertEqual(controls.window_s, 60)
        controls.press(ord("w"))
        self.assertEqual(controls.window_s, 300)
        controls.press(ord("w"))
        self.assertEqual(controls.window_s, 60)
        seen = []
        for _ in range(3):
            controls.press(ord("a"))
            seen.append(controls.glyphs)
        self.assertEqual(seen, ["ascii", "unicode", "acs"])

    def test_refresh_and_resize_clear_the_screen(self):
        self.assertEqual(Controls().press(ord("r")), Controls.RELOAD)
        self.assertEqual(Controls().press(curses.KEY_RESIZE), Controls.CLEAR)


def snapshot_document(now, age, interval=10, status="ok", **extra):
    document = {"schema": 1, "generator": {"name": "test", "version": "1"},
                "observed_at": now - age, "language": "en",
                "node": {"status": "ok", "name": "pve-01"},
                "cluster": {"status": "ok", "members": [], "is_cluster": False},
                "resources": {"status": status, "observed_at": now - age,
                              "nodes": [], "guests": [], "storages": []}}
    if interval is not None:
        document["publish_interval_s"] = interval
    document.update(extra)
    return document


class FreshnessTests(unittest.TestCase):
    def view(self, document, now):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "console.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            return console_tui._snapshot_view(console_snapshot.load_snapshot(path, now), now)

    def test_fresh_within_twice_the_publish_interval(self):
        now = time.time()
        data, fresh = self.view(snapshot_document(now, 15), now)
        self.assertTrue(fresh)
        self.assertAlmostEqual(data["age_s"], 15, places=3)
        self.assertTrue(self.view(snapshot_document(now, 20), now)[1])
        self.assertFalse(self.view(snapshot_document(now, 21), now)[1])
        self.assertFalse(self.view(snapshot_document(now, 15, interval=5), now)[1])
        self.assertTrue(self.view(snapshot_document(now, 9, interval=5), now)[1])

    def test_missing_interval_defaults_to_ten_seconds(self):
        now = time.time()
        self.assertTrue(self.view(snapshot_document(now, 15, interval=None), now)[1])
        self.assertFalse(self.view(snapshot_document(now, 25, interval=None), now)[1])

    def test_only_ok_resources_are_fresh(self):
        now = time.time()
        for status in ("stale", "starting", "unavailable", "error"):
            self.assertFalse(self.view(snapshot_document(now, 1, status=status), now)[1])

    def test_unreadable_snapshot_has_no_data(self):
        self.assertEqual(console_tui._snapshot_view(
            console_snapshot.Snapshot.unavailable("missing"), time.time()), (None, False))
        self.assertEqual(console_tui._snapshot_view(None, time.time()), (None, False))


class StyleTests(unittest.TestCase):
    def setUp(self):
        self.mono = console_tui._palette(True)

    def test_every_render_role_has_colour_and_monochrome_styles(self):
        self.assertEqual(set(console_tui._COLOURS), set(RENDER_ROLES))
        self.assertEqual(set(console_tui._MONO_TEXT), set(RENDER_ROLES))
        self.assertTrue(set(RENDER_ROLES) <= console_render._ROLES)

    def test_monochrome_text_cells_use_attributes(self):
        style = lambda role, attrs=(): console_tui._style(role, attrs, self.mono)
        self.assertEqual(style("title"), curses.A_BOLD)
        self.assertEqual(style("ok"), 0)
        self.assertEqual(style("text"), 0)
        self.assertEqual(style("warn"), curses.A_BOLD)
        self.assertEqual(style("crit"), curses.A_BOLD | curses.A_REVERSE)
        self.assertEqual(style("dim"), curses.A_DIM)
        self.assertEqual(style("selected", ("reverse",)), curses.A_REVERSE)
        self.assertEqual(style("brand", ("bold",)), curses.A_BOLD)
        self.assertEqual(style("brand_badge", ("bold", "reverse")),
                         curses.A_BOLD | curses.A_REVERSE)

    def test_monochrome_bar_and_graph_cells_are_never_reverse(self):
        glyph = (console_render.GLYPH,)
        style = lambda role, attrs=glyph: console_tui._style(role, attrs, self.mono)
        self.assertEqual(style("ok"), 0)
        self.assertEqual(style("warn"), curses.A_BOLD)
        self.assertEqual(style("crit"), curses.A_BOLD)
        self.assertEqual(style("dim"), curses.A_DIM)
        for role in RENDER_ROLES:
            for attrs in (glyph, glyph + ("reverse",), glyph + ("bold", "reverse", "dim")):
                self.assertFalse(style(role, attrs) & curses.A_REVERSE, (role, attrs))

    def test_colour_pairs_follow_the_adr_roles(self):
        pairs = {}
        fake = dict(has_colors=lambda: True, start_color=lambda: None,
                    use_default_colors=lambda: None,
                    init_pair=lambda number, fg, bg: pairs.__setitem__(number, (fg, bg)),
                    color_pair=lambda number: number << 8)
        with mock.patch.multiple(console_tui.curses, **fake):
            palette = console_tui._palette(False)
        by_role = {role: pairs[number]
                   for number, role in enumerate(console_tui._COLOURS, 1)}
        self.assertEqual(by_role["title"], (curses.COLOR_CYAN, -1))
        self.assertEqual(by_role["text"], (-1, -1))
        self.assertEqual(by_role["ok"], (curses.COLOR_GREEN, -1))
        self.assertEqual(by_role["warn"], (curses.COLOR_YELLOW, -1))
        self.assertEqual(by_role["crit"], (curses.COLOR_RED, -1))
        self.assertEqual(by_role["graph_in"], (curses.COLOR_CYAN, -1))
        self.assertEqual(by_role["graph_out"], (curses.COLOR_MAGENTA, -1))
        self.assertEqual(by_role["brand"], (curses.COLOR_WHITE, -1))
        style = lambda role, attrs=(): console_tui._style(role, attrs, palette)
        number = {role: index for index, role in enumerate(console_tui._COLOURS, 1)}
        self.assertEqual(style("warn"), (number["warn"] << 8) | curses.A_BOLD)
        self.assertEqual(style("crit"), (number["crit"] << 8) | curses.A_BOLD)
        self.assertEqual(style("ok"), number["ok"] << 8)
        self.assertEqual(style("dim"), (number["dim"] << 8) | curses.A_DIM)
        self.assertEqual(style("brand", ("bold",)), (number["brand"] << 8) | curses.A_BOLD)
        self.assertEqual(style("brand_badge", ("bold", "reverse")),
                         (number["brand_badge"] << 8) | curses.A_BOLD | curses.A_REVERSE)
        self.assertEqual(style("crit", (console_render.GLYPH,)),
                         (number["crit"] << 8) | curses.A_BOLD)
        for role in RENDER_ROLES:
            self.assertFalse(style(role, (console_render.GLYPH, "reverse")) & curses.A_REVERSE)

    def test_colour_pair_failure_keeps_monochrome_attributes(self):
        def init_pair(number, fg, bg):
            raise curses.error("no more pairs")
        fake = dict(has_colors=lambda: True, start_color=lambda: None,
                    use_default_colors=lambda: None, init_pair=init_pair,
                    color_pair=lambda number: number << 8)
        with mock.patch.multiple(console_tui.curses, **fake):
            self.assertEqual(console_tui._palette(False), self.mono)


class CharTests(unittest.TestCase):
    def test_literal_tokens_are_never_looked_up_in_curses(self):
        with mock.patch.object(console_tui.curses, "_", 123, create=True):
            self.assertEqual(console_tui._char("_"), "_")
            self.assertEqual(console_tui._char("BAR_THIN"), "_")
        for char in ("x", " ", "█", "·", "#"):
            self.assertEqual(console_tui._char(char), char)

    def test_full_block_is_u2588_in_a_utf8_locale(self):
        acs = {"ACS_BLOCK": 4194352, "ACS_CKBOARD": 4194401}
        with mock.patch.multiple(console_tui.curses, create=True, **acs):
            with mock.patch.object(console_tui, "_utf8", True):
                self.assertEqual(console_tui._char("BAR_FULL"), "\u2588")
                self.assertEqual(console_tui._char("BAR_HALF"), 4194401)
            with mock.patch.object(console_tui, "_utf8", False):
                self.assertEqual(console_tui._char("BAR_FULL"), 4194352)

    def test_acs_tokens_use_the_curses_constant_or_the_ascii_fallback(self):
        with mock.patch.object(console_tui.curses, "ACS_HLINE", 4194417, create=True):
            self.assertEqual(console_tui._char("BOX_H"), 4194417)
        with mock.patch.object(console_tui, "curses", mock.Mock(spec=[])):
            for token, name in console_render.ACS_TOKENS.items():
                expected = (console_render.ASCII_TOKENS[token] if name.startswith("ACS_")
                            else name)
                self.assertEqual(console_tui._char(token), expected, token)


class FakeScreen:
    """Records what ``_paint`` writes, cell by cell."""

    def __init__(self, height, width):
        self.height, self.width = height, width
        self.cells = {}
        self.calls = []

    def getmaxyx(self):
        return self.height, self.width

    def erase(self):
        self.calls.append(("erase",))
        self.cells = {}

    def addstr(self, y, x, text, style):
        self.calls.append(("addstr", y, x, text))
        if y == self.height - 1 and x + len(text) >= self.width:
            raise curses.error("bottom-right cell")
        for offset, char in enumerate(text):
            self.cells[(y, x + offset)] = (char, style)

    def addch(self, y, x, char, style):
        self.calls.append(("addch", y, x, char))
        if (y, x) == (self.height - 1, self.width - 1):
            raise curses.error("bottom-right cell")
        self.cells[(y, x)] = (char, style)

    def redrawwin(self):
        self.calls.append(("redrawwin",))

    def move(self, y, x):
        self.calls.append(("move", y, x))

    def refresh(self):
        self.calls.append(("refresh",))


def translator():
    with mock.patch.dict(os.environ):
        os.environ.pop("APPDIR", None)
        return console_tui.Translator()


class PaintTests(unittest.TestCase):
    def grid(self, name, width, height, **changes):
        vm = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        vm.update(tr=translator(), **changes)
        return console_render.render(vm, width, height)

    def test_every_cell_but_the_bottom_right_is_written_in_runs(self):
        grid = self.grid("viewmodel_node320.json", 320, 90, glyphs="acs")
        screen = FakeScreen(90, 320)
        acs = {"ACS_HLINE": 1001, "ACS_VLINE": 1002, "ACS_BLOCK": 1003, "ACS_BULLET": 1004}
        with mock.patch.multiple(console_tui.curses, create=True, **acs):
            console_tui._paint(screen, grid, console_tui._palette(True))
            expected = {(y, x): console_tui._char(cell[0])
                        for y, row in enumerate(grid) for x, cell in enumerate(row)}
        self.assertEqual(len(screen.cells), 320 * 90 - 1)
        self.assertNotIn((89, 319), screen.cells)
        self.assertEqual({value for value in expected.values() if isinstance(value, int)},
                         set(acs.values()))
        writes = sum(1 for call in screen.calls if call[0] in ("addstr", "addch"))
        self.assertLess(writes, 320 * 90 // 3)
        for position, (char, _) in screen.cells.items():
            self.assertEqual(char, expected[position], position)

    def test_monochrome_never_reverses_a_bar_or_graph_cell(self):
        for name, view, width, height in (("viewmodel_node320.json", "node", 320, 90),
                                          ("viewmodel_cluster.json", "cluster", 100, 30),
                                          ("viewmodel_cluster.json", "node", 80, 24)):
            with self.subTest(name=name, view=view):
                grid = self.grid(name, width, height, selected_view=view)
                screen = FakeScreen(height, width)
                console_tui._paint(screen, grid, console_tui._palette(True))
                glyphs = [(y, x) for y, row in enumerate(grid) for x, cell in enumerate(row)
                          if console_render.GLYPH in cell[2]]
                self.assertTrue(glyphs)
                for y, x in glyphs:
                    if (y, x) in screen.cells:
                        self.assertFalse(screen.cells[(y, x)][1] & curses.A_REVERSE, (y, x))
                reversed_text = [cell for cell in screen.cells.values()
                                 if cell[1] & curses.A_REVERSE]
                self.assertTrue(reversed_text)  # the selected tab

    def test_cursor_is_parked_at_the_origin_and_redraw_precedes_refresh(self):
        grid = self.grid("viewmodel_cluster.json", 80, 24)
        screen = FakeScreen(24, 80)
        console_tui._paint(screen, grid, console_tui._palette(True))
        self.assertEqual(screen.calls[-2:], [("move", 0, 0), ("refresh",)])
        self.assertNotIn(("redrawwin",), screen.calls)
        screen = FakeScreen(24, 80)
        console_tui._paint(screen, grid, console_tui._palette(True), redraw=True)
        self.assertEqual(screen.calls[-3:], [("redrawwin",), ("move", 0, 0), ("refresh",)])

    def test_a_smaller_screen_than_the_grid_is_clipped(self):
        grid = self.grid("viewmodel_cluster.json", 100, 30)
        screen = FakeScreen(24, 80)
        console_tui._paint(screen, grid, console_tui._palette(True))
        self.assertTrue(all(y < 24 and x < 80 for y, x in screen.cells))


class LocalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for target, fixture in (("proc/stat", "proc_stat_1"), ("proc/net/dev", "proc_net_1"),
                                ("proc/diskstats", "proc_disk_1")):
            path = self.root / target
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((FIXTURES / fixture).read_bytes())
        for target, content in (("proc/meminfo", "MemTotal: 1000000 kB\nMemAvailable: 500000 kB\n"),
                                ("proc/loadavg", "0.25 0.50 0.75 1/10 1\n"),
                                ("proc/uptime", "300.0 10.0\n")):
            (self.root / target).write_text(content, encoding="utf-8")

    def advance(self):
        for target, fixture in (("proc/stat", "proc_stat_2"), ("proc/net/dev", "proc_net_2"),
                                ("proc/diskstats", "proc_disk_2")):
            (self.root / target).write_bytes((FIXTURES / fixture).read_bytes())

    def test_kernel_release_from_the_proc_root(self):
        self.assertIsNone(console_tui._kernel(self.root))
        path = self.root / "proc/sys/kernel/osrelease"
        path.parent.mkdir(parents=True)
        path.write_text("6.14.11-4-pve\n", encoding="ascii")
        self.assertEqual(console_tui._kernel(self.root), "6.14.11-4-pve")

    def test_local_sample_carries_series_stats_and_kernel(self):
        sampler = console_metrics.LocalSampler(proc_root=self.root, storage_paths=[])
        console_tui._local(sampler, "6.14.11-4-pve", 60, 100.0)
        self.advance()
        local = console_tui._local(sampler, "6.14.11-4-pve", 300, 101.0)
        names = {"rx", "tx", "read", "write", "cpu_total", "mem_used"}
        self.assertEqual(set(local["series"]), names)
        self.assertEqual(set(local["stats"]), names)
        self.assertEqual(local["kernel"], "6.14.11-4-pve")
        for name in names:
            self.assertIsInstance(local["series"][name], list)
            self.assertEqual(len(local["series"][name]), 1)
            self.assertEqual(local["stats"][name], sampler.stats(name, 300))
        self.assertIsNotNone(local["series"]["cpu_total"][0])


class ViewModelTests(unittest.TestCase):
    """What the TUI hands to the renderer reaches the screen."""

    def frame(self, controls, width, height, brand=None, **document):
        now = time.time()
        local = json.loads((FIXTURES / "viewmodel_cluster.json").read_text("utf-8"))["local"]
        local["kernel"] = "6.14.11-4-pve"
        local.setdefault("series", {})
        local.setdefault("stats", {})
        data = snapshot_document(now, 2, **document)
        snapshot = console_snapshot.Snapshot(data, 2)
        view, fresh = console_tui._snapshot_view(snapshot, now)
        vm = console_tui._view_model(controls, local, view, fresh, translator(), now,
                                     brand or {"badge": None, "art": []})
        grid = console_render.render(vm, width, height)
        return vm, ["".join(str(cell[0]) for cell in row) for row in grid]

    def test_view_model_fields(self):
        controls = Controls(view="cluster", glyphs="unicode", zoom=(3, 8))
        controls.window_s = 300
        brand = {"badge": "HOMELAB", "art": []}
        vm, _ = self.frame(controls, 100, 30, brand)
        self.assertEqual((vm["selected_view"], vm["glyphs"], vm["window_s"], vm["zoom"],
                          vm["brand"], vm["sort"], vm["lang"]),
                         ("cluster", "unicode", 300, [3, 8], brand, "cpu", "en"))
        self.assertEqual(vm["local"]["kernel"], "6.14.11-4-pve")
        self.assertIsNone(self.frame(Controls(), 100, 30)[0]["zoom"])

    def test_zoom_badge_window_and_kernel_reach_the_screen(self):
        controls = Controls(glyphs="unicode", zoom=(3, 8))
        controls.window_s = 300
        _, rows = self.frame(controls, 160, 45, {"badge": "HOMELAB", "art": []})
        self.assertIn(" HOMELAB ", rows[0])
        self.assertIn("+/- text (3/8)", rows[-1])
        self.assertTrue(any("live 5m" in row for row in rows))
        self.assertTrue(any("6.14.11-4-pve" in row for row in rows))

    def test_brand_art_reaches_the_screen_only_where_rows_are_free(self):
        art = ["+---------+", "| HOMELAB |", "+---------+"]
        for glyphs in ("acs", "unicode", "ascii"):
            _, rows = self.frame(Controls(glyphs=glyphs), 160, 45, {"badge": None, "art": art})
            self.assertTrue(any("| HOMELAB |" in row for row in rows), glyphs)
        _, rows = self.frame(Controls(), 100, 30, {"badge": None, "art": art})
        self.assertFalse(any("HOMELAB" in row for row in rows))

    def test_cluster_view_is_rendered(self):
        _, rows = self.frame(Controls(view="cluster", glyphs="unicode"), 100, 30)
        self.assertIn("[Cluster]", rows[0])


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


if __name__ == "__main__":
    unittest.main()
