"""Cluster view (view B) of the ProxMenux console.

``render(grid, vm, state)`` paints rows 1 to ``height - 2`` of a
``console_render.Grid``; the header and the footer belong to console_render.
``vm`` is the console ViewModel and ``state`` the freshness of its snapshot
(``ok``, ``stale``, ``unavailable`` or ``starting``). From top to bottom:

* the node table, one row per node plus a column header, at most ``H // 4``
  rows (``+k nodes`` when more), with ``LOAD`` from the history at >= 120
  columns;
* the CPU and MEMORY panels with the last 60 minutes of every node, a block
  of ``g`` rows per node, ``g`` in ``[2, 8]``; nodes that do not fit are
  summed up as ``+k nodes`` on the bottom border;
* the TOP CPU and TOP MEMORY lists;
* the rest: the guests outside the lists on one or two dim lines below 40
  rows, the full guest table from 40 rows on.

Below 100 columns or 28 rows, or with no room for one history block, the view
is compact: node table, lists and the rest, without history panels.

History columns hold a whole number of minutes, or each minute a whole number
of columns: ``ceil(60 / room)`` minutes per column when 60 points do not fit,
otherwise ``room // 60`` columns per minute (``1 min = 2 cols`` at 320
columns), so the label under each panel is always exact.

Cells are written directly as ``(char, role, attrs)``. Bar and graph cells
carry the ``glyph`` attribute. In ``acs`` mode ``char`` is a logical token
(``BOX_*``, ``BAR_FULL``, ``BAR_HALF``, ``BAR_EMPTY``, ``BULLET``) that the
curses caller maps through ``console_render.ACS_TOKENS``; ``BAR_THIN`` is the
literal ``_`` in every mode. This module never imports curses.
"""

import math
import re
import unicodedata

import console_graphs


_UNICODE = {"BOX_H": "─", "BOX_V": "│", "BOX_UL": "┌", "BOX_UR": "┐",
            "BOX_LL": "└", "BOX_LR": "┘", "BAR_EMPTY": "·", "BULLET": "·",
            **console_graphs.UNICODE_TOKENS}
_ASCII = {"BOX_H": "-", "BOX_V": "|", "BOX_UL": "+", "BOX_UR": "+",
          "BOX_LL": "+", "BOX_LR": "+", "BAR_EMPTY": ".", "BULLET": ".",
          **console_graphs.ASCII_TOKENS}
_GLYPH = ("glyph",)
_SPACES = re.compile(r" +")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_GIB = 1073741824
_MIB = 1048576
_TOP_GUEST = 21          # identity column of the TOP lists at >= 100 columns
_TOP_GUEST_NARROW = 12   # ... and below 100 columns (ADR 001 §2.4, A-8)


def sanitize(text, max_cells, glyphs="acs"):
    """Bounded printable ASCII, as ``console_render.sanitize``."""
    if text is None or max_cells <= 0:
        return ""
    normalized = unicodedata.normalize("NFKD", _ANSI.sub("", str(text)))
    kept = []
    for char in normalized:
        if unicodedata.combining(char) or ord(char) < 32 or ord(char) == 127:
            continue
        kept.append(char if " " <= char <= "~" else "?")
    cleaned = _SPACES.sub(" ", "".join(kept)).strip()
    if len(cleaned) > max_cells:
        return cleaned[:max_cells - 1] + ("…" if glyphs == "unicode" else "~")
    return cleaned


def _num(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _fraction(used, total):
    used, total = _num(used), _num(total)
    if used is None or not total or total <= 0:
        return None
    return max(0.0, min(1.0, used / total))


def _pct(fraction):
    return f"{max(0.0, min(1.0, fraction)) * 100:3.0f}%"


def _uptime(seconds):
    seconds = max(0, int(_num(seconds) or 0))
    days, hours = divmod(seconds // 3600, 24)
    return f"{days}d {hours:02d}h" if days else f"{hours}h"


def _age(seconds):
    seconds = max(0, int(_num(seconds) or 0))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h"


def _short(value):
    value = max(0.0, _num(value) or 0.0)
    return f"{value / _MIB:.0f}M" if value < _GIB else f"{value / _GIB:.1f}G"


def _size(value):
    value = max(0.0, _num(value) or 0.0)
    return f"{value / _MIB:.0f} MiB" if value < _GIB else f"{value / _GIB:.1f} GiB"


def _cores(guest):
    return max(0.0, _num(guest.get("cpu")) or 0.0) * max(0.0, _num(guest.get("maxcpu")) or 0.0)


def _vmid(guest):
    value = _num(guest.get("vmid"))
    return int(value) if value is not None else 0


def _key(guest):
    return (guest.get("vmid"), guest.get("node"))


class _Painter:
    """Glyph-aware cell writer and label lookup for one frame."""

    def __init__(self, grid, vm):
        self.grid = grid
        self.vm = vm
        self.glyphs = grid.glyphs if grid.glyphs in ("acs", "unicode", "ascii") else "acs"
        self.width = grid.width
        self.height = grid.height

    def glyph(self, token):
        if self.glyphs == "unicode":
            return _UNICODE[token]
        if self.glyphs == "ascii":
            return _ASCII[token]
        acs = console_graphs.ACS_TOKENS.get(token, "ACS_")
        return token if acs.startswith("ACS_") else acs

    def cell(self, x, y, char, role, attrs=()):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.grid[y][x] = (char, role, tuple(attrs))

    def text(self, x, y, text, role="text", limit=None):
        """Write ``text`` from ``x``, never at or past ``limit``; returns the end."""
        limit = self.width if limit is None else min(self.width, limit)
        for char in str(text):
            if x >= limit:
                break
            self.cell(x, y, self.glyph("BULLET") if char == "·" else char, role)
            x += 1
        return x

    def rtext(self, right, y, text, role="text"):
        """Right-align ``text`` so that it ends just before ``right``."""
        self.text(right - len(text), y, text, role, right)

    def label(self, key, **values):
        translator = self.vm.get("tr")
        full_key = "runtime.consoleTui." + key
        result = str(translator(full_key)) if callable(translator) else full_key
        if self.glyphs != "unicode":
            result = sanitize(result, 200, self.glyphs)
        for name, value in values.items():
            result = result.replace("{" + name + "}", str(value))
        return result

    def untrusted(self, value, cells):
        return sanitize(value, cells, self.glyphs)

    def box(self, x, y, w, h, segments):
        if w < 2 or h < 2:
            return
        right, bottom = x + w - 1, y + h - 1
        for column in range(x + 1, right):
            self.cell(column, y, self.glyph("BOX_H"), "dim")
            self.cell(column, bottom, self.glyph("BOX_H"), "dim")
        for row in range(y + 1, bottom):
            self.cell(x, row, self.glyph("BOX_V"), "dim")
            self.cell(right, row, self.glyph("BOX_V"), "dim")
        for column, row, token in ((x, y, "BOX_UL"), (right, y, "BOX_UR"),
                                   (x, bottom, "BOX_LL"), (right, bottom, "BOX_LR")):
            self.cell(column, row, self.glyph(token), "dim")
        cursor = x + 2
        for text, role in segments:
            cursor = self.text(cursor, y, text, role, right - 1)

    def bar(self, x, y, w, fraction):
        fraction = max(0.0, min(1.0, fraction))
        filled = round(w * fraction)
        role = console_graphs.threshold_role(fraction)
        for column in range(w):
            if column < filled:
                self.cell(x + column, y, self.glyph("BAR_FULL"), role, _GLYPH)
            else:
                self.cell(x + column, y, self.glyph("BAR_EMPTY"), "dim", _GLYPH)

    def graph(self, x, y, values, cols, rows, colour):
        matrix = console_graphs.graph(values, cols, rows, 1.0, colour=colour)
        for dy, row in enumerate(matrix):
            for dx, (token, role) in enumerate(row):
                if token is not None:
                    self.cell(x + dx, y + dy, self.glyph(token), role, _GLYPH)


def layout(width, height, nodes, longest_list, outside):
    """Rows of each block of view B (ADR 001 §2.4 «Vista B», A-7/A-8).

    ``nodes`` is the node count, ``longest_list`` the length of the longer
    TOP list and ``outside`` whether some guest stays out of both lists.
    """
    tall = height >= 40
    # Without nodes the table still keeps one line for "waiting for data".
    table_lines = max(1, min(nodes, height // 4 - 1))
    table = 1 + table_lines
    t = max(3, min(10 if tall else 5, longest_list))
    r = 2 if tall or outside else 1
    base = 1 + 1 + table + 2 + (3 + 3) + 1
    n_hist = max(0, min(nodes, (height - base) // 2))
    result = {"tall": tall, "table_y": 1, "table_lines": table_lines,
              "n_hist": n_hist, "g": 0, "panel_y": 1 + table, "panel_rows": 0}
    compact = n_hist < 1 or height < 28 or width < 100
    if compact:
        result["n_hist"] = 0
        free = height - 1 - (1 + table)
        if tall:
            top = min(3 + t, max(3, free - r))
            other = free - top
        else:
            other = min(r, max(0, free - 4))
            top = free - other
    else:
        room = height - (1 + 1 + table + 2 + 3 + t + r)
        while room < 2 * n_hist and t > 3:
            t, room = t - 1, room + 1
        if room < 2 * n_hist and r > 1:
            r, room = r - 1, room + 1
        g = min(8, room // n_hist)
        spare = room - g * n_hist
        if not tall:
            t += spare
        result.update(g=g, panel_rows=2 + g * n_hist)
        top = 3 + t
        other = height - 1 - (1 + table) - result["panel_rows"] - top
    result.update(compact=compact, top_y=1 + table + result["panel_rows"], top_rows=top,
                  t=max(0, top - 3), other_y=1 + table + result["panel_rows"] + top,
                  other_rows=max(0, other))
    return result


def _shown(items, rows):
    if rows <= 0:
        return []
    return items[:rows - 1] if len(items) > rows else items[:rows]


def _outside(guests, cpu_items, mem_items, rows):
    shown = {_key(g) for g in _shown(cpu_items, rows)} | {_key(g) for g in _shown(mem_items, rows)}
    return [g for g in guests if _key(g) not in shown]


def _identity(p, guest, cells):
    kind = "VM" if guest.get("type") == "qemu" else "CT"
    prefix = f"{kind} {_vmid(guest)} "
    if len(prefix) >= cells:
        return prefix[:cells]
    return prefix + p.untrusted(guest.get("name"), cells - len(prefix))


class _View:
    def __init__(self, grid, vm, state):
        self.p = _Painter(grid, vm)
        self.vm = vm
        self.state = state
        self.fresh = state == "ok"
        snapshot = vm.get("snapshot") or {}
        self.snapshot = snapshot if isinstance(snapshot, dict) else {}
        cluster = self.snapshot.get("cluster") or {}
        resources = self.snapshot.get("resources") or {}
        self.resources = {n.get("name"): n for n in resources.get("nodes") or []
                          if isinstance(n, dict) and n.get("name")}
        members = [m for m in cluster.get("members") or []
                   if isinstance(m, dict) and m.get("name")]
        if not members:
            local = (self.snapshot.get("node") or {}).get("name")
            members = [{"name": name, "online": node.get("status") == "online",
                        "local": name == local} for name, node in self.resources.items()]
        self.members = sorted(members, key=lambda m: (bool(m.get("online")), str(m.get("name"))))
        self.guests = [g for g in resources.get("guests") or []
                       if isinstance(g, dict) and not g.get("template")]
        self.cpu_items = sorted((g for g in self.guests if _cores(g) > 0),
                                key=lambda g: (-_cores(g), _vmid(g)))
        self.mem_items = sorted((g for g in self.guests if (_num(g.get("mem")) or 0) > 0),
                                key=lambda g: (-(_num(g.get("mem")) or 0), _vmid(g)))
        history = self.snapshot.get("history")
        self.history = history if isinstance(history, dict) else {"status": "unavailable"}
        entries = self.history.get("nodes")
        self.entries = entries if isinstance(entries, dict) else {}

    # -- node table ---------------------------------------------------------
    def node(self, member):
        """Resource row of an online member, else None."""
        node = self.resources.get(member.get("name"))
        if member.get("online") and isinstance(node, dict) and node.get("status") == "online":
            return node
        return None

    def status(self, member):
        if not member.get("online"):
            return self.p.label("labels.offline"), "crit"
        node = self.resources.get(member.get("name")) or {}
        if node.get("status") == "online":
            return self.p.label("labels.online"), "ok"
        if node.get("status") == "offline":
            return self.p.label("labels.offline"), "crit"
        return self.p.label("labels.unknown"), "warn"

    def last_load(self, name):
        entry = self.entries.get(name)
        if not isinstance(entry, dict):
            return None
        for value in reversed(list(entry.get("load1") or [])):
            value = _num(value)
            if value is not None and value >= 0:
                return value
        return None

    def node_table(self, y, lines):
        p = self.p
        narrow = p.width < 100
        bw = 5 if narrow else 10
        s1 = 10 - bw
        s2 = 2 * s1
        heads = [(1, "columns.node"), (10, "columns.status"), (19, "columns.cpu"),
                 (38 - s1, None), (66 - s2, "%"), (70 - s2, "columns.root"),
                 (76 - s2, "columns.guests"), (84 - s2, "columns.up")]
        if p.width >= 120:
            heads.append((94 - s2, "columns.load"))
        for index, (x, key) in enumerate(heads):
            text = (f"{p.label('columns.mem')} {p.label('columns.usedTotal')}" if key is None
                    else key if key == "%" else p.label(key))
            limit = heads[index + 1][0] - 1 if index + 1 < len(heads) else p.width - 1
            p.text(x, y, text, "title", limit)
        if not self.members:
            message = (p.label("status.waitingForData") if self.state == "starting"
                       else p.label("status.noData"))
            p.text(1, y + 1, message, "dim", p.width - 1)
            return
        shown = self.members if len(self.members) <= lines else self.members[:lines - 1]
        guests_by_node = {}
        for guest in self.guests:
            guests_by_node.setdefault(guest.get("node"), []).append(guest)
        for index, member in enumerate(shown):
            row = y + 1 + index
            node = self.node(member)
            role = "text" if self.fresh else "dim"
            local = "*" if member.get("local") else ""
            p.text(1, row, p.untrusted(member.get("name"), 8 - len(local)) + local, role, 9)
            word, status_role = self.status(member)
            p.text(10, row, word, status_role if self.fresh or status_role == "crit" else "dim", 17)
            hosted = guests_by_node.get(member.get("name"), [])
            running = sum(g.get("status") == "running" for g in hosted)
            p.text(74 - s2, row, f"{running}/{len(hosted)}", role, 81 - s2)
            if node is None:
                for x, w in ((18, 4), (36 - s1, 4), (62 - s2, 4), (68 - s2, 4), (82 - s2, 2)):
                    p.text(x + w - 2, row, "--", "dim")
                continue
            cpu = max(0.0, min(1.0, _num(node.get("cpu")) or 0.0))
            mem = _fraction(node.get("mem"), node.get("maxmem")) or 0.0
            root = _fraction(node.get("disk"), node.get("maxdisk")) or 0.0
            figure = (lambda f: console_graphs.threshold_role(f)) if self.fresh else (lambda f: "dim")
            p.text(18, row, _pct(cpu), figure(cpu))
            p.bar(23, row, bw, cpu)
            used = (_num(node.get("mem")) or 0.0) / _GIB
            total = (_num(node.get("maxmem")) or 0.0) / _GIB
            p.text(36 - s1, row, f"{used:4.1f}/{total:.0f} GiB", role, 50 - s1 - 1)
            p.bar(50 - s1, row, bw, mem)
            p.text(62 - s2, row, _pct(mem), figure(mem))
            p.text(68 - s2, row, _pct(root), figure(root))
            p.text(82 - s2, row, _uptime(node.get("uptime")), role, 92 - s2 - 1)
            if p.width >= 120:
                load = self.last_load(member.get("name"))
                p.text(92 - s2, row, "--" if load is None else f"{load:.2f}",
                       role if load is not None else "dim", p.width - 1)
        if len(shown) < len(self.members):
            p.text(1, y + 1 + len(shown),
                   p.label("labels.moreNodes", count=len(self.members) - len(shown)),
                   "dim", p.width - 1)

    # -- history panels -----------------------------------------------------
    def history_panels(self, y, g, n_hist):
        p = self.p
        points = int(_num(self.history.get("points")) or 60)
        step = _num(self.history.get("step_s")) or 60
        nodes = self.members[:n_hist]
        series = {}
        for member in nodes:
            entry = self.entries.get(member.get("name"))
            if isinstance(entry, dict) and _num(entry.get("t_end")) is not None:
                series[member.get("name")] = entry
        aligned = {}
        for key in ("cpu", "mem"):
            aligned[key] = console_graphs.align(
                {name: (_num(e.get("t_end")), list(e.get(key) or [])) for name, e in series.items()},
                step)
        halves = ((0, p.width // 2, "cpu"), (p.width // 2, p.width - p.width // 2, "mem"))
        for px, pw, key in halves:
            room = pw - 2 - 18
            cols = len(console_graphs.resample([0.0] * points, room))
            if points > room:
                per = math.ceil(points / room) * step / 60
                scale = p.label("labels.minPerCol", minutes=f"{per:g}")
            elif room // points > 1:
                scale = p.label("labels.colsPerMin", cols=room // points)
            else:
                scale = p.label("labels.minPerCol", minutes=f"{step / 60:g}")
            title = p.label("panels.cpu" if key == "cpu" else "panels.memory")
            subtitle = " · ".join((p.label("labels.now"), p.label("labels.last60"),
                                   p.label("labels.peak")))
            p.box(px, y, pw, 2 + g * len(nodes), ((title + " ", "title"), (subtitle, "dim")))
            bottom = y + 1 + g * len(nodes)
            p.text(px + 2, bottom, scale, "dim", px + pw - 1)
            if len(nodes) < len(self.members):
                more = p.label("labels.moreNodes", count=len(self.members) - len(nodes))
                p.rtext(px + pw - 2, bottom, more, "dim")
            for index, member in enumerate(nodes):
                self.history_block(px, y + 1 + index * g, g, cols, room, key, member,
                                   series.get(member.get("name")),
                                   aligned[key].get(member.get("name")))

    def history_block(self, px, y, g, cols, room, key, member, entry, values):
        p = self.p
        name_row = y + max(0, g - 3)
        now_row = max(name_row + 1, y + g - 2)
        local = "*" if member.get("local") else ""
        p.text(px + 2, name_row, p.untrusted(member.get("name"), 11 - len(local)) + local,
               "text", px + 13)
        node = self.node(member)
        if node is None:
            word, role = self.status(member)
            p.text(px + 2, now_row, word, role, px + 13)
        else:
            now = (max(0.0, min(1.0, _num(node.get("cpu")) or 0.0)) if key == "cpu"
                   else _fraction(node.get("mem"), node.get("maxmem")) or 0.0)
            p.text(px + 9, now_row, _pct(now),
                   console_graphs.threshold_role(now) if self.fresh else "dim")
        graph_x = px + 14
        present = [v for v in (_num(v) for v in values or []) if v is not None and v >= 0]
        if entry is None or not present:
            waiting = self.history.get("status") == "starting"
            message = p.label("status.waitingForData" if waiting else "labels.noHistory")
            p.text(graph_x, now_row, message, "dim", graph_x + room)
            return
        stale = entry.get("status") != "ok" or not self.fresh
        sampled = console_graphs.resample(values, room)
        p.graph(graph_x, y, sampled, cols, g, "dim" if stale else "threshold")
        strip = graph_x + cols + 1
        raw = [v for v in (_num(v) for v in entry.get(key) or []) if v is not None and v >= 0]
        peak = max(raw) if raw else max(present)
        observed = _num(entry.get("observed_at"))
        if stale and observed is not None:
            age = _age((_num(self.vm.get("now")) or observed) - observed)
            p.text(strip, y + g - 2, age, "warn", strip + 4)
        else:
            p.text(strip, y + g - 2, p.label("labels.peakShort"), "dim", strip + 4)
        p.text(strip, y + g - 1, _pct(peak), console_graphs.threshold_role(min(1.0, peak)))

    # -- TOP lists ----------------------------------------------------------
    def top_lists(self, y, rows):
        p = self.p
        mid = p.width // 2
        shift = 0 if p.width >= 100 else _TOP_GUEST - _TOP_GUEST_NARROW
        suffix = ""
        if self.snapshot and self.state in ("stale", "unavailable"):
            suffix = " (" + p.label("status.stale", age=_age(self.snapshot.get("age_s"))) + ")"
        panels = ((0, mid, "cpu", p.label("panels.topCpuShort"), p.label("labels.hostCores")),
                  (mid, p.width - mid, "mem", p.label("panels.topMemory"), p.label("labels.footprint")))
        for x, w, mode, title, subtitle in panels:
            p.box(x, y, w, rows, ((title + " ", "title"), (subtitle + suffix, "dim")))
            node_x = x + 2 + _TOP_GUEST - shift
            heads = [(x + 2, p.label("columns.guest")), (node_x, p.label("columns.node"))]
            if mode == "cpu":
                heads += [(x + 31 - shift, p.label("columns.cpuPercent")),
                          (x + 36 - shift, p.label("columns.vcpu")),
                          (x + 42 - shift, p.label("columns.hostCores"))]
            else:
                heads += [(x + 31 - shift, p.label("columns.usedAssigned")), (x + 46 - shift, "%")]
            for index, (hx, text) in enumerate(heads):
                limit = heads[index + 1][0] - 1 if index + 1 < len(heads) else x + w - 1
                p.text(hx, y + 1, text, "title", limit)
            body = rows - 3
            if self.state == "starting" or not self.snapshot:
                message = (p.label("status.waitingForData") if self.state == "starting"
                           else p.label("status.noData"))
                p.text(x + 2, y + 2, message, "dim", x + w - 1)
                continue
            items = self.cpu_items if mode == "cpu" else self.mem_items
            for index, guest in enumerate(_shown(items, body)):
                self.top_row(x, y + 2 + index, mode, guest, shift)
            if len(items) > body > 0:
                p.text(x + 2, y + 1 + body,
                       p.label("labels.moreGuests", count=len(items) - (body - 1)),
                       "dim", x + w - 1)

    def top_row(self, x, row, mode, guest, shift):
        p = self.p
        role = "text" if self.fresh else "dim"
        field = _TOP_GUEST - shift
        p.text(x + 2, row, _identity(p, guest, field - 1), role)
        p.text(x + 2 + field, row, p.untrusted(guest.get("node"), 7), role)
        figure = console_graphs.threshold_role if self.fresh else (lambda f: "dim")
        if mode == "cpu":
            cpu = max(0.0, min(1.0, _num(guest.get("cpu")) or 0.0))
            vcpu = int(_num(guest.get("maxcpu")) or 0)
            p.text(x + 31 - shift, row, _pct(cpu), figure(cpu))
            p.text(x + 36 - shift, row, f"{vcpu:>3}  {_cores(guest):>4.1f}c"[:11], role)
        else:
            used = f"{_short(guest.get('mem'))}/{_short(guest.get('maxmem'))}"
            p.rtext(x + 42 - shift, row, used[-11:], role)
            share = _fraction(guest.get("mem"), guest.get("maxmem")) or 0.0
            p.text(x + 43 - shift, row, _pct(share), figure(share))

    # -- the rest -----------------------------------------------------------
    def item(self, guest):
        kind = "VM" if guest.get("type") == "qemu" else "CT"
        text = f"{kind} {_vmid(guest)} {self.p.untrusted(guest.get('name'), 24)}"
        node = self.p.untrusted(guest.get("node"), 16)
        status = guest.get("status")
        extra = "" if status in ("running", "stopped") else " " + self.p.untrusted(status, 10)
        return f"{text} {node}{extra}" if node else text + extra

    def packed(self, x, y, head, items):
        """``head · item · item`` up to the right edge, then ``· +n``."""
        p = self.p
        room = p.width - 1 - x
        text = head
        for index, item in enumerate(items):
            rest = len(items) - index - 1
            tail = len(f" · +{rest}") if rest else 0
            if len(text) + 3 + len(item) + tail > room:
                text += f" · +{len(items) - index}"
                break
            text += " · " + item
        p.text(x, y, text, "dim", p.width - 1)

    def other_lines(self, y, rows, t):
        p = self.p
        if rows <= 0 or not self.snapshot:
            return
        outside = sorted(_outside(self.guests, self.cpu_items, self.mem_items, t), key=_vmid)
        idle = [g for g in outside if g.get("status") != "running"]
        busy = [g for g in outside if g.get("status") == "running"]
        head = f"{p.label('labels.other')} {len(outside)}"
        p.text(1, y, head, "title", p.width - 1)
        x = 1 + len(head) + 1
        stopped = f"{p.label('labels.stopped')} {len(idle)}"
        running = f"{p.label('labels.running')} {len(busy)} {p.label('labels.outsideTop')}"
        if rows == 1:
            if busy:
                self.packed(x, y, f"{stopped} · {running}", [self.item(g) for g in idle + busy])
            else:
                self.packed(x, y, stopped, [self.item(g) for g in idle])
            return
        self.packed(x, y, stopped, [self.item(g) for g in idle])
        self.packed(x, y + 1, running, [self.item(g) for g in busy])

    def guest_table(self, y, rows):
        """Full guest table of the r3 cluster view, sorted by ``c``/``m``."""
        p = self.p
        if rows <= 0:
            return y
        for x in range(p.width):
            p.cell(x, y, p.glyph("BOX_H"), "dim")
        running = sum(g.get("status") == "running" for g in self.guests)
        sort = "mem" if self.vm.get("sort") == "mem" else "cpu"
        x = p.text(2, y, f" {p.label('panels.guests')} ", "title", p.width - 2)
        p.text(x, y, (f" {p.label('labels.running')} {running} · {p.label('labels.stopped')} "
                      f"{len(self.guests) - running} · {p.label('labels.sort')}: {sort} (c/m) "),
               "text", p.width - 2)
        if rows == 1:
            return y + 1
        wide, bars = p.width >= 160, p.width >= 100
        name_w = 16 if bars else 13
        id_w = max([5] + [len(str(_vmid(g))) + 1 for g in self.guests])
        cols = [("columns.type", 5, "<"), ("columns.id", id_w, "<"), ("columns.name", name_w, "<"),
                ("columns.node", 8, "<"), ("columns.status", 9, "<"),
                ("columns.usedAssignedLong", 20, "<")]
        cols += [(None, 10, "bar")] if bars else []
        cols += [("%", 6, ">"), ("columns.cpuPercent", 7, ">"), ("columns.vcpu", 5, ">")]
        if wide:
            cols += [("columns.hostCores", 7, ">"), (None, 2, "<"), ("columns.up", 8, "<"),
                     ("columns.ha", 6, "<"), ("columns.tags", 0, "<")]
        x = 1
        places = []
        for key, w, align in cols:
            places.append((x, w, align))
            if key is not None:
                head = key if key == "%" else (
                    f"{p.label('columns.mem')} {p.label('columns.usedAssignedLong')}"
                    if key == "columns.usedAssignedLong" else p.label(key))
                if align == ">":
                    p.rtext(x + w, y + 1, head[:w], "title")
                else:
                    p.text(x, y + 1, head, "title", x + w - 1 if key != "columns.tags" else p.width - 1)
            x += w
        ordered = sorted(self.guests, key=lambda g: (
            g.get("status") != "running",
            -((_num(g.get("mem")) or 0) if sort == "mem" else _cores(g)), _vmid(g)))
        body = rows - 2
        shown = ordered if len(ordered) <= body else ordered[:max(0, body - 1)]
        for index, guest in enumerate(shown):
            self.table_row(y + 2 + index, guest, places, wide, bars)
        if len(shown) < len(ordered) and body > 0:
            p.text(1, y + 2 + len(shown), p.label("labels.moreGuests", count=len(ordered) - len(shown)),
                   "dim", p.width - 1)
            return y + 3 + len(shown)
        return y + 2 + len(shown)

    def table_row(self, row, guest, places, wide, bars):
        p = self.p
        active = guest.get("status") == "running" and self.fresh
        role = "text" if active else "dim"
        figure = console_graphs.threshold_role if active else (lambda f: "dim")
        share = _fraction(guest.get("mem"), guest.get("maxmem")) or 0.0
        cpu = max(0.0, min(1.0, _num(guest.get("cpu")) or 0.0))
        values = [("VM" if guest.get("type") == "qemu" else "CT", role),
                  (str(_vmid(guest)), role),
                  (p.untrusted(guest.get("name"), places[2][1] - 1), role),
                  (p.untrusted(guest.get("node"), 7), role),
                  (p.untrusted(guest.get("status"), 8), "ok" if active else role),
                  (f"{_size(guest.get('mem'))}/{_size(guest.get('maxmem'))}", role)]
        values += [("bar", share)] if bars else []
        values += [(_pct(share).strip(), figure(share)), (_pct(cpu).strip(), figure(cpu)),
                   (str(int(_num(guest.get("maxcpu")) or 0)), role)]
        if wide:
            tags = ",".join(p.untrusted(t, 16) for t in (guest.get("tags") or [])[:3])
            values += [(f"{_cores(guest):.1f}c", role), ("", role),
                       (_uptime(guest.get("uptime")), role),
                       (p.untrusted(guest.get("hastate"), 5) or "-", role), (tags, role)]
        for (x, w, align), (text, extra) in zip(places, values):
            if text == "bar":
                p.bar(x, row, 10, extra)
            elif align == ">":
                p.rtext(x + w, row, text[:w], extra)
            else:
                p.text(x, row, text, extra, min(p.width - 1, x + max(1, w - 1)) if w else p.width - 1)


def render(grid, vm, state):
    """Paint view B on rows 1 to ``height - 2``; returns the layout used.

    The result maps ``g``, ``t``, ``n_hist``, ``compact`` and the block rows,
    and ``art_area`` gives ``(x, y, w, h)`` of the free rows under the guest
    table from 40 rows on, where optional brand art may go, else ``None``.
    """
    view = _View(grid, vm, state)
    tall = grid.height >= 40
    longest = max(len(view.cpu_items), len(view.mem_items))
    base = max(3, min(10 if tall else 5, longest))
    outside = bool(_outside(view.guests, view.cpu_items, view.mem_items, base))
    plan = layout(grid.width, grid.height, len(view.members), longest, outside)
    view.node_table(plan["table_y"], plan["table_lines"])
    if not plan["compact"]:
        view.history_panels(plan["panel_y"], plan["g"], plan["n_hist"])
    if plan["top_rows"] >= 3:
        view.top_lists(plan["top_y"], plan["top_rows"])
    plan["art_area"] = None
    if tall:
        end = view.guest_table(plan["other_y"], plan["other_rows"])
        free = grid.height - 1 - end
        if free > 0:
            plan["art_area"] = (0, end, grid.width, free)
    else:
        view.other_lines(plan["other_y"], plan["other_rows"], plan["t"])
    return plan
