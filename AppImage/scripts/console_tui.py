"""Curses entry point for the read-only ProxMenux console."""

import os
import sys
_HERE = os.path.dirname(os.path.realpath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
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


_ROLES = {"title": curses.COLOR_CYAN, "text": None, "dim": None,
          "ok": curses.COLOR_GREEN, "warn": curses.COLOR_YELLOW,
          "crit": curses.COLOR_RED, "selected": None}
_ASCII_TOKENS = {key: ("-" if key == "BOX_H" else "|" if key == "BOX_V"
                       else "#" if key == "BAR_FULL" else "."
                       if key in ("BAR_EMPTY", "BULLET") else "+")
                 for key in console_render.ACS_TOKENS}
_COUNTERS = {"netin": "net_rx_bps", "netout": "net_tx_bps",
             "diskread": "disk_read_bps", "diskwrite": "disk_write_bps"}
_LANGUAGE = re.compile(r"[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]+)?\Z")
_stop_requested = False


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


def _uptime(proc_root):
    try:
        with (Path(proc_root) / "proc/uptime").open(encoding="ascii") as stream:
            return max(0.0, float(stream.read().split()[0]))
    except (OSError, UnicodeError, ValueError, IndexError):
        return 0.0


class GuestRates:
    """Derive guest byte rates only across consecutive valid observations."""

    def __init__(self):
        self.previous = {}
        self.observed_at = None

    def update(self, guests, observed_at):
        dt = (observed_at - self.observed_at
              if isinstance(observed_at, (int, float)) and
              isinstance(self.observed_at, (int, float)) else 0)
        current = {}
        output = []
        for item in guests:
            guest = dict(item)
            key = (guest.get("type"), guest.get("vmid"))
            old = self.previous.get(key)
            stable = (dt > 0 and old is not None and
                      old.get("node") == guest.get("node") and
                      isinstance(guest.get("uptime"), (int, float)) and
                      isinstance(old.get("uptime"), (int, float)) and
                      guest["uptime"] >= old["uptime"])
            if stable:
                stable = all(not (isinstance(old.get(source), (int, float)) and
                                  isinstance(guest.get(source), (int, float)) and
                                  guest[source] < old[source]) for source in _COUNTERS)
            if stable:
                for source, target in _COUNTERS.items():
                    first, second = old.get(source), guest.get(source)
                    if (isinstance(first, (int, float)) and
                            isinstance(second, (int, float)) and second >= first):
                        guest[target] = (second - first) / dt
            current[key] = item
            output.append(guest)
        self.previous = current
        self.observed_at = observed_at
        return output


def _color_pairs():
    pairs = {role: 0 for role in _ROLES}
    if not curses.has_colors():
        return pairs
    curses.start_color()
    try:
        curses.use_default_colors()
        background = -1
    except curses.error:
        background = curses.COLOR_BLACK
    for number, (role, foreground) in enumerate(_ROLES.items(), 1):
        try:
            color = (background if background == -1 else curses.COLOR_WHITE)
            curses.init_pair(number, color if foreground is None else foreground,
                             background)
            pairs[role] = curses.color_pair(number)
        except curses.error:
            pass
    return pairs


def _paint(stdscr, grid, pairs):
    height, width = stdscr.getmaxyx()
    stdscr.erase()
    for y, row in enumerate(grid):
        if y >= height:
            break
        for x, (char, role, attrs) in enumerate(row):
            if x >= width or (y == height - 1 and x == width - 1):
                continue
            style = pairs.get(role, 0)
            for attr in attrs:
                style |= {"dim": curses.A_DIM, "reverse": curses.A_REVERSE,
                          "bold": curses.A_BOLD}.get(attr, 0)
            if role == "dim":
                style |= curses.A_DIM
            if role == "selected":
                style |= curses.A_REVERSE
            token = console_render.ACS_TOKENS.get(char)
            if token is not None:
                glyph = getattr(curses, token, None)
                if glyph is None:
                    char = _ASCII_TOKENS[char]
                else:
                    char = glyph
            try:
                if isinstance(char, int):
                    stdscr.addch(y, x, char, style)
                else:
                    stdscr.addstr(y, x, char, style)
            except curses.error:
                # A resize may land between getmaxyx and a cell write.
                continue
    stdscr.refresh()


def _signal_stop(_signum, _frame):
    global _stop_requested
    _stop_requested = True


def _parse_args(argv):
    parser = argparse.ArgumentParser(description="ProxMenux console TUI")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--snapshot", default=console_snapshot.DEFAULT_PATH)
    parser.add_argument("--proc-root", default="/")
    parser.add_argument("--state-dir", default=os.environ.get(
        "PMX_CONSOLE_STATE_DIR", console_snapshot.DEFAULT_STATE_DIR))
    parser.add_argument("--glyphs", choices=("acs", "unicode", "ascii", "auto"),
                        default="acs")
    parser.add_argument("--autostart", action="store_true")
    return parser.parse_args(argv)


def _run(stdscr, args):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.timeout(1000)
    stdscr.keypad(True)
    pairs = _color_pairs()
    sampler = console_metrics.LocalSampler(proc_root=args.proc_root)
    translator = Translator()
    rates = GuestRates()
    glyphs = "acs" if args.glyphs == "auto" else args.glyphs
    selected_view = "node"
    sort = "cpu"
    snapshot = None
    guests = []
    previous_mtime = object()
    last_clear = time.monotonic()
    reload_now = True
    repaint = False
    while not _stop_requested:
        now = time.time()
        local = sampler.sample(time.monotonic())
        local["uptime"] = _uptime(args.proc_root)
        try:
            console_snapshot.touch_lease(args.state_dir, now)
        except (OSError, ValueError):
            pass
        try:
            info = os.stat(args.snapshot)
            mtime = (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size)
        except OSError:
            mtime = None
        if reload_now or mtime != previous_mtime:
            snapshot = console_snapshot.load_snapshot(args.snapshot, now)
            if snapshot.reason is None:
                resources = snapshot.data.get("resources") or {}
                guests = rates.update(resources.get("guests") or [],
                                      resources.get("observed_at"))
            else:
                rates = GuestRates()
                guests = []
            previous_mtime = mtime
            reload_now = False
        if snapshot is not None and snapshot.reason is None:
            data = dict(snapshot.data)
            observed = data.get("observed_at")
            data["age_s"] = max(0, now - observed) if observed is not None else None
            data["resources"] = dict(data.get("resources") or {}, guests=guests)
            language = data.get("language")
        else:
            data = None
            language = _configuration_language()
        translator.set_language(language)
        resources = (data or {}).get("resources") or {}
        node = (data or {}).get("node") or {}
        fresh = (resources.get("status") == "ok" and data["age_s"] is not None
                 and data["age_s"] <= 10)
        other = console_metrics.host_other(local, guests, node.get("name"), fresh)
        view_model = {"local": local, "snapshot": data, "host_other": other,
                      "glyphs": glyphs, "lang": translator.language, "tr": translator,
                      "now": now, "selected_view": selected_view, "sort": sort}
        height, width = stdscr.getmaxyx()
        if repaint or time.monotonic() - last_clear >= 30:
            stdscr.clearok(True)
            last_clear = time.monotonic()
            repaint = False
        _paint(stdscr, console_render.render(view_model, width, height), pairs)
        if args.once or _stop_requested:
            break
        key = stdscr.getch()
        if key in (ord("q"), ord("Q")):
            break
        if key in (9, curses.KEY_LEFT, curses.KEY_RIGHT):
            selected_view = "cluster" if selected_view == "node" else "node"
        elif key == ord("1"):
            selected_view = "node"
        elif key == ord("2"):
            selected_view = "cluster"
        elif key == ord("r"):
            reload_now = True
            repaint = True
            try:
                console_snapshot.touch_lease(args.state_dir, time.time())
            except (OSError, ValueError):
                pass
        elif key == ord("a"):
            glyphs = {"acs": "ascii", "ascii": "unicode", "unicode": "acs"}[glyphs]
        elif key == curses.KEY_RESIZE:
            repaint = True
        elif selected_view == "cluster" and key in (ord("c"), ord("m")):
            sort = "cpu" if key == ord("c") else "mem"


def main(argv=None):
    global _stop_requested
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    args = _parse_args(argv)
    _stop_requested = False
    previous = {}
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        previous[signum] = signal.signal(signum, _signal_stop)
    try:
        curses.wrapper(_run, args)
    except Exception as exc:
        print("console_tui: " + str(exc).replace("\n", " "), file=sys.stderr)
        return 1
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    return 0


if __name__ == "__main__":
    sys.exit(main())
