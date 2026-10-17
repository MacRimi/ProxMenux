"""Pure rate graph primitives using logical terminal glyph tokens."""

import math


ACS_TOKENS = {
    "BAR_LOW": "ACS_BOARD",
    "BAR_MID": "ACS_CKBOARD",
    "BAR_FULL": "ACS_BLOCK",
}
UNICODE_TOKENS = {
    "BAR_LOW": "░", "BAR_MID": "▒", "BAR_FULL": "█",
}
ASCII_TOKENS = {
    "BAR_LOW": ".", "BAR_MID": ":", "BAR_FULL": "#",
}
GRAPH_ROLES = frozenset(("graph_in", "graph_out"))
_NICE_STEPS = (1, 1.5, 2, 3, 4, 5, 6, 8)
_LEVELS = ("BAR_LOW", "BAR_MID", "BAR_FULL")


def nice_scale(peak, minimum):
    """Round up to a nice scale, with ``minimum`` in the caller's unit."""
    target = max(peak, minimum)
    if target <= 0:
        return 1
    magnitude = 10 ** math.floor(math.log10(target))
    for step in _NICE_STEPS:
        candidate = step * magnitude
        if candidate >= target:
            return candidate
    return 10 * magnitude


def graph(values, cols, rows, scale, inverted=False):
    """Render newest samples at the right, with three levels per cell."""
    if scale <= 0:
        raise ValueError("scale must be positive")
    result = [[" " for _ in range(cols)] for _ in range(rows)]
    samples = list(values)[-cols:] if cols > 0 else []
    start = cols - len(samples)
    for column, value in enumerate(samples, start):
        if value is None or value <= 0:
            continue
        filled = min(rows * 3, max(1, math.ceil(value / scale * rows * 3)))
        for level in range(filled):
            row = level // 3 if inverted else rows - 1 - level // 3
            result[row][column] = _LEVELS[level % 3]
    return result


def sparkline(values, cols, scale):
    """Render one row of the same rate glyphs."""
    return graph(values, cols, 1, scale)
