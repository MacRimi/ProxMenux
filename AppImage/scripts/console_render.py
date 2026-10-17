"""Pure terminal grid renderer for the ProxMenux console.

Each cell is ``(char, color_role, attrs)``. ``attrs`` is a tuple containing
``dim``, ``reverse`` or ``bold`` when needed. In ACS mode ``char`` can be one
of the logical tokens below. The curses caller must map ``ACS_TOKENS[token]``
to the corresponding ``curses.ACS_*`` value before calling ``addch``; all
other cells contain one printable character. This module never imports curses.
"""

import datetime
import math
import re
import unicodedata


ACS_TOKENS = {
    "BOX_H": "ACS_HLINE", "BOX_V": "ACS_VLINE",
    "BOX_UL": "ACS_ULCORNER", "BOX_UR": "ACS_URCORNER",
    "BOX_LL": "ACS_LLCORNER", "BOX_LR": "ACS_LRCORNER",
    "BOX_LT": "ACS_LTEE", "BOX_RT": "ACS_RTEE",
    "BOX_TT": "ACS_TTEE", "BOX_BT": "ACS_BTEE",
    "BOX_X": "ACS_PLUS", "BAR_FULL": "ACS_BLOCK",
    "BAR_EMPTY": "ACS_CKBOARD", "BULLET": "ACS_BULLET",
}

_UNICODE = dict(zip(ACS_TOKENS, "─│┌┐└┘├┤┬┴┼█░·"))
_ASCII = {key: ("-" if key == "BOX_H" else "|" if key == "BOX_V"
                else "#" if key == "BAR_FULL" else "." if key in ("BAR_EMPTY", "BULLET")
                else "+") for key in ACS_TOKENS}
_ROLES = frozenset(("title", "text", "dim", "ok", "warn", "crit", "selected"))
_CONTROL = re.compile(r" +")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


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
    cleaned = _CONTROL.sub(" ", "".join(printable)).strip()
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


def _pct(value):
    return max(0, min(100, round(_number(value) * 100)))


def _percent(used, total):
    total = _number(total)
    return 0 if total <= 0 else max(0, min(100, round(_number(used) * 100 / total)))


def _gib(value):
    return _number(value) / 1073741824


def _size(value):
    value = max(0, _number(value))
    if value < 1073741824:
        return f"{value / 1048576:.0f} MiB"
    return f"{_gib(value):.1f} GiB"


def _decimal(value):
    text = f"{value:.1f}"
    return f"{value:.0f}" if float(text) >= 10 else text


def _short_size(value):
    value = max(0, _number(value))
    if value == 0:
        return "0"
    if value < 1073741824:
        return f"{_decimal(value / 1048576)}M"
    return f"{_decimal(_gib(value))}G"


def _fit(width, *candidates):
    """Return the first candidate that fits ``width`` cells, else the last one."""
    for text in candidates:
        if len(text) <= width:
            return text
    return candidates[-1]


def _uptime(seconds):
    seconds = max(0, int(_number(seconds)))
    days, hours = divmod(seconds // 3600, 24)
    return f"{days}d {hours:02d}h" if days else f"{hours}h"


def _age(seconds):
    seconds = max(0, int(_number(seconds)))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h"


def _rate(value, bits=False):
    value = max(0, _number(value)) * (8 if bits else 1)
    units = ("b/s", "Kb/s", "Mb/s", "Gb/s") if bits else ("B/s", "KiB/s", "MiB/s", "GiB/s")
    for unit in units:
        base = 1000 if bits else 1024
        if value < base or unit == units[-1]:
            return f"{_decimal(value)} {unit}"
        value /= base


def _paired_rate(first, second):
    values = [max(0, _number(first)), max(0, _number(second))]
    unit = "B/s"
    for next_unit in ("KiB/s", "MiB/s", "GiB/s"):
        if max(values) < 1024:
            break
        values = [value / 1024 for value in values]
        unit = next_unit
    return f"{values[0]:.0f}/{values[1]:.0f} {unit}"


class Grid(list):
    """List of rows of logical ``(char, color_role, attrs)`` cells."""

    def __init__(self, width, height, glyphs):
        super().__init__([[(' ', 'text', ()) for _ in range(width)] for _ in range(height)])
        self.width = width
        self.height = height
        self.glyphs = glyphs

    def glyph(self, token):
        if self.glyphs == "acs":
            return token
        return (_UNICODE if self.glyphs == "unicode" else _ASCII)[token]

    def put(self, x, y, value, role="text", attrs=(), limit=None):
        if not 0 <= y < self.height or x >= self.width:
            return
        assert role in _ROLES
        attrs = tuple(attrs)
        max_x = self.width if limit is None else min(self.width, limit)
        for index, char in enumerate(str(value)):
            at = x + index
            if 0 <= at < max_x:
                self[y][at] = (char, role, attrs)

    def token(self, x, y, token, role="text", attrs=()):
        if 0 <= x < self.width and 0 <= y < self.height:
            self[y][x] = (self.glyph(token), role, tuple(attrs))

    def box(self, x, y, width, height, title):
        if width < 2 or height < 2:
            return
        right, bottom = x + width - 1, y + height - 1
        for column in range(x + 1, right):
            self.token(column, y, "BOX_H")
            self.token(column, bottom, "BOX_H")
        for row in range(y + 1, bottom):
            self.token(x, row, "BOX_V")
            self.token(right, row, "BOX_V")
        for column, row, token in ((x, y, "BOX_UL"), (right, y, "BOX_UR"),
                                   (x, bottom, "BOX_LL"), (right, bottom, "BOX_LR")):
            self.token(column, row, token)
        self.put(x + 2, y, str(title)[:width - 4], "title", limit=right)

    def bar(self, x, y, width, fraction):
        if width <= 0:
            return
        fraction = max(0, min(1, _number(fraction)))
        filled = round(width * fraction)
        role = "crit" if fraction >= .9 else "warn" if fraction >= .7 else "ok"
        for column in range(width):
            self.token(x + column, y, "BAR_FULL" if column < filled else "BAR_EMPTY", role)


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


def _separator(grid):
    return "·" if grid.glyphs == "unicode" else "."


def _remote_state(vm):
    snapshot = vm.get("snapshot") or {}
    resources = snapshot.get("resources") or {}
    age = _number(snapshot.get("age_s"))
    status = resources.get("status")
    if status == "starting":
        return ("starting" if age <= 15 or
                _number((vm.get("local") or {}).get("uptime"), 999999) < 120
                else "unavailable")
    if not snapshot:
        return "starting" if _number((vm.get("local") or {}).get("uptime"), 999999) < 120 else "unavailable"
    if age > 60 or status in ("unavailable", "error"):
        return "unavailable"
    if status == "stale" or age > 10:
        return "stale"
    return "ok" if status == "ok" else "unavailable"


def _clock(vm):
    now = vm.get("now")
    try:
        return datetime.datetime.fromtimestamp(_number(now)).strftime("%H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return "--:--:--"


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
    grid.put(grid.width - 1 - len(clock), 0, clock)
    remaining = max(0, grid.width - tabs_x - len(clock) - 3)
    if state == "starting":
        info, role = label("status.starting"), "warn"
    elif state == "unavailable":
        info = label("status.monitorUnavailable") + (f" ({_age(snapshot.get('age_s'))})" if snapshot else "")
        role = "crit"
    elif cluster_view:
        if not cluster.get("is_cluster", True):
            info, role = label("labels.standalone"), "text"
        else:
            up = int(_number(cluster.get("nodes_online")))
            total = int(_number(cluster.get("nodes_total")))
            quorum = bool(cluster.get("quorate"))
            title = label("labels.quorumOk" if quorum else "labels.noQuorum")
            info = f"{sanitize(cluster.get('name') or '', 24, grid.glyphs)} {title} {up}/{total}"
            role = "ok" if quorum else "crit"
            coverage = _coverage(snapshot)
            if state == "ok" and quorum and coverage == total and total > 0:
                nodes = _online_nodes(snapshot)
                mem = sum(_number(n.get("maxmem")) for n in nodes)
                capacity = sum(_number(n.get("maxcpu")) for n in nodes)
                cores = sum(_number(n.get("cpu")) * _number(n.get("maxcpu")) for n in nodes)
                info += f" {mem / 1073741824:.0f} GiB {label('columns.cpu')} {round(cores * 100 / capacity) if capacity else 0}%"
            else:
                info += f" {label('labels.coverage')} {coverage}/{total}"
    else:
        version = sanitize(node.get("pve_version") or "n/d", 40, grid.glyphs)
        match = re.search(r"\d+\.\d+", version)
        version = match.group(0) if match else version
        name = sanitize(node.get("name") or "", 20, grid.glyphs)
        info = (f"{name} {_separator(grid)} PVE {version} "
                f"{_separator(grid)} {label('labels.uptime')} {_uptime((vm.get('local') or {}).get('uptime'))}")
        role = "title"
        if state == "ok" and not cluster.get("is_cluster", True):
            info = f"{name} {_separator(grid)} {label('labels.standalone')}"
        elif state == "ok" and cluster.get("quorate") is False:
            up = int(_number(cluster.get("nodes_online")))
            total = int(_number(cluster.get("nodes_total")))
            info = f"{name} {_separator(grid)} {label('labels.noQuorum')} {up}/{total}"
            role = "crit"
    _text(grid, tabs_x + 1, 0, info, remaining, role)


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
    parts = [label("footer.quit"), label("footer.switchNode" if cluster_view else "footer.switch")]
    if cluster_view:
        parts.append(label("footer.sort"))
    parts.extend((label("footer.refresh"), label("footer.glyphs")))
    if not cluster_view:
        parts.append(label("footer.otherTty"))
    separator = f" {_separator(grid)} "
    status = (_label_with(vm, "status.data", grid.glyphs,
                          age=_age(vm["snapshot"].get("age_s")))
              if state != "starting" and vm.get("snapshot") else label("status.noData"))
    help_text = separator.join(parts)
    _text(grid, 1, grid.height - 1, help_text, max(0, grid.width - len(status) - 4), "dim")
    _text(grid, grid.width - len(status) - 1, grid.height - 1, status, len(status), "dim")


def _cpu_memory(grid, vm, rows):
    label = lambda key: _label(vm, key, grid.glyphs)
    local = vm.get("local") or {}
    mem = local.get("mem") or {}
    cpu_fraction = _number(local.get("cpu_total"))
    memory_fraction = _number(mem.get("used")) / max(1, _number(mem.get("total")))
    left = 43 if grid.width == 80 else (grid.width + 1) // 2
    right = grid.width - left
    cpu_title = f"{label('panels.cpu')}  {_pct(cpu_fraction)}%"
    memory_title = (f"{label('panels.memory')}  {_gib(mem.get('used')):.1f}/"
                    f"{_gib(mem.get('total')):.0f} GiB  {_pct(memory_fraction)}%")
    grid.box(0, 1, left, rows, cpu_title)
    grid.box(left, 1, right, rows, memory_title)
    cpu_percent = f"{_pct(cpu_fraction)}%"
    memory_percent = f"{_pct(memory_fraction)}%"
    grid.put(2 + cpu_title.rfind(cpu_percent), 1, cpu_percent, "title", ("bold",), limit=left - 1)
    grid.put(left + 2 + memory_title.rfind(memory_percent), 1,
             memory_percent, "title", ("bold",), limit=grid.width - 1)
    grid.bar(2, 2, left - 4, cpu_fraction)
    grid.bar(left + 2, 2, right - 4, memory_fraction)
    load = " ".join(f"{_number(local.get('load' + str(i))):.2f}" for i in (1, 5, 15))
    degree = "°" if grid.glyphs == "unicode" else ""
    temp = f" {_separator(grid)} {round(_number(local.get('temp_c')))}{degree} C" if local.get("temp_c") is not None else ""
    _text(grid, 2, 3, f"{label('labels.load')} {load} {_separator(grid)} {int(_number(local.get('threads')))} {label('labels.threads')}{temp}", left - 4)
    _text(grid, left + 2, 3,
          f"{label('labels.arc')} {_size(mem.get('arc'))} {_separator(grid)} {label('labels.available')} {_size(mem.get('available'))}", right - 4)
    zram = local.get("zram") or {}
    zram_used = zram.get("swap_used_bytes", zram.get("used", 0))
    zram_total = zram.get("capacity_bytes", zram.get("total", 0))
    ratio = _number(zram.get("compression_ratio"))
    swap = f"{label('labels.swap')} {_size(mem.get('swap_used'))}/{_size(mem.get('swap_total'))}"
    if _number(zram_total) > 0:
        zram_part = f"{label('labels.zram')} {_size(zram_used)}/{_size(zram_total)} {ratio:.1f}x {_separator(grid)} "
        compact_zram = f"{label('labels.zram')} {_short_size(zram_used)}/{_short_size(zram_total)} {ratio:.1f}x {_separator(grid)} "
        compact_swap = f"{label('labels.swap')} {_short_size(mem.get('swap_used'))}/{_short_size(mem.get('swap_total'))}"
        row = _fit(right - 4, zram_part + swap, compact_zram + compact_swap)
    else:
        row = swap
    _text(grid, left + 2, 4, row, right - 4)
    history = local.get("cpu_history") or []
    history_start = 4
    history_rows = 1 if rows == 5 else 4
    per_core = local.get("per_core") or []
    history_width = (left - 4) // 2 if rows > 5 and grid.width >= 120 and per_core else left - 4
    for row in range(history_rows):
        y = history_start + row
        for index, fraction in enumerate(history[-history_width:]):
            height = round(max(0, min(1, _number(fraction))) * history_rows)
            token = "BAR_FULL" if height > history_rows - row - 1 else "BAR_EMPTY"
            grid.token(2 + index, y, token, "ok" if token == "BAR_FULL" else "dim")
    if rows > 5 and grid.width >= 120 and per_core:
        grouped = len(per_core) > 64
        values = [max(per_core[i:i + 2]) for i in range(0, len(per_core), 2)] if grouped else per_core
        shown = min(len(values), max(1, (left - history_width - 4) // 15))
        for index, value in enumerate(values[:shown]):
            x = history_width + 3 + index * 15
            _text(grid, x, 5, f"CPU{index}{' x2' if grouped else ''} {_pct(value)}%", 14)
            grid.bar(x, 6, 5, value)


def _strip(grid, vm, y, rows, state):
    label = lambda key: _label(vm, key, grid.glyphs)
    local = vm.get("local") or {}
    snapshot = vm.get("snapshot") or {}
    cluster = snapshot.get("cluster") or {}
    standalone = not cluster.get("is_cluster", True)
    net_width = 23 if grid.width == 80 else round(grid.width * .28)
    disk_width = (grid.width - net_width if standalone else 28) if grid.width == 80 else round(grid.width * (.72 if standalone else .34))
    cluster_x = net_width + disk_width
    net = local.get("net") or {}
    disk = local.get("disk") or {}
    speed = _number(net.get("speed_mbps"))
    speed_text = f" {speed / 1000:g}G" if speed >= 1000 else f" {speed:g}M" if speed else ""
    grid.box(0, y, net_width, rows, f"{label('panels.network')} {sanitize(net.get('nic'), 12, grid.glyphs)}{speed_text}")
    grid.box(net_width, y, disk_width, rows,
             f"{label('panels.disk')}{' ' + label('labels.standalone') if standalone else ''}")
    _text(grid, 2, y + 1, f"{label('labels.rx')} {_rate(net.get('rx_bps'), True)}", net_width - 4)
    _text(grid, 2, y + 2, f"{label('labels.tx')} {_rate(net.get('tx_bps'), True)}", net_width - 4)
    _text(grid, net_width + 2, y + 1,
          f"{label('labels.read')} {_rate(disk.get('read_bps'))}  {label('labels.write')} {_rate(disk.get('write_bps'))}", disk_width - 4)
    storages = local.get("storages_local") or []
    if storages:
        storage = storages[0]
        used = storage.get("used", storage.get("disk"))
        total = storage.get("total", storage.get("maxdisk"))
        _text(grid, net_width + 2, y + 2,
              f"{sanitize(storage.get('storage'), 14, grid.glyphs)} {_percent(used, total)}%", disk_width - 4)
    if rows >= 5 and len(storages) > 1:
        storage = storages[1]
        _text(grid, net_width + 2, y + 3, sanitize(storage.get("storage"), disk_width - 4, grid.glyphs), disk_width - 4)
    if standalone:
        return
    cluster_width = grid.width - cluster_x
    up = int(_number(cluster.get("nodes_online")))
    total = int(_number(cluster.get("nodes_total")))
    quorate = cluster.get("quorate")
    head = label("panels.cluster")
    name = sanitize(cluster.get("name"), 15, grid.glyphs)
    named = f"{head} {name}" if name else head
    separator = _separator(grid)
    if quorate is None:
        title = _fit(cluster_width - 4, named, head)
    else:
        quorum_text = f"{label('labels.quorumOk') if quorate else label('labels.noQuorum')} {up}/{total}"
        title = _fit(cluster_width - 4, f"{named} {separator} {quorum_text}",
                     f"{head} {separator} {quorum_text}", f"{head} {separator} {up}/{total}")
    grid.box(cluster_x, y, cluster_width, rows, title)
    if state == "starting" or quorate is None:
        text = label("status.waitingForData") if state == "starting" else label("status.noData")
        _text(grid, cluster_x + 2, y + 1, text, cluster_width - 4, "dim")
        return
    members = cluster.get("members") or []
    visible = max(0, rows - 2)
    if len(members) > visible:
        visible -= 1
    nodes = {node.get("name"): node for node in (snapshot.get("resources") or {}).get("nodes", [])}
    for index, member in enumerate(members[:visible]):
        node = nodes.get(member.get("name"), {})
        status = label("labels.online" if member.get("online") else "labels.offline")
        name = sanitize(member.get("name"), 12, grid.glyphs) + ("*" if member.get("local") else "")
        value = f"{name} {_pct(node.get('cpu'))}% {_percent(node.get('mem'), node.get('maxmem'))}% {status}"
        _text(grid, cluster_x + 2, y + 1 + index, value, cluster_width - 4,
              "crit" if not member.get("online") else "dim" if state != "ok" else "text")
    if len(members) > visible:
        _text(grid, cluster_x + 2, y + 1 + visible,
              _label_with(vm, "labels.moreNodes", grid.glyphs,
                          count=len(members) - visible), cluster_width - 4, "dim")


def _guests(snapshot):
    return [guest for guest in (snapshot.get("resources") or {}).get("guests", [])
            if not guest.get("template")]


def _cpu_key(guest):
    return _number(guest.get("cpu")) * _number(guest.get("maxcpu"))


def _top_row(grid, guest, x, y, width, mode, standalone):
    kind = "VM" if guest.get("type") == "qemu" else "CT"
    identity = f"{kind} {guest.get('vmid', '')} "
    name_width = max(8, min(24 if grid.width >= 160 else 13, width - (39 if not standalone else 30)))
    node = "" if standalone else sanitize(guest.get("node"), 10, grid.glyphs)
    value = (f"{_cpu_key(guest):.1f}c  {_pct(guest.get('cpu')):>3}%" if mode == "cpu"
             else _size(guest.get("mem")))
    right = x + width - 2
    status = (sanitize(guest.get("status"), 7, grid.glyphs)
              if guest.get("status") != "running" and mode == "mem" else "")
    detail = " ".join(part for part in (node, status) if part)
    available_name = max(8, right - len(value) - len(detail) - len(identity) - x - 6)
    name = sanitize(guest.get("name"), min(name_width, available_name), grid.glyphs)
    _text(grid, x + 2, y, identity + name, max(0, width - 4))
    if detail:
        _text(grid, right - len(value) - len(detail) - 1, y, detail, len(detail),
              "warn" if status else "dim")
    _text(grid, right - len(value), y, value, len(value),
          "dim" if guest.get("status") != "running" else "text")
    if grid.width >= 160:
        extra = f" UP {_uptime(guest.get('uptime'))}"
        if guest.get("net_rx_bps") is not None:
            extra += f" NET {_paired_rate(guest.get('net_rx_bps'), guest.get('net_tx_bps'))}"
        if guest.get("disk_read_bps") is not None:
            extra += f" DISK {_paired_rate(guest.get('disk_read_bps'), guest.get('disk_write_bps'))}"
        extra_x = x + 2 + len(identity) + len(name) + 1
        _text(grid, extra_x, y, extra,
              max(0, right - len(value) - len(detail) - 2 - extra_x), "dim")


def _top(grid, vm, y, rows, state):
    label = lambda key: _label(vm, key, grid.glyphs)
    snapshot = vm.get("snapshot") or {}
    cluster = snapshot.get("cluster") or {}
    standalone = not cluster.get("is_cluster", True)
    guests = _guests(snapshot)
    midpoint = grid.width // 2
    cpu_name = label("panels.topCpu")
    cpu_short = label("panels.topCpuShort")
    memory_title = label("panels.topMemory")
    cpu_suffix = ""
    if state == "ok":
        host_other = vm.get("host_other") or {}
        if host_other.get("cpu") is not None:
            cpu_suffix = f" {_separator(grid)} {label('labels.hostOther')} {_number(host_other['cpu']):.1f}c"
        if host_other.get("mem") is not None:
            memory_title += f" {_separator(grid)} {label('labels.hostOther')} {_size(host_other['mem'])}"
    elif snapshot and state in ("stale", "unavailable"):
        stale = _label_with(vm, "status.stale", grid.glyphs,
                            age=_age(snapshot.get("age_s")))
        cpu_suffix = f" ({stale})"
        memory_title += f" ({stale})"
    cpu_title = _fit(midpoint - 4, cpu_name + cpu_suffix, cpu_short + cpu_suffix, cpu_short)
    grid.box(0, y, midpoint, rows, cpu_title)
    grid.box(midpoint, y, grid.width - midpoint, rows, memory_title)
    if state == "starting" or not snapshot:
        text = label("status.waitingForData") if state == "starting" else label("status.noData")
        for x, width in ((0, midpoint), (midpoint, grid.width - midpoint)):
            _text(grid, x + 2, y + 1, text, width - 4, "dim")
        return
    if not snapshot or not guests:
        return
    cpu_guests = sorted((g for g in guests if _cpu_key(g) > 0),
                        key=lambda g: (-_cpu_key(g), int(_number(g.get("vmid")))))
    mem_guests = sorted((g for g in guests if _number(g.get("mem")) > 0),
                        key=lambda g: (-_number(g.get("mem")), int(_number(g.get("vmid")))))
    for x, width, items, mode in ((0, midpoint, cpu_guests, "cpu"),
                                   (midpoint, grid.width - midpoint, mem_guests, "mem")):
        visible = max(0, rows - 2)
        if len(items) > visible:
            visible -= 1
        for index, guest in enumerate(items[:visible]):
            _top_row(grid, guest, x, y + index + 1, width, mode, standalone)
            if state != "ok":
                for column in range(x + 1, x + width - 1):
                    char, _, attrs = grid[y + index + 1][column]
                    grid[y + index + 1][column] = (char, "dim", attrs)
        if len(items) > visible:
            _text(grid, x + 2, y + 1 + visible,
                  _label_with(vm, "labels.moreGuests", grid.glyphs,
                              count=len(items) - visible), width - 4, "dim")


def _node_view(grid, vm, state):
    cpu_rows = 8 if grid.height >= 40 else 5
    strip_rows = 5 if grid.height >= 40 else 4
    _cpu_memory(grid, vm, cpu_rows)
    _strip(grid, vm, 1 + cpu_rows, strip_rows, state)
    top_y = 1 + cpu_rows + strip_rows
    _top(grid, vm, top_y, grid.height - top_y - 1, state)


def _cluster_view(grid, vm, state):
    label = lambda key: _label(vm, key, grid.glyphs)
    snapshot = vm.get("snapshot") or {}
    cluster = snapshot.get("cluster") or {}
    resources = snapshot.get("resources") or {}
    members = sorted(cluster.get("members") or [],
                     key=lambda item: (bool(item.get("online")), str(item.get("name") or "")))
    nodes = {n.get("name"): n for n in resources.get("nodes") or []}
    if not cluster.get("is_cluster", True) and not members:
        local_name = (snapshot.get("node") or {}).get("name")
        members = [{"name": name, "online": node.get("status") == "online", "local": True}
                   for name, node in nodes.items() if name == local_name]
    node_limit = max(1, grid.height // 3 - 2)
    visible = min(len(members), node_limit)
    if len(members) > visible:
        visible = max(0, visible - 1)
    for x, key in ((1, "columns.node"), (11, "columns.status"),
                   (20, "columns.cpu"), (34, "columns.mem"),
                   (63, "columns.root"), (70, "columns.guests")):
        _text(grid, x, 1, label(key), max(0, grid.width - x - 1), "title")
    if grid.width >= 90:
        _text(grid, 81, 1, label("columns.up"), grid.width - 82, "title")
    guests = _guests(snapshot)
    for index, member in enumerate(members[:visible]):
        node = nodes.get(member.get("name"), {}) if member.get("online") else {}
        node_guests = [g for g in guests if g.get("node") == member.get("name")]
        running = sum(g.get("status") == "running" for g in node_guests)
        name = sanitize(member.get("name"), 8, grid.glyphs) + ("*" if member.get("local") else "")
        status = label("labels.online" if member.get("online") else "labels.offline")
        cpu = f"{_pct(node.get('cpu'))}%" if node else "--"
        mem = f"{_size(node.get('mem'))}/{_gib(node.get('maxmem')):.0f} GiB" if node else "--"
        root = f"{_percent(node.get('disk'), node.get('maxdisk'))}%" if node else "--"
        row = index + 2
        role = "crit" if not member.get("online") else "dim" if state != "ok" else "text"
        _text(grid, 1, row, name, 9, role)
        _text(grid, 11, row, status, 8, role)
        _text(grid, 20, row, cpu, 4, role)
        if node:
            grid.bar(25, row, 8, node.get("cpu"))
        _text(grid, 34, row, mem, 17, role)
        if node:
            grid.bar(54, row, 8, _number(node.get("mem")) / max(1, _number(node.get("maxmem"))))
        _text(grid, 63, row, root, 6, role)
        _text(grid, 70, row, f"{running}/{len(node_guests)}", 7, role)
        if grid.width >= 90:
            _text(grid, 81, row, _uptime(node.get("uptime")) if node else "--", 10, role)
    if len(members) > visible:
        _text(grid, 2, 2 + visible,
              _label_with(vm, "labels.moreNodes", grid.glyphs,
                          count=len(members) - visible), grid.width - 4, "dim")
    separator_y = 2 + visible + (1 if len(members) > visible else 0)
    for x in range(grid.width):
        grid.token(x, separator_y, "BOX_H")
    running = sum(g.get("status") == "running" for g in guests)
    title = (f" {label('panels.guests')}  {label('labels.running')} {running} "
             f"{_separator(grid)} {label('labels.stopped')} {len(guests) - running} "
             f"{_separator(grid)} {label('labels.sort')}: {vm.get('sort', 'cpu')} (c/m) ")
    _text(grid, 2, separator_y, title, grid.width - 4, "title")
    guest_header_y = separator_y + 1
    name_column = 25 if grid.width >= 160 else 19
    guest_header = (f"{label('columns.type'):<6}{label('columns.id'):<5}"
                    f"{label('columns.name'):<{name_column}}{label('columns.node'):<9}"
                    f"{label('columns.status'):<10}{label('columns.cpu'):<13}{label('columns.mem'):<12}")
    if grid.width >= 160:
        guest_header += (f"{label('columns.cores')}  {label('columns.uptime')}  "
                         f"{label('columns.ha')}  {label('columns.tags')}")
    _text(grid, 1, guest_header_y, guest_header, grid.width - 2, "title")
    sort_mem = vm.get("sort") == "mem"
    ordered = sorted(guests, key=lambda g: (g.get("status") != "running",
                                           -(_number(g.get("mem")) if sort_mem else _cpu_key(g)),
                                           int(_number(g.get("vmid")))))
    start = guest_header_y + 1
    available = max(0, grid.height - start - 1)
    if len(ordered) > available:
        available = max(0, available - 1)
    for index, guest in enumerate(ordered[:available]):
        kind = "VM" if guest.get("type") == "qemu" else "CT"
        name_width = 24 if grid.width >= 160 else 18
        name = sanitize(guest.get("name"), name_width, grid.glyphs)
        node = sanitize(guest.get("node"), 8, grid.glyphs)
        status = sanitize(guest.get("status"), 9, grid.glyphs)
        base = (f"{kind:<6}{str(guest.get('vmid', '')):<5}{name:<{name_width + 1}}"
                f"{node:<9}{status:<10}{_cpu_key(guest):.1f}c {_pct(guest.get('cpu')):>3}%")
        base += f"   {_size(guest.get('mem'))}"
        if grid.width >= 160:
            base += (f"  {int(_number(guest.get('maxcpu')))}"
                     f"  {_uptime(guest.get('uptime'))}"
                     f"  {sanitize(guest.get('hastate'), 10, grid.glyphs) or '-'}"
                     f"  {','.join(sanitize(t, 16, grid.glyphs) for t in (guest.get('tags') or [])[:3])}")
        _text(grid, 1, start + index, base, grid.width - 2,
              "dim" if guest.get("status") != "running" or state != "ok" else "text")
    if len(ordered) > available:
        _text(grid, 2, start + available,
              _label_with(vm, "labels.moreGuests", grid.glyphs,
                          count=len(ordered) - available), grid.width - 4, "dim")
    if state == "starting" and not guests:
        _text(grid, 2, start, label("status.waitingForData"), grid.width - 4, "dim")


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
        _cluster_view(grid, view_model, state)
    else:
        _node_view(grid, view_model, state)
    _footer(grid, view_model, state, cluster_view)
    return grid
