"""Optional branding for the ProxMenux console: a header badge and block art.

Branding is off by default. ``load`` validates ``--brand`` and ``--brand-art``
once at start-up; any problem means "no brand" plus a one-line warning on
stderr, never an exception. ``paint_badge`` and ``paint_art`` draw onto a
``console_render.Grid`` only over free cells, so the brand never displaces or
overwrites other content, and only characters from a fixed whitelist (ASCII,
three block glyphs and box drawing) can ever reach the terminal.
"""

import errno
import os
import re
import stat
import sys
import unicodedata


BADGE_ROLE = "brand_badge"
ART_ROLE = "brand"
MAX_ART_BYTES = 4096
MAX_ART_LINES = 6
MAX_ART_CELLS = 64

# Required owner of the art file and of its directory; tests patch it.
_ROOT_UID = 0
_BADGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._+-]{0,23}")
_BLOCKS = {"█": "#", "▒": ":", "░": "."}
# Box drawing with a curses ACS equivalent, as logical console_render tokens.
_ACS_ART = dict(zip("─│┌┐└┘├┤┬┴┼█", (
    "BOX_H", "BOX_V", "BOX_UL", "BOX_UR", "BOX_LL", "BOX_LR",
    "BOX_LT", "BOX_RT", "BOX_TT", "BOX_BT", "BOX_X", "BAR_FULL")))


class _Rejected(Exception):
    """Reason why the art file is ignored as a whole."""


def _allowed(char):
    return " " <= char <= "~" or char in _BLOCKS or "─" <= char <= "╿"


def _ascii_box(char):
    name = unicodedata.name(char, "")
    if "DIAGONAL CROSS" in name:
        return "X"
    if "UPPER RIGHT TO LOWER LEFT" in name:
        return "/"
    if "UPPER LEFT TO LOWER RIGHT" in name:
        return "\\"
    words = set(name.split())
    horizontal = bool(words & {"HORIZONTAL", "LEFT", "RIGHT"})
    vertical = bool(words & {"VERTICAL", "UP", "DOWN"})
    if horizontal != vertical:
        return "-" if horizontal else "|"
    return "+"


_ASCII_ART = {**_BLOCKS, **{chr(code): _ascii_box(chr(code)) for code in range(0x2500, 0x2580)}}


def _warn(message):
    stream = sys.stderr
    if stream is None:
        return
    try:
        print(f"proxmenux-console: {message}", file=stream)
    except (OSError, ValueError):
        pass


def _shown(path):
    # ascii() escapes control characters, so the warning cannot carry escapes.
    return ascii(path)[:160] if isinstance(path, str) else type(path).__name__


def _valid_badge(text):
    if not isinstance(text, str):
        return None
    text = text.strip(" ")
    return text if _BADGE.fullmatch(text) else None


def _check_owner(info, what):
    if info.st_uid != _ROOT_UID:
        raise _Rejected(f"{what} not owned by root")
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise _Rejected(f"{what} writable by group or others")


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _open_directory(path):
    """Descriptor of directory ``path``, opened one component at a time from ``/``.

    ``O_NOFOLLOW`` only guards the last component of a path, so each one is
    opened relative to the descriptor of the previous one: no component of
    ``path`` can be a symlink, now or swapped in later. The stat() call only
    gives a clear reason; the descriptors decide.
    """
    fd = os.open("/", _DIR_FLAGS)
    try:
        for part in path.split("/"):
            if part in ("", "."):
                continue
            if stat.S_ISLNK(os.stat(part, dir_fd=fd, follow_symlinks=False).st_mode):
                raise _Rejected("is a symlink")
            child = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd


def _read_art(path):
    if not isinstance(path, str) or not os.path.isabs(path):
        raise _Rejected("path must be absolute")
    if "\0" in path:
        raise _Rejected("invalid path")
    parent, name = os.path.split(path)
    if not name:
        raise _Rejected("not a regular file")
    # Validate the directory, then open the file relative to that descriptor:
    # neither can be swapped for a symlink between the check and the read.
    dir_fd = _open_directory(parent)
    try:
        _check_owner(os.fstat(dir_fd), "directory")
        # FIFOs and devices are never opened; O_NONBLOCK covers a race.
        info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode):
            raise _Rejected("is a symlink")
        if not stat.S_ISREG(info.st_mode):
            raise _Rejected("not a regular file")
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NOCTTY
                     | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dir_fd)
    finally:
        os.close(dir_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise _Rejected("not a regular file")
        _check_owner(info, "file")
        if info.st_size > MAX_ART_BYTES:
            raise _Rejected(f"larger than {MAX_ART_BYTES} bytes")
        data = b""
        while len(data) <= MAX_ART_BYTES:
            chunk = os.read(fd, MAX_ART_BYTES + 1 - len(data))
            if not chunk:
                break
            data += chunk
        if len(data) > MAX_ART_BYTES:
            raise _Rejected(f"larger than {MAX_ART_BYTES} bytes")
        return data
    finally:
        os.close(fd)


def _parse_art(data):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise _Rejected("not valid UTF-8") from None
    lines = []
    for raw in text.splitlines(keepends=True):
        # Only \n and \r\n end a line; any other separator splitlines()
        # recognises (\v, \f, \x1c-\x1e, \x85, U+2028/9, a lone \r) stays in
        # the line and fails the whitelist below.
        if raw.endswith("\r\n"):
            raw = raw[:-2]
        elif raw.endswith("\n"):
            raw = raw[:-1]
        if not all(_allowed(char) for char in raw):
            raise _Rejected("characters other than ASCII, block and box drawing")
        lines.append(raw.rstrip(" "))
    while lines and not lines[-1]:
        lines.pop()
    if not lines:
        raise _Rejected("empty")
    if len(lines) > MAX_ART_LINES:
        raise _Rejected(f"more than {MAX_ART_LINES} lines")
    if max(len(line) for line in lines) > MAX_ART_CELLS:
        raise _Rejected(f"wider than {MAX_ART_CELLS} cells")
    return lines


def _load_art(path):
    if path is None or path == "":
        return []
    try:
        return _parse_art(_read_art(path))
    except _Rejected as error:
        reason = str(error)
    except OSError as error:
        reason = ("is a symlink" if error.errno == errno.ELOOP
                  else os.strerror(error.errno) if error.errno else "unreadable")
    except (ValueError, TypeError):
        reason = "invalid path"
    _warn(f"--brand-art ignored ({reason}): {_shown(path)}")
    return []


def load(text, art_path):
    """Validate the optional brand once; ``{"badge": str|None, "art": [str]}``.

    ``text`` must match ``[A-Za-z0-9][A-Za-z0-9 ._+-]{0,23}`` after trimming
    spaces. ``art_path`` must be an absolute path to a regular, root-owned
    file of at most 4 KiB, not writable by group or others, in a root-owned
    directory not writable by group or others (e.g. ``0644`` in ``0755``),
    with no symlink anywhere in the path, and at most 6 lines of 64 cells of
    ASCII, U+2588/2591/2592 and box drawing (U+2500-257F). Either input is
    rejected as a whole, never in part.
    """
    badge = None
    if text is not None and text != "":
        badge = _valid_badge(text)
        if badge is None:
            _warn("--brand ignored: use 1-24 characters from A-Z a-z 0-9 and"
                  " space . _ + -, starting with a letter or digit")
    return {"badge": badge, "art": _load_art(art_path)}


def _free(cell):
    char, role, attrs = cell
    return char == " " and "reverse" not in attrs and role not in ("selected", BADGE_ROLE)


def paint_badge(grid, y, right_x, badge):
    """Paint `` BADGE `` on row ``y`` so that its last cell is ``right_x - 1``.

    It needs the ``len(badge) + 4`` cells left of ``right_x`` to be free (the
    padded badge plus two blank cells before it); otherwise nothing changes,
    so whatever the caller painted first (the header status) always wins.
    Returns True when the badge was painted.
    """
    badge = _valid_badge(badge)
    if badge is None or not 0 <= y < grid.height:
        return False
    right_x = min(right_x, grid.width)
    start = right_x - len(badge) - 4
    if start < 0 or not all(_free(grid[y][x]) for x in range(start, right_x)):
        return False
    for offset, char in enumerate(f" {badge} ", right_x - len(badge) - 2):
        grid[y][offset] = (char, BADGE_ROLE, ("bold", "reverse"))
    return True


def _valid_art(art):
    if not isinstance(art, (list, tuple)) or not art or len(art) > MAX_ART_LINES:
        return None
    for line in art:
        if (not isinstance(line, str) or len(line) > MAX_ART_CELLS
                or not all(_allowed(char) for char in line)):
            return None
    return art if any(line.strip(" ") for line in art) else None


def _art_glyph(char, glyphs):
    if glyphs == "unicode":
        return char
    if glyphs == "acs" and char in _ACS_ART:
        return _ACS_ART[char]
    return _ASCII_ART.get(char, char)


def paint_art(grid, x, y, w, h, art):
    """Centre ``art`` in the region ``(x, y, w, h)`` clipped to the grid.

    The art plus a one-cell margin must fit in the region and every cell of
    that margin box must be free; otherwise nothing changes. Spaces in the art
    are transparent. In ``acs`` mode block and light box glyphs become logical
    tokens; in ``acs`` and ``ascii`` modes the rest fall back to ASCII.
    Returns True when the art was painted.
    """
    art = _valid_art(art)
    if art is None:
        return False
    left, top = max(0, x), max(0, y)
    right, bottom = min(grid.width, x + w), min(grid.height, y + h)
    art_w, art_h = max(len(line) for line in art), len(art)
    if right - left < art_w + 2 or bottom - top < art_h + 2:
        return False
    ax = left + (right - left - art_w) // 2
    ay = top + (bottom - top - art_h) // 2
    if not all(_free(grid[row][col])
               for row in range(ay - 1, ay + art_h + 1)
               for col in range(ax - 1, ax + art_w + 1)):
        return False
    for dy, line in enumerate(art):
        for dx, char in enumerate(line):
            if char != " ":
                grid[ay + dy][ax + dx] = (_art_glyph(char, grid.glyphs), ART_ROLE, ("bold",))
    return True
