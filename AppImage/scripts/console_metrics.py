"""Read local console metrics from procfs and sysfs."""

import os
from collections import deque
from pathlib import Path

from zram_metrics import read_zram_metrics


def _read_text(path):
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _children(path):
    try:
        return sorted(path.iterdir())
    except OSError:
        return []


def _cpu_counters(root):
    counters = {}
    for line in _read_text(root / "proc/stat").splitlines():
        fields = line.split()
        if not fields or not fields[0].startswith("cpu"):
            continue
        try:
            values = [int(value) for value in fields[1:9]]
        except ValueError:
            continue
        if len(values) < 4:
            continue
        # Guest time is already included in user/nice; do not add it again.
        counters[fields[0]] = (sum(values), values[3] + (values[4] if len(values) > 4 else 0))
    return counters


def _cpu_fraction(previous, current):
    if previous is None or current is None:
        return None
    total = current[0] - previous[0]
    idle = current[1] - previous[1]
    if total <= 0 or idle < 0 or idle > total:
        return None
    return max(0.0, min(1.0, (total - idle) / total))


def _memory(root):
    values = {}
    for line in _read_text(root / "proc/meminfo").splitlines():
        name, separator, remainder = line.partition(":")
        if not separator:
            continue
        try:
            values[name] = int(remainder.split()[0]) * 1024
        except (IndexError, ValueError):
            continue

    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", values.get("MemFree", 0))
    arc = 0
    for line in _read_text(root / "proc/spl/kstat/zfs/arcstats").splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0] == "size":
            try:
                arc = max(0, int(fields[2]))
            except ValueError:
                pass
            break
    # MemAvailable already accounts for reclaimable memory. ARC remains
    # inside used so the renderer can show it separately and host_other can
    # subtract it exactly once.
    return {
        "total": total,
        "used": max(0, total - available),
        "available": available,
        "cached": values.get("Cached", 0) + values.get("SReclaimable", 0),
        "arc": arc,
        "swap_used": max(0, values.get("SwapTotal", 0) - values.get("SwapFree", 0)),
        "swap_total": values.get("SwapTotal", 0),
    }


def _temperature(root):
    sensors = []
    for hwmon in _children(root / "sys/class/hwmon"):
        name = _read_text(hwmon / "name").strip()
        priority = {"k10temp": 0, "coretemp": 1}.get(name, 2)
        for input_path in hwmon.glob("temp*_input"):
            try:
                temp = int(_read_text(input_path).strip()) / 1000
            except ValueError:
                continue
            if not -40 <= temp <= 150:
                continue
            label = _read_text(input_path.with_name(input_path.name.replace("_input", "_label"))).strip()
            label_priority = 0 if label.lower() in ("tdie", "package id 0") else 1
            sensors.append((priority, label_priority, hwmon.name, input_path.name, temp))
    if sensors:
        return min(sensors)[-1]
    for zone in _children(root / "sys/class/thermal"):
        if not zone.name.startswith("thermal_zone"):
            continue
        try:
            temp = int(_read_text(zone / "temp").strip()) / 1000
        except ValueError:
            continue
        if -40 <= temp <= 150:
            return temp
    return None


def _network(root):
    counters = {}
    ignored = ("vmbr", "fwbr", "fwpr", "fwln", "tap", "veth", "bond")
    for line in _read_text(root / "proc/net/dev").splitlines()[2:]:
        name, separator, data = line.partition(":")
        if not separator:
            continue
        name = name.strip()
        if name == "lo" or name.startswith(ignored):
            continue
        device = root / "sys/class/net" / name
        if not (device / "device").exists():
            continue
        try:
            fields = [int(field) for field in data.split()]
        except ValueError:
            continue
        if len(fields) >= 9:
            counters[name] = (fields[0], fields[8])
    return counters


def _disk(root):
    counters = {}
    for line in _read_text(root / "proc/diskstats").splitlines():
        fields = line.split()
        if len(fields) < 10:
            continue
        name = fields[2]
        # /sys/block contains whole devices; a device/ link excludes virtual
        # block devices (loop, dm, md, zram) that can double count IO.
        if not (root / "sys/block" / name / "device").exists():
            continue
        try:
            counters[name] = (int(fields[5]) * 512, int(fields[9]) * 512)
        except ValueError:
            continue
    return counters


def _rates(previous, current, dt):
    if previous is None or dt <= 0:
        return 0, 0
    first = second = 0
    for name, values in current.items():
        old = previous.get(name)
        if old is None:
            continue
        if values[0] >= old[0]:
            first += values[0] - old[0]
        if values[1] >= old[1]:
            second += values[1] - old[1]
    return first / dt, second / dt


def _speed(root, nic):
    if nic is None:
        return None
    try:
        value = int(_read_text(root / "sys/class/net" / nic / "speed").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def _zram(root):
    metrics = read_zram_metrics(root / "sys/block", root / "proc/swaps")
    if not metrics["available"]:
        return None
    devices = metrics["devices"]
    original = sum(device["original_bytes"] for device in devices)
    compressed = sum(device["compressed_bytes"] for device in devices)
    return {
        "devices": devices,
        "capacity_bytes": sum(device["capacity_bytes"] for device in devices),
        "swap_used_bytes": sum(device["swap_used_bytes"] for device in devices),
        "compression_ratio": original / compressed if compressed else None,
    }


class LocalSampler:
    """Keep counter baselines while sampling an injectable proc/sys root."""

    def __init__(self, proc_root="/", storage_paths=None, statvfs=None):
        self.root = Path(proc_root)
        self.storage_paths = [("root", "/")] if storage_paths is None else storage_paths
        self.statvfs = os.statvfs if statvfs is None else statvfs
        self.previous_time = None
        self.previous_cpu = None
        self.previous_net = None
        self.previous_disk = None
        self.history = {name: deque(maxlen=600) for name in (
            "rx", "tx", "read", "write", "cpu_total", "mem_used")}

    @property
    def cpu_history(self):
        """Keep the existing renderer's 60 valid CPU values available."""
        return [value for value in self.history["cpu_total"] if value is not None][-60:]

    def window(self, series, seconds, columns):
        """Return oldest-to-newest column maxima, leaving unknown time empty."""
        if seconds <= 0 or columns <= 0:
            raise ValueError("seconds and columns must be positive")
        samples = list(self.history[series])[-seconds:]
        samples = [None] * (seconds - len(samples)) + samples
        values = []
        for column in range(columns):
            start = column * seconds // columns
            end = max(start + 1, (column + 1) * seconds // columns)
            present = [value for value in samples[start:end] if value is not None]
            values.append(max(present) if present else None)
        return values

    def stats(self, series, seconds):
        """Return the latest value and peak, plus the prior full-window mean."""
        if seconds <= 0:
            raise ValueError("seconds must be positive")
        samples = list(self.history[series])
        current = [value for value in samples[-seconds:] if value is not None]
        previous = samples[-2 * seconds:-seconds]
        return {
            "now": samples[-1] if samples else None,
            "prev": (sum(previous) / seconds if len(previous) == seconds and
                     all(value is not None for value in previous) else None),
            "peak": max(current) if current else None,
        }

    def _storages(self):
        storages = []
        for name, path in self.storage_paths:
            rooted = self.root / str(path).lstrip("/")
            try:
                status = self.statvfs(str(rooted))
            except OSError:
                continue
            total = status.f_blocks * status.f_frsize
            storages.append({
                "storage": name,
                "total": total,
                "used": max(0, total - status.f_bfree * status.f_frsize),
                "available": status.f_bavail * status.f_frsize,
            })
        return storages

    def sample(self, now):
        try:
            uptime = max(0.0, float(_read_text(self.root / "proc/uptime").split()[0]))
        except (ValueError, IndexError):
            uptime = 0.0
        cpu = _cpu_counters(self.root)
        net = _network(self.root)
        disk = _disk(self.root)
        dt = now - self.previous_time if self.previous_time is not None else 0
        cpu_total = _cpu_fraction(self.previous_cpu.get("cpu") if self.previous_cpu else None,
                                  cpu.get("cpu")) if dt > 0 else None
        per_core = [
            (_cpu_fraction(self.previous_cpu.get(name) if self.previous_cpu else None, cpu[name])
             or 0) if dt > 0 else 0
            for name in sorted((name for name in cpu if name != "cpu"),
                               key=lambda name: int(name[3:]) if name[3:].isdigit() else name)
        ]
        rx_bps, tx_bps = _rates(self.previous_net, net, dt)
        read_bps, write_bps = _rates(self.previous_disk, disk, dt)
        nic = next((name for name in sorted(net)
                    if _read_text(self.root / "sys/class/net" / name / "operstate").strip() == "up"),
                   next(iter(sorted(net)), None))
        loads = _read_text(self.root / "proc/loadavg").split()
        try:
            load1, load5, load15 = map(float, loads[:3])
        except ValueError:
            load1 = load5 = load15 = 0.0
        if len(loads) < 3:
            load1 = load5 = load15 = 0.0
        memory = _memory(self.root)
        if dt > 0:
            for name, value in (
                ("rx", rx_bps * 8), ("tx", tx_bps * 8),
                ("read", read_bps), ("write", write_bps),
                ("cpu_total", cpu_total),
                ("mem_used", min(1.0, memory["used"] / memory["total"])
                 if memory["total"] > 0 else None),
            ):
                self.history[name].append(value)
        result = {
            "uptime": uptime,
            "cpu_total": cpu_total,
            "cpu_history": list(self.cpu_history),
            "per_core": per_core,
            "load1": load1, "load5": load5, "load15": load15,
            "threads": len(per_core),
            "temp_c": _temperature(self.root),
            "mem": memory,
            "zram": _zram(self.root),
            "net": {"rx_bps": rx_bps, "tx_bps": tx_bps, "nic": nic,
                    "speed_mbps": _speed(self.root, nic)},
            "disk": {"read_bps": read_bps, "write_bps": write_bps},
            "storages_local": self._storages(),
        }
        if self.previous_time is None or dt > 0:
            self.previous_time = now
            self.previous_cpu = cpu
            self.previous_net = net
            self.previous_disk = disk
        return result


def host_other(local, guests, node, snapshot_fresh):
    """Return residual local CPU cores and bytes outside guests."""
    if not snapshot_fresh:
        return {"cpu": None, "mem": None}
    local_guests = [guest for guest in guests if guest.get("node") == node]
    running = [guest for guest in local_guests if guest.get("status") == "running"]
    cpu = local.get("cpu_total")
    cpu_other = None if cpu is None else max(0.0, cpu * local.get("threads", 0) - sum(
        (guest.get("cpu") or 0) * (guest.get("maxcpu") or 0) for guest in running))
    memory = local.get("mem", {})
    mem_other = max(0, memory.get("used", 0) - memory.get("arc", 0) - sum(
        guest.get("mem") or 0 for guest in local_guests))
    return {"cpu": cpu_other, "mem": mem_other}
