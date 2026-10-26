"""Pure terminal grid renderer for the ProxMenux console.

Each cell is ``(char, color_role, attrs)``. ``attrs`` is a tuple that may
contain ``dim``, ``reverse`` or ``bold``, and ``glyph`` on every bar and graph
cell so that a monochrome painter never draws those in reverse video. In ACS
mode ``char`` can be a logical token from ``ACS_TOKENS``: the curses caller
maps it to the ``curses.ACS_*`` constant named there. Tokens whose value has
no ``ACS_`` prefix are literal characters and are stored as that character,
so the caller only ever sees ``ACS_*`` tokens or printable text. This module
never imports curses.

The ViewModel is a dict of basic types (plus the ``tr`` translator):
``local`` (``cpu_total``, ``per_core``, ``load1/5/15``, ``threads``,
``temp_c``, ``uptime``, ``kernel``, ``mem``, ``zram``, ``net``, ``disk``,
``storages_local``, ``series`` and ``stats``), ``snapshot`` (the
``console_snapshot`` document plus ``age_s``), ``host_other``, ``glyphs``,
``lang``, ``now``, ``selected_view``, ``sort``, ``window_s`` (60 or 300),
``brand`` (``console_brand.load`` result) and ``zoom`` (``[position, count]``).
``local.series`` holds the per-second samples of ``LocalSampler.history``
(``cpu_total`` and ``mem_used`` as fractions, ``rx``/``tx`` in bits/s,
``read``/``write`` in bytes/s, oldest first) and ``local.stats`` the
``LocalSampler.stats(name, window_s)`` result for each of them.
"""

import datetime
import math
import re
import unicodedata

import console_brand
import console_graphs


ACS_TOKENS = {
    "BOX_H": "ACS_HLINE", "BOX_V": "ACS_VLINE",
    "BOX_UL": "ACS_ULCORNER", "BOX_UR": "ACS_URCORNER",
    "BOX_LL": "ACS_LLCORNER", "BOX_LR": "ACS_LRCORNER",
    "BOX_LT": "ACS_LTEE", "BOX_RT": "ACS_RTEE",
    "BOX_TT": "ACS_TTEE", "BOX_BT": "ACS_BTEE", "BOX_X": "ACS_PLUS",
    **console_graphs.ACS_TOKENS,
    "BAR_EMPTY": "ACS_BULLET", "BULLET": "ACS_BULLET",
}
UNICODE_TOKENS = {
    **dict(zip(("BOX_H", "BOX_V", "BOX_UL", "BOX_UR", "BOX_LL", "BOX_LR",
                "BOX_LT", "BOX_RT", "BOX_TT", "BOX_BT", "BOX_X"), "─│┌┐└┘├┤┬┴┼")),
    **console_graphs.UNICODE_TOKENS,
    "BAR_EMPTY": "·", "BULLET": "·",
}
ASCII_TOKENS = {
    **{key: "-" if key == "BOX_H" else "|" if key == "BOX_V" else "+"
       for key in UNICODE_TOKENS if key.startswith("BOX_")},
    **console_graphs.ASCII_TOKENS,
    "BAR_EMPTY": ".", "BULLET": ".",
}
GLYPH = "glyph"
_ROLES = frozenset(("title", "text", "dim", "ok", "warn", "crit", "selected",
                    "graph_in", "graph_out", "brand", "brand_badge"))
_SPACES = re.compile(r" +")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_MIB = 1048576
_GIB = 1073741824
_BIT_UNITS = ((1e9, "Gb/s"), (1e6, "Mb/s"), (1e3, "Kb/s"), (1, "b/s"))
_BYTE_UNITS = ((_GIB, "GiB/s"), (_MIB, "MiB/s"), (1024, "KiB/s"), (1, "B/s"))
# Rate graphs never zoom below 10 K units/s (btop rescales down to 10 KiB/s).
_MIN_RATE = {True: 10000, False: 10240}


def sanitize(text, max_cells, glyphs="acs"):
    """Transliterate untrusted text into bounded, printable terminal cells."""
    if text is None or max_cells <= 0:
        return ""
    normalized = unicodedata.normalize("NFKD", _ANSI.sub("", str(text)))
    printable = []
    for char in normalized:
        if unicodedata.combining(char):
            continue
        if ord(char) < 32 or ord(char) == 127:
            continue
        printable.append(char if " " <= char <= "~" else "?")
    cleaned = _SPACES.sub(" ", "".join(printable)).strip()
    if len(cleaned) > max_cells:
        marker = "…" if glyphs == "unicode" else "~"
        return cleaned[:max_cells - 1] + marker
    return cleaned


def _number(value, default=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _optional(value):
    """A finite number, or None for anything missing or invalid."""
    return None if isinstance(value, bool) else _number(value, None)


def _fraction(value):
    return max(0.0, min(1.0, _number(value)))


def _role(fraction):
    return console_graphs.threshold_role(_fraction(fraction))


def _pct(value):
    return max(0, min(100, round(_number(value) * 100)))


def _ratio(used, total):
    total = _number(total)
    return 0.0 if total <= 0 else _fraction(_number(used) / total)


def _gib(value):
    return _number(value) / _GIB


def _size(value):
    value = max(0, _number(value))
    if value == 0:
        return "0"
    if value < _GIB:
        return f"{value / _MIB:.0f} MiB"
    return f"{_gib(value):.1f} GiB"


def _decimal(value):
    text = f"{value:.1f}"
    return f"{value:.0f}" if float(text) >= 10 else text


def _short_size(value):
    value = max(0, _number(value))
    if value == 0:
        return "0"
    if value < _GIB:
        return f"{value / _MIB:.0f}M"
    return f"{_gib(value):.1f}G"


def _fit(width, *candidates):
    """Return the first candidate that fits ``width`` cells, else the last one."""
    for text in candidates:
        if _length(text) <= width:
            return text
    return candidates[-1]


def _length(text):
    """Cells of a string or of a ``[(text, role)]`` segment list."""
    return len(text) if isinstance(text, str) else sum(len(part) for part, _ in text)


def _uptime(seconds):
    seconds = max(0, int(_number(seconds)))
    days, hours = divmod(seconds // 3600, 24)
    return f"{days}d {hours:02d}h" if days else f"{hours}h {seconds // 60 % 60:02d}m"


def _age(seconds):
    seconds = max(0, int(_number(seconds)))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h"


def _rate_unit(value, bits):
    """``(factor, unit)`` that shows ``value`` (raw units/s) between 1 and 1000."""
    units = _BIT_UNITS if bits else _BYTE_UNITS
    value = max(0, _number(value))
    return next(((factor, unit) for factor, unit in units if value >= factor), units[-1])


def _rate_scale(peak, bits):
    """Nice graph scale for a peak, in raw units, plus its display unit."""
    peak = max(_number(peak), _MIN_RATE[bits])
    factor, unit = _rate_unit(peak, bits)
    return console_graphs.nice_scale(peak / factor, 0) * factor, factor, unit


def _compact_unit(unit):
    """``Mb/s`` -> ``Mb`` and ``MiB/s`` -> ``MB``: units glued to the value."""
    return unit.replace("i", "").replace("/s", "")


def _compact_rate(value, bits):
    if value is None:
        return "--"
    factor, unit = _rate_unit(value, bits)
    return f"{_decimal(_number(value) / factor)}{_compact_unit(unit)}"


def _window(samples, seconds, columns):
    """Oldest-to-newest column maxima of the last ``seconds`` samples.

    Same binning as ``LocalSampler.window``: each column covers
    ``seconds / columns`` seconds and, with fewer seconds than columns, a
    sample repeats; unknown time stays ``None``.
    """
    if seconds <= 0 or columns <= 0:
        return []
    samples = list(samples or [])[-seconds:]
    samples = [None] * (seconds - len(samples)) + [_optional(value) for value in samples]
    values = []
    for column in range(columns):
        start = column * seconds // columns
        end = max(start + 1, (column + 1) * seconds // columns)
        present = [value for value in samples[start:end] if value is not None]
        values.append(max(present) if present else None)
    return values


class Grid(list):
    """List of rows of logical ``(char, color_role, attrs)`` cells."""

    def __init__(self, width, height, glyphs):
        super().__init__([[(' ', 'text', ()) for _ in range(width)] for _ in range(height)])
        self.width = width
        self.height = height
        self.glyphs = glyphs
        self.boxes = []
        self.graphs = []

    def glyph(self, token):
        if self.glyphs == "acs":
            value = ACS_TOKENS[token]
            return token if value.startswith("ACS_") else value
        return (UNICODE_TOKENS if self.glyphs == "unicode" else ASCII_TOKENS)[token]

    def put(self, x, y, value, role="text", attrs=(), limit=None):
        if not 0 <= y < self.height or x >= self.width:
            return
        assert role in _ROLES
        attrs = tuple(attrs)
        bullet = self.glyph("BULLET")
        max_x = self.width if limit is None else min(self.width, limit)
        for index, char in enumerate(str(value)):
            at = x + index
            if 0 <= at < max_x:
                self[y][at] = (bullet if char == "·" else char, role, attrs)

    def segments(self, x, y, parts, limit=None):
        """Put ``[(text, role)]`` one after the other from ``x``."""
        for text, role in parts:
            self.put(x, y, text, role, limit=limit)
            x += len(text)

    def token(self, x, y, token, role="text", attrs=()):
        if 0 <= x < self.width and 0 <= y < self.height:
            assert role in _ROLES
            self[y][x] = (self.glyph(token), role, tuple(attrs))

    def box(self, x, y, width, height, title=()):
        """Draw a dim frame; ``title`` is text or ``[(text, role)]`` segments."""
        if width < 2 or height < 2:
            return
        self.boxes.append((x, y, width, height))
        right, bottom = x + width - 1, y + height - 1
        for column in range(x + 1, right):
            self.token(column, y, "BOX_H", "dim")
            self.token(column, bottom, "BOX_H", "dim")
        for row in range(y + 1, bottom):
            self.token(x, row, "BOX_V", "dim")
            self.token(right, row, "BOX_V", "dim")
        for column, row, token in ((x, y, "BOX_UL"), (right, y, "BOX_UR"),
                                   (x, bottom, "BOX_LL"), (right, bottom, "BOX_LR")):
            self.token(column, row, token, "dim")
        parts = [(title, "title")] if isinstance(title, str) else list(title)
        self.segments(x + 2, y, parts, limit=right - 1)

    def bar(self, x, y, width, fraction):
        """Filled cells in the threshold role of ``fraction``, empty ones dim."""
        if width <= 0:
            return
        fraction = _fraction(fraction)
        filled = round(width * fraction)
        role = console_graphs.threshold_role(fraction)
        for column in range(width):
            if column < filled:
                self.token(x + column, y, "BAR_FULL", role, (GLYPH,))
            else:
                self.token(x + column, y, "BAR_EMPTY", "dim", (GLYPH,))

    def graph(self, x, y, values, cols, rows, scale, colour="threshold"):
        """Paint ``console_graphs.graph`` with its top-left cell at ``(x, y)``."""
        if cols <= 0 or rows <= 0:
            return
        self.graphs.append((x, y, cols, rows))
        cells = console_graphs.graph(values, cols, rows, scale, colour=colour)
        for dy, row in enumerate(cells):
            for dx, (token, role) in enumerate(row):
                if token is not None:
                    self.token(x + dx, y + dy, token, role, (GLYPH,))


def _label(vm, key, glyphs):
    full_key = "runtime.consoleTui." + key
    translator = vm.get("tr")
    result = translator(full_key) if callable(translator) else full_key
    return str(result) if glyphs == "unicode" else sanitize(result, 200, glyphs)


def _label_with(vm, key, glyphs, **values):
    result = _label(vm, key, glyphs)
    for name, value in values.items():
        result = result.replace("{" + name + "}", str(value))
    return result


def _text(grid, x, y, text, width, role="text", untrusted=False):
    if width <= 0:
        return
    if untrusted:
        text = sanitize(text, width, grid.glyphs)
    else:
        text = str(text)[:width]
    grid.put(x, y, text, role, limit=x + width)


def _clip(grid, text, width):
    """``text`` cut to ``width`` cells with a visible end marker."""
    if len(text) <= width:
        return text
    return text[:max(0, width - 1)] + ("…" if grid.glyphs == "unicode" else "~")


def _separator(grid):
    return "." if grid.glyphs == "ascii" else "·"


def _join(grid, parts):
    return f" {_separator(grid)} ".join(part for part in parts if part)


def _degree(grid):
    return " °C" if grid.glyphs == "unicode" else " C"


def _remote_state(vm):
    snapshot = vm.get("snapshot") or {}
    resources = snapshot.get("resources") or {}
    age = _number(snapshot.get("age_s"))
    interval = _number(snapshot.get("publish_interval_s"), 10) or 10
    status = resources.get("status")
    uptime = _number((vm.get("local") or {}).get("uptime"), 999999)
    if status == "starting":
        return "starting" if age <= 15 or uptime < 120 else "unavailable"
    if not snapshot:
        return "starting" if uptime < 120 else "unavailable"
    if age > max(60, 4 * interval) or status in ("unavailable", "error"):
        return "unavailable"
    if status == "stale" or age > 2 * interval:
        return "stale"
    return "ok" if status == "ok" else "unavailable"


def _clock(vm):
    now = vm.get("now")
    try:
        return datetime.datetime.fromtimestamp(_number(now)).strftime("%H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return "--:--:--"


def _version(grid, node, full=False):
    text = sanitize(node.get("pve_version") or "n/d", 40, grid.glyphs)
    match = re.search(r"\d+(?:\.\d+)+" if full else r"\d+\.\d+", text)
    return match.group(0) if match else text


def _header(grid, vm, state, cluster_view):
    label = lambda key: _label(vm, key, grid.glyphs)
    snapshot = vm.get("snapshot") or {}
    cluster = snapshot.get("cluster") or {}
    node = snapshot.get("node") or {}
    grid.put(1, 0, label("title"), "title")
    tabs_x = 22
    for view, key in (("node", "tabs.node"), ("cluster", "tabs.cluster")):
        name = label(key)
        selected = cluster_view == (view == "cluster")
        shown = f"[{name}]" if selected else name
        grid.put(tabs_x, 0, shown, "selected" if selected else "text",
                 ("reverse",) if selected else ())
        tabs_x += len(shown) + 1
    clock = _clock(vm)
    clock_x = grid.width - 1 - len(clock)
    grid.put(clock_x, 0, clock)
    info_x = tabs_x + 1
    width = max(0, clock_x - 1 - info_x)
    separator = f" {_separator(grid)} "
    if state == "starting":
        candidates = [[(label("status.starting"), "warn")]]
    elif state == "unavailable":
        age = f" ({_age(snapshot.get('age_s'))})" if snapshot else ""
        candidates = [[(label("status.monitorUnavailable") + age, "crit")]]
    elif cluster_view:
        candidates = _cluster_info(grid, vm, state, separator)
    else:
        name = sanitize(node.get("name") or "", 20, grid.glyphs)
        version = f"PVE {_version(grid, node)}"
        uptime = f"{label('labels.uptime')} {_uptime((vm.get('local') or {}).get('uptime'))}"
        middle = []
        if state == "ok" and not cluster.get("is_cluster", True):
            middle = [(separator + label("labels.standalone"), "title")]
        elif state == "ok" and cluster.get("quorate") is False:
            up = int(_number(cluster.get("nodes_online")))
            total = int(_number(cluster.get("nodes_total")))
            middle = [(separator, "title"), (f"{label('labels.noQuorum')} {up}/{total}", "crit")]
        head = [(name, "title")] + middle
        candidates = [head + [(separator + version + separator + uptime, "title")],
                      head + [(separator + version, "title")], head]
    parts = _fit(width, *candidates)
    grid.segments(info_x, 0, parts, limit=info_x + width)
    badge = (vm.get("brand") or {}).get("badge")
    if badge:
        console_brand.paint_badge(grid, 0, clock_x - 3, badge)


def _cluster_info(grid, vm, state, separator):
    """Header candidates of view B, longest first."""
    label = lambda key: _label(vm, key, grid.glyphs)
    snapshot = vm.get("snapshot") or {}
    cluster = snapshot.get("cluster") or {}
    if not cluster.get("is_cluster", True):
        return [[(label("labels.standalone"), "text")]]
    up = int(_number(cluster.get("nodes_online")))
    total = int(_number(cluster.get("nodes_total")))
    quorum = bool(cluster.get("quorate"))
    role = "ok" if quorum else "crit"
    name = sanitize(cluster.get("name") or "", 24, grid.glyphs)
    title = f"{label('labels.quorumOk' if quorum else 'labels.noQuorum')} {up}/{total}"
    coverage = _coverage(snapshot)
    if state == "ok" and quorum and coverage == total and total > 0:
        nodes = _online_nodes(snapshot)
        mem = sum(_number(n.get("maxmem")) for n in nodes)
        capacity = sum(_number(n.get("maxcpu")) for n in nodes)
        cores = sum(_number(n.get("cpu")) * _number(n.get("maxcpu")) for n in nodes)
        usage = cores / capacity if capacity else 0.0
        tail = [(f"{separator}{mem / _GIB:.0f} GiB{separator}{label('columns.cpu')} ", role),
                (f"{_pct(usage)}%", _role(usage))]
    else:
        tail = [(f" {label('labels.coverage')} {coverage}/{total}", role)]
    return [[(_join(grid, (name, title)), role)] + tail, [(title, role)] + tail,
            [(_join(grid, (name, title)), role)], [(title, role)]]


def _online_nodes(snapshot):
    return [n for n in (snapshot.get("resources") or {}).get("nodes", [])
            if n.get("status") == "online"]


def _coverage(snapshot):
    cluster = snapshot.get("cluster") or {}
    members = {m.get("name") for m in cluster.get("members", []) if m.get("online")}
    nodes = {n.get("name") for n in _online_nodes(snapshot)}
    return len(members & nodes)


def _footer(grid, vm, state, cluster_view):
    label = lambda key: _label(vm, key, grid.glyphs)
    parts = [label("footer.quit"), label("footer.switchNode" if cluster_view else "footer.switch"),
             label("footer.sort" if cluster_view else "footer.window"),
             label("footer.refresh"), label("footer.glyphs")]
    zoom = vm.get("zoom")
    if isinstance(zoom, (list, tuple)) and len(zoom) == 2:
        parts.append(_label_with(vm, "footer.zoom", grid.glyphs,
                                 position=int(_number(zoom[0])), count=int(_number(zoom[1]))))
    status = (_label_with(vm, "status.data", grid.glyphs,
                          age=_age(vm["snapshot"].get("age_s")))
              if state != "starting" and vm.get("snapshot") else label("status.noData"))
    width = max(0, grid.width - len(status) - 4)
    candidates = [_join(grid, parts)]
    if not cluster_view:
        other = label("footer.otherTty")
        candidates = [_join(grid, parts + [f"{other} {label('footer.otherTtyHint')}"]),
                      _join(grid, parts + [other]), candidates[0]]
    _text(grid, 1, grid.height - 1, _fit(width, *candidates), width, "dim")
    _text(grid, grid.width - len(status) - 1, grid.height - 1, status, len(status), "dim")


# ---------------------------------------------------------------- node view layout

def _halves(width):
    left = 43 if width == 80 else (width + 1) // 2
    return left, width - left


def _core_cells(per_core):
    """``[(label, value)]``: threads, pairs above 64, quartets above 128."""
    values = [_fraction(value) for value in per_core or []]
    group = 4 if len(values) > 128 else 2 if len(values) > 64 else 1
    cells = []
    for start in range(0, len(values), group):
        chunk = values[start:start + group]
        name = f"C{start}" if group == 1 else f"C{start}-{start + len(chunk) - 1}"
        cells.append((name, max(chunk)))
    return cells


def _core_columns(cells, inner):
    label_width = max(len(name) for name, _ in cells) + 1
    cell_width = label_width + 10
    return label_width, cell_width, max(1, inner // cell_width)


def _node_layout(grid, guests_needed, cells):
    """Rows of the CPU/MEMORY panels, NET/DISK row and TOP lists (ADR §2.4)."""
    height = grid.height
    available = height - 2
    if height < 40:
        return {"cpu": 5, "graphs": 5, "lists": available - 10, "hist": 1, "cores": 0}
    core_rows = 0
    if grid.width >= 120 and cells:
        _, _, per_row = _core_columns(cells, _halves(grid.width)[0] - 4)
        core_rows = min(math.ceil(len(cells) / per_row), max(1, height // 6))
    # The guest lists get G + 3 rows, at least a sixth and at most a quarter
    # of the screen. The CPU/MEMORY history then grows from 4 to 20 rows as
    # long as the rate graphs keep a third of the screen; the graphs take the
    # rest up to half of it, and what is left stays in the CPU/MEMORY panels.
    lists = max(5, min(max(guests_needed + 3, height // 6), height // 4))
    fixed = 4 + core_rows
    hist = max(4, min(20, available - lists - fixed - height // 3))
    graphs = min(height // 2, available - lists - fixed - hist)
    if graphs < 7:
        lists = max(5, lists - (7 - graphs))
        graphs = min(height // 2, available - lists - fixed - hist)
    cpu = available - lists - graphs
    return {"cpu": cpu, "graphs": graphs, "lists": lists, "hist": hist, "cores": core_rows}


def _band_rows(hist):
    """Graph rows of the live band and of the 60-minute band (about 3 : 2)."""
    rows = max(2, hist - 2)
    sixty = max(1, rows * 2 // 5)
    return rows - sixty, sixty


def _window_text(vm):
    window = 300 if _number(vm.get("window_s"), 60) >= 300 else 60
    return window, f"{window // 60}m"


def _series(vm, name):
    return ((vm.get("local") or {}).get("series") or {}).get(name) or []


def _stats(vm, name):
    stats = ((vm.get("local") or {}).get("stats") or {}).get(name) or {}
    return {key: _optional(stats.get(key)) for key in ("now", "prev", "peak")}


def _local_history(vm):
    """This node's 60-minute RRD entry, or None when it has no data."""
    snapshot = vm.get("snapshot") or {}
    history = snapshot.get("history")
    name = (snapshot.get("node") or {}).get("name")
    if not isinstance(history, dict) or not name:
        return None
    entry = (history.get("nodes") or {}).get(name)
    if not isinstance(entry, dict):
        return None
    if not any(_optional(value) is not None
               for key in ("cpu", "mem") for value in entry.get(key) or []):
        return None
    return entry


def _cpu_memory(grid, vm, layout):
    label = lambda key: _label(vm, key, grid.glyphs)
    local = vm.get("local") or {}
    mem = local.get("mem") or {}
    cpu_fraction = _fraction(local.get("cpu_total"))
    memory_fraction = _ratio(mem.get("used"), mem.get("total"))
    left, right = _halves(grid.width)
    rows = layout["cpu"]
    tall = grid.height >= 40
    _, window_label = _window_text(vm)
    live = _label_with(vm, "labels.live", grid.glyphs, window=window_label) + " (w)"
    subtitle = _join(grid, (live, label("labels.last60"))) if tall else live
    used = _gib(mem.get("used"))
    for x, width, head, fraction in (
            (0, left, f"{label('panels.cpu')}  ", cpu_fraction),
            (left, right, f"{label('panels.memory')}  {_decimal(used)}/"
                          f"{_gib(mem.get('total')):.0f} GiB  ", memory_fraction)):
        title = [(head, "title"), (f"{_pct(fraction)}%", _role(fraction))]
        grid.box(x, 1, width, rows, _fit(width - 4, title + [(" " + subtitle, "dim")], title))
        grid.bar(x + 2, 2, width - 4, fraction)
    load = " ".join(f"{_number(local.get('load' + str(i))):.2f}" for i in (1, 5, 15))
    parts = [f"{label('labels.load')} {load}",
             f"{int(_number(local.get('threads')))} {label('labels.threads')}"]
    if local.get("temp_c") is not None:
        parts.append(f"{round(_number(local.get('temp_c')))}{_degree(grid)}")
    _text(grid, 2, 3, _join(grid, parts), left - 4)
    _memory_info(grid, vm, left + 2, right - 4, tall)
    if not tall:
        values = _window(_series(vm, "cpu_total"), _window_text(vm)[0], left - 4)
        grid.graph(2, 4, values, left - 4, 1, 1.0)
        return
    for x, width, name, history_key in ((2, left - 4, "cpu_total", "cpu"),
                                        (left + 2, right - 4, "mem_used", "mem")):
        _bands(grid, vm, x, 4, width, layout["hist"], name, history_key)
    if layout["cores"]:
        _cores(grid, vm, 4 + layout["hist"], left - 4, layout["cores"])


def _memory_info(grid, vm, x, width, tall):
    label = lambda key: _label(vm, key, grid.glyphs)
    local = vm.get("local") or {}
    mem = local.get("mem") or {}
    zram = local.get("zram") or {}
    zram_used = zram.get("swap_used_bytes", zram.get("used", 0))
    zram_total = zram.get("capacity_bytes", zram.get("total", 0))
    ratio = _number(zram.get("compression_ratio"))
    full, short = [], []
    for sizer, target in ((_size, full), (_short_size, short)):
        target.append(f"{label('labels.arc')} {sizer(mem.get('arc'))} {_separator(grid)} "
                      f"{label('labels.available')} {sizer(mem.get('available'))}")
        swap = f"{label('labels.swap')} {sizer(mem.get('swap_used'))}/{sizer(mem.get('swap_total'))}"
        if _number(zram_total) > 0:
            swap = (f"{label('labels.zram')} {sizer(zram_used)}/{sizer(zram_total)} "
                    f"{ratio:.1f}x {_separator(grid)} {swap}")
        target.append(swap)
    if tall:
        _text(grid, x, 3, _fit(width, _join(grid, full), _join(grid, short), short[0]), width)
        return
    _text(grid, x, 3, _fit(width, full[0], short[0]), width)
    _text(grid, x, 4, _fit(width, full[1], short[1]), width)


def _bands(grid, vm, x, y, width, hist, name, history_key):
    """The live band (1 s samples, key ``w``) over the 60-minute RRD band."""
    label = lambda key: _label(vm, key, grid.glyphs)
    window, window_label = _window_text(vm)
    live_rows, sixty_rows = _band_rows(hist)
    seconds = f"{window / max(1, width):.1f}"
    _text(grid, x, y, _join(grid, (
        _label_with(vm, "labels.live", grid.glyphs, window=window_label),
        _label_with(vm, "labels.secPerCol", grid.glyphs, seconds=seconds))), width, "dim")
    grid.graph(x, y + 1, _window(_series(vm, name), window, width), width, live_rows, 1.0)
    label_y = y + 1 + live_rows
    entry = _local_history(vm)
    points = [_optional(value) for value in (entry or {}).get(history_key) or []]
    if not points:
        _text(grid, x, label_y, _join(grid, (label("labels.last60"), label("labels.noHistory"))),
              width, "dim")
        return
    target = len(points) * (width // len(points)) if width >= len(points) else width
    values = console_graphs.resample(points, target)
    if len(values) > len(points):
        scale = _label_with(vm, "labels.colsPerMin", grid.glyphs, cols=len(values) // len(points))
    else:
        scale = _label_with(vm, "labels.minPerCol", grid.glyphs,
                            minutes=math.ceil(len(points) / len(values)))
    parts = [label("labels.last60"), scale]
    if entry.get("status") == "stale":
        age = _number(vm.get("now")) - _number(entry.get("observed_at"))
        parts.append(_label_with(vm, "status.stale", grid.glyphs, age=_age(age)))
    head = _join(grid, parts + [label("labels.peakShort")]) + " "
    peak = max((value for value in points if value is not None), default=None)
    _text(grid, x, label_y, head, width, "dim")
    if peak is not None:
        _text(grid, x + len(head), label_y, f"{_pct(peak):>3}%", width - len(head), _role(peak))
    grid.graph(x, label_y + 1, values, len(values), sixty_rows, 1.0)
    axis = f"{label('labels.minAgo')} {len(points)} {_separator(grid) * 4} 0"
    if width - len(values) >= len(axis) + 2:
        _text(grid, x + len(values) + 2, label_y + sixty_rows, axis, len(axis), "dim")


def _cores(grid, vm, y, inner, rows):
    cells = _core_cells((vm.get("local") or {}).get("per_core"))
    label_width, cell_width, per_row = _core_columns(cells, inner)
    shown = cells[:rows * per_row]
    for index, (name, value) in enumerate(shown):
        x = 2 + (index % per_row) * cell_width
        row = y + index // per_row
        grid.put(x, row, name, "dim")
        grid.put(x + label_width, row, f"{_pct(value):>3}%", _role(value))
        grid.bar(x + label_width + 5, row, 4, value)
    if len(shown) < len(cells):
        # The last cell says how many did not fit.
        index = len(shown) - 1
        x = 2 + (index % per_row) * cell_width
        row = y + index // per_row
        grid.put(x, row, " " * (cell_width - 1))
        _text(grid, x, row, f"+{len(cells) - index} {_label(vm, 'labels.threads', grid.glyphs)}",
              cell_width - 1, "dim")


# ---------------------------------------------------------------- NET / DISK / side

def _side_widths(width):
    side = max(27, width // 4)
    net = (width - side) // 2
    return net, width - side - net, side


def _io_row(grid, vm, y, rows, state):
    net_width, disk_width, side_width = _side_widths(grid.width)
    if grid.height < 40:
        _rate_compact(grid, vm, 0, y, net_width, rows, "net")
        _rate_compact(grid, vm, net_width, y, disk_width, rows, "disk")
    else:
        _rate_panel(grid, vm, 0, y, net_width, rows, "net")
        _rate_panel(grid, vm, net_width, y, disk_width, rows, "disk")
    _side_panel(grid, vm, net_width + disk_width, y, side_width, rows, state)


_RATES = {"net": (("rx", "labels.rx", "graph_in"), ("tx", "labels.tx", "graph_out")),
          "disk": (("read", "labels.read", "graph_in"), ("write", "labels.write", "graph_out"))}


def _rate_title(grid, vm, kind, width, tail):
    label = lambda key: _label(vm, key, grid.glyphs)
    local = vm.get("local") or {}
    _, window_label = _window_text(vm)
    window = _label_with(vm, "labels.window", grid.glyphs, window=window_label)
    if kind == "net":
        net = local.get("net") or {}
        speed = _number(net.get("speed_mbps"))
        speed_text = f" {speed / 1000:g}G" if speed >= 1000 else f" {speed:g}M" if speed else ""
        head = f"{label('panels.network')} {sanitize(net.get('nic'), 12, grid.glyphs)}{speed_text} "
    else:
        head = f"{label('panels.disk')} "
    title = [(head, "title")]
    candidates = [title + [(window, "dim")], title + [(window_label, "dim")], title]
    storages = local.get("storages_local") or []
    if kind == "disk" and not tail and storages:
        storage = storages[0]
        fraction = _ratio(storage.get("used", storage.get("disk")),
                          storage.get("total", storage.get("maxdisk")))
        name = sanitize(storage.get("storage"), 10, grid.glyphs)
        extra = [(f" {name} ", "dim"), (f"{_pct(fraction)}%", _role(fraction))]
        candidates = [candidates[0] + extra, candidates[1] + extra] + candidates
    return _fit(width - 4, *candidates)


def _rate_panel(grid, vm, x, y, width, rows, kind):
    """Two halves (RX/TX or R/W), each with its own scale (ADR §2.4)."""
    label = lambda key: _label(vm, key, grid.glyphs)
    local = vm.get("local") or {}
    storages = (local.get("storages_local") or []) if kind == "disk" else []
    tail = storages[:min(8, max(0, (rows - 7) // 2 - 3))] if rows >= 20 else []
    grid.box(x, y, width, rows, _rate_title(grid, vm, kind, width, tail))
    inner = width - 4
    half = max(1, (rows - 2 - 5) // 2 - len(tail))
    window, _ = _window_text(vm)
    bits = kind == "net"
    top = y + 1
    for name, key, role in _RATES[kind]:
        stats = _stats(vm, name)
        scale, factor, unit = _rate_scale(stats["peak"], bits)
        shown = lambda value: "--" if value is None else _decimal(value / factor)
        head = (f"{label(key)} {shown(stats['now'])} {_separator(grid)} {label('labels.prev')} "
                f"{shown(stats['prev'])} {_separator(grid)} {label('labels.peak')} "
                f"{shown(stats['peak'])} {unit}")
        maximum = f"{label('labels.max')} {_decimal(scale / factor)} {unit}"
        _text(grid, x + 2, top, head, inner, role)
        if len(head) + 1 + len(maximum) <= inner:
            _text(grid, x + width - 2 - len(maximum), top, maximum, len(maximum), "dim")
        grid.graph(x + 2, top + 1, _window(_series(vm, name), window, inner), inner, half, scale, role)
        top += half + 2
    for index, storage in enumerate(tail):
        _storage_row(grid, x + 2, top + index, inner, storage)


def _storage_row(grid, x, y, width, storage):
    used = storage.get("used", storage.get("disk"))
    total = storage.get("total", storage.get("maxdisk"))
    fraction = _ratio(used, total)
    amount = f"{_gib(used):.0f}/{_gib(total):.0f} GiB"
    bar = min(20, width - 11 - 2 - 4 - 2 - len(amount))
    grid.put(x, y, sanitize(storage.get("storage"), 10, grid.glyphs))
    if bar >= 4:
        grid.bar(x + 11, y, bar, fraction)
    pct_x = x + 11 + max(bar, 0) + 2
    grid.put(pct_x, y, f"{_pct(fraction):>3}%", _role(fraction))
    _text(grid, pct_x + 6, y, amount, x + width - pct_x - 6)


def _rate_compact(grid, vm, x, y, width, rows, kind):
    """Two one-row sparklines and ``prev a/b max scale`` (ADR §2.4, 80x24)."""
    label = lambda key: _label(vm, key, grid.glyphs)
    grid.box(x, y, width, rows, _rate_title(grid, vm, kind, width, []))
    inner = width - 4
    bits = kind == "net"
    window, _ = _window_text(vm)
    names = _RATES[kind]
    stats = [_stats(vm, name) for name, _, _ in names]
    peak = max((item["peak"] for item in stats if item["peak"] is not None), default=0)
    scale, factor, unit = _rate_scale(peak, bits)
    spark = inner - 10
    for row, ((name, key, role), item) in enumerate(zip(names, stats)):
        now = item["now"]
        if now is None:
            source = (vm.get("local") or {}).get(kind) or {}
            raw = source.get({"rx": "rx_bps", "tx": "tx_bps", "read": "read_bps",
                              "write": "write_bps"}[name])
            now = None if raw is None else _number(raw) * (8 if bits else 1)
        _text(grid, x + 2, y + 1 + row, f"{label(key):<3}{_compact_rate(now, bits):>6}", inner, role)
        if spark > 0:
            grid.graph(x + 12, y + 1 + row, _window(_series(vm, name), window, spark),
                       spark, 1, scale, role)
    previous = "/".join("--" if item["prev"] is None else _decimal(item["prev"] / factor)
                        for item in stats)
    line = (f"{label('labels.prev')} {previous} {label('labels.max')} "
            f"{_decimal(scale / factor)}{_compact_unit(unit)}")
    _text(grid, x + 2, y + 3, line, inner)


def _guest_counts(snapshot, node=None):
    guests = [g for g in _guests(snapshot) if node is None or g.get("node") == node]
    running = sum(g.get("status") == "running" for g in guests)
    return running, len(guests) - running


def _side_panel(grid, vm, x, y, width, rows, state):
    label = lambda key: _label(vm, key, grid.glyphs)
    snapshot = vm.get("snapshot") or {}
    cluster = snapshot.get("cluster") or {}
    standalone = not cluster.get("is_cluster", True)
    inner = width - 4
    if standalone:
        grid.box(x, y, width, rows, label("labels.standalone"))
        node = snapshot.get("node") or {}
        running, stopped = _guest_counts(snapshot, node.get("name"))
        version = f"PVE {_version(grid, node, full=True)}"
        kernel = (vm.get("local") or {}).get("kernel")
        versions = [version]
        if kernel:
            kernel = f"{label('labels.kernel')} {sanitize(kernel, 40, grid.glyphs)}"
            versions.insert(0, _join(grid, (version, kernel)))
        counts = (f"{label('labels.running')} {running}", f"{label('labels.stopped')} {stopped}")
        lines = [(_clip(grid, label("labels.noCluster"), inner), "dim"),
                 (_fit(inner, f"{label('labels.guests')} {_join(grid, counts)}",
                       _join(grid, counts)), "text"),
                 (_fit(inner, *versions), "dim")]
        used = min(len(lines), rows - 2)
        for index, (text, role) in enumerate(lines[:used]):
            _text(grid, x + 2, y + 1 + index, text, inner, role)
    else:
        used = _cluster_panel(grid, vm, x, y, width, rows, state)
    art = (vm.get("brand") or {}).get("art")
    if art and grid.height >= 40:
        first = y + 1 + used
        console_brand.paint_art(grid, x + 1, first, width - 2, y + rows - 1 - first, art)


def _cluster_panel(grid, vm, x, y, width, rows, state):
    """Members of the cluster, then the guest counts; returns the rows used."""
    label = lambda key: _label(vm, key, grid.glyphs)
    snapshot = vm.get("snapshot") or {}
    cluster = snapshot.get("cluster") or {}
    inner = width - 4
    up = int(_number(cluster.get("nodes_online")))
    total = int(_number(cluster.get("nodes_total")))
    quorate = cluster.get("quorate")
    head = label("panels.cluster")
    name = sanitize(cluster.get("name"), 15, grid.glyphs)
    named = f"{head} {name}" if name else head
    separator = _separator(grid)
    if quorate is None:
        title = [(_fit(inner, named, head), "title")]
    else:
        quorum = f"{label('labels.quorumOk') if quorate else label('labels.noQuorum')} {up}/{total}"
        role = "ok" if quorate else "crit"
        title = _fit(inner, [(f"{named} {separator} ", "title"), (quorum, role)],
                     [(f"{head} {separator} ", "title"), (quorum, role)],
                     [(f"{head} {separator} {up}/{total}", "title")])
    grid.box(x, y, width, rows, title)
    if state == "starting" or quorate is None:
        text = label("status.waitingForData") if state == "starting" else label("status.noData")
        _text(grid, x + 2, y + 1, text, inner, "dim")
        return 1
    members = cluster.get("members") or []
    space = max(0, rows - 2)
    visible = min(len(members), space)
    if len(members) > visible:
        visible = max(0, visible - 1)
    nodes = {node.get("name"): node for node in (snapshot.get("resources") or {}).get("nodes", [])}
    stale = state != "ok"
    for index, member in enumerate(members[:visible]):
        node = nodes.get(member.get("name"), {}) if member.get("online") else {}
        row = y + 1 + index
        member_name = sanitize(member.get("name"), 7, grid.glyphs) + ("*" if member.get("local") else "")
        online = bool(member.get("online"))
        status = label("labels.online" if online else "labels.offline")
        if node:
            cpu = _fraction(node.get("cpu"))
            mem = _ratio(node.get("mem"), node.get("maxmem"))
            parts = [(f"{member_name:<8}", "text"), (f"{_pct(cpu):>2}%", _role(cpu)), (" ", "text"),
                     (f"{_pct(mem):>2}%", _role(mem)), (" ", "text"), (status, "ok")]
        else:
            parts = [(f"{member_name:<8}", "crit" if not online else "text"),
                     ("--  --  ", "text"), (status, "crit" if not online else "warn")]
        if stale:
            parts = [(text, "dim" if part_role not in ("crit",) else part_role)
                     for text, part_role in parts]
        grid.segments(x + 2, row, parts, limit=x + width - 2)
    used = visible
    if len(members) > visible:
        _text(grid, x + 2, y + 1 + visible,
              _label_with(vm, "labels.moreNodes", grid.glyphs, count=len(members) - visible),
              inner, "dim")
        used += 1
    if used < space:
        running, stopped = _guest_counts(snapshot)
        guests = label("labels.guests")
        text = _fit(inner, _join(grid, (f"{guests} {label('labels.running')} {running}",
                                        f"{label('labels.stopped')} {stopped}")),
                    f"{guests} {running} {label('labels.running')}")
        _text(grid, x + 2, y + 1 + used, text, inner, "dim" if stale else "text")
        used += 1
    return used


# ---------------------------------------------------------------- TOP lists

def _guests(snapshot):
    return [guest for guest in (snapshot.get("resources") or {}).get("guests", [])
            if not guest.get("template")]


def _cpu_key(guest):
    return _number(guest.get("cpu")) * _number(guest.get("maxcpu"))


def _top_lists(guests):
    """TOP MEMORY (``mem > 0``, any status) and TOP CPU (host cores > 0)."""
    memory = sorted((g for g in guests if _number(g.get("mem")) > 0),
                    key=lambda g: (-_number(g.get("mem")), int(_number(g.get("vmid")))))
    cpu = sorted((g for g in guests if _cpu_key(g) > 0),
                 key=lambda g: (-_cpu_key(g), int(_number(g.get("vmid")))))
    return memory, cpu


def _identity(grid, guest, width):
    kind = "VM" if guest.get("type") == "qemu" else "CT"
    head = f"{kind} {guest.get('vmid', '')} "
    return head + sanitize(guest.get("name"), max(1, width - len(head)), grid.glyphs)


def _status_role(guest):
    status = guest.get("status")
    return "ok" if status == "running" else "warn" if status in ("unknown", "stale") else "text"


def _wide_prefix(grid, guest, x, y):
    kind = "VM" if guest.get("type") == "qemu" else "CT"
    grid.put(x, y, f"{kind:<5}{str(guest.get('vmid', ''))[:4]:<5}"
                   f"{sanitize(guest.get('name'), 13, grid.glyphs):<14}"
                   f"{sanitize(guest.get('node'), 7, grid.glyphs):<8}")
    grid.put(x + 32, y, sanitize(guest.get("status"), 9, grid.glyphs), _status_role(guest))


def _memory_row(grid, guest, x, y, width, wide):
    used, assigned = guest.get("mem"), guest.get("maxmem")
    fraction = _ratio(used, assigned)
    pct = f"{_pct(fraction):>3}%" if _number(assigned) > 0 else " --%"
    if wide:
        x0 = x + 2
        _wide_prefix(grid, guest, x0, y)
        grid.put(x0 + 41, y, f"{_size(used)}/{_size(assigned)}"[:19])
        grid.put(x0 + 60, y, pct, _role(fraction))
        if x0 + 76 <= x + width - 2 and _number(assigned) > 0:
            grid.bar(x0 + 66, y, 10, fraction)
        return
    assign_x = x + width - 18
    _text(grid, x + 2, y, _identity(grid, guest, assign_x - x - 3), assign_x - x - 3)
    amount = f"{_short_size(used):>5}/{_short_size(assigned)}"
    _text(grid, assign_x, y, amount, x + width - 7 - assign_x)
    grid.put(x + width - 7, y, pct, _role(fraction))


def _cpu_row(grid, guest, x, y, width, wide):
    fraction = _fraction(guest.get("cpu"))
    cores = f"{_cpu_key(guest):.1f}c"
    vcpu = str(int(_number(guest.get("maxcpu"))))
    if wide:
        x0 = x + 2
        _wide_prefix(grid, guest, x0, y)
        grid.put(x0 + 42, y, f"{_pct(fraction):>3}%", _role(fraction))
        grid.put(x0 + 51 - len(vcpu), y, vcpu)
        grid.put(x0 + 58 - len(cores), y, cores)
        used = _size(guest.get("mem"))
        if x0 + 69 <= x + width - 2:
            grid.put(x0 + 69 - len(used), y, used)
        return
    name_end = x + width - 19
    _text(grid, x + 2, y, _identity(grid, guest, name_end - x - 2), name_end - x - 2)
    grid.put(x + width - 18, y, f"{_pct(fraction):>3}%", _role(fraction))
    grid.put(x + width - 9 - len(vcpu), y, vcpu)
    grid.put(x + width - 4 - len(cores), y, cores)


def _list_headers(grid, vm, x, y, width, mode, wide):
    label = lambda key: _label(vm, key, grid.glyphs)
    if wide:
        prefix = (f"{label('columns.type'):<5}{label('columns.id'):<5}{label('columns.name'):<14}"
                  f"{label('columns.node'):<8}{label('columns.status'):<9}")
        if mode == "mem":
            text = f"{prefix}{label('columns.usedAssignedLong'):<22}%  {label('columns.mem')}"
        else:
            text = (f"{prefix} {label('columns.cpuPercent'):>4} {label('columns.vcpu'):>4}"
                    f"   {label('columns.hostCores'):>4}   {label('columns.memUsed')}")
        _text(grid, x + 2, y, text, width - 4, "title")
        return
    _text(grid, x + 2, y, label("columns.guest"), width - 4, "title")
    if mode == "mem":
        _text(grid, x + width - 18, y, label("columns.usedAssigned"), 12, "title")
        grid.put(x + width - 4, y, "%", "title")
    else:
        for last, key in ((width - 15, "columns.cpuPercent"), (width - 10, "columns.vcpu"),
                          (width - 5, "columns.hostCores")):
            text = label(key)
            grid.put(x + last - len(text) + 1, y, text, "title")


def _top(grid, vm, y, rows, state):
    label = lambda key: _label(vm, key, grid.glyphs)
    snapshot = vm.get("snapshot") or {}
    midpoint = grid.width // 2
    # TYPE/ID/NAME/NODE/STATUS columns need 69 cells inside each panel.
    wide = midpoint - 4 >= 69
    mem_extra = [label("labels.footprint")]
    cpu_extra = [label("labels.shareOfVcpu"), label("labels.hostCores")]
    # The host-other figure is a value, so it keeps the text role (I4).
    mem_tail = cpu_tail = []
    if state == "ok":
        host_other = vm.get("host_other") or {}
        other = label("labels.hostOther") + " "
        if host_other.get("mem") is not None:
            mem_tail = [(other, "dim"), (_size(host_other["mem"]), "text")]
        if host_other.get("cpu") is not None:
            cpu_tail = [(other, "dim"), (f"{_number(host_other['cpu']):.1f}c", "text")]
    elif snapshot and state in ("stale", "unavailable"):
        mem_tail = cpu_tail = [("(" + _label_with(vm, "status.stale", grid.glyphs,
                                                  age=_age(snapshot.get("age_s"))) + ")", "dim")]
    panels = ((0, midpoint, "mem", label("panels.topMemory") + " ", mem_extra, mem_tail),
              (midpoint, grid.width - midpoint, "cpu", label("panels.topCpuShort") + " ",
               cpu_extra, cpu_tail))
    memory, cpu = _top_lists(_guests(snapshot))
    for x, width, mode, head, extra, tail in panels:
        candidates = []
        for start in range(len(extra) + 1):
            described = _join(grid, extra[start:])
            if described and tail:
                described += f" {_separator(grid)} "
            candidates.append([(head, "title"), (described, "dim")] + tail)
        candidates.append([(head.rstrip(), "title")])
        grid.box(x, y, width, rows, _fit(width - 4, *candidates))
        if state == "starting" or not snapshot:
            text = label("status.waitingForData") if state == "starting" else label("status.noData")
            _text(grid, x + 2, y + 1, text, width - 4, "dim")
            continue
        items = memory if mode == "mem" else cpu
        if not items:
            continue
        _list_headers(grid, vm, x, y + 1, width, mode, wide)
        visible = max(0, rows - 3)
        if len(items) > visible:
            visible = max(0, visible - 1)
        for index, guest in enumerate(items[:visible]):
            row = y + 2 + index
            (_memory_row if mode == "mem" else _cpu_row)(grid, guest, x, row, width, wide)
            if state != "ok":
                for column in range(x + 1, x + width - 1):
                    char, _, attrs = grid[row][column]
                    if GLYPH not in attrs:
                        grid[row][column] = (char, "dim", attrs)
        if len(items) > visible:
            _text(grid, x + 2, y + 2 + visible,
                  _label_with(vm, "labels.moreGuests", grid.glyphs, count=len(items) - visible),
                  width - 4, "dim")


def _node_view(grid, vm, state):
    snapshot = vm.get("snapshot") or {}
    memory, cpu = _top_lists(_guests(snapshot))
    cells = _core_cells((vm.get("local") or {}).get("per_core"))
    layout = _node_layout(grid, max(len(memory), len(cpu)), cells)
    _cpu_memory(grid, vm, layout)
    _io_row(grid, vm, 1 + layout["cpu"], layout["graphs"], state)
    _top(grid, vm, 1 + layout["cpu"] + layout["graphs"], layout["lists"], state)


def _cluster_module():
    """``console_cluster`` (vista B), or None while it is not installed."""
    try:
        import console_cluster
    except ModuleNotFoundError as error:
        if error.name != "console_cluster":
            raise
        return None
    return console_cluster


def render(view_model, width, height):
    """Render a ViewModel to a deterministic ``height × width`` Grid."""
    glyphs = view_model.get("glyphs", "acs")
    if glyphs not in ("acs", "ascii", "unicode"):
        glyphs = "acs"
    grid = Grid(width, height, glyphs)
    if width < 80 or height < 24:
        message = _label(view_model, "status.terminalTooSmall", glyphs)
        _text(grid, max(0, (width - len(message)) // 2), max(0, height // 2),
              message, width, "warn")
        return grid
    state = _remote_state(view_model)
    cluster_view = view_model.get("selected_view") == "cluster"
    _header(grid, view_model, state, cluster_view)
    if cluster_view:
        cluster = _cluster_module()
        if cluster is not None:
            plan = cluster.render(grid, view_model, state) or {}
            art = (view_model.get("brand") or {}).get("art")
            if art and plan.get("art_area"):
                console_brand.paint_art(grid, *plan["art_area"], art)
        else:
            _text(grid, 2, 2, _label(view_model, "status.noData", glyphs), width - 4, "dim")
    else:
        _node_view(grid, view_model, state)
    _footer(grid, view_model, state, cluster_view)
    return grid
