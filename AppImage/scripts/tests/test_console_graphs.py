"""Tests for pure console graph primitives."""

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from console_graphs import (ACS_TOKENS, ASCII_TOKENS, GRAPH_ROLES, UNICODE_TOKENS,
                            align, graph, nice_scale, resample, sparkline,
                            threshold_role)


EMPTY = (None, None)
TOKENS = frozenset(("BAR_FULL", "BAR_HALF", "BAR_THIN"))
CAPS = frozenset(("BAR_HALF", "BAR_THIN"))


def column(matrix, index):
    return [row[index] for row in matrix]


def tokens(matrix):
    return [[token for token, _role in row] for row in matrix]


class NiceScaleTests(unittest.TestCase):
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


class GraphLevelTests(unittest.TestCase):
    def test_tiny_value_draws_one_thin_cap(self):
        self.assertEqual(graph([.01], 1, 4, 1),
                         [[EMPTY], [EMPTY], [EMPTY], [("BAR_THIN", "ok")]])

    def test_half_in_four_rows_is_two_full_cells_and_no_cap(self):
        self.assertEqual(tokens(graph([.5], 1, 4, 1)),
                         [[None], [None], ["BAR_FULL"], ["BAR_FULL"]])

    def test_three_levels_per_row_with_one_cap_cell(self):
        levels = [index / 12 for index in range(13)]
        self.assertEqual(tokens(graph(levels, 13, 4, 1)), [
            [None] * 10 + ["BAR_THIN", "BAR_HALF", "BAR_FULL"],
            [None] * 7 + ["BAR_THIN", "BAR_HALF", "BAR_FULL", "BAR_FULL", "BAR_FULL", "BAR_FULL"],
            [None] * 4 + ["BAR_THIN", "BAR_HALF", "BAR_FULL"] + ["BAR_FULL"] * 6,
            ["BAR_THIN", "BAR_THIN", "BAR_HALF"] + ["BAR_FULL"] * 10,
        ])

    def test_levels_round_to_nearest(self):
        # 0.14 * 12 = 1.68 -> 2 levels (half cap); 0.12 * 12 = 1.44 -> 1 level.
        self.assertEqual(tokens(graph([.12, .14], 2, 4, 1))[3], ["BAR_THIN", "BAR_HALF"])
        # 0.95 * 12 = 11.4 -> three full cells and a half cap, not a full column.
        self.assertEqual(tokens(graph([.95], 1, 4, 1)),
                         [["BAR_HALF"], ["BAR_FULL"], ["BAR_FULL"], ["BAR_FULL"]])

    def test_zero_is_a_thin_baseline_and_none_is_empty(self):
        self.assertEqual(graph([None, 0], 2, 2, 1),
                         [[EMPTY, EMPTY], [EMPTY, ("BAR_THIN", "ok")]])

    def test_missing_values_draw_nothing(self):
        for value in (None, float("nan"), float("inf"), -.5):
            with self.subTest(value=value):
                self.assertEqual(graph([value], 1, 3, 1), [[EMPTY], [EMPTY], [EMPTY]])

    def test_values_above_scale_fill_the_column(self):
        self.assertEqual(tokens(graph([2.5], 1, 2, 1)), [["BAR_FULL"], ["BAR_FULL"]])

    def test_scale_divides_values(self):
        self.assertEqual(graph([50, 100], 2, 2, 100, colour="graph_in"), [
            [EMPTY, ("BAR_FULL", "graph_in")],
            [("BAR_FULL", "graph_in"), ("BAR_FULL", "graph_in")],
        ])

    def test_inverted_grows_downward_with_cap_at_the_end(self):
        self.assertEqual(tokens(graph([2 / 6, 3 / 6, 4 / 6, 5 / 6, 1], 5, 2, 1, inverted=True)), [
            ["BAR_HALF", "BAR_FULL", "BAR_FULL", "BAR_FULL", "BAR_FULL"],
            [None, None, "BAR_THIN", "BAR_HALF", "BAR_FULL"],
        ])

    def test_right_aligns_and_clips_oldest_samples(self):
        self.assertEqual(tokens(graph([1], 3, 1, 1)), [[None, None, "BAR_FULL"]])
        self.assertEqual(tokens(graph([.5, .5, 1], 2, 1, 1)), [["BAR_HALF", "BAR_FULL"]])
        self.assertEqual(graph([], 2, 1, 1), [[EMPTY, EMPTY]])
        self.assertEqual(graph([1], 0, 2, 1), [[], []])
        self.assertEqual(graph([1], 2, 0, 1), [])

    def test_rejects_non_positive_scale_and_bad_colour(self):
        for scale in (0, -1):
            with self.subTest(scale=scale):
                with self.assertRaises(ValueError):
                    graph([1], 1, 1, scale)
        for colour in ("", None, 3):
            with self.subTest(colour=colour):
                with self.assertRaises(ValueError):
                    graph([1], 1, 1, 1, colour=colour)

    def test_sparkline_is_one_row(self):
        self.assertEqual(sparkline([None, 0, .01, .5, 1], 5, 1, colour="graph_out"), [[
            EMPTY, ("BAR_THIN", "graph_out"), ("BAR_THIN", "graph_out"),
            ("BAR_HALF", "graph_out"), ("BAR_FULL", "graph_out"),
        ]])


class GraphShapeInvariantTests(unittest.TestCase):
    """ADR 001 I2: no shade but one cap cell, only at the growing end."""

    VALUES = [None] + [step / 97 for step in range(0, 120)]

    def assert_column_shape(self, cells, rows):
        names = [token for token, _role in cells]
        filled = [name for name in names if name is not None]
        self.assertTrue(set(filled) <= TOKENS, names)
        self.assertLessEqual(sum(name in CAPS for name in names), 1, names)
        if filled:
            # Empty cells first, then at most one cap, then full cells.
            first = names.index(filled[0])
            self.assertTrue(all(name is None for name in names[:first]), names)
            self.assertTrue(all(name == "BAR_FULL" for name in names[first + 1:]), names)
            self.assertEqual(len(names), rows)

    def test_every_column_is_solid_with_one_cap_on_top(self):
        for rows in (1, 2, 4, 7):
            matrix = graph(self.VALUES, len(self.VALUES), rows, 1)
            for index in range(len(self.VALUES)):
                with self.subTest(rows=rows, index=index):
                    self.assert_column_shape(column(matrix, index), rows)

    def test_inverted_columns_mirror_the_same_shape(self):
        for rows in (1, 3, 5):
            matrix = graph(self.VALUES, len(self.VALUES), rows, 1, inverted=True)
            for index in range(len(self.VALUES)):
                with self.subTest(rows=rows, index=index):
                    self.assert_column_shape(column(matrix, index)[::-1], rows)

    def test_each_column_has_one_role(self):
        matrix = graph(self.VALUES, len(self.VALUES), 4, 1)
        for index in range(len(self.VALUES)):
            roles = {role for token, role in column(matrix, index) if token is not None}
            self.assertLessEqual(len(roles), 1)
            empty_roles = {role for token, role in column(matrix, index) if token is None}
            self.assertLessEqual(empty_roles, {None})


class ThresholdTests(unittest.TestCase):
    def test_exact_cuts(self):
        cases = ((0, "ok"), (.6999, "ok"), (.70, "warn"), (.8999, "warn"),
                 (.90, "crit"), (1, "crit"), (1.5, "crit"))
        for fraction, role in cases:
            with self.subTest(fraction=fraction):
                self.assertEqual(threshold_role(fraction), role)

    def test_each_column_takes_the_role_of_its_own_value(self):
        matrix = graph([.6999, .70, .8999, .90], 4, 3, 1)
        bottom = matrix[-1]
        self.assertEqual([role for _token, role in bottom], ["ok", "warn", "warn", "crit"])
        for index, expected in enumerate(("ok", "warn", "warn", "crit")):
            roles = {role for token, role in column(matrix, index) if token is not None}
            self.assertEqual(roles, {expected})

    def test_threshold_uses_the_fraction_of_scale(self):
        bottom = graph([69, 70, 90], 3, 1, 100)[0]
        self.assertEqual([role for _token, role in bottom], ["ok", "warn", "crit"])

    def test_fixed_role_overrides_threshold(self):
        matrix = graph([.1, .95], 2, 2, 1, colour="graph_out")
        self.assertEqual({role for row in matrix for token, role in row if token},
                         {"graph_out"})


class ResampleTests(unittest.TestCase):
    def test_bin_takes_the_maximum_of_present_values(self):
        self.assertEqual(resample([.45, None], 1), [.45])
        self.assertEqual(resample([None, .45], 1), [.45])
        self.assertEqual(resample([.2, .9, .4, .1], 2), [.9, .4])

    def test_bin_is_none_only_when_all_values_are_none(self):
        self.assertEqual(resample([None, None], 1), [None])
        self.assertEqual(resample([None, None, 0, None], 2), [None, 0])

    def test_sixty_minutes_into_thirty_columns_is_two_minutes_per_column(self):
        values = [index / 100 for index in range(60)]
        self.assertEqual(resample(values, 30), [values[index + 1] for index in range(0, 60, 2)])

    def test_uneven_bins_are_anchored_at_the_newest_point(self):
        values = list(range(60))
        result = resample(values, 9)  # ceil(60 / 9) = 7 minutes per column
        self.assertEqual(len(result), 9)
        self.assertEqual(result, [3, 10, 17, 24, 31, 38, 45, 52, 59])

    def test_fewer_bins_than_columns_when_minutes_per_column_rounds_up(self):
        result = resample(list(range(60)), 25)  # ceil(60 / 25) = 3 -> 20 columns
        self.assertEqual(len(result), 20)
        self.assertEqual(result[-1], 59)

    def test_upsampling_repeats_each_point_a_whole_number_of_times(self):
        self.assertEqual(resample([.1, None, .3], 6), [.1, .1, None, None, .3, .3])
        self.assertEqual(len(resample([0] * 60, 120)), 120)
        self.assertEqual(len(resample([0] * 60, 156)), 120)
        self.assertEqual(resample([.1, .2], 3), [.1, .2])

    def test_missing_values_never_win_a_bin(self):
        self.assertEqual(resample([float("nan"), .3, -1, None], 1), [.3])
        self.assertEqual(resample([float("nan"), None], 1), [None])
        self.assertEqual(resample([float("nan"), -1, .2], 3), [None, None, .2])
        self.assertEqual(resample([float("inf")], 2), [None, None])

    def test_degenerate_inputs(self):
        self.assertEqual(resample([], 30), [])
        self.assertEqual(resample([1, 2], 0), [])
        self.assertEqual(resample((value for value in (1, 2, 3, 4)), 2), [2, 4])


class AlignTests(unittest.TestCase):
    def test_sixty_second_lag_leaves_one_none_column_on_the_right(self):
        values = [index / 100 for index in range(60)]
        aligned = align({"pve01": (1793041560, values),
                         "pve02": (1793041500, values)}, 60)
        self.assertEqual(aligned["pve01"], values)
        self.assertEqual(aligned["pve02"], values[1:] + [None])
        matrix = graph(aligned["pve02"], 60, 2, 1)
        self.assertEqual(column(matrix, 59), [EMPTY, EMPTY])
        self.assertNotEqual(column(matrix, 58), [EMPTY, EMPTY])

    def test_same_index_is_the_same_minute(self):
        aligned = align({"a": (600, [1, 2, 3]), "b": (480, [7, 8, 9])}, 60)
        self.assertEqual(aligned, {"a": [1, 2, 3], "b": [9, None, None]})

    def test_series_too_old_or_without_t_end_is_all_none(self):
        aligned = align({"a": (6000, [1, 2]), "b": (0, [3, 4]), "c": (None, [5, 6])}, 60)
        self.assertEqual(aligned, {"a": [1, 2], "b": [None, None], "c": [None, None]})

    def test_small_clock_offset_rounds_to_the_nearest_step(self):
        aligned = align({"a": (1200, [1, 2, 3]), "b": (1145, [4, 5, 6]),
                         "c": (1175, [7, 8, 9])}, 60)
        self.assertEqual(aligned, {"a": [1, 2, 3], "b": [5, 6, None], "c": [7, 8, 9]})

    def test_keeps_each_length_and_rejects_bad_step(self):
        self.assertEqual(align({}, 60), {})
        self.assertEqual(align({"a": (60, [])}, 60), {"a": []})
        with self.assertRaises(ValueError):
            align({"a": (60, [1])}, 0)


class TokenTableTests(unittest.TestCase):
    def test_tables_match_the_adr(self):
        self.assertEqual(GRAPH_ROLES, frozenset(("graph_in", "graph_out")))
        self.assertEqual(ACS_TOKENS, {
            "BAR_FULL": "ACS_BLOCK", "BAR_HALF": "ACS_CKBOARD", "BAR_THIN": "_",
        })
        self.assertEqual(UNICODE_TOKENS, {
            "BAR_FULL": "█", "BAR_HALF": "▒", "BAR_THIN": "_",
        })
        self.assertEqual(ASCII_TOKENS, {
            "BAR_FULL": "#", "BAR_HALF": ":", "BAR_THIN": "_",
        })

    def test_no_light_shade_anywhere(self):
        for table in (ACS_TOKENS, UNICODE_TOKENS, ASCII_TOKENS):
            self.assertEqual(set(table), TOKENS)
            self.assertNotIn("░", "".join(table.values()))
            self.assertNotIn("ACS_BOARD", table.values())

    def test_acs_values_are_curses_names_or_one_ascii_character(self):
        for token, value in ACS_TOKENS.items():
            with self.subTest(token=token):
                self.assertTrue(value.startswith("ACS_") or
                                (len(value) == 1 and 0x20 < ord(value) < 0x7f))

    def test_ascii_mode_has_no_byte_above_0x7e(self):
        for row in graph([None, 0, .01, .5, 1], 5, 2, 1):
            rendered = "".join(" " if token is None else ASCII_TOKENS[token]
                               for token, _role in row)
            self.assertTrue(all(byte <= 0x7e for byte in rendered.encode("ascii")))


if __name__ == "__main__":
    unittest.main()
