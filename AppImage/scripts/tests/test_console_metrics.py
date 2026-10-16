"""Local console metrics from an injected proc/sys tree."""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from console_metrics import LocalSampler, host_other


FIXTURES = Path(__file__).parent / "fixtures" / "console"


class LocalSamplerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write("proc/loadavg", "0.25 0.50 0.75 1/100 1\n")
        self.write("proc/meminfo", (
            "MemTotal: 10000 kB\nMemFree: 1000 kB\nMemAvailable: 4000 kB\n"
            "Cached: 2000 kB\nSReclaimable: 500 kB\n"
            "SwapTotal: 3000 kB\nSwapFree: 2500 kB\n"
        ))
        self.write("proc/swaps", "Filename Type Size Used Priority\n")
        self.write("proc/stat", (FIXTURES / "proc_stat_1").read_text())
        self.write("proc/net/dev", (FIXTURES / "proc_net_1").read_text())
        self.write("proc/diskstats", (FIXTURES / "proc_disk_1").read_text())
        for nic in ("eno1", "eno2", "lo", "vmbr0", "bond0"):
            self.write(f"sys/class/net/{nic}/speed", "2500\n")
            self.write(f"sys/class/net/{nic}/operstate", "up\n")
            (self.root / "sys/class/net" / nic / "device").mkdir()
        for disk in ("sda", "nvme0n1"):
            (self.root / "sys/block" / disk / "device").mkdir(parents=True)

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def sampler(self, **kwargs):
        return LocalSampler(proc_root=self.root, storage_paths=[], **kwargs)

    def second_counters(self):
        for target, fixture in (("proc/stat", "proc_stat_2"),
                                ("proc/net/dev", "proc_net_2"),
                                ("proc/diskstats", "proc_disk_2")):
            self.write(target, (FIXTURES / fixture).read_text())

    def test_two_samples_give_exact_cpu_network_and_whole_disk_rates(self):
        sampler = self.sampler()
        first = sampler.sample(10.0)
        self.assertIsNone(first["cpu_total"])
        self.assertEqual(first["per_core"], [0, 0])
        self.assertEqual(first["cpu_history"], [])
        self.assertEqual(first["net"]["rx_bps"], 0)
        self.assertEqual(first["disk"]["read_bps"], 0)

        self.second_counters()
        second = sampler.sample(11.0)
        self.assertEqual(second["cpu_total"], 0.3)
        self.assertEqual(second["per_core"], [0.3, 0.3])
        self.assertEqual(second["cpu_history"], [0.3])
        self.assertEqual(second["threads"], 2)
        self.assertEqual((second["load1"], second["load5"], second["load15"]),
                         (0.25, 0.5, 0.75))
        self.assertEqual(second["net"], {
            "rx_bps": 1000, "tx_bps": 1000, "nic": "eno1", "speed_mbps": 2500,
        })
        self.assertEqual(second["disk"], {"read_bps": 4096, "write_bps": 6144})

    def test_only_physical_nics_with_device_are_counted(self):
        for nic in ("fwbr1", "fwpr1", "fwln1", "tap1", "veth1", "wlan0"):
            self.write(f"sys/class/net/{nic}/speed", "1000\n")
            (self.root / "sys/class/net" / nic / "device").mkdir()
        (self.root / "sys/class/net/eno2/device").rmdir()
        self.write("sys/class/net/eno1/operstate", "down\n")
        self.write("sys/class/net/wlan0/operstate", "up\n")
        self.write("proc/net/dev", (FIXTURES / "proc_net_1").read_text() +
                   "  fwbr1: 1 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0\n"
                   "  fwpr1: 1 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0\n"
                   "  fwln1: 1 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0\n"
                   "   tap1: 1 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0\n"
                   "  veth1: 1 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0\n"
                   "  wlan0: 10 0 0 0 0 0 0 0 20 0 0 0 0 0 0 0\n")
        sampler = self.sampler()
        sampler.sample(1.0)
        second = (self.root / "proc/net/dev").read_text()
        second = second.replace("wlan0: 10", "wlan0: 110").replace(
            "0 0 0 0 0 0 0 20", "0 0 0 0 0 0 0 220")
        second = second.replace("eno2: 3000", "eno2: 10000")
        for nic in ("fwbr1", "fwpr1", "fwln1", "tap1", "veth1"):
            second = second.replace(f"{nic}: 1", f"{nic}: 1001")
        self.write("proc/net/dev", second)
        result = sampler.sample(2.0)["net"]
        self.assertEqual(result["rx_bps"], 100)
        self.assertEqual(result["tx_bps"], 200)
        self.assertEqual(result["nic"], "wlan0")

    def test_mem_used_includes_arc_once_and_cached_is_separate(self):
        self.write("proc/spl/kstat/zfs/arcstats", "13 1 0x01 1 1 1\nname type data\nsize 4 1048576\n")
        result = self.sampler().sample(1.0)["mem"]
        self.assertEqual(result, {
            "total": 10240000, "used": 6144000, "available": 4096000,
            "cached": 2560000, "arc": 1048576,
            "swap_used": 512000, "swap_total": 3072000,
        })
        (self.root / "proc/spl/kstat/zfs/arcstats").unlink()
        without_arc = self.sampler().sample(1.0)["mem"]
        self.assertEqual(without_arc["arc"], 0)
        self.assertEqual(without_arc["used"], result["used"])

    def test_hwmon_priority_and_thermal_fallback(self):
        self.write("sys/class/hwmon/hwmon0/name", "other\n")
        self.write("sys/class/hwmon/hwmon0/temp1_input", "42000\n")
        self.write("sys/class/hwmon/hwmon1/name", "coretemp\n")
        self.write("sys/class/hwmon/hwmon1/temp1_input", "51000\n")
        self.write("sys/class/hwmon/hwmon2/name", "k10temp\n")
        self.write("sys/class/hwmon/hwmon2/temp1_input", "48000\n")
        self.write("sys/class/hwmon/hwmon2/temp1_label", "Tctl\n")
        self.write("sys/class/hwmon/hwmon2/temp2_input", "46000\n")
        self.write("sys/class/hwmon/hwmon2/temp2_label", "Tdie\n")
        self.assertEqual(self.sampler().sample(1.0)["temp_c"], 46.0)
        (self.root / "sys/class/hwmon/hwmon2/temp2_input").unlink()
        self.assertEqual(self.sampler().sample(1.0)["temp_c"], 48.0)
        (self.root / "sys/class/hwmon/hwmon2/temp1_input").unlink()
        self.assertEqual(self.sampler().sample(1.0)["temp_c"], 51.0)
        (self.root / "sys/class/hwmon/hwmon1/temp1_input").unlink()
        self.assertEqual(self.sampler().sample(1.0)["temp_c"], 42.0)
        (self.root / "sys/class/hwmon/hwmon0/temp1_input").unlink()
        self.write("sys/class/thermal/thermal_zone0/temp", "39000\n")
        self.assertEqual(self.sampler().sample(1.0)["temp_c"], 39.0)
        (self.root / "sys/class/thermal/thermal_zone0/temp").unlink()
        self.assertIsNone(self.sampler().sample(1.0)["temp_c"])

    def test_zram_uses_injected_paths(self):
        self.write("sys/block/zram0/disksize", "1073741824\n")
        self.write("sys/block/zram0/mm_stat", "2097152 1048576 1179648\n")
        self.write("sys/block/zram0/comp_algorithm", "lzo [zstd] lz4\n")
        self.write("proc/swaps", "Filename Type Size Used Priority\n/dev/zram0 partition 1048576 1024 100\n")
        zram = self.sampler().sample(1.0)["zram"]
        self.assertEqual(zram["devices"][0]["algorithm"], "zstd")
        self.assertEqual(zram["capacity_bytes"], 1073741824)
        self.assertEqual(zram["swap_used_bytes"], 1048576)
        self.assertEqual(zram["compression_ratio"], 2.0)
        (self.root / "sys/block/zram0/mm_stat").unlink()
        self.assertIsNone(self.sampler().sample(1.0)["zram"])

    def test_counter_decrease_resets_without_negative_rates(self):
        sampler = self.sampler()
        sampler.sample(1.0)
        self.write("proc/stat", "cpu 1 0 1 8 0 0 0 0 0 0\ncpu0 1 0 0 4 0 0 0 0 0 0\n")
        self.write("proc/net/dev", (FIXTURES / "proc_net_1").read_text().replace("eno1: 1000", "eno1: 1"))
        self.write("proc/diskstats", (FIXTURES / "proc_disk_1").read_text().replace("sda 0 0 100", "sda 0 0 1"))
        reset = sampler.sample(2.0)
        self.assertIsNone(reset["cpu_total"])
        self.assertEqual(reset["net"]["rx_bps"], 0)
        self.assertEqual(reset["disk"]["read_bps"], 0)
        self.second_counters()
        later = sampler.sample(3.0)
        self.assertIsNotNone(later["cpu_total"])
        self.assertGreaterEqual(later["net"]["rx_bps"], 0)
        self.assertGreaterEqual(later["disk"]["read_bps"], 0)

    def test_history_is_capped_at_sixty(self):
        sampler = self.sampler()
        sampler.sample(0.0)
        for index in range(1, 66):
            self.write("proc/stat", f"cpu {100 + index} 0 50 850 0 0 0 0 0 0\n")
            sample = sampler.sample(float(index))
        self.assertEqual(len(sample["cpu_history"]), 60)
        self.assertEqual(sample["cpu_history"][-1], 1.0)

    def test_statvfs_is_injectable(self):
        seen = []

        def fake_statvfs(path):
            seen.append(path)
            return SimpleNamespace(f_frsize=4096, f_blocks=100, f_bfree=40, f_bavail=30)

        sampler = LocalSampler(proc_root=self.root, storage_paths=[("local", "/")],
                               statvfs=fake_statvfs)
        self.assertEqual(sampler.sample(1.0)["storages_local"], [{
            "storage": "local", "total": 409600,
            "used": 245760, "available": 122880,
        }])
        self.assertEqual(seen, [str(self.root)])


class HostOtherTests(unittest.TestCase):
    def test_arithmetic_filters_local_running_guests(self):
        local = {"cpu_total": 0.5, "threads": 8, "mem": {"used": 10_000, "arc": 1000}}
        guests = [
            {"node": "p3-01", "status": "running", "cpu": 0.5, "maxcpu": 2, "mem": 3000},
            {"node": "p3-01", "status": "stopped", "cpu": 0.5, "maxcpu": 2, "mem": 2000},
            {"node": "p3-02", "status": "running", "cpu": 0.5, "maxcpu": 2, "mem": 4000},
        ]
        self.assertEqual(host_other(local, guests, "p3-01", snapshot_fresh=True),
                         {"cpu": 3.0, "mem": 4000})

    def test_clamps_and_omits_stale_snapshot(self):
        local = {"cpu_total": 0.1, "threads": 2, "mem": {"used": 1000, "arc": 500}}
        guests = [{"node": "p3-01", "status": "running", "cpu": 1, "maxcpu": 2, "mem": 2000}]
        self.assertEqual(host_other(local, guests, "p3-01", snapshot_fresh=True),
                         {"cpu": 0.0, "mem": 0})
        self.assertEqual(host_other(local, guests, "p3-01", snapshot_fresh=False),
                         {"cpu": None, "mem": None})


if __name__ == "__main__":
    unittest.main()
