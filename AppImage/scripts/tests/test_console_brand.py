"""Tests for the optional console brand: validation and painting."""

import contextlib
import copy
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import console_brand  # noqa: E402
from console_render import ACS_TOKENS, Grid  # noqa: E402


LOGO = [
    " ████  ██  ██ ██   ██ ███████",
    "██  ██ ██  ██ ███ ███ ██     ",
    "██  ██ ██  ██ ███████ █████  ",
    "██ ███ ██  ██ ██ █ ██ ██     ",
    " █████  ████  ██   ██ ███████",
]
BOX_ART = ["┌──┐ ░▒█", "│OK│ ╔═╗", "└──┘ ╚═╝"]
NO_BRAND = {"badge": None, "art": []}


def _load(text, art_path):
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        result = console_brand.load(text, art_path)
    return result, stderr.getvalue()


def _printable(text):
    return all(char == "\n" or " " <= char <= "~" for char in text)


class BadgeValidationTests(unittest.TestCase):
    def test_valid_text_is_trimmed_and_kept(self):
        for text, expected in (("HOMELAB", "HOMELAB"), ("  Lab-01  ", "Lab-01"),
                               ("A", "A"), ("node 1.2_b+c-d", "node 1.2_b+c-d"),
                               ("X" * 24, "X" * 24)):
            with self.subTest(text=text):
                result, warning = _load(text, None)
                self.assertEqual(result, {"badge": expected, "art": []})
                self.assertEqual(warning, "")

    def test_absent_text_is_silent(self):
        for text in (None, ""):
            with self.subTest(text=text):
                self.assertEqual(_load(text, None), (NO_BRAND, ""))

    def test_invalid_text_is_ignored_with_a_clean_warning(self):
        for text in ("X" * 25, "-LAB", ".LAB", "LÁB", "LAB\n", "\nLAB", "LA\tB",
                     "\x1b[31mLAB", "LAB\x1b[0m", "LAB\x07", "LAB\x9b1m", "   ",
                     "LAB/1", "LAB;rm", "LAB█", b"LAB", 7):
            with self.subTest(text=text):
                result, warning = _load(text, None)
                self.assertEqual(result, NO_BRAND)
                self.assertIn("--brand ignored", warning)
                self.assertTrue(_printable(warning), repr(warning))


class ArtFileTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="console-brand-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        os.chmod(self.dir, 0o755)
        # The owner check targets root; without root, our own uid stands in.
        patcher = mock.patch.object(console_brand, "_ROOT_UID", os.geteuid())
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, content, name="brand.txt", mode=0o644):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as handle:
            handle.write(content if isinstance(content, bytes) else content.encode("utf-8"))
        os.chmod(path, mode)
        return path

    def assertAccepted(self, path, expected):
        result, warning = _load(None, path)
        self.assertEqual(warning, "")
        self.assertEqual(result, {"badge": None, "art": expected})
        for line in result["art"]:
            self.assertTrue(all(console_brand._allowed(char) for char in line), repr(line))

    def assertRejected(self, path, reason):
        result, warning = _load(None, path)
        self.assertEqual(result, NO_BRAND)
        self.assertIn("--brand-art ignored", warning)
        self.assertIn(reason, warning)
        self.assertTrue(_printable(warning), repr(warning))
        self.assertEqual(warning.count("\n"), 1)
        return warning

    def test_valid_art_is_loaded(self):
        self.assertAccepted(self.write("\n".join(LOGO) + "\n"), [line.rstrip() for line in LOGO])

    def test_box_drawing_ascii_and_blocks_are_accepted(self):
        art = BOX_ART + ["~!@#$%^&*()_+{}|:<>? `-=[]\\;',./"]
        self.assertAccepted(self.write("\n".join(art)), art)

    def test_crlf_and_trailing_spaces_and_blank_lines(self):
        self.assertAccepted(self.write("██  \r\n █ \r\n\r\n██\r\n\r\n\n"), ["██", " █", "", "██"])

    def test_limits_are_inclusive(self):
        art = ["█" * 64] * 6
        path = self.write("\n".join(art) + "\n")
        self.assertLessEqual(os.path.getsize(path), console_brand.MAX_ART_BYTES)
        self.assertAccepted(path, art)

    def test_readonly_modes_are_accepted(self):
        for mode in (0o644, 0o444, 0o600, 0o400):
            with self.subTest(mode=oct(mode)):
                self.assertAccepted(self.write("ART", f"brand-{mode:o}.txt", mode), ["ART"])

    def test_escape_sequences_reject_the_whole_file(self):
        for payload in ("\x1b[31m██", "██\x1b[2J", "\x1b]0;title\x07", "\x1bc",
                        "\x9b31m██", "\x1b(0lqk\x1b(B"):
            with self.subTest(payload=payload):
                path = self.write("██ ██\n" + payload + "\n██ ██\n")
                self.assertRejected(path, "characters other than")

    def test_every_control_character_is_rejected(self):
        controls = [chr(code) for code in list(range(0x20)) + list(range(0x7f, 0xa0))]
        controls += [" ", " ", "﻿", "​"]
        for char in controls:
            if char == "\n":
                continue
            with self.subTest(code=hex(ord(char))):
                self.assertRejected(self.write(f"██{char}██\n██\n"), "characters other than")

    def test_other_line_separators_never_split_lines(self):
        # splitlines() alone would turn these into extra lines and accept them.
        for separator in ("\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85"):
            with self.subTest(code=hex(ord(separator))):
                self.assertRejected(self.write(f"██{separator}██"), "characters other than")

    def test_bad_charset_is_rejected(self):
        for char in ("▁", "▄", "▓", "·", "é", "⠀",
                     "\U0001f600", "▀", "■"):
            with self.subTest(code=hex(ord(char))):
                self.assertRejected(self.write(f"██\n█{char}█\n"), "characters other than")

    def test_invalid_utf8_is_rejected(self):
        for payload in (b"\xff\xfe", b"\x9b31m", b"\xe2\x96", b"\xc0\xaf"):
            with self.subTest(payload=payload):
                self.assertRejected(self.write(b"ART\n" + payload), "not valid UTF-8")

    def test_one_bad_line_rejects_every_line(self):
        self.assertRejected(self.write("\n".join(LOGO + ["▁"])), "characters other than")

    def test_too_many_lines(self):
        self.assertRejected(self.write("\n".join(["█"] * 7)), "more than 6 lines")
        self.assertRejected(self.write("█\n\n\n\n\n\n█\n"), "more than 6 lines")

    def test_too_wide(self):
        self.assertRejected(self.write("█" * 65), "wider than 64 cells")
        self.assertRejected(self.write("██\n" + "x" * 65 + "\n"), "wider than 64 cells")

    def test_oversize_file(self):
        self.assertRejected(self.write("#" * 5120), "larger than 4096 bytes")
        self.assertRejected(self.write("#" * 4097), "larger than 4096 bytes")

    def test_empty_file(self):
        self.assertRejected(self.write(""), "empty")
        self.assertRejected(self.write("   \n\n  \n"), "empty")

    def test_group_or_other_writable_file(self):
        for mode in (0o664, 0o646, 0o666, 0o620, 0o602):
            with self.subTest(mode=oct(mode)):
                self.assertRejected(self.write("ART", mode=mode), "file writable by group or others")

    def test_group_or_other_writable_directory(self):
        path = self.write("ART")
        for mode in (0o775, 0o757, 0o777, 0o1777):
            with self.subTest(mode=oct(mode)):
                os.chmod(self.dir, mode)
                self.assertRejected(path, "directory writable by group or others")

    def test_foreign_owner_is_rejected(self):
        path = self.write("ART")
        with mock.patch.object(console_brand, "_ROOT_UID", os.geteuid() + 1):
            self.assertRejected(path, "directory not owned by root")

    def test_owner_check_on_a_foreign_file(self):
        # Without root a test cannot chown, so check the fstat() result rule.
        for uid, mode, reason in ((65534, 0o100644, "file not owned by root"),
                                  (0, 0o100664, "file writable by group or others")):
            with mock.patch.object(console_brand, "_ROOT_UID", 0):
                info = os.stat_result((mode, 1, 1, 1, uid, 0, 3, 0, 0, 0))
                with self.assertRaisesRegex(console_brand._Rejected, reason):
                    console_brand._check_owner(info, "file")
        console_brand._check_owner(os.stat_result((0o100644, 1, 1, 1, os.geteuid(), 0, 3, 0, 0, 0)), "file")

    @unittest.skipUnless(os.geteuid() == 0, "chown needs root")
    def test_file_owned_by_another_user_is_rejected(self):
        path = self.write("ART")
        os.chown(path, 65534, 65534)
        self.assertRejected(path, "file not owned by root")

    @unittest.skipUnless(os.geteuid() == 0, "chown needs root")
    def test_directory_owned_by_another_user_is_rejected(self):
        path = self.write("ART")
        os.chown(self.dir, 65534, 65534)
        self.assertRejected(path, "directory not owned by root")

    def test_symlink_to_a_valid_file_is_rejected(self):
        target = self.write("ART")
        link = os.path.join(self.dir, "link.txt")
        os.symlink(target, link)
        self.assertRejected(link, "is a symlink")

    def test_symlinked_directory_is_rejected(self):
        real = os.path.join(self.dir, "real")
        os.mkdir(real, 0o755)
        os.chmod(real, 0o755)
        self.write("ART", name="real/brand.txt")
        link = os.path.join(self.dir, "linked")
        os.symlink(real, link)
        self.assertAccepted(os.path.join(real, "brand.txt"), ["ART"])
        self.assertRejected(os.path.join(link, "brand.txt"), "is a symlink")

    def test_dangling_symlink_is_rejected(self):
        link = os.path.join(self.dir, "dangling.txt")
        os.symlink(os.path.join(self.dir, "missing.txt"), link)
        self.assertRejected(link, "is a symlink")

    def test_non_regular_files_are_rejected_without_blocking(self):
        fifo = os.path.join(self.dir, "fifo")
        os.mkfifo(fifo, 0o644)
        os.chmod(fifo, 0o644)
        self.assertRejected(fifo, "not a regular file")
        sub = os.path.join(self.dir, "sub")
        os.mkdir(sub, 0o755)
        self.assertRejected(sub, "not a regular file")
        self.assertRejected(sub + "/", "not a regular file")

    def test_device_is_rejected(self):
        with mock.patch.object(console_brand, "_ROOT_UID", 0):
            if os.stat("/dev").st_uid != 0 or os.stat("/dev").st_mode & 0o022:
                self.skipTest("/dev is not a root-owned 0755 directory here")
            self.assertRejected("/dev/null", "not a regular file")

    def test_bad_paths_never_raise(self):
        self.assertRejected("brand.txt", "path must be absolute")
        self.assertRejected("./brand.txt", "path must be absolute")
        self.assertRejected(os.path.join(self.dir, "a\0b"), "invalid path")
        self.assertRejected(os.path.join(self.dir, "missing.txt"), "No such file")
        self.assertRejected(os.path.join(self.dir, "missing", "brand.txt"), "No such file")
        self.assertRejected(42, "path must be absolute")
        self.assertRejected(b"/etc/brand.txt", "path must be absolute")

    def test_warning_escapes_a_hostile_path(self):
        warning = self.assertRejected(os.path.join(self.dir, "\x1b[2J\x1b]0;x\x07"), "No such file")
        self.assertIn("\\x1b[2J", warning)

    def test_absent_path_is_silent(self):
        for path in (None, ""):
            with self.subTest(path=path):
                self.assertEqual(_load(None, path), (NO_BRAND, ""))

    def test_bad_art_keeps_a_valid_badge(self):
        result, warning = _load("HOMELAB", self.write("\x1b[31m"))
        self.assertEqual(result, {"badge": "HOMELAB", "art": []})
        self.assertIn("--brand-art ignored", warning)


def _header(width=40):
    grid = Grid(width, 3, "unicode")
    grid.put(1, 0, "TITLE status text", "title")
    return grid


class PaintBadgeTests(unittest.TestCase):
    def test_badge_is_right_aligned_bold_and_reverse(self):
        grid = _header()
        self.assertTrue(console_brand.paint_badge(grid, 0, 36, "LAB"))
        self.assertEqual("".join(cell[0] for cell in grid[0][31:36]), " LAB ")
        for cell in grid[0][31:36]:
            self.assertEqual(cell[1:], ("brand_badge", ("bold", "reverse")))
        self.assertEqual(grid[0][30], (" ", "text", ()))
        self.assertEqual(grid[0][36], (" ", "text", ()))

    def test_badge_needs_len_plus_four_free_cells(self):
        grid = _header()
        status_end = 1 + len("TITLE status text")
        exact = status_end + len("LAB") + 4
        before = copy.deepcopy(grid)
        self.assertFalse(console_brand.paint_badge(grid, 0, exact - 1, "LAB"))
        self.assertEqual(grid, before)
        self.assertTrue(console_brand.paint_badge(grid, 0, exact, "LAB"))
        self.assertEqual(grid[0][status_end - 1][0], "t")
        self.assertEqual(grid[0][status_end:status_end + 2], [(" ", "text", ())] * 2)
        self.assertEqual(grid[0][status_end + 2], (" ", "brand_badge", ("bold", "reverse")))

    def test_status_text_wins(self):
        grid = Grid(30, 1, "acs")
        grid.put(0, 0, "X" * 25)
        before = copy.deepcopy(grid)
        self.assertFalse(console_brand.paint_badge(grid, 0, 30, "LAB"))
        self.assertEqual(grid, before)

    def test_reversed_blank_cells_are_not_free(self):
        grid = _header()
        grid.put(30, 0, " ", "selected", ("reverse",))
        self.assertFalse(console_brand.paint_badge(grid, 0, 36, "LAB"))

    def test_right_edge_is_clamped_to_the_grid(self):
        grid = _header()
        self.assertTrue(console_brand.paint_badge(grid, 0, 999, "LAB"))
        self.assertEqual("".join(cell[0] for cell in grid[0][35:40]), " LAB ")
        self.assertEqual(len(grid[0]), 40)

    def test_no_badge_or_bad_input_is_a_no_op(self):
        for badge, y, right_x in ((None, 0, 36), ("", 0, 36), ("\x1b[2JLAB", 0, 36),
                                  ("LAB\n", 0, 36), ("LAB", -1, 36), ("LAB", 3, 36),
                                  ("LAB", 0, 6), ("LAB", 0, -5)):
            with self.subTest(badge=badge, y=y, right_x=right_x):
                grid = _header()
                before = copy.deepcopy(grid)
                self.assertFalse(console_brand.paint_badge(grid, y, right_x, badge))
                self.assertEqual(grid, before)


class PaintArtTests(unittest.TestCase):
    def test_art_is_centred_bold_and_transparent(self):
        grid = Grid(40, 12, "unicode")
        art = ["█ █", "███"]
        self.assertTrue(console_brand.paint_art(grid, 0, 0, 40, 12, art))
        ax, ay = (40 - 3) // 2, (12 - 2) // 2
        self.assertEqual(grid[ay][ax], ("█", "brand", ("bold",)))
        self.assertEqual(grid[ay][ax + 1], (" ", "text", ()))
        self.assertEqual(grid[ay + 1][ax + 1], ("█", "brand", ("bold",)))
        painted = sum(cell[1] == "brand" for row in grid for cell in row)
        self.assertEqual(painted, 5)

    def test_art_needs_a_one_cell_margin(self):
        art = ["███", "███"]
        for w, h in ((4, 4), (5, 3)):
            with self.subTest(w=w, h=h):
                grid = Grid(10, 6, "unicode")
                before = copy.deepcopy(grid)
                self.assertFalse(console_brand.paint_art(grid, 1, 1, w, h, art))
                self.assertEqual(grid, before)
        grid = Grid(10, 6, "unicode")
        self.assertTrue(console_brand.paint_art(grid, 1, 1, 5, 4, art))
        self.assertEqual([row[2:5] for row in grid[2:4]], [[("█", "brand", ("bold",))] * 3] * 2)

    def test_art_never_overwrites_a_panel_border(self):
        for glyphs in ("acs", "unicode", "ascii"):
            grid = Grid(30, 10, glyphs)
            grid.box(2, 1, 20, 8, "PANEL")
            border = {(x, y): grid[y][x] for y in range(10) for x in range(30)
                      if grid[y][x] != (" ", "text", ())}
            art = ["█" * 16, "█" * 16, "█" * 16, "█" * 16]
            # Interior is 18x6: the art plus its margin fits exactly.
            self.assertTrue(console_brand.paint_art(grid, 3, 2, 18, 6, art), glyphs)
            for (x, y), cell in border.items():
                self.assertEqual(grid[y][x], cell, (glyphs, x, y))
            # A region that includes the border has no free margin: no paint.
            grid = Grid(30, 10, glyphs)
            grid.box(2, 1, 20, 8, "PANEL")
            before = copy.deepcopy(grid)
            self.assertFalse(console_brand.paint_art(grid, 2, 1, 20, 8, ["█" * 18] * 6), glyphs)
            self.assertEqual(grid, before)

    def test_occupied_cells_block_the_art(self):
        grid = Grid(20, 8, "unicode")
        grid.put(9, 1, "x")
        before = copy.deepcopy(grid)
        self.assertFalse(console_brand.paint_art(grid, 0, 0, 20, 8, ["█" * 10] * 6))
        self.assertEqual(grid, before)

    def test_region_is_clipped_to_the_grid(self):
        grid = Grid(10, 5, "unicode")
        self.assertTrue(console_brand.paint_art(grid, -20, -20, 100, 100, ["███"]))
        self.assertEqual(len(grid), 5)
        self.assertTrue(all(len(row) == 10 for row in grid))
        self.assertEqual(grid[2][3:6], [("█", "brand", ("bold",))] * 3)
        grid = Grid(10, 5, "unicode")
        self.assertFalse(console_brand.paint_art(grid, 8, 3, 50, 50, ["███"]))

    def test_glyph_modes(self):
        art = ["┌─┐█▒░╔═╗", "│x│┼├┤╳╱╲", "└─┘┬┴╴╵┄┆"]
        unicode_grid = Grid(20, 6, "unicode")
        self.assertTrue(console_brand.paint_art(unicode_grid, 0, 0, 20, 6, art))
        self.assertEqual("".join(cell[0] for cell in unicode_grid[1][5:14]), art[0])
        acs_grid = Grid(20, 6, "acs")
        self.assertTrue(console_brand.paint_art(acs_grid, 0, 0, 20, 6, art))
        self.assertEqual([cell[0] for cell in acs_grid[1][5:14]],
                         ["BOX_UL", "BOX_H", "BOX_UR", "BAR_FULL", ":", ".", "+", "-", "+"])
        self.assertEqual([cell[0] for cell in acs_grid[2][5:14]],
                         ["BOX_V", "x", "BOX_V", "BOX_X", "BOX_LT", "BOX_RT", "X", "/", "\\"])
        self.assertEqual([cell[0] for cell in acs_grid[3][5:14]],
                         ["BOX_LL", "BOX_H", "BOX_LR", "BOX_TT", "BOX_BT", "-", "|", "-", "|"])
        ascii_grid = Grid(20, 6, "ascii")
        self.assertTrue(console_brand.paint_art(ascii_grid, 0, 0, 20, 6, art))
        self.assertEqual("".join(cell[0] for cell in ascii_grid[1][5:14]), "+-+#:.+-+")
        self.assertEqual("".join(cell[0] for cell in ascii_grid[2][5:14]), "|x|+++X/\\")
        self.assertEqual("".join(cell[0] for cell in ascii_grid[3][5:14]), "+-+++-|-|")

    def test_every_allowed_glyph_maps_to_ascii_or_a_known_token(self):
        box = "".join(chr(code) for code in range(0x2500, 0x2580))
        art = [box[:64], box[64:], "█▒░ ~AZaz09"]
        for glyphs in ("acs", "ascii"):
            grid = Grid(70, 6, glyphs)
            self.assertTrue(console_brand.paint_art(grid, 0, 0, 70, 6, art))
            for row in grid:
                for char, role, _attrs in row:
                    if role != "brand":
                        continue
                    if glyphs == "acs" and len(char) > 1:
                        self.assertIn(char, ACS_TOKENS)
                    else:
                        self.assertEqual(len(char), 1)
                        self.assertTrue(" " < char <= "~", (glyphs, char))

    def test_unvalidated_art_is_refused(self):
        for art in (["\x1b[31m"], ["██", "▁"], ["█" * 65], ["█"] * 7, "███", [b"##"],
                    [], ["   "], None, [None]):
            with self.subTest(art=art):
                grid = Grid(80, 12, "unicode")
                before = copy.deepcopy(grid)
                self.assertFalse(console_brand.paint_art(grid, 0, 0, 80, 12, art))
                self.assertEqual(grid, before)

    def test_without_brand_the_grid_is_unchanged(self):
        brand = console_brand.load(None, None)
        grid = _header()
        grid.box(0, 1, 40, 2, "PANEL")
        before = copy.deepcopy(grid)
        self.assertFalse(console_brand.paint_badge(grid, 0, 36, brand["badge"]))
        self.assertFalse(console_brand.paint_art(grid, 0, 0, 40, 3, brand["art"]))
        self.assertEqual(grid, before)


if __name__ == "__main__":
    unittest.main()
