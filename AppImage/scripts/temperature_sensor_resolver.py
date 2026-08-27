#!/usr/bin/env python3

import os
import re
import time
from pathlib import Path


_TOPOLOGY_CACHE = {
    "key": None,
    "time": 0.0,
    "entries": [],
}
_TOPOLOGY_CACHE_TTL = 60


def _read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except (OSError, ValueError):
        return ""


def _read_temperature(path):
    value = _read_text(path)
    if not value:
        return 0.0
    try:
        return float(value) / 1000.0
    except ValueError:
        return 0.0


def _related_path_distance(first, second):
    first_parts = Path(first).parts
    second_parts = Path(second).parts
    common = 0
    for first_part, second_part in zip(first_parts, second_parts):
        if first_part != second_part:
            break
        common += 1
    if common == min(len(first_parts), len(second_parts)):
        return (len(first_parts) - common) + (len(second_parts) - common)
    return None


def _block_devices_for_hwmon(hwmon_device, block_root):
    exact = []
    related = []
    try:
        block_entries = sorted(Path(block_root).iterdir(), key=lambda item: item.name)
    except OSError:
        return []

    hwmon_real = os.path.realpath(hwmon_device)
    for block_entry in block_entries:
        block_device = block_entry / "device"
        if not block_device.exists():
            continue
        block_real = os.path.realpath(block_device)
        if block_real == hwmon_real:
            exact.append(block_entry.name)
            continue
        distance = _related_path_distance(hwmon_real, block_real)
        if distance is not None:
            related.append((distance, block_entry.name))

    if exact:
        return exact
    if not related:
        return []

    minimum_distance = min(distance for distance, _ in related)
    return [name for distance, name in related if distance == minimum_distance]


def _device_metadata(device_name, hwmon_kind, block_root):
    block_path = Path(block_root) / device_name
    rotational = _read_text(block_path / "queue" / "rotational")
    if hwmon_kind == "nvme":
        sensor_type = "nvme"
    elif rotational == "1":
        sensor_type = "hdd"
    elif rotational == "0":
        sensor_type = "ssd"
    else:
        sensor_type = "storage"

    return {
        "type": sensor_type,
        "model": _read_text(block_path / "device" / "model"),
        "serial": _read_text(block_path / "device" / "serial"),
    }


def _build_topology(hwmon_root, block_root):
    entries = []
    try:
        hwmon_entries = sorted(Path(hwmon_root).glob("hwmon*"), key=lambda item: item.name)
    except OSError:
        return entries

    for hwmon_path in hwmon_entries:
        hwmon_kind = _read_text(hwmon_path / "name").lower()
        if hwmon_kind not in {"nvme", "drivetemp"}:
            continue

        devices = _block_devices_for_hwmon(hwmon_path / "device", block_root)
        device = devices[0] if devices else ""
        metadata = _device_metadata(device, hwmon_kind, block_root) if device else {
            "type": "nvme" if hwmon_kind == "nvme" else "storage",
            "model": "",
            "serial": "",
        }
        entries.append({
            "hwmon_path": str(hwmon_path),
            "kind": hwmon_kind,
            "device": device,
            "devices": devices,
            **metadata,
        })
    return entries


def _get_topology(hwmon_root, block_root, cache_ttl):
    cache_key = (os.path.realpath(hwmon_root), os.path.realpath(block_root))
    now = time.monotonic()
    if (
        _TOPOLOGY_CACHE["key"] == cache_key
        and now - _TOPOLOGY_CACHE["time"] < cache_ttl
    ):
        return _TOPOLOGY_CACHE["entries"]

    entries = _build_topology(hwmon_root, block_root)
    _TOPOLOGY_CACHE.update({
        "key": cache_key,
        "time": now,
        "entries": entries,
    })
    return entries


def clear_temperature_topology_cache():
    _TOPOLOGY_CACHE.update({"key": None, "time": 0.0, "entries": []})


def _temperature_inputs(entry):
    hwmon_path = Path(entry["hwmon_path"])
    inputs = sorted(hwmon_path.glob("temp*_input"), key=lambda item: item.name)
    if entry["kind"] == "drivetemp":
        preferred = [item for item in inputs if item.name == "temp1_input"]
        return preferred or inputs[:1]

    selected = []
    for input_path in inputs:
        match = re.fullmatch(r"temp(\d+)_input", input_path.name)
        if not match:
            continue
        index = match.group(1)
        label = _read_text(hwmon_path / f"temp{index}_label")
        if label.lower() == "composite" or (not label and index == "1"):
            selected.append(input_path)
    return selected


def get_storage_temperatures(
    hwmon_root="/sys/class/hwmon",
    block_root="/sys/block",
    cache_ttl=_TOPOLOGY_CACHE_TTL,
):
    temperatures = []
    expected_by_kind = {}
    resolved_by_kind = {}

    for entry in _get_topology(hwmon_root, block_root, cache_ttl):
        inputs = _temperature_inputs(entry)
        if not inputs:
            continue
        expected_by_kind[entry["kind"]] = expected_by_kind.get(entry["kind"], 0) + 1

        input_path = inputs[0]
        match = re.fullmatch(r"temp(\d+)_input", input_path.name)
        if not match:
            continue
        index = match.group(1)
        current = _read_temperature(input_path)
        if current == 0.0 and not _read_text(input_path):
            # Sensor present but no readable temperature (e.g. an NVMe in
            # low power state that leaves temp1_input empty). Mark the
            # kind as covered anyway so the lm-sensors fallback does not
            # add a duplicate entry for the same hwmon device.
            resolved_by_kind[entry["kind"]] = resolved_by_kind.get(entry["kind"], 0) + 1
            continue

        sensor_type = entry["type"]
        if sensor_type == "nvme":
            name = "NVMe SSD"
            adapter = "PCI adapter"
        elif sensor_type == "hdd":
            name = "HDD"
            adapter = "SCSI adapter"
        elif sensor_type == "ssd":
            name = "SSD"
            adapter = "SCSI adapter"
        else:
            name = "Storage device"
            adapter = "SCSI adapter"

        label = _read_text(Path(entry["hwmon_path"]) / f"temp{index}_label")
        temperatures.append({
            "name": name,
            "original_name": label or f"temp{index}",
            "current": current,
            "high": _read_temperature(Path(entry["hwmon_path"]) / f"temp{index}_max"),
            "critical": _read_temperature(Path(entry["hwmon_path"]) / f"temp{index}_crit"),
            "adapter": adapter,
            "type": sensor_type,
            "device": entry["device"],
            "devices": entry["devices"],
            "model": entry["model"],
            "serial": entry["serial"],
        })
        resolved_by_kind[entry["kind"]] = resolved_by_kind.get(entry["kind"], 0) + 1

    covered_kinds = {
        kind
        for kind, expected in expected_by_kind.items()
        if resolved_by_kind.get(kind, 0) == expected
    }
    temperatures.sort(key=lambda item: (item["type"], item["device"], item["name"]))
    return temperatures, covered_kinds
