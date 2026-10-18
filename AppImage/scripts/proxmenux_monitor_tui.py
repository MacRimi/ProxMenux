#!/usr/bin/env python3
"""Native keyboard-only ProxMenux Monitor console view."""

import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import curses
except ImportError:  # report a clear error; packaging tests enforce this dependency
    curses = None

SNAPSHOT_PATH = "/run/proxmenux-monitor/console.json"
ESCAPE_RE = re.compile(r"\x1b|[\x00-\x1f\x7f-\x9f]")


def clean_text(value, limit=32):
    value = ESCAPE_RE.sub("?", str(value or ""))
    return value[:limit]


def cpu_busy_percent(current, previous):
    # Linux's guest and guest_nice counters are already included in user/nice.
    # Sum only the first eight columns to avoid counting them a second time.
    total = sum(current[:8]) - sum(previous[:8])
    idle = ((current[3] + current[4]) - (previous[3] + previous[4]))
    return round(100 * (total-idle) / total, 1) if total > 0 else 0.0


def is_host_network_interface(name, has_device, is_vlan):
    if name == "lo" or name.startswith(("vmbr", "br", "tap", "fwbr", "fwpr", "fwln", "veth", "docker", "virbr")):
        return False
    if is_vlan:
        return False
    return has_device or re.fullmatch(r"bond\d+", name) is not None


def sorted_guests(guests, field):
    return sorted(guests, key=lambda item: (item.get(field) is not None, item.get(field) or 0), reverse=True)


def read_snapshot(path=SNAPSHOT_PATH, now=None, max_age=45, max_future_skew=30):
    try:
        with open(path, encoding="utf-8") as stream:
            data = json.load(stream)
        if (not isinstance(data, dict) or data.get("schema_version") != 1 or
                data.get("publisher") != "proxmenux-monitor"):
            return None, "schema"
        cluster = data.get("cluster")
        nodes = cluster.get("nodes", []) if isinstance(cluster, dict) else None
        guests = data.get("guests", [])
        if (not isinstance(cluster, dict) or
                not all(field in cluster for field in ("enabled", "quorum", "nodes")) or
                not isinstance(cluster.get("enabled"), bool) or
                (cluster.get("quorum") is not None and not isinstance(cluster.get("quorum"), bool)) or
                not isinstance(nodes, list) or
                not isinstance(guests, list) or
                any(not isinstance(node, dict) for node in nodes) or
                any(not isinstance(guest, dict) for guest in guests)):
            return None, "schema"
        for node in nodes:
            if (not isinstance(node.get("name"), str) or
                    (node.get("online") is not None and not isinstance(node.get("online"), bool))):
                return None, "schema"
            for field in ("cpu", "maxcpu", "mem", "maxmem"):
                value = node.get(field)
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                    return None, "schema"
        for guest in guests:
            if (not all(field in guest for field in ("vmid", "name", "type", "node", "cpu", "mem", "maxmem")) or
                    any(not isinstance(guest.get(field), str) for field in ("vmid", "name", "type", "node"))):
                return None, "schema"
            for field in ("cpu", "mem", "maxmem"):
                value = guest.get(field)
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                    return None, "schema"
        stamp = datetime.fromisoformat(data["observed_at"].replace("Z", "+00:00"))
        raw_age = ((now or datetime.now(timezone.utc)) - stamp).total_seconds()
        if raw_age < -max_future_skew:
            return None, "future"
        age = max(0, int(raw_age))
        if age > max_age:
            return data, f"stale {age}s"
        return data, f"fresh {age}s"
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return None, "unavailable"


def cluster_configured():
    """Use the local PVE marker to distinguish offline cluster from standalone."""
    return os.path.isfile("/etc/pve/corosync.conf")


def format_bytes(value):
    if value is None:
        return "N/D"
    amount = float(value)
    for unit in ("B", "K", "M", "G", "T"):
        if amount < 1024 or unit == "T":
            return f"{amount:.1f}{unit}"
        amount /= 1024


class LocalSampler:
    """Collect only local kernel counters; no API calls or privileged commands."""
    def __init__(self):
        self.cpu_previous = None
        self.net_previous = None

    @staticmethod
    def _cpu_times():
        rows = {}
        try:
            with open("/proc/stat", encoding="ascii") as stream:
                for line in stream:
                    fields = line.split()
                    if not fields or not re.fullmatch(r"cpu\d*", fields[0]):
                        if rows:
                            break
                        continue
                    rows[fields[0]] = [int(x) for x in fields[1:]]
        except OSError:
            pass
        return rows

    def cpu(self):
        current = self._cpu_times()
        result = {}
        if self.cpu_previous:
            for name, values in current.items():
                old = self.cpu_previous.get(name)
                if not old:
                    continue
                result[name] = cpu_busy_percent(values, old)
        self.cpu_previous = current
        return result

    @staticmethod
    def memory():
        values = {}
        try:
            with open("/proc/meminfo", encoding="ascii") as stream:
                for line in stream:
                    key, _, rest = line.partition(":")
                    if key in ("MemTotal", "MemAvailable"):
                        values[key] = int(rest.split()[0]) * 1024
        except (OSError, ValueError, IndexError):
            pass
        return values

    @staticmethod
    def arc():
        values = {}
        try:
            with open("/proc/spl/kstat/zfs/arcstats", encoding="ascii") as stream:
                for line in stream:
                    fields = line.split()
                    if len(fields) >= 3 and fields[0] in ("size", "c", "c_max"):
                        values[fields[0]] = int(fields[2])
        except (OSError, ValueError):
            pass
        return values

    @staticmethod
    def zram():
        try:
            from zram_metrics import read_zram_metrics
            return read_zram_metrics()
        except Exception:
            return {"available": False, "devices": []}

    @staticmethod
    def storage():
        result = []
        virtual_prefixes = ("loop", "ram", "zram", "dm-", "md", "sr", "nbd", "fd", "zd")
        try:
            for name in sorted(os.listdir("/sys/block")):
                if name.startswith(virtual_prefixes) or os.path.exists(f"/sys/block/{name}/partition"):
                    continue
                size_path = f"/sys/block/{name}/size"
                try:
                    total = int(Path(size_path).read_text(encoding="ascii").strip()) * 512
                except (OSError, ValueError):
                    total = None
                if total is not None:
                    result.append({"name": name, "total": total})
        except OSError:
            pass
        try:
            stat = os.statvfs("/")
            total = stat.f_blocks * stat.f_frsize
            available = stat.f_bavail * stat.f_frsize
            result.append({"name": "/", "total": total, "used": total - available})
        except OSError:
            pass
        return result

    def network(self):
        counters = {}
        try:
            names = os.listdir("/sys/class/net")
        except OSError:
            names = []
        for name in names:
            base = f"/sys/class/net/{name}"
            has_device = os.path.exists(f"{base}/device")
            is_vlan = os.path.exists(f"/proc/net/vlan/{name}")
            if not is_host_network_interface(name, has_device, is_vlan):
                continue
            # A bond's counter replaces its physical slaves. Bridge slaves are
            # still the actual uplinks, so count the physical interface there.
            if os.path.exists(f"{base}/master") and os.path.basename(os.path.realpath(f"{base}/master")).startswith("bond"):
                continue
            try:
                rx = int(open(f"{base}/statistics/rx_bytes", encoding="ascii").read())
                tx = int(open(f"{base}/statistics/tx_bytes", encoding="ascii").read())
                counters[name] = (rx, tx)
            except (OSError, ValueError):
                continue
        now = time.monotonic()
        rates = {}
        if self.net_previous:
            elapsed = max(0.001, now - self.net_previous[0])
            for name, (rx, tx) in counters.items():
                old = self.net_previous[1].get(name)
                if old:
                    rates[name] = (max(0, rx-old[0])/elapsed, max(0, tx-old[1])/elapsed)
        self.net_previous = (now, counters)
        return rates

    def sample(self):
        try:
            load = os.getloadavg()
        except OSError:
            load = ()
        mem = self.memory()
        return {"cpu": self.cpu(), "load": load, "memory": mem, "arc": self.arc(),
                "zram": self.zram(), "storage": self.storage(), "network": self.network(),
                "snapshot": read_snapshot()}


def _put(stdscr, row, col, value, width, attr=0):
    if row < 0 or col < 0:
        return
    try:
        stdscr.addnstr(row, col, clean_text(value, width), width, attr)
    except curses.error:
        pass


def render(stdscr, sampler, mode="NODE"):
    height, width = stdscr.getmaxyx()
    stdscr.erase()
    if width < 80 or height < 24:
        _put(stdscr, 0, 0, "ProxMenux Monitor needs 80x24", width)
        stdscr.refresh()
        return
    data = sampler.sample()
    bold = curses.A_BOLD if curses else 0
    snap, freshness = data["snapshot"]
    cluster_present = bool(snap and snap.get("cluster", {}).get("enabled")) or cluster_configured()
    if not cluster_present:
        mode = "STANDALONE"
    display_mode = ("NODE" if cluster_present else "STANDALONE") if mode == "NODE" else mode
    _put(stdscr, 0, 0, f"PROXMENUX MONITOR  {display_mode}  {time.strftime('%H:%M:%S')}", width, bold)
    cpu = data["cpu"]
    total_cpu = f"{cpu['cpu']:4.1f}%" if cpu.get("cpu") is not None else " N/D "
    core_values = sorted(((k, v) for k, v in cpu.items() if k != "cpu"), key=lambda item: int(item[0][3:]))
    _put(stdscr, 1, 0, "Load " + " / ".join(f"{x:.2f}" for x in data["load"]), width)
    _put(stdscr, 2, 0, f"CPU total {total_cpu}", width)
    shown_cores = core_values[:16]
    if shown_cores:
        core_label = f"CPU{shown_cores[0][0][3:]}-{shown_cores[-1][0][3:]}"
        if len(core_values) > len(shown_cores):
            core_label += f" +{len(core_values)-len(shown_cores)}"
        core_text = " ".join(f"{value:3.0f}" for _, value in shown_cores)
        _put(stdscr, 3, 0, f"Cores {core_label} {core_text}", width)
    else:
        _put(stdscr, 3, 0, "Cores N/D", width)
    mem = data["memory"]
    total, available = mem.get("MemTotal"), mem.get("MemAvailable")
    used_ram = total - available if total is not None and available is not None else None
    _put(stdscr, 4, 0, f"RAM {format_bytes(used_ram)} / {format_bytes(total)}  avail {format_bytes(available)}", width)
    arc = data["arc"]
    _put(stdscr, 5, 0, f"ZFS ARC {format_bytes(arc.get('size'))} / {format_bytes(arc.get('c_max'))}", width)
    zram = data["zram"] if isinstance(data.get("zram"), dict) else {}
    devices = zram.get("devices", []) if isinstance(zram, dict) else []
    used = sum((d.get("swap_used_bytes") or 0) for d in devices if isinstance(d,dict))
    compressed = sum((d.get("compressed_bytes") or 0) for d in devices if isinstance(d,dict))
    original = sum((d.get("original_bytes") or 0) for d in devices if isinstance(d,dict))
    ratio = f"{original/compressed:.1f}x" if compressed and original else "N/D"
    _put(stdscr, 6, 0, f"ZRAM use {format_bytes(used) if zram.get('available') else 'N/D'} compressed {format_bytes(compressed) if zram.get('available') else 'N/D'} ({ratio})", width)
    storage = ", ".join(
        f"{x['name']} {format_bytes(x.get('used'))}/{format_bytes(x['total'])}"
        if x.get("used") is not None else f"{x['name']} {format_bytes(x['total'])}"
        for x in data["storage"]
    ) or "N/D"
    _put(stdscr, 7, 0, f"Storage {storage}", width)
    network = data["network"]
    rates = "  ".join(f"{name} rx {format_bytes(rx)}/s tx {format_bytes(tx)}/s" for name,(rx,tx) in sorted(network.items())) or "sampling/N/D"
    _put(stdscr, 8, 0, f"NET {rates}", width)
    guests = snap.get("guests", []) if snap and freshness.startswith("fresh") else []
    if mode == "CLUSTER" and snap and cluster_present:
        cluster = snap.get("cluster", {})
        quorum = cluster.get("quorum")
        state = "quorum" if quorum else ("no quorum" if quorum is False else "cluster N/D")
        _put(stdscr, 9, 0, f"CLUSTER {state}  remote {freshness}", width, bold)
        nodes = cluster.get("nodes", [])
        complete = bool(nodes) and all(
            n.get("online") is True and n.get("cpu") is not None
            and n.get("maxcpu") is not None and n.get("maxcpu") > 0
            and n.get("mem") is not None
            and n.get("maxmem") is not None and n.get("maxmem") > 0
            for n in nodes
        ) and cluster.get("complete") is True
        max_node_rows = max(1, height - 20)
        visible_nodes = nodes[:max_node_rows]
        for i, node in enumerate(visible_nodes):
            status = "UP" if node.get("online") is True else ("DOWN" if node.get("online") is False else "N/D")
            cpu = f"{node['cpu'] * 100:.0f}%" if node.get("cpu") is not None else "N/D"
            ram = f"{node['mem']/1024**3:.0f}/{node['maxmem']/1024**3:.0f}G" if node.get("mem") is not None and node.get("maxmem") else "N/D"
            storage_items = node.get("storage", [])
            if isinstance(storage_items, list) and storage_items:
                item = storage_items[0]
                storage = f"{clean_text(item.get('name'),8)} {format_bytes(item.get('used'))}/{format_bytes(item.get('total'))}"
                if len(storage_items) > 1:
                    storage += f" +{len(storage_items)-1}"
            else:
                storage = "N/D"
            zram_used = format_bytes(node.get("zram_used"))
            network = node.get("network") if isinstance(node.get("network"), dict) else None
            net = "N/D" if network is None else clean_text(network.get("summary") or "N/D", 10)
            summary = f"{clean_text(node.get('name'),16)} {status} C{cpu} R{ram} Z:{zram_used} S:{storage} N:{net}"
            _put(stdscr, 10 + i, 0, summary, width)
        cluster_rows = len(visible_nodes)
        if len(visible_nodes) < len(nodes):
            _put(stdscr, 10 + cluster_rows, 0, f"+ {len(nodes)-len(visible_nodes)} nodes not shown", width)
            cluster_rows += 1
        summary_end = 10 + cluster_rows
        if freshness.startswith("fresh") and quorum is True and complete:
            cpu_total = sum(n["cpu"] * n["maxcpu"] for n in nodes) / sum(n["maxcpu"] for n in nodes) * 100
            mem_used = sum(n["mem"] for n in nodes)
            mem_total = sum(n["maxmem"] for n in nodes)
            _put(stdscr, summary_end, 0, f"Cluster total CPU {cpu_total:.1f}% RAM {format_bytes(mem_used)}/{format_bytes(mem_total)}", width, bold)
        else:
            _put(stdscr, summary_end, 0, "Cluster totals withheld: samples incomplete, stale, or no quorum", width)
        list_top = min(summary_end + 2, height - 2)
    elif mode == "CLUSTER":
        label = "CLUSTER unavailable; local metrics remain live"
        _put(stdscr, 9, 0, label, width, bold)
        list_top = 11
    else:
        if cluster_present and snap:
            quorum = snap.get("cluster", {}).get("quorum")
            status = "no quorum" if quorum is False else ("quorum" if quorum is True else "cluster N/D")
            _put(stdscr, 9, 0, f"Local view  {status}  remote {freshness}", width, bold)
        elif cluster_present:
            _put(stdscr, 9, 0, "Local view  remote unavailable", width, bold)
        list_top = 11
    available_rows = max(0, height-list_top-1)
    guest_rows = max(0, available_rows-1)
    _put(stdscr, list_top, 0, "TOP CPU", min(width//2-1,width), bold)
    _put(stdscr, list_top, width//2, "TOP MEMORY", width-width//2, bold)
    by_cpu = sorted_guests(guests, "cpu")
    by_mem = sorted_guests(guests, "mem")
    if not guests:
        _put(stdscr, list_top+1, 0, "N/D", width//2-1)
        _put(stdscr, list_top+1, width//2, "N/D", width-width//2)
    for i in range(min(guest_rows, len(guests))):
        left = by_cpu[i]
        right = by_mem[i]
        prefix_l = f"{left['node']} " if cluster_present else ""
        prefix_r = f"{right['node']} " if cluster_present else ""
        cpu_pct = f"{left['cpu']*100:.1f}%" if left["cpu"] is not None else "N/D"
        _put(stdscr, list_top+1+i, 0, f"{prefix_l}{left['type']} {left['vmid']} {left['name']} {cpu_pct}", width//2-1, 0)
        _put(stdscr, list_top+1+i, width//2, f"{prefix_r}{right['type']} {right['vmid']} {right['name']} {format_bytes(right['mem']) if right['mem'] is not None else 'N/D'}", width-width//2, 0)
    _put(stdscr, height-1, 0, "n NODE/STANDALONE  c CLUSTER  q quit  Ctrl-C exit", width)
    stdscr.refresh()


def run(stdscr):
    curses.curs_set(0)
    # Read Ctrl-C as a keyboard byte inside the UI instead of letting the
    # AppImage runtime and its extracted child race to deliver SIGINT. The
    # curses wrapper restores the original tty modes when the loop returns.
    curses.raw()
    try:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_GREEN, -1)
    except curses.error:
        pass
    stdscr.nodelay(True)
    stdscr.timeout(1000)
    sampler = LocalSampler()
    mode = "NODE"
    while True:
        render(stdscr, sampler, mode)
        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 3):
            break
        if key in (ord("c"), ord("C")):
            mode = "CLUSTER" if mode != "CLUSTER" else "NODE"
        if key in (ord("n"), ord("N")):
            mode = "NODE"


def main():
    if curses is None:
        raise SystemExit("Python curses support is unavailable (install a compatible _curses runtime)")
    try:
        curses.setupterm(term=os.environ.get("TERM", "linux"))
    except curses.error as exc:
        raise SystemExit(f"Terminal capabilities unavailable for TERM={os.environ.get('TERM', 'linux')}: {exc}")
    try:
        curses.wrapper(run)
    except KeyboardInterrupt:
        # curses.wrapper restores termios in its finally block before the
        # interrupt reaches here; a clean return lets tty1 continue to getty.
        return


if __name__ == "__main__":
    main()
