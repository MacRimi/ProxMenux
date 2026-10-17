"""Tests for pure console rate graph primitives."""

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from console_graphs import (ACS_TOKENS, ASCII_TOKENS, GRAPH_ROLES, UNICODE_TOKENS,
                            graph, nice_scale, sparkline)


class ConsoleGraphsTests(unittest.TestCase):
    def test_nice_scale_uses_each_step_and_next_decade(self):
        cases = (
            (1, 1), (1.01, 1.5), (1.5, 1.5), (1.51, 2),
            (2.01, 3), (3.01, 4), (4.01, 5), (5.01, 6),
            (6.01, 8), (8.01, 10), (149, 150), (151, 200),
        )
        for peak, expected in cases:
            with self.subTest(peak=peak):
                self.assertEqual(nice_scale(peak, 0), expected)

    def test_nice_scale_respects_minimum_in_callers_unit(self):
        self.assertEqual(nice_scale(0, 10), 10)
        self.assertEqual(nice_scale(9, 10), 10)
        self.assertEqual(nice_scale(10.1, 10), 15)
        self.assertEqual(nice_scale(2, 10240), 15000)

    def test_sparkline_cell_levels_and_missing_samples(self):
        self.assertEqual(
            sparkline([None, 0, .01, .5, 1], 5, 1),
            [[" ", " ", "BAR_LOW", "BAR_MID", "BAR_FULL"]],
        )

    def test_graph_stacks_three_levels_per_cell(self):
        self.assertEqual(
            graph([0, 1 / 6, .5, 2 / 3, 1, 2], 6, 2, 1),
            [
                [" ", " ", " ", "BAR_LOW", "BAR_FULL", "BAR_FULL"],
                [" ", "BAR_LOW", "BAR_FULL", "BAR_FULL", "BAR_FULL", "BAR_FULL"],
            ],
        )

    def test_graph_inverted_grows_downward(self):
        self.assertEqual(
            graph([1 / 6, .5, 2 / 3, 1], 4, 2, 1, inverted=True),
            [
                ["BAR_LOW", "BAR_FULL", "BAR_FULL", "BAR_FULL"],
                [" ", " ", "BAR_LOW", "BAR_FULL"],
            ],
        )

    def test_graph_right_aligns_and_clips_samples(self):
        self.assertEqual(graph([1], 3, 1, 1), [[" ", " ", "BAR_FULL"]])
        self.assertEqual(graph([0, 0, 1], 2, 1, 1), [[" ", "BAR_FULL"]])
        self.assertEqual(graph([None, 1], 2, 1, 1), [[" ", "BAR_FULL"]])
        self.assertEqual(graph([], 2, 1, 1), [[" ", " "]])

    def test_glyph_tables_resolve_ascii_without_non_ascii_bytes(self):
        self.assertEqual(GRAPH_ROLES, frozenset(("graph_in", "graph_out")))
        self.assertEqual(ACS_TOKENS, {
            "BAR_LOW": "ACS_BOARD",
            "BAR_MID": "ACS_CKBOARD",
            "BAR_FULL": "ACS_BLOCK",
        })
        self.assertEqual(UNICODE_TOKENS, {
            "BAR_LOW": "░", "BAR_MID": "▒", "BAR_FULL": "█",
        })
        self.assertEqual(ASCII_TOKENS, {
            "BAR_LOW": ".", "BAR_MID": ":", "BAR_FULL": "#",
        })
        for row in graph([None, 0, .01, .5, 1], 5, 1, 1):
            rendered = "".join(ASCII_TOKENS.get(token, token) for token in row)
            self.assertTrue(all(byte <= 0x7e for byte in rendered.encode("ascii")))


if __name__ == "__main__":
    unittest.main()
