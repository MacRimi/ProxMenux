"""
CPU and board facts for the Hardware page, on x86 and on ARM boards alike.

lscpu prints "-" for Socket(s) and other counters on ARM, so every number
is read tolerantly: a field that is not a number is left out instead of
dropping the whole CPU block. Boards without DMI tables (Raspberry Pi,
most SBCs) describe themselves through the device tree, which stands in
for dmidecode's baseboard section when that one comes back empty.
"""

import os
from typing import Any, Dict

_DEVICE_TREE = "/proc/device-tree"

_LSCPU_INT = {
    "CPU(s)": "total_threads",
    "Core(s) per socket": "cores_per_socket",
    "Socket(s)": "sockets",
}
_LSCPU_FLOAT = {
    "CPU MHz": "current_mhz",
    "CPU max MHz": "max_mhz",
    "CPU min MHz": "min_mhz",
}
_LSCPU_TEXT = {
    "Model name": "model",
    "Virtualization": "virtualization",
    "L1d cache": "l1d_cache",
    "L1i cache": "l1i_cache",
    "L2 cache": "l2_cache",
    "L3 cache": "l3_cache",
}


def parse_lscpu(output: str) -> Dict[str, Any]:
    """The CPU block from lscpu's text output. Fields lscpu does not know
    or prints as "-" are simply absent."""
    cpu: Dict[str, Any] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not value:
            continue
        if key in _LSCPU_TEXT:
            cpu.setdefault(_LSCPU_TEXT[key], value)
        elif key in _LSCPU_INT:
            number = _to_number(value, int)
            if number is not None:
                cpu[_LSCPU_INT[key]] = number
        elif key in _LSCPU_FLOAT:
            number = _to_number(value, float)
            if number is not None:
                cpu[_LSCPU_FLOAT[key]] = number
    return cpu


def read_device_tree_board(root: str = _DEVICE_TREE) -> Dict[str, str]:
    """Manufacturer, model and serial of a device-tree board, or an empty
    dict on machines that have no device tree (x86 with DMI)."""
    board: Dict[str, str] = {}
    model = _read_string(os.path.join(root, "model"))
    if model:
        board["model"] = model
    serial = _read_string(os.path.join(root, "serial-number"))
    if serial:
        board["serial"] = serial
    compatible = _read_string(os.path.join(root, "compatible"))
    if compatible:
        # "raspberrypi,5-model-b" -> the vendor prefix
        vendor = compatible.split(",", 1)[0].strip()
        if vendor:
            board["manufacturer"] = vendor
    return board


def _to_number(value: str, cast):
    try:
        return cast(value)
    except (TypeError, ValueError):
        return None


def _read_string(path: str) -> str:
    """Device-tree strings are NUL-terminated, sometimes NUL-separated lists;
    the first entry is returned."""
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return ""
    return raw.split(b"\x00", 1)[0].decode("utf-8", "ignore").strip()
