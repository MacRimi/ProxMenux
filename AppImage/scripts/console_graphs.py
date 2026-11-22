"""Pure graph primitives for the console, using logical glyph tokens.

A graph is a matrix of ``(token, role)`` cells, top row first. ``token`` is
``BAR_FULL``, ``BAR_HALF``, ``BAR_THIN`` or ``None`` (an empty cell, whose
role is also ``None``). Each row holds three levels: a column is solid
``BAR_FULL`` cells topped by at most one cap cell, ``BAR_THIN`` for one level
or ``BAR_HALF`` for two. The renderer maps tokens through the tables below.
In ``ACS_TOKENS`` a value is either the name of a ``curses.ACS_*`` constant
or one literal printable character: ``BAR_THIN`` has no ACS glyph and is the
ASCII underscore in every mode.

A missing value (``None``, not finite, or negative) draws nothing; any other
value, zero included, draws at least ``BAR_THIN``. This module never imports
curses.
"""

import math


ACS_TOKENS = {
    "BAR_FULL": "ACS_BLOCK", "BAR_HALF": "ACS_CKBOARD", "BAR_THIN": "_",
}
UNICODE_TOKENS = {
    "BAR_FULL": "█", "BAR_HALF": "▒", "BAR_THIN": "_",
}
ASCII_TOKENS = {
    "BAR_FULL": "#", "BAR_HALF": ":", "BAR_THIN": "_",
}
GRAPH_ROLES = frozenset(("graph_in", "graph_out"))
WARN_AT = 0.70
CRIT_AT = 0.90
_NICE_STEPS = (1, 1.5, 2, 3, 4, 5, 6, 8)
_CAPS = (None, "BAR_THIN", "BAR_HALF")
_EMPTY = (None, None)


def _present(value):
    return value is not None and math.isfinite(value) and value >= 0


def threshold_role(fraction):
    """Role for a usage fraction: ok below 0.70, warn below 0.90, else crit."""
    if fraction >= CRIT_AT:
        return "crit"
    if fraction >= WARN_AT:
        return "warn"
    return "ok"


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


def graph(values, cols, rows, scale, inverted=False, colour="threshold"):
    """Draw one column per value, newest at the right, as ``[[(token, role)]]``.

    Only the newest ``cols`` values are drawn and fewer leave the left
    columns empty; callers resample first. A column fills ``value / scale``
    of ``rows * 3`` levels, rounded to the nearest level, and grows upwards,
    or downwards with ``inverted``. ``colour="threshold"`` gives each column
    the role of its own ``value / scale`` (``threshold_role``); any other
    string is a fixed role for every filled cell.
    """
    if scale <= 0:
        raise ValueError("scale must be positive")
    if not isinstance(colour, str) or not colour:
        raise ValueError("colour must be 'threshold' or a role name")
    result = [[_EMPTY] * max(cols, 0) for _ in range(rows)]
    if cols <= 0 or rows <= 0:
        return result
    samples = list(values)[-cols:]
    levels_max = rows * 3
    for column, value in enumerate(samples, cols - len(samples)):
        if not _present(value):
            continue
        fraction = value / scale
        role = threshold_role(fraction) if colour == "threshold" else colour
        levels = min(levels_max, max(1, math.floor(fraction * levels_max + 0.5)))
        full, cap = divmod(levels, 3)
        cells = [("BAR_FULL", role)] * full
        if cap:
            cells.append((_CAPS[cap], role))
        for depth, cell in enumerate(cells):
            result[depth if inverted else rows - 1 - depth][column] = cell
    return result


def sparkline(values, cols, scale, colour="threshold"):
    """One-row ``graph``."""
    return graph(values, cols, 1, scale, colour=colour)


def resample(values, cols):
    """Fit oldest-first ``values`` into at most ``cols`` columns.

    With more values than columns, each column is the maximum of
    ``ceil(len(values) / cols)`` consecutive values (bins anchored at the
    newest value, so only the oldest bin can be shorter), and ``None`` only
    when none of them is present: 60 points in 30 columns are 2 min/col.
    With fewer, each value repeats ``cols // len(values)`` times: 60 points
    in 120 columns are 1 min = 2 cols. The result can be shorter than
    ``cols``; ``graph`` right-aligns it. Missing values come back as ``None``.
    """
    samples = [value if _present(value) else None for value in values]
    if not samples or cols <= 0:
        return []
    if len(samples) <= cols:
        repeat = cols // len(samples)
        return [value for value in samples for _ in range(repeat)]
    width = math.ceil(len(samples) / cols)
    result = []
    for end in range(len(samples), 0, -width):
        present = [value for value in samples[max(0, end - width):end] if value is not None]
        result.append(max(present) if present else None)
    return result[::-1]


def align(series, step_s):
    """Align per-node series on absolute time, as ``{key: values}``.

    ``series`` maps a key to ``(t_end, values)``: ``values`` are oldest
    first, one per ``step_s`` seconds, and ``t_end`` is the time of the last
    one. The newest ``t_end`` is "now"; a series ending ``k`` steps earlier
    drops its ``k`` oldest values and gains ``k`` ``None`` at the right, so
    the same index is the same minute in every result and each keeps its
    length. A series without ``t_end`` cannot be placed and is all ``None``.
    """
    if step_s <= 0:
        raise ValueError("step_s must be positive")
    ends = [t_end for t_end, _values in series.values() if t_end is not None]
    now = max(ends) if ends else None
    aligned = {}
    for key, (t_end, values) in series.items():
        values = list(values)
        lag = len(values) if t_end is None else round((now - t_end) / step_s)
        lag = min(len(values), max(0, lag))
        aligned[key] = values[lag:] + [None] * lag
    return aligned
