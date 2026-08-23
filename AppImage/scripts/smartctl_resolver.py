#!/usr/bin/env python3

import json
import os
import subprocess
from typing import Any, Iterable, Optional


USB_NVME_DRIVERS = ("sntasmedia", "sntjmicron", "sntrealtek")
USB_SATA_DRIVERS = ("sat", "sat,12", "sat,16")

_probe_cache: dict[str, tuple[tuple[Any, ...], str]] = {}


def disk_name(device: str) -> str:
    return os.path.basename(device.rstrip("/"))


def disk_fingerprint(device: str) -> tuple[Any, ...]:
    name = disk_name(device)
    dev_path = f"/dev/{name}"
    try:
        stat = os.stat(dev_path)
        return (os.path.realpath(f"/sys/block/{name}"), stat.st_rdev, stat.st_ctime_ns)
    except OSError:
        return (os.path.realpath(f"/sys/block/{name}"),)


def is_usb_disk(device: str) -> bool:
    try:
        real_path = os.path.realpath(f"/sys/block/{disk_name(device)}")
        return any(
            segment.startswith("usb")
            and (len(segment) == 3 or segment[3:].isdigit())
            for segment in real_path.split("/")
        )
    except OSError:
        return False


def smartctl_probe_types(device: str) -> tuple[str, ...]:
    name = disk_name(device)
    if is_usb_disk(name):
        if name.startswith("nvme"):
            return USB_NVME_DRIVERS + ("auto", "nvme")
        return USB_SATA_DRIVERS + ("auto", "scsi", "ata")
    if name.startswith("nvme"):
        return ("auto", "nvme")
    return ("auto", "scsi", "ata", "sat", "sat,12", "sat,16")


def smartctl_type_args(probe: Optional[str]) -> list[str]:
    if not probe or probe == "auto":
        return []
    return ["-d", probe]


def smartctl_command(device: str, options: Iterable[str], probe: Optional[str]) -> list[str]:
    path = device if device.startswith("/dev/") else f"/dev/{disk_name(device)}"
    return ["smartctl", *options, *smartctl_type_args(probe), path]


def smartctl_result_is_standby(returncode: int, stdout: str = "", stderr: str = "") -> bool:
    """Distinguish a real low-power response from another exit-code-2 error."""
    if returncode != 2:
        return False
    message = f"{stdout}\n{stderr}".lower()
    return any(
        marker in message
        for marker in ("standby", "sleep mode", "low-power mode", "low power mode")
    )


def smart_json_has_telemetry(data: dict[str, Any]) -> bool:
    ata_attributes = data.get("ata_smart_attributes", {}).get("table", [])
    return bool(
        ata_attributes
        or data.get("nvme_smart_health_information_log")
        or data.get("scsi_error_counter_log")
        or "scsi_grown_defect_list" in data
        or data.get("ata_smart_data")
        or data.get("temperature", {}).get("current") is not None
        or data.get("power_on_time")
        or data.get("power_cycle_count") is not None
    )


def _smart_json_score(data: dict[str, Any]) -> int:
    score = 100 if smart_json_has_telemetry(data) else 0
    score += 12 if data.get("temperature", {}).get("current") is not None else 0
    score += 8 if data.get("power_on_time") else 0
    score += 5 if data.get("model_name") or data.get("model_family") else 0
    score += 5 if data.get("serial_number") else 0
    score += 2 if data.get("smart_status", {}).get("passed") is not None else 0
    return score


def probe_smartctl_json(
    device: str,
    options: Iterable[str],
    *,
    timeout: int = 5,
    require_telemetry: bool = True,
) -> dict[str, Any]:
    name = disk_name(device)
    fingerprint = disk_fingerprint(name)
    probes = list(smartctl_probe_types(name))
    cached = _probe_cache.get(name)
    if cached and cached[0] == fingerprint and cached[1] in probes:
        probes.remove(cached[1])
        probes.insert(0, cached[1])

    best: dict[str, Any] = {
        "data": {},
        "probe": None,
        "command": [],
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "standby": False,
    }
    best_score = -1

    for probe in probes:
        command = smartctl_command(name, options, probe)
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError):
            continue

        if "-n" in command and smartctl_result_is_standby(
            proc.returncode,
            proc.stdout,
            proc.stderr,
        ):
            return {
                "data": {},
                "probe": probe,
                "command": command,
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "standby": True,
            }

        try:
            data = json.loads(proc.stdout) if proc.stdout else {}
        except (TypeError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict) or not data:
            continue

        score = _smart_json_score(data)
        candidate = {
            "data": data,
            "probe": probe,
            "command": command,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "standby": False,
        }
        if score > best_score:
            best = candidate
            best_score = score

        identity = bool(data.get("model_name") or data.get("model_family") or data.get("serial_number"))
        status = data.get("smart_status", {}).get("passed") is not None
        complete = smart_json_has_telemetry(data) if require_telemetry else (identity or status)
        if complete:
            _probe_cache[name] = (fingerprint, probe)
            return candidate

    return best


def resolve_smartctl_probe(device: str, timeout: int = 5) -> Optional[str]:
    name = disk_name(device)
    cached = _probe_cache.get(name)
    fingerprint = disk_fingerprint(name)
    if cached and cached[0] == fingerprint:
        return cached[1]
    result = probe_smartctl_json(
        name,
        ("-i", "-j"),
        timeout=timeout,
        require_telemetry=False,
    )
    return result.get("probe")


def clear_smartctl_probe(device: Optional[str] = None) -> None:
    if device is None:
        _probe_cache.clear()
    else:
        _probe_cache.pop(disk_name(device), None)
