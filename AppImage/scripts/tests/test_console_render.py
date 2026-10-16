"""Contract tests for the terminal-independent console renderer."""

import copy
import json
import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from console_render import ACS_TOKENS, render, sanitize


CATALOG = json.loads((SCRIPTS_DIR.parent / "messages" / "en" / "common.json")
                     .read_text(encoding="utf-8"))["runtime"]["consoleTui"]


def tr(key):
    value = CATALOG
    try:
        for part in key.removeprefix("runtime.consoleTui.").split("."):
            value = value[part]
    except (KeyError, TypeError):
        return key
    return value


def lines(grid):
    return ["".join(cell[0] for cell in row) for row in grid]


class ConsoleRenderTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).parent / "fixtures" / "console" / "viewmodel_cluster.json"
        self.vm = json.loads(fixture.read_text(encoding="utf-8"))
        self.vm["tr"] = tr

    def test_exact_grid_dimensions_for_both_views(self):
        for view in ("node", "cluster"):
            for width, height in ((80, 24), (128, 48), (240, 67)):
                with self.subTest(view=view, size=(width, height)):
                    self.vm["selected_view"] = view
                    grid = render(self.vm, width, height)
                    self.assertEqual(len(grid), height)
                    self.assertTrue(all(len(row) == width for row in grid))
                    self.assertTrue(all(len(cell) == 3 for row in grid for cell in row))

    def test_node_80x24_panel_positions_and_collapse(self):
        rows = lines(render(self.vm, 80, 24))
        self.assertIn("[Node] Cluster", rows[0])
        self.assertIn("CPU", rows[1])
        self.assertIn("MEMORY", rows[1])
        self.assertEqual(rows[1][42:44], "++")
        self.assertIn("NET", rows[6])
        self.assertEqual(rows[6][22:24], "++")
        self.assertEqual(rows[6][50:52], "++")
        self.assertIn("TOP CPU", rows[10])
        self.assertIn("TOP MEMORY", rows[10])
        self.assertEqual(rows[5][0], "+")
        self.assertNotIn("CPU0", "\n".join(rows))
        self.assertIn("q login", rows[23])
        self.assertIn("data 2s", rows[23])
        self.assertIn("+2 nodes", "\n".join(rows[6:10]))
        self.assertIn("TOP CPU (host cores)", rows[10])
        self.assertEqual(rows[10].count("(host cores)"), 1)

    def test_selected_tab_uses_selected_role(self):
        grid = render(self.vm, 80, 24)
        self.assertEqual(grid[0][22], ("[", "selected", ("reverse",)))
        self.vm["selected_view"] = "cluster"
        grid = render(self.vm, 80, 24)
        self.assertEqual(grid[0][22][1], "text")
        self.assertEqual(grid[0][27][1], "selected")

    def test_top_lists_use_host_cores_and_memory_not_status(self):
        rows = lines(render(self.vm, 80, 24))
        self.assertIn("plex", rows[11][:40])
        self.assertIn("nginx", rows[12][:40])
        self.assertIn("db", rows[11][40:])
        self.assertIn("plex", rows[12][40:])
        self.assertIn("win", "\n".join(row[40:] for row in rows[11:23]))
        self.assertNotIn("template", "\n".join(rows))

    def test_host_other_titles_only_with_fresh_snapshot(self):
        rows = lines(render(self.vm, 128, 48))
        self.assertIn("host other 1.6c", rows[14])
        self.assertIn("host other 8.0 GiB", rows[14])
        self.vm["snapshot"]["resources"]["status"] = "stale"
        rows = lines(render(self.vm, 128, 48))
        self.assertNotIn("host other", rows[14])
        self.assertIn("old", rows[14])

    def test_host_other_none_is_hidden_independently(self):
        self.vm["host_other"]["cpu"] = None
        rows = lines(render(self.vm, 128, 48))
        self.assertNotIn("host other", rows[14][:64])
        self.assertIn("host other 8.0 GiB", rows[14][64:])

    def test_stale_and_unavailable_age_labels(self):
        self.vm["snapshot"]["age_s"] = 120
        rows = lines(render(self.vm, 128, 48))
        self.assertIn("(2m old)", rows[14])
        self.vm["snapshot"]["age_s"] = 180
        rows = lines(render(self.vm, 128, 48))
        self.assertIn("MONITOR UNAVAILABLE (3m)", rows[0])
        self.vm["snapshot"]["age_s"] = 3600
        self.assertIn("(1h old)", lines(render(self.vm, 128, 48))[14])

    def test_pve_version_accepts_plain_and_manager_forms(self):
        for version in ("9.0.6", "pve-manager/9.0.6/abc"):
            with self.subTest(version=version):
                self.vm["snapshot"]["node"]["pve_version"] = version
                self.assertIn("PVE 9.0", lines(render(self.vm, 80, 24))[0])

    def test_translation_with_stray_brace_keeps_rendering(self):
        self.vm["tr"] = lambda key: "data {age} {" if key.endswith("status.data") else tr(key)
        self.assertIn("data 2s {", lines(render(self.vm, 80, 24))[-1])

    def test_cluster_offline_first_and_coverage_suppresses_totals(self):
        self.vm["selected_view"] = "cluster"
        rows = lines(render(self.vm, 80, 24))
        self.assertIn("p3-03", rows[2])
        self.assertIn("offline", rows[2])
        self.assertIn("coverage 2/3", rows[0])
        self.assertNotIn("64 GiB", rows[0])

    def test_cluster_totals_require_quorum_and_full_coverage(self):
        self.vm["selected_view"] = "cluster"
        cluster = self.vm["snapshot"]["cluster"]
        cluster["nodes_total"] = 2
        cluster["members"] = cluster["members"][:2]
        rows = lines(render(self.vm, 80, 24))
        self.assertIn("64 GiB", rows[0])
        cluster["quorate"] = False
        rows = lines(render(self.vm, 80, 24))
        self.assertIn("NO QUORUM", rows[0])
        self.assertNotIn("64 GiB", rows[0])

    def test_cluster_node_bars_and_overflow_markers(self):
        self.vm["selected_view"] = "cluster"
        grid = render(self.vm, 80, 24)
        self.assertIn("#", lines(grid)[3])
        self.assertIn(".", lines(grid)[3])
        cluster = self.vm["snapshot"]["cluster"]
        for index in range(5):
            cluster["members"].append({"name": f"p3-{index + 10}", "online": False})
        cluster["nodes_total"] = len(cluster["members"])
        guests = self.vm["snapshot"]["resources"]["guests"]
        for index in range(13):
            extra = copy.deepcopy(guests[0])
            extra["vmid"] = 300 + index
            extra["name"] = f"guest-{index}"
            guests.append(extra)
        rows = lines(render(self.vm, 80, 24))
        self.assertIn("+3 nodes", "\n".join(rows))
        self.assertIn("+5 guests", "\n".join(rows))

    def test_cluster_guest_sort_and_status(self):
        self.vm["selected_view"] = "cluster"
        rows = lines(render(self.vm, 80, 24))
        self.assertIn("plex", rows[7])
        self.assertIn("nginx", rows[8])
        self.vm["sort"] = "mem"
        rows = lines(render(self.vm, 80, 24))
        self.assertIn("db", rows[7])
        self.assertIn("plex", rows[8])
        self.assertIn("unknown", "\n".join(rows))

    def test_host_other_uses_viewmodel_values(self):
        self.vm["host_other"] = {"cpu": 0.0, "mem": 0}
        rows = lines(render(self.vm, 128, 48))
        self.assertIn("host other 0.0c", rows[14])
        self.assertIn("host other 0 MiB", rows[14])

    def test_node_growth_and_standalone(self):
        rows = lines(render(self.vm, 128, 48))
        self.assertIn("CPU0", "\n".join(rows[:9]))
        self.assertIn("TOP CPU", rows[14])
        guest = self.vm["snapshot"]["resources"]["guests"][0]
        guest["net_rx_bps"] = 1024
        guest["net_tx_bps"] = 2048
        guest["disk_read_bps"] = 4096
        guest["disk_write_bps"] = 8192
        rows = lines(render(self.vm, 240, 67))
        self.assertEqual(rows[65][0], "+")
        self.assertIn("q login", rows[66])
        self.assertIn("UP", rows[14 + 1])
        self.assertIn("NET", rows[14 + 1])
        self.assertIn("DISK", rows[14 + 1])
        self.vm["selected_view"] = "cluster"
        rows = lines(render(self.vm, 240, 67))
        self.assertIn("CORES", "\n".join(rows[:8]))
        self.assertIn("UPTIME", "\n".join(rows[:8]))
        self.assertIn("HA", "\n".join(rows[:8]))
        self.assertIn("TAGS", "\n".join(rows[:8]))
        self.vm["selected_view"] = "node"
        self.vm["snapshot"]["cluster"]["is_cluster"] = False
        rows = lines(render(self.vm, 80, 24))
        self.assertIn("STANDALONE", rows[0])
        self.assertIn("STANDALONE", rows[6])
        self.assertNotIn("CLUSTER", rows[6])
        self.vm["selected_view"] = "cluster"
        self.vm["snapshot"]["cluster"]["members"] = []
        rows = lines(render(self.vm, 80, 24))
        self.assertIn("p3-01", rows[2])

    def test_no_quorum_and_stale_roles(self):
        self.vm["selected_view"] = "cluster"
        self.vm["snapshot"]["cluster"]["quorate"] = False
        grid = render(self.vm, 80, 24)
        header = lines(grid)[0]
        self.assertEqual(grid[0][header.index("NO QUORUM")][1], "crit")
        self.vm["selected_view"] = "node"
        grid = render(self.vm, 80, 24)
        self.assertIn("NO QUORUM", lines(grid)[0])
        self.vm["snapshot"]["resources"]["status"] = "stale"
        grid = render(self.vm, 80, 24)
        self.assertEqual(grid[11][3][1], "dim")

    def test_status_starting_warn_unavailable_crit(self):
        self.vm["snapshot"]["resources"]["status"] = "starting"
        grid = render(self.vm, 80, 24)
        self.assertIn("Monitor starting", lines(grid)[0])
        self.assertEqual(grid[0][lines(grid)[0].index("Monitor starting")][1], "warn")
        self.assertIn("waiting for data", "\n".join(lines(grid)))
        self.vm["snapshot"]["resources"]["status"] = "unavailable"
        grid = render(self.vm, 80, 24)
        self.assertIn("MONITOR UNAVAILABLE", lines(grid)[0])
        self.assertEqual(grid[0][lines(grid)[0].index("MONITOR UNAVAILABLE")][1], "crit")

    def test_absent_snapshot_uses_local_uptime_for_starting(self):
        self.vm["snapshot"] = None
        self.vm["local"]["uptime"] = 80
        grid = render(self.vm, 80, 24)
        self.assertIn("Monitor starting", lines(grid)[0])
        self.assertEqual(grid[0][lines(grid)[0].index("Monitor starting")][1], "warn")
        self.vm["local"]["uptime"] = 180
        grid = render(self.vm, 80, 24)
        self.assertIn("MONITOR UNAVAILABLE", lines(grid)[0])
        self.assertEqual(grid[0][lines(grid)[0].index("MONITOR UNAVAILABLE")][1], "crit")

    def test_small_terminal_message(self):
        for width, height in ((79, 24), (80, 23)):
            rows = lines(render(self.vm, width, height))
            self.assertIn("Terminal too small (80x24)", "\n".join(rows))
            self.assertNotIn("TOP CPU", "\n".join(rows))

    def test_ascii_mode_and_sanitize(self):
        self.assertEqual(sanitize("\x1b[31mhi\nč", 20, "ascii"), "hic")
        self.assertEqual(sanitize("abcdefghijkl", 6, "ascii"), "abcde~")
        self.assertEqual(sanitize("abcdefghijkl", 6, "unicode"), "abcde…")
        for view in ("node", "cluster"):
            self.vm["selected_view"] = view
            self.assertTrue(all(ord(cell[0]) <= 0x7e for row in render(self.vm, 80, 24) for cell in row))

    def test_acs_glyphs_are_logical_tokens_for_curses_layer(self):
        self.vm["glyphs"] = "acs"
        grid = render(self.vm, 80, 24)
        self.assertEqual(grid[1][0][0], "BOX_UL")
        self.assertEqual(ACS_TOKENS[grid[1][0][0]], "ACS_ULCORNER")
        self.assertEqual(grid[2][0][0], "BOX_V")

    def test_unicode_glyph_mode_uses_box_and_bar_characters(self):
        self.vm["glyphs"] = "unicode"
        grid = render(self.vm, 80, 24)
        self.assertEqual(grid[1][0][0], "┌")
        self.assertEqual(grid[2][0][0], "│")
        self.assertIn(grid[2][2][0], ("█", "░"))

    def test_snapshot_and_nic_names_are_sanitized(self):
        self.vm["snapshot"]["node"]["name"] = "p3\x1b[31m-01"
        self.vm["local"]["net"]["nic"] = "eno\n1"
        rows = lines(render(self.vm, 80, 24))
        self.assertIn("p3-01", rows[0])
        self.assertIn("eno1", rows[6])
        self.assertNotIn("[31m", "\n".join(rows))


if __name__ == "__main__":
    unittest.main()
