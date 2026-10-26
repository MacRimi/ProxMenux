"""Curses entry point for the read-only ProxMenux console.

Exit codes: 0 when the operator quits (``q``, Ctrl+C, SIGTERM or SIGHUP),
10 to ask for bigger text (``+`` or ``=``), 11 to ask for smaller text
(``-``), 64 for invalid arguments; any other code is a crash. The text keys
only act with ``--zoom i/n`` (given by a launcher that can change the console
font) and never past either end of that range.
"""

import os
import sys
_HERE = os.path.dirname(os.path.realpath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import console_brand  # noqa: E402
import console_metrics  # noqa: E402
import console_render  # noqa: E402
import console_snapshot  # noqa: E402

import argparse
import curses
import json
import locale
from pathlib import Path
import re
import signal
import time


EXIT_OK = 0
EXIT_BIGGER = 10
EXIT_SMALLER = 11
EXIT_USAGE = 64
REDRAW_EVERY_S = 5
WINDOWS_S = (60, 300)
_MAX_ZOOM_STEPS = 64

# Role -> (foreground, attributes) on the default background; None keeps the
# terminal's default foreground.
_COLOURS = {
    "title": (curses.COLOR_CYAN, 0),
    "text": (None, 0),
    "dim": (None, curses.A_DIM),
    "ok": (curses.COLOR_GREEN, 0),
    "warn": (curses.COLOR_YELLOW, curses.A_BOLD),
    "crit": (curses.COLOR_RED, curses.A_BOLD),
    "selected": (None, curses.A_REVERSE),
    "graph_in": (curses.COLOR_CYAN, 0),
    "graph_out": (curses.COLOR_MAGENTA, 0),
    "brand": (curses.COLOR_WHITE, curses.A_BOLD),
    "brand_badge": (None, curses.A_BOLD | curses.A_REVERSE),
}
# Monochrome: attributes per role for text cells, and for bar and graph cells
# (the ``glyph`` attribute), which are never drawn in reverse video.
_MONO_TEXT = {
    "title": curses.A_BOLD, "text": 0, "dim": curses.A_DIM, "ok": 0,
    "warn": curses.A_BOLD, "crit": curses.A_BOLD | curses.A_REVERSE,
    "selected": curses.A_REVERSE, "graph_in": 0, "graph_out": 0,
    "brand": curses.A_BOLD, "brand_badge": curses.A_REVERSE,
}
_MONO_GLYPH = {"dim": curses.A_DIM, "warn": curses.A_BOLD, "crit": curses.A_BOLD}
_CELL_ATTRS = {"dim": curses.A_DIM, "reverse": curses.A_REVERSE, "bold": curses.A_BOLD}
# In a UTF-8 locale ncurses sends ACS_BLOCK as U+25AE, which the console fonts
# (Lat15-Terminus) draw as a small square; bars and graphs need U+2588.
_UTF8_ACS = {"BAR_FULL": "\u2588"}
_LANGUAGE = re.compile(r"[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]+)?\Z")
_ZOOM = re.compile(r"([0-9]{1,2})/([0-9]{1,2})\Z")
_stop_requested = False
_utf8 = False  # whether the locale's codeset is UTF-8; set by main()


def _catalog_value(catalog, key):
    value = catalog
    for part in key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value if isinstance(value, str) else None


class Translator:
    """Resolve keys from the selected catalog, English, then the key."""

    def __init__(self, module_file=__file__):
        module = Path(module_file).resolve()
        appdir = Path(os.environ.get("APPDIR") or module.parents[2])
        self.roots = [appdir / "usr/share/proxmenux/messages",
                      module.parents[1] / "messages"]
        self.language = None
        self.catalogs = {}
        self.set_language("en")

    def _load(self, language):
        if language not in self.catalogs:
            self.catalogs[language] = {}
            for root in self.roots:
                try:
                    with (root / language / "common.json").open(encoding="utf-8") as stream:
                        value = json.load(stream)
                except (OSError, UnicodeError, ValueError):
                    continue
                if isinstance(value, dict):
                    self.catalogs[language] = value
                    break
        return self.catalogs[language]

    def set_language(self, language):
        language = (language if isinstance(language, str) and
                    _LANGUAGE.fullmatch(language) else "en")
        if language != self.language:
            self.language = language
            self.catalogs = {}
            self._load(language)
            self._load("en")

    def __call__(self, key):
        return (_catalog_value(self._load(self.language), key) or
                _catalog_value(self._load("en"), key) or key)


def _configuration_language():
    try:
        with open("/usr/local/share/proxmenux/config.json", encoding="utf-8") as stream:
            language = json.load(stream).get("language")
        return language if isinstance(language, str) and _LANGUAGE.fullmatch(language) else "en"
    except (OSError, UnicodeError, ValueError, AttributeError):
        return "en"


def _kernel(proc_root):
    """Running kernel release from ``proc/sys/kernel/osrelease``, or None."""
    try:
        with open(Path(proc_root) / "proc/sys/kernel/osrelease", encoding="ascii",
                  errors="replace") as stream:
            release = stream.read(256).strip()
    except OSError:
        return None
    return release or None


# ---------------------------------------------------------------- painting

def _palette(mono):
    """Role -> (text style, glyph style); colour pairs unless ``mono``."""
    palette = {role: (_MONO_TEXT[role], _MONO_GLYPH.get(role, 0)) for role in _MONO_TEXT}
    if mono or not curses.has_colors():
        return palette
    curses.start_color()
    try:
        curses.use_default_colors()
        background = default = -1
    except curses.error:
        background, default = curses.COLOR_BLACK, curses.COLOR_WHITE
    for number, (role, (foreground, attrs)) in enumerate(_COLOURS.items(), 1):
        try:
            curses.init_pair(number, default if foreground is None else foreground, background)
        except curses.error:
            continue  # this role keeps its monochrome attributes
        style = curses.color_pair(number) | attrs
        palette[role] = (style, style & ~curses.A_REVERSE)
    return palette


def _style(role, attrs, palette):
    """Curses attributes of a cell; bar and graph cells never in reverse."""
    glyph = console_render.GLYPH in attrs
    style = palette.get(role, (0, 0))[1 if glyph else 0]
    for attr in attrs:
        style |= _CELL_ATTRS.get(attr, 0)
    return style & ~curses.A_REVERSE if glyph else style


def _char(value):
    """A grid character as curses needs it: an ``ACS_*`` constant or text.

    Logical tokens map through ``console_render.ACS_TOKENS``; a value without
    the ``ACS_`` prefix is the literal character itself. Before ``initscr`` (or
    on a terminal without the constant) the ASCII fallback is used; in a UTF-8
    locale the full block is sent as U+2588 (see ``_UTF8_ACS``).
    """
    name = console_render.ACS_TOKENS.get(value)
    if name is None:
        return value
    if not name.startswith("ACS_"):
        return name
    if _utf8 and value in _UTF8_ACS:
        return _UTF8_ACS[value]
    glyph = getattr(curses, name, None)
    return glyph if glyph is not None else console_render.ASCII_TOKENS[value]


def _runs(row, width, palette, last_row, memo):
    """Yield ``(x, text_or_acs, style)``, joining text cells of one style.

    ``memo`` caches ``cell -> (char, style)`` across the rows of a frame.
    """
    start, text, style = 0, "", None
    for x, cell in enumerate(row[:width]):
        if last_row and x == width - 1:
            break  # writing the bottom-right cell would scroll the screen
        try:
            char, cell_style = memo[cell]
        except (KeyError, TypeError):  # TypeError: a cell that is not hashable
            value, role, attrs = cell
            char, cell_style = _char(value), _style(role, attrs, palette)
            if isinstance(attrs, tuple):
                memo[cell] = char, cell_style
        if isinstance(char, str) and cell_style == style:
            text += char
            continue
        if text:
            yield start, text, style
        if isinstance(char, str):
            start, text, style = x, char, cell_style
        else:
            yield x, char, cell_style
            start, text, style = x + 1, "", None
    if text:
        yield start, text, style


def _paint(stdscr, grid, palette, redraw=False):
    """Write the grid, park the cursor at (0, 0) and refresh.

    ``redraw`` rewrites every cell even where curses thinks the screen is
    already right (kernel messages scrolled or overwrote it), without the
    clear-screen flash of ``clearok``.
    """
    height, width = stdscr.getmaxyx()
    stdscr.erase()
    memo = {}
    for y, row in enumerate(grid[:height]):
        for x, value, style in _runs(row, width, palette, y == height - 1, memo):
            try:
                if isinstance(value, int):
                    stdscr.addch(y, x, value, style)
                else:
                    try:
                        stdscr.addstr(y, x, value, style)
                    except UnicodeEncodeError:
                        stdscr.addstr(y, x, value.encode("ascii", "replace").decode(), style)
            except curses.error:
                # A resize may land between getmaxyx and a cell write.
                continue
    if redraw:
        stdscr.redrawwin()
    try:
        stdscr.move(0, 0)
    except curses.error:
        pass
    stdscr.refresh()


# ---------------------------------------------------------------- arguments

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def _zoom(value):
    match = _ZOOM.match(value)
    position, count = (int(match.group(1)), int(match.group(2))) if match else (0, 0)
    if not 1 <= position <= count <= _MAX_ZOOM_STEPS:
        raise argparse.ArgumentTypeError(
            f"expected POSITION/COUNT with 1 <= POSITION <= COUNT <= {_MAX_ZOOM_STEPS}: {value!r}")
    return position, count


def _parse_args(argv):
    parser = _Parser(prog="proxmenux-console", description="ProxMenux console TUI")
    parser.add_argument("--once", action="store_true", help="draw one frame and exit")
    parser.add_argument("--snapshot", default=console_snapshot.DEFAULT_PATH)
    parser.add_argument("--proc-root", default="/")
    parser.add_argument("--state-dir", default=os.environ.get(
        "PMX_CONSOLE_STATE_DIR", console_snapshot.DEFAULT_STATE_DIR))
    parser.add_argument("--glyphs", choices=("acs", "unicode", "ascii", "auto"),
                        default="acs")
    parser.add_argument("--view", choices=("node", "cluster"), default="node",
                        help="view shown first")
    parser.add_argument("--mono", action="store_true",
                        help="no colours: roles as bold, dim and reverse text")
    parser.add_argument("--brand", metavar="TEXT",
                        help="badge in the header (e.g. HOMELAB); invalid text is ignored")
    parser.add_argument("--brand-art", metavar="FILE",
                        help="root-owned block art shown where rows are free; "
                             "an invalid file is ignored")
    parser.add_argument("--zoom", type=_zoom, metavar="POSITION/COUNT",
                        help="font step of the launcher; enables + and - (exit 10 and 11)")
    parser.add_argument("--autostart", action="store_true")
    return parser.parse_args(argv)


# ---------------------------------------------------------------- loop

def _signal_stop(_signum, _frame):
    global _stop_requested
    _stop_requested = True


class Controls:
    """What the keyboard changes: view, guest sort, graph window and glyphs.

    ``press(key)`` returns an exit code (``EXIT_OK``, ``EXIT_BIGGER``,
    ``EXIT_SMALLER``), ``RELOAD`` (re-read the snapshot and clear the screen),
    ``CLEAR`` (clear the screen) or None.
    """

    RELOAD = "reload"
    CLEAR = "clear"
    _NEXT_GLYPHS = {"acs": "ascii", "ascii": "unicode", "unicode": "acs"}

    def __init__(self, view="node", glyphs="acs", zoom=None):
        self.view = view
        self.glyphs = "acs" if glyphs == "auto" else glyphs
        self.zoom = zoom
        self.sort = "cpu"
        self.window_s = WINDOWS_S[0]

    def press(self, key):
        if self.zoom is not None:
            position, count = self.zoom
            if key in (ord("+"), ord("=")):
                return EXIT_BIGGER if position < count else None
            if key == ord("-"):
                return EXIT_SMALLER if position > 1 else None
        if key in (ord("q"), ord("Q"), 3):  # 3: Ctrl+C when it is not a signal
            return EXIT_OK
        if key in (9, curses.KEY_LEFT, curses.KEY_RIGHT):
            self.view = "cluster" if self.view == "node" else "node"
        elif key in (ord("1"), ord("2")):
            self.view = "node" if key == ord("1") else "cluster"
        elif key == ord("r"):
            return self.RELOAD
        elif key == curses.KEY_RESIZE:
            return self.CLEAR
        elif key == ord("a"):
            self.glyphs = self._NEXT_GLYPHS[self.glyphs]
        elif key == ord("w"):
            self.window_s = WINDOWS_S[(WINDOWS_S.index(self.window_s) + 1) % len(WINDOWS_S)]
        elif self.view == "cluster" and key in (ord("c"), ord("m")):
            self.sort = "cpu" if key == ord("c") else "mem"
        return None


def _snapshot_view(snapshot, now):
    """``(data, fresh)``: the document with ``age_s`` and whether guest data is
    recent enough (``age <= 2 × publish_interval_s``) for host totals."""
    if snapshot is None or snapshot.reason is not None:
        return None, False
    data = dict(snapshot.data)
    observed = data.get("observed_at")
    age = max(0, now - observed) if observed is not None else None
    data["age_s"] = age
    interval = data.get("publish_interval_s") or console_snapshot.PUBLISH_INTERVAL_S
    fresh = ((data.get("resources") or {}).get("status") == "ok" and age is not None
             and age <= 2 * interval)
    return data, fresh


def _local(sampler, kernel, window_s, now):
    """One local sample plus what the graphs need from the sampler."""
    local = sampler.sample(now)
    local["kernel"] = kernel
    local["series"] = {name: list(values) for name, values in sampler.history.items()}
    local["stats"] = {name: sampler.stats(name, window_s) for name in sampler.history}
    return local


def _view_model(controls, local, data, fresh, translator, now, brand):
    guests = ((data or {}).get("resources") or {}).get("guests") or []
    node = ((data or {}).get("node") or {}).get("name")
    return {"local": local, "snapshot": data,
            "host_other": console_metrics.host_other(local, guests, node, fresh),
            "glyphs": controls.glyphs, "lang": translator.language, "tr": translator,
            "now": now, "selected_view": controls.view, "sort": controls.sort,
            "window_s": controls.window_s, "brand": brand,
            "zoom": list(controls.zoom) if controls.zoom else None}


def _renew_lease(state_dir, now):
    """Keep the publisher's lease (``<state_dir>/client/lease``) fresh."""
    try:
        console_snapshot.touch_lease(state_dir, now)
    except (OSError, ValueError):
        pass


def _run(stdscr, args, brand):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.timeout(1000)
    stdscr.keypad(True)
    stdscr.leaveok(False)
    curses.flushinp()  # keys typed while a launcher restarted the console
    palette = _palette(args.mono)
    sampler = console_metrics.LocalSampler(proc_root=args.proc_root)
    kernel = _kernel(args.proc_root)
    translator = Translator()
    controls = Controls(args.view, args.glyphs, args.zoom)
    snapshot = None
    previous_key = object()
    reload_now = True
    clear = False
    last_redraw = time.monotonic()
    while not _stop_requested:
        now = time.time()
        local = _local(sampler, kernel, controls.window_s, time.monotonic())
        _renew_lease(args.state_dir, now)
        try:
            info = os.stat(args.snapshot)
            key = (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size)
        except OSError:
            key = None
        if reload_now or key != previous_key:
            snapshot = console_snapshot.load_snapshot(args.snapshot, now)
            previous_key = key
            reload_now = False
        data, fresh = _snapshot_view(snapshot, now)
        translator.set_language(data.get("language") if data else _configuration_language())
        height, width = stdscr.getmaxyx()
        grid = console_render.render(
            _view_model(controls, local, data, fresh, translator, now, brand), width, height)
        redraw = False
        if clear:
            stdscr.clearok(True)
            clear = False
            last_redraw = time.monotonic()
        elif time.monotonic() - last_redraw >= REDRAW_EVERY_S:
            redraw = True
            last_redraw = time.monotonic()
        _paint(stdscr, grid, palette, redraw)
        if args.once or _stop_requested:
            break
        action = controls.press(stdscr.getch())
        if action == Controls.RELOAD:
            reload_now = clear = True
            _renew_lease(args.state_dir, time.time())
        elif action == Controls.CLEAR:
            clear = True
        elif action is not None:
            return action
    return EXIT_OK


def _session(args, brand):
    """``curses.wrapper`` without colours by default and with a teardown that
    always reaches ``endwin`` (a hung-up terminal may fail the earlier steps)."""
    stdscr = curses.initscr()
    try:
        curses.noecho()
        curses.cbreak()
        return _run(stdscr, args, brand)
    finally:
        for step in (lambda: stdscr.keypad(False), curses.echo, curses.nocbreak,
                     curses.endwin):
            try:
                step()
            except curses.error:
                pass


def main(argv=None):
    global _stop_requested, _utf8
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    _utf8 = locale.nl_langinfo(locale.CODESET).upper().replace("-", "") == "UTF8"
    args = _parse_args(argv)
    brand = console_brand.load(args.brand, args.brand_art)
    _stop_requested = False
    previous = {}
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        previous[signum] = signal.signal(signum, _signal_stop)
    # Ignored before initscr, so curses does not install its own suspend handler.
    previous[signal.SIGTSTP] = signal.signal(signal.SIGTSTP, signal.SIG_IGN)
    try:
        return _session(args, brand)
    except Exception as exc:
        print("console_tui: " + str(exc).replace("\n", " "), file=sys.stderr)
        return 1
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    sys.exit(main())
