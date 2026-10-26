"""Tests for the console cluster view (view B, console_cluster.render)."""

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import console_cluster  # noqa: E402
import console_graphs  # noqa: E402
import console_render  # noqa: E402
import console_snapshot  # noqa: E402


FIXTURES = SCRIPTS_DIR / "tests" / "fixtures" / "console"
CATALOG = json.loads((SCRIPTS_DIR.parent / "messages" / "en" / "common.json").read_text(encoding="utf-8"))
GIB = 1 << 30
NOW = 1793041625
T_END = 1793041560


def tr(key):
    value = CATALOG
    for part in key.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value if isinstance(value, str) else key


# Rows 1-28 of the Owner-approved mockup "Vista B - Cluster - 100x30"
# (docs/specs/2026-10-26-console-tui-mockups-r4.md; rows 1-28 are the same with
# and without brand, which only changes the header row). Row 0 (header) and
# row 29 (footer) belong to console_render.
GOLDEN = [
    ' NODE     STATUS   CPU                MEM USED/TOTAL              %   ROOT  GUESTS  UP              ',
    ' pve01    online   74% ███████···    9.9/31 GiB   ███·······   32%    1%  1/1     4d 03h            ',
    ' pve02    online   12% █·········    9.0/31 GiB   ███·······   29%    1%  1/1     4d 03h            ',
    ' pve03*   online   27% ███·······    9.5/31 GiB   ███·······   31%    1%  1/4     4d 03h            ',
    '┌─CPU now · last 60 min · peak───────────────────┐┌─MEMORY now · last 60 min · peak────────────────┐',
    '│                       ▒▒                       ││                                                │',
    '│ pve01                ███                 █     ││ pve01                                          │',
    '│         74%  ▒▒ _ _▒ ███▒  _ ▒▒  _▒      █ pk  ││         32% ______________________________ pk  │',
    '│             ▒███████▒████▒█████▒▒█████▒███  95%││             ██████████████████████████████  32%│',
    '│                                                ││                                                │',
    '│ pve02                                          ││ pve02                                          │',
    '│         12%                     ▒          pk  ││         29%        __      _ _ _  _  _  __ pk  │',
    '│             ▒______________▒____█_________  45%││             ██████████████████████████████  29%│',
    '│                                                ││                                                │',
    '│ pve03*         █                               ││ pve03*                               ██        │',
    '│         27%    █      _                    pk  ││         31% ________________ ________██___ pk  │',
    '│             ▒█▒██__█▒▒█▒█▒█▒██▒██_██▒_████  72%││             ██████████████████████████████  75%│',
    '└─2 min/col──────────────────────────────────────┘└─2 min/col──────────────────────────────────────┘',
    '┌─TOP CPU host cores─────────────────────────────┐┌─TOP MEMORY footprint───────────────────────────┐',
    '│ GUEST                NODE    CPU% vCPU  HOST   ││ GUEST                NODE    USED/ASSIGN    %  │',
    '│ VM 110 runner-01     pve01    80%  14  11.2c   ││ VM 110 runner-01     pve01    6.5G/25.0G  26%  │',
    '│ VM 310 runner-03     pve03    28%  14   3.9c   ││ VM 310 runner-03     pve03    5.7G/25.0G  23%  │',
    '│ VM 210 runner-02     pve02    11%  14   1.5c   ││ VM 210 runner-02     pve02    5.6G/21.0G  27%  │',
    '│                                                ││                                                │',
    '│                                                ││                                                │',
    '└────────────────────────────────────────────────┘└────────────────────────────────────────────────┘',
    ' OTHER 3 stopped 3 · VM 9310 build-infra pve03 · VM 9320 build-datos pve03 · CT 9330 build-upstream ',
    '         running 0 outside the top lists                                                            ',
]
# Role of every non-blank cell of GOLDEN, from the mockup generator: t text,
# T title, d dim, o ok, w warn, c crit.
GOLDEN_ROLES = [
    ' TTTT     TTTTTT   TTT                TTT TTTTTTTTTT              T   TTTT  TTTTTT  TT              ',
    ' ttttt    oooooo   www wwwwwwwddd    tttttt ttt   oooddddddd   ooo    oo  ttt     tt ttt            ',
    ' ttttt    oooooo   ooo oddddddddd    tttttt ttt   oooddddddd   ooo    oo  ttt     tt ttt            ',
    ' tttttt   oooooo   ooo oooddddddd    tttttt ttt   oooddddddd   ooo    oo  ttt     tt ttt            ',
    'ddTTT ddd d dddd dd ddd d ddddddddddddddddddddddddddTTTTTT ddd d dddd dd ddd d ddddddddddddddddddddd',
    'd                       cc                       dd                                                d',
    'd ttttt                wcc                 w     dd ttttt                                          d',
    'd         www  oo o oo wcco  o oo  oo      w dd  dd         ooo oooooooooooooooooooooooooooooo dd  d',
    'd             ooooooooowccooooooooooooooooow  cccdd             oooooooooooooooooooooooooooooo  oood',
    'd                                                dd                                                d',
    'd ttttt                                          dd ttttt                                          d',
    'd         ooo                     o          dd  dd         ooo        oo      o o o  o  o  oo dd  d',
    'd             oooooooooooooooooooooooooooooo  ooodd             oooooooooooooooooooooooooooooo  oood',
    'd                                                dd                                                d',
    'd tttttt         w                               dd tttttt                               ww        d',
    'd         ooo    w      o                    dd  dd         ooo oooooooooooooooo oooooooowwooo dd  d',
    'd             ooowoooooooooooooooooooooooooo  wwwdd             ooooooooooooooooooooooooowwooo  wwwd',
    'ddd ddddddddddddddddddddddddddddddddddddddddddddddddd dddddddddddddddddddddddddddddddddddddddddddddd',
    'ddTTT TTT dddd dddddddddddddddddddddddddddddddddddddTTT TTTTTT ddddddddddddddddddddddddddddddddddddd',
    'd TTTTT                TTTT    TTTT TTTT  TTTT   dd TTTTT                TTTT    TTTTTTTTTTT    T  d',
    'd tt ttt ttttttttt     ttttt    www  tt  ttttt   dd tt ttt ttttttttt     ttttt    tttttttttt  ooo  d',
    'd tt ttt ttttttttt     ttttt    ooo  tt   tttt   dd tt ttt ttttttttt     ttttt    tttttttttt  ooo  d',
    'd tt ttt ttttttttt     ttttt    ooo  tt   tttt   dd tt ttt ttttttttt     ttttt    tttttttttt  ooo  d',
    'd                                                dd                                                d',
    'd                                                dd                                                d',
    'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
    ' TTTTT T ddddddd d d dd dddd ddddddddddd ddddd d dd dddd ddddddddddd ddddd d dd dddd dddddddddddddd ',
    '         ddddddd d ddddddd ddd ddd ddddd                                                            ',
]
ROLE_CODES = {"t": "text", "T": "title", "d": "dim", "o": "ok", "w": "warn", "c": "crit"}
# The mockup lets the third stopped guest run off the screen; ADR 001 §2.4
# truncates the OTHER line with "+n" instead, from column 77 of row 27.
OTHER_TRUNCATED_FROM = (27, 77)

# The mockup's 30 two-minute values per node; each becomes two equal RRD points.
C1_HISTORY = {
    "pve01": ([0.190309, 0.40423, 0.379132, 0.226521, 0.298631, 0.284847, 0.345478, 0.386617, 0.178158, 0.74, 0.95, 0.92, 0.378684, 0.150632, 0.283616, 0.366462, 0.218629, 0.433581, 0.420428, 0.159177, 0.157634, 0.312424, 0.431745, 0.264361, 0.21498, 0.276635, 0.158712, 0.216507, 0.281366, 0.74],
              [0.309048, 0.311195, 0.318484, 0.309313, 0.310157, 0.311748, 0.303693, 0.310238, 0.312598, 0.31586, 0.301882, 0.306068, 0.301813, 0.316193, 0.313869, 0.300838, 0.319644, 0.319295, 0.313078, 0.312311, 0.30315, 0.3003, 0.310568, 0.301191, 0.303804, 0.304839, 0.300602, 0.309279, 0.308811, 0.316849]),
    "pve02": ([0.125603, 0.124783, 0.035655, 0.038487, 0.11355, 0.103597, 0.096973, 0.060814, 0.090594, 0.09068, 0.08812, 0.045838, 0.073067, 0.069353, 0.102301, 0.129482, 0.12494, 0.084418, 0.074485, 0.056824, 0.45, 0.032744, 0.076489, 0.061847, 0.068001, 0.119179, 0.082575, 0.086051, 0.053612, 0.032386],
              [0.289746, 0.291575, 0.291664, 0.286426, 0.285109, 0.288748, 0.28774, 0.293103, 0.291906, 0.291015, 0.290582, 0.291613, 0.286453, 0.289401, 0.286623, 0.29406, 0.285588, 0.293188, 0.285746, 0.291869, 0.28837, 0.289046, 0.293424, 0.285186, 0.285608, 0.29415, 0.290089, 0.28591, 0.294871, 0.294467]),
    "pve03": ([0.147593, 0.208846, 0.173991, 0.72, 0.225144, 0.113106, 0.102634, 0.267494, 0.151871, 0.146866, 0.299129, 0.194053, 0.267292, 0.195271, 0.227814, 0.130123, 0.226972, 0.273609, 0.204636, 0.24825, 0.234282, 0.112806, 0.251646, 0.21822, 0.160254, 0.106202, 0.273105, 0.27, 0.243765, 0.275763],
              [0.29518, 0.303705, 0.303682, 0.306987, 0.293714, 0.294611, 0.292943, 0.294503, 0.30468, 0.292604, 0.300626, 0.294278, 0.295893, 0.298632, 0.306753, 0.302168, 0.290289, 0.295517, 0.292934, 0.307426, 0.306195, 0.306121, 0.306527, 0.304895, 0.308986, 0.72, 0.75, 0.306999, 0.299736, 0.3051]),
}
EMPTY_GLYPHS = {"unicode": "·", "ascii": ".", "acs": "BAR_EMPTY"}
GRAPH_GLYPHS = {"unicode": "█▒_", "ascii": "#:_", "acs": ("BAR_FULL", "BAR_HALF", "_")}
FULL = {"unicode": "█", "ascii": "#", "acs": "BAR_FULL"}
BOX = {"unicode": "─│┌┐└┘", "ascii": "-|+", "acs": ("BOX_H", "BOX_V", "BOX_UL", "BOX_UR",
                                                     "BOX_LL", "BOX_LR")}
ACS_CELLS = {"BOX_H", "BOX_V", "BOX_UL", "BOX_UR", "BOX_LL", "BOX_LR",
             "BAR_FULL", "BAR_HALF", "BAR_EMPTY", "BULLET"}


def doubled(values):
    return [value for value in values for _ in (0, 1)]


def node(name, cpu, mem_gib, status="online", total_gib=31):
    return {"name": name, "status": status, "cpu": cpu, "maxcpu": 16,
            "mem": round(mem_gib * GIB), "maxmem": total_gib * GIB,
            "disk": GIB, "maxdisk": 100 * GIB, "uptime": 4 * 86400 + 3 * 3600}


def guest(vmid, name, host, cpu=0.0, mem_gib=0.0, maxmem_gib=8.0, status="running",
          kind="qemu", maxcpu=14, tags=None):
    return {"vmid": vmid, "type": kind, "name": name, "node": host, "status": status,
            "cpu": cpu, "maxcpu": maxcpu, "mem": round(mem_gib * GIB),
            "maxmem": round(maxmem_gib * GIB), "uptime": 3600 if status == "running" else 0,
            "template": False, "tags": tags or []}


def entry(cpu, mem, status="ok", t_end=T_END, observed=NOW - 5, load=0.54):
    return {"status": status, "observed_at": observed, "t_end": t_end, "maxcpu": 16,
            "memtotal": 31 * GIB, "cpu": list(cpu), "mem": list(mem), "load1": [load] * len(cpu)}


def c1_vm(**changes):
    nodes = [node("pve01", 0.74, 9.9), node("pve02", 0.12, 9.0), node("pve03", 0.27, 9.5)]
    guests = [guest(110, "runner-01", "pve01", 0.80, 6.5, 25.0),
              guest(310, "runner-03", "pve03", 0.28, 5.7, 25.0),
              guest(210, "runner-02", "pve02", 0.11, 5.6, 21.0),
              guest(9310, "build-infra", "pve03", status="stopped"),
              guest(9320, "build-datos", "pve03", status="stopped"),
              guest(9330, "build-upstream", "pve03", status="stopped", kind="lxc")]
    history = {"status": "ok", "observed_at": NOW - 5, "source": "rrddata", "step_s": 60,
               "points": 60, "error": None,
               "nodes": {name: entry(doubled(c), doubled(m)) for name, (c, m) in C1_HISTORY.items()}}
    members = [{"name": n["name"], "nodeid": i + 1, "online": True, "local": n["name"] == "pve03"}
               for i, n in enumerate(nodes)]
    vm = {"glyphs": "unicode", "lang": "en", "tr": tr, "now": NOW, "selected_view": "cluster",
          "sort": "cpu", "local": {}, "host_other": {},
          "snapshot": {"schema": 1, "age_s": 2, "observed_at": NOW - 2, "publish_interval_s": 10,
                       "node": {"status": "ok", "name": "pve03"},
                       "cluster": {"status": "ok", "is_cluster": True, "name": "c1", "quorate": True,
                                   "nodes_total": 3, "nodes_online": 3, "members": members},
                       "resources": {"status": "ok", "nodes": nodes, "guests": guests, "storages": []},
                       "history": history}}
    vm.update(changes)
    return vm


def many_nodes_vm(count, offline=(), guests_per_list=3):
    names = [f"pve-{index:02d}" for index in range(1, count + 1)]
    vm = c1_vm()
    snapshot = vm["snapshot"]
    snapshot["cluster"]["members"] = [{"name": n, "online": n not in offline, "local": i == 0}
                                      for i, n in enumerate(names)]
    snapshot["cluster"]["nodes_total"] = count
    snapshot["resources"]["nodes"] = [node(n, 0.1 + 0.08 * (i % 10), 4.0 + i, "offline" if n in offline else "online")
                                      for i, n in enumerate(names)]
    guests = [guest(100 + i, f"vm-{i}", names[i % count], 0.1 + 0.05 * i, 2.0 + i, 16.0)
              for i in range(guests_per_list)]
    guests.append(guest(900, "parked", names[0], status="stopped"))
    snapshot["resources"]["guests"] = guests
    cpu = [0.2 + 0.01 * (i % 30) for i in range(60)]
    mem = [0.4] * 60
    snapshot["history"]["nodes"] = {n: entry(cpu, mem, "stale" if n in offline else "ok",
                                             T_END - (600 if n in offline else 0),
                                             NOW - (660 if n in offline else 5))
                                    for n in names}
    return vm


def draw(vm, width, height, state="ok"):
    grid = console_render.Grid(width, height, vm.get("glyphs", "unicode"))
    plan = console_cluster.render(grid, vm, state)
    return grid, plan


def row_text(grid, y):
    return "".join(cell[0] if len(cell[0]) == 1 else "#" for cell in grid[y])


def all_text(grid):
    return "\n".join(row_text(grid, y) for y in range(grid.height))


def find(grid, text):
    for y in range(grid.height):
        x = row_text(grid, y).find(text)
        if x >= 0:
            return x, y
    return None


def boxes(plan, width):
    """(x, y, w, h) of every box console_cluster draws for ``plan``."""
    result = []
    halves = ((0, width // 2), (width // 2, width - width // 2))
    if not plan["compact"]:
        result += [(x, plan["panel_y"], w, plan["panel_rows"]) for x, w in halves]
    if plan["top_rows"] >= 3:
        result += [(x, plan["top_y"], w, plan["top_rows"]) for x, w in halves]
    return result


class InvariantMixin:
    """ADR 001 §2.8 invariants I1, I2, I3 (graphs), I6 for view B grids."""

    def assert_invariants(self, grid, plan):
        glyphs = grid.glyphs
        graph_glyphs = GRAPH_GLYPHS[glyphs]
        for y, row in enumerate(grid):
            self.assertEqual(len(row), grid.width)
            for x, (char, role, attrs) in enumerate(row):
                self.assertNotEqual(char, "░", (x, y))
                if char == EMPTY_GLYPHS[glyphs] and "glyph" in attrs:
                    self.assertEqual(role, "dim", ("I1", x, y))
                if char in graph_glyphs and "glyph" in attrs:
                    self.assertIn(role, ("ok", "warn", "crit", "dim"), ("I3", x, y))
                if glyphs == "acs" and len(char) > 1:
                    self.assertIn(char, ACS_CELLS, (x, y))
                if glyphs == "ascii":
                    self.assertLessEqual(ord(char), 0x7E, (x, y))
        for x, y, w, h in boxes(plan, grid.width):
            border = [(c, y) for c in range(x, x + w)] + [(c, y + h - 1) for c in range(x, x + w)]
            border += [(x, r) for r in range(y, y + h)] + [(x + w - 1, r) for r in range(y, y + h)]
            box_glyphs = BOX[glyphs]
            for c, r in border:
                char, role, _attrs = grid[r][c]
                on_title = r in (y, y + h - 1) and x < c < x + w - 1
                if on_title and char not in box_glyphs:
                    continue  # titles and bottom labels sit on the horizontal edges
                self.assertIn(char, box_glyphs, ("I6", c, r))
                self.assertEqual(role, "dim", ("I6", c, r))
            for r in (y, y + h - 1):
                for c in (x, x + 1, x + w - 2, x + w - 1):
                    self.assertIn(grid[r][c][0], box_glyphs, ("I6 corner", c, r))
        if not plan["compact"]:
            self.assert_caps(grid, plan)

    def assert_caps(self, grid, plan):
        """I2: within a node block, a column is solid with one cap cell at its top."""
        full = FULL[grid.glyphs]
        for start in range(plan["panel_y"] + 1, plan["panel_y"] + 1 + plan["g"] * plan["n_hist"], plan["g"]):
            for x in range(grid.width):
                column = [grid[y][x] for y in range(start, start + plan["g"])]
                cells = [char for char, _role, attrs in column if "glyph" in attrs]
                if not cells:
                    continue
                self.assertTrue(all(char == full for char in cells[1:]), ("I2", x, start, cells))
                filled = [i for i, (char, _r, attrs) in enumerate(column) if "glyph" in attrs]
                self.assertEqual(filled, list(range(filled[0], plan["g"])), ("I2 gap", x, start))


class GoldenTests(unittest.TestCase):
    def test_100x30_matches_the_approved_mockup_cell_by_cell(self):
        grid, plan = draw(c1_vm(), 100, 30)
        self.assertEqual((plan["g"], plan["t"], plan["other_rows"], plan["n_hist"]), (4, 5, 2, 3))
        for y in range(1, 29):
            expected, roles = GOLDEN[y - 1], GOLDEN_ROLES[y - 1]
            for x in range(100):
                if (y, x) >= OTHER_TRUNCATED_FROM and y == OTHER_TRUNCATED_FROM[0]:
                    continue
                char, role, _attrs = grid[y][x]
                self.assertEqual(char, expected[x], f"char at row {y} col {x}:\n{row_text(grid, y)}\n{expected}")
                if expected[x] != " ":
                    self.assertEqual(role, ROLE_CODES[roles[x]], f"role at row {y} col {x} ({expected[x]!r})")

    def test_other_line_is_truncated_with_a_count(self):
        grid, _plan = draw(c1_vm(), 100, 30)
        self.assertEqual(row_text(grid, 27).rstrip(),
                         " OTHER 3 stopped 3 · VM 9310 build-infra pve03 · VM 9320 build-datos pve03 · +1")
        self.assertEqual(grid[27][78][1], "dim")

    def test_header_and_footer_rows_are_left_alone(self):
        grid, _plan = draw(c1_vm(), 100, 30)
        for y in (0, 29):
            self.assertTrue(all(cell == (" ", "text", ()) for cell in grid[y]), y)

    def test_bar_and_graph_cells_carry_the_glyph_attribute(self):
        grid, _plan = draw(c1_vm(), 100, 30)
        self.assertEqual(grid[2][23], ("█", "warn", ("glyph",)))
        self.assertEqual(grid[2][30], ("·", "dim", ("glyph",)))
        self.assertEqual(grid[9][14], ("▒", "ok", ("glyph",)))
        self.assertEqual(grid[7][9], (" ", "text", ()))
        self.assertEqual(grid[8][10], ("7", "warn", ()))


class LayoutTests(unittest.TestCase):
    def test_reference_sizes(self):
        cases = (
            # width, height, nodes, longest list, outside -> n_hist, g, t, other rows
            ((100, 30, 3, 3, True), (3, 4, 5, 2)),
            ((100, 30, 2, 5, True), (2, 6, 6, 2)),
            ((100, 30, 2, 3, True), (2, 7, 4, 2)),
            ((100, 30, 1, 3, True), (1, 8, 11, 2)),
            ((100, 30, 6, 3, True), (6, 2, 3, 1)),
            ((100, 30, 7, 3, True), (6, 2, 3, 1)),
            ((100, 30, 8, 3, True), (6, 2, 3, 1)),
            ((100, 28, 3, 3, False), (3, 4, 4, 1)),
            ((160, 45, 3, 3, True), (3, 8, 3, 7)),
            ((320, 90, 3, 5, True), (3, 8, 5, 50)),
            ((320, 90, 10, 3, True), (10, 6, 3, 9)),
        )
        for args, expected in cases:
            with self.subTest(args=args):
                plan = console_cluster.layout(*args)
                self.assertFalse(plan["compact"])
                self.assertEqual((plan["n_hist"], plan["g"], plan["t"], plan["other_rows"]), expected)
                self.assertEqual(plan["other_y"] + plan["other_rows"], args[1] - 1)
                self.assertEqual(plan["panel_rows"], 2 + plan["g"] * plan["n_hist"])

    def test_compact_below_100x28(self):
        for size in ((80, 24), (99, 30), (100, 27), (120, 26)):
            with self.subTest(size=size):
                plan = console_cluster.layout(size[0], size[1], 3, 3, True)
                self.assertTrue(plan["compact"])
                self.assertEqual(plan["panel_rows"], 0)
                self.assertEqual(plan["top_y"], 1 + 1 + 3)
                self.assertEqual(plan["other_y"] + plan["other_rows"], size[1] - 1)

    def test_g_stays_within_two_and_eight(self):
        for height in range(28, 100):
            for nodes in range(1, 40):
                plan = console_cluster.layout(160, height, nodes, 5, True)
                if not plan["compact"]:
                    self.assertTrue(2 <= plan["g"] <= 8, (height, nodes, plan))
                    self.assertGreaterEqual(plan["other_rows"], 1, (height, nodes))
                    self.assertGreaterEqual(plan["t"], 3, (height, nodes))

    def test_node_table_is_capped_at_a_quarter_of_the_height(self):
        plan = console_cluster.layout(100, 30, 7, 3, True)
        self.assertEqual(plan["table_lines"], 6)


class NodeCountTests(InvariantMixin, unittest.TestCase):
    def test_one_node(self):
        grid, plan = draw(many_nodes_vm(1), 100, 30)
        self.assertEqual((plan["n_hist"], plan["g"]), (1, 8))
        self.assert_invariants(grid, plan)
        self.assertIsNotNone(find(grid, "pve-01*"))

    def test_three_nodes_in_every_glyph_mode(self):
        for glyphs in ("unicode", "acs", "ascii"):
            with self.subTest(glyphs=glyphs):
                grid, plan = draw(c1_vm(glyphs=glyphs), 100, 30)
                self.assert_invariants(grid, plan)

    def test_acs_mode_uses_logical_tokens(self):
        grid, _plan = draw(c1_vm(glyphs="acs"), 100, 30)
        self.assertEqual(grid[5][0][0], "BOX_UL")
        self.assertEqual(grid[2][23][0], "BAR_FULL")
        self.assertEqual(grid[2][30][0], "BAR_EMPTY")
        self.assertEqual(grid[9][14][0], "BAR_HALF")
        self.assertEqual(grid[13][15][0], "_")
        self.assertEqual(grid[5][10][0], "BULLET")

    def test_eight_nodes_summarise_the_rest(self):
        grid, plan = draw(many_nodes_vm(8), 100, 30)
        self.assertEqual((plan["n_hist"], plan["g"], plan["table_lines"]), (6, 2, 6))
        self.assert_invariants(grid, plan)
        self.assertEqual(row_text(grid, 7).strip(), "+3 nodes")
        bottom = plan["panel_y"] + plan["panel_rows"] - 1
        self.assertIn("+2 nodes", row_text(grid, bottom)[:50])
        self.assertIn("+2 nodes", row_text(grid, bottom)[50:])
        # One row left for the rest: only the stopped guest, no "running 0".
        self.assertEqual(row_text(grid, plan["other_y"]).rstrip(), " OTHER 1 stopped 1 · VM 900 parked pve-01")

    def test_seven_nodes_at_100x30(self):
        grid, plan = draw(many_nodes_vm(7), 100, 30)
        self.assertEqual(plan["n_hist"], 6)
        bottom = plan["panel_y"] + plan["panel_rows"] - 1
        self.assertIn("+1 nodes", row_text(grid, bottom))
        self.assert_invariants(grid, plan)


class OfflineAndHistoryTests(InvariantMixin, unittest.TestCase):
    def test_offline_node_sorts_first_and_is_red(self):
        grid, plan = draw(many_nodes_vm(3, offline={"pve-02"}), 100, 30)
        self.assert_invariants(grid, plan)
        self.assertTrue(row_text(grid, 2).startswith(" pve-02   offline"))
        self.assertEqual(grid[2][10][1], "crit")
        self.assertIn("--", row_text(grid, 2))
        block = plan["panel_y"] + 1
        self.assertIn("offline", row_text(grid, block + plan["g"] - 2)[:14])
        roles = {grid[y][x][1] for y in range(block, block + plan["g"]) for x in range(14, 44)
                 if "glyph" in grid[y][x][2]}
        self.assertEqual(roles, {"dim"})
        age_x = 14 + 30 + 1
        self.assertEqual(row_text(grid, block + plan["g"] - 2)[age_x:age_x + 3], "11m")
        self.assertEqual(grid[block + plan["g"] - 2][age_x][1], "warn")

    def test_lagging_node_is_aligned_by_t_end(self):
        vm = c1_vm()
        vm["snapshot"]["history"]["nodes"]["pve02"]["t_end"] = T_END - 240
        grid, _plan = draw(vm, 100, 30)
        # Four minutes late at 2 min/col: its two newest columns are empty.
        block_bottom = 6 + 4 + 3
        self.assertEqual([grid[block_bottom][x][0] for x in (42, 43)], [" ", " "])
        self.assertEqual(grid[block_bottom][41][0], "_")

    def test_missing_node_history_says_no_history(self):
        vm = c1_vm()
        del vm["snapshot"]["history"]["nodes"]["pve02"]
        grid, _plan = draw(vm, 100, 30)
        self.assertEqual(row_text(grid, 12)[14:24], "no history")
        self.assertEqual(grid[12][14][1], "dim")
        self.assertEqual(row_text(grid, 12)[10:13], "12%")

    def test_snapshot_without_history_section_draws_no_history(self):
        vm = c1_vm()
        del vm["snapshot"]["history"]
        for width, height in ((100, 30), (160, 45)):
            with self.subTest(size=(width, height)):
                grid, plan = draw(vm, width, height)
                self.assertFalse(plan["compact"])
                self.assert_invariants(grid, plan)
                text = all_text(grid)
                self.assertEqual(text.count("no history"), 6)
                self.assertNotIn("pk", text)

    def test_unavailable_history_from_the_reader_draws_no_history(self):
        vm = c1_vm()
        vm["snapshot"]["history"] = {"status": "unavailable", "observed_at": None, "source": None,
                                     "step_s": 60, "points": 60, "nodes": {}, "error": None}
        grid, plan = draw(vm, 100, 30)
        self.assertEqual(all_text(grid).count("no history"), 6)
        self.assert_invariants(grid, plan)

    def test_starting_history_waits_for_data(self):
        vm = c1_vm()
        vm["snapshot"]["history"] = {"status": "starting", "step_s": 60, "points": 60, "nodes": {}}
        grid, _plan = draw(vm, 100, 30)
        self.assertEqual(all_text(grid).count("waiting for data"), 6)

    def test_real_snapshot_reader_and_rrd_fixture(self):
        rows = json.loads((FIXTURES / "rrddata_hour.json").read_text(encoding="utf-8"))
        history_entry = console_snapshot.normalize_history({"source": "rrddata", "rows": rows})
        vm = c1_vm()
        document = copy.deepcopy(vm["snapshot"])
        document.pop("age_s")
        document["generator"] = {"name": "proxmenux-monitor", "version": "test", "pid": 1}
        document["observed_at"] = history_entry["t_end"] + 70
        document["history"] = {"status": "ok", "observed_at": document["observed_at"],
                               "source": "rrddata", "step_s": 60, "points": 60, "error": None,
                               "nodes": {"pve03": {**history_entry, "status": "ok",
                                                   "observed_at": document["observed_at"]}}}
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "console.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump(document, stream)
            snapshot = console_snapshot.load_snapshot(path, document["observed_at"] + 2)
        self.assertIsNone(snapshot.reason)
        data = dict(snapshot.data, age_s=snapshot.age_s)
        vm = c1_vm(snapshot=data, now=document["observed_at"] + 2)
        grid, plan = draw(vm, 160, 45)
        self.assert_invariants(grid, plan)
        text = all_text(grid)
        self.assertEqual(text.count("no history"), 4)  # pve01 and pve02 in both panels
        peak = max(v for v in history_entry["cpu"] if v is not None)
        block = plan["panel_y"] + 1 + 2 * plan["g"]
        strip = 14 + 60 + 1
        self.assertEqual(row_text(grid, block + plan["g"] - 1)[strip:strip + 4], f"{peak * 100:3.0f}%")
        load = [v for v in history_entry["load1"] if v is not None][-1]
        self.assertIn(f"{load:.2f}", row_text(grid, 4))


class SizeTests(InvariantMixin, unittest.TestCase):
    def test_80x24_is_compact(self):
        vm = c1_vm()
        vm["snapshot"]["resources"]["guests"][0]["name"] = "runner-01-with-a-very-long-name"
        for glyphs in ("unicode", "acs", "ascii"):
            with self.subTest(glyphs=glyphs):
                vm["glyphs"] = glyphs
                grid, plan = draw(vm, 80, 24)
                self.assertTrue(plan["compact"])
                self.assert_invariants(grid, plan)
                text = all_text(grid)
                self.assertNotIn("last 60 min", text)
                self.assertIn("OTHER 3", text)
        vm["glyphs"] = "unicode"
        grid, plan = draw(vm, 80, 24)
        row = row_text(grid, plan["top_y"] + 2)
        self.assertEqual(row[:40], "│ VM 110 run… pve01    80%  14  11.2c  │")
        self.assertEqual(row[40:], "│ VM 110 run… pve01    6.5G/25.0G  26% │")
        self.assertTrue(row_text(grid, 2).startswith(" pve01    online   74% ████·    9.9/31 GiB   ██···   32%"))

    def test_160x45(self):
        grid, plan = draw(c1_vm(), 160, 45)
        self.assertEqual((plan["n_hist"], plan["g"]), (3, 8))
        self.assert_invariants(grid, plan)
        bottom = plan["panel_y"] + plan["panel_rows"] - 1
        self.assertTrue(row_text(grid, bottom).startswith("└─1 min/col─"))
        self.assertIn("LOAD", row_text(grid, 1))
        self.assertIn("0.54", row_text(grid, 2))
        graph_cells = {x for y in range(plan["panel_y"] + 1, plan["panel_y"] + 1 + plan["g"])
                       for x in range(80) if "glyph" in grid[y][x][2]}
        self.assertEqual((min(graph_cells), max(graph_cells)), (14, 73))
        table = row_text(grid, plan["other_y"])
        self.assertIn("GUESTS", table)
        self.assertIn("running 3", table)
        header = row_text(grid, plan["other_y"] + 1)
        for column in ("TYPE", "MEM USED/ASSIGNED", "CPU%", "vCPU", "HOST", "UP", "HA", "TAGS"):
            self.assertIn(column, header)
        self.assertTrue(row_text(grid, plan["other_y"] + 2).startswith(" VM   110  runner-01"))
        self.assertIsNone(plan["art_area"])  # six guests fill the table

    def test_320x90(self):
        grid, plan = draw(c1_vm(), 320, 90)
        self.assertEqual((plan["n_hist"], plan["g"]), (3, 8))
        self.assert_invariants(grid, plan)
        bottom = plan["panel_y"] + plan["panel_rows"] - 1
        self.assertTrue(row_text(grid, bottom).startswith("└─1 min = 2 cols─"))
        graph_cells = {x for y in range(plan["panel_y"] + 1, plan["panel_y"] + 1 + plan["g"])
                       for x in range(160) if "glyph" in grid[y][x][2]}
        self.assertEqual((min(graph_cells), max(graph_cells)), (14, 133))
        # 1 min = 2 cols: both columns of each minute are identical.
        for y in range(plan["panel_y"] + 1, plan["panel_y"] + 1 + plan["g"]):
            for x in range(14, 134, 2):
                self.assertEqual(grid[y][x], grid[y][x + 1], (x, y))
        x, y, w, h = plan["art_area"]
        self.assertEqual((x, w, y + h), (0, 320, 89))
        self.assertGreaterEqual(h, 7)
        for row in range(y, y + h):
            self.assertTrue(all(cell == (" ", "text", ()) for cell in grid[row]), row)

    def test_guest_table_overflow_and_sort(self):
        vm = c1_vm(sort="mem")
        vm["snapshot"]["resources"]["guests"] = [
            guest(200 + i, f"g{i}", "pve01", 0.01 * i, 1.0 + i, 128.0) for i in range(70)]
        grid, plan = draw(vm, 320, 90)
        self.assert_invariants(grid, plan)
        first = row_text(grid, plan["other_y"] + 2)
        self.assertTrue(first.startswith(" VM   269  g69"), first)
        last = row_text(grid, plan["other_y"] + plan["other_rows"] - 1).strip()
        self.assertRegex(last, r"^\+\d+ guests$")

    def test_guest_table_widens_the_id_column_for_long_vmids(self):
        vm = c1_vm()
        vm["snapshot"]["resources"]["guests"][0]["vmid"] = 123456
        grid, plan = draw(vm, 160, 45)
        self.assertTrue(row_text(grid, plan["other_y"] + 2).startswith(" VM   123456 runner-01"))


class StateTests(unittest.TestCase):
    def test_stale_snapshot_dims_values_and_titles(self):
        vm = c1_vm()
        vm["snapshot"]["age_s"] = 180
        grid, _plan = draw(vm, 100, 30, state="stale")
        self.assertEqual(grid[2][19][1], "dim")
        self.assertIn("(3m old)", row_text(grid, 19))
        graph_roles = {grid[y][x][1] for y in range(6, 18) for x in range(14, 44)
                       if "glyph" in grid[y][x][2]}
        self.assertEqual(graph_roles, {"dim"})

    def test_no_snapshot_is_safe(self):
        for state in ("starting", "unavailable"):
            with self.subTest(state=state):
                grid, plan = draw(c1_vm(snapshot=None), 100, 30, state=state)
                self.assertTrue(plan["compact"])
                expected = "waiting for data" if state == "starting" else "no data"
                self.assertIn(expected, row_text(grid, 2))

    def test_standalone_node_from_resources(self):
        vm = c1_vm()
        vm["snapshot"]["cluster"] = {"status": "ok", "is_cluster": False, "members": []}
        vm["snapshot"]["resources"]["nodes"] = vm["snapshot"]["resources"]["nodes"][2:]
        grid, plan = draw(vm, 100, 30)
        self.assertEqual(plan["n_hist"], 1)
        self.assertTrue(row_text(grid, 2).startswith(" pve03*"))

    def test_untrusted_names_are_sanitized(self):
        vm = c1_vm()
        vm["snapshot"]["resources"]["guests"][0]["name"] = "evil\x1b[31mname\nčx"
        vm["snapshot"]["cluster"]["members"][0]["name"] = "pve01\x1b[2J"
        grid, _plan = draw(vm, 100, 30)
        text = all_text(grid)
        self.assertNotIn("\x1b", text)
        self.assertIn("VM 110 evilnamecx", text)

    def test_percent_roles_follow_thresholds(self):
        vm = c1_vm()
        nodes = vm["snapshot"]["resources"]["nodes"]
        for item, value in zip(nodes, (0.69, 0.70, 0.90)):
            item["cpu"] = value
        grid, _plan = draw(vm, 100, 30)
        self.assertEqual([grid[y][20][1] for y in (2, 3, 4)], ["ok", "warn", "crit"])
        self.assertEqual([grid[y][23][1] for y in (2, 3, 4)], ["ok", "warn", "crit"])

    def test_graph_column_roles_follow_thresholds(self):
        vm = c1_vm()
        values = [0.69] * 20 + [0.70] * 20 + [0.90] * 20
        vm["snapshot"]["history"]["nodes"]["pve01"]["cpu"] = values
        grid, _plan = draw(vm, 100, 30)
        bottom = 6 + 3
        self.assertEqual([grid[bottom][x][1] for x in (14, 25, 43)], ["ok", "warn", "crit"])

    def test_digits_in_values_are_never_dim(self):
        """I4 over the node table, the history panels and the TOP lists."""
        grid, plan = draw(c1_vm(), 100, 30)
        labels = {plan["panel_y"], plan["panel_y"] + plan["panel_rows"] - 1}  # "last 60 min", "2 min/col"
        for y in range(1, plan["other_y"]):
            if y in labels:
                continue
            for x, (char, role, _attrs) in enumerate(grid[y]):
                if char.isdigit():
                    self.assertNotEqual(role, "dim", (x, y))


if __name__ == "__main__":
    unittest.main()
