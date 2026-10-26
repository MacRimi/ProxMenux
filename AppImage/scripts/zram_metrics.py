"""Read zram swap metrics from procfs and sysfs."""

import re
from pathlib import Path


def _swap_usage(swaps_path):
    usage = {}
    try:
        lines = Path(swaps_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return usage

    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 4:
            continue
        name = Path(fields[0]).name
        if not re.fullmatch(r"zram\d+", name):
            continue
        try:
            usage[name] = int(fields[3]) * 1024
        except ValueError:
            continue
    return usage


def read_zram_metrics(sys_block_root="/sys/block", swaps_path="/proc/swaps"):
    """Return zram device counters with byte units and active swap usage."""
    root = Path(sys_block_root)
    try:
        device_paths = sorted(
            path for path in root.iterdir()
            if path.is_dir() and re.fullmatch(r"zram\d+", path.name)
        )
    except OSError:
        device_paths = []

    swap_usage = _swap_usage(swaps_path)
    devices = []
    for path in device_paths:
        try:
            capacity = int((path / "disksize").read_text(encoding="utf-8").strip())
            counters = (path / "mm_stat").read_text(encoding="utf-8").split()
            if len(counters) < 3:
                continue
            original, compressed, memory_used = map(int, counters[:3])
            if min(capacity, original, compressed, memory_used) < 0:
                continue
            algorithms = (path / "comp_algorithm").read_text(encoding="utf-8")
        except (OSError, ValueError):
            continue

        selected = re.search(r"\[([^\]]+)\]", algorithms)
        devices.append({
            "name": path.name,
            "active": path.name in swap_usage,
            "capacity_bytes": capacity,
            "swap_used_bytes": swap_usage.get(path.name, 0),
            "original_bytes": original,
            "compressed_bytes": compressed,
            "memory_used_bytes": memory_used,
            "algorithm": selected.group(1) if selected else None,
            "compression_ratio": original / compressed if compressed else None,
            "saved_bytes": original - memory_used,
        })

    return {"available": bool(devices), "devices": devices}
