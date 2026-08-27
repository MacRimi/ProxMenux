import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from temperature_sensor_resolver import (  # noqa: E402
    clear_temperature_topology_cache,
    get_storage_temperatures,
)


class TemperatureSensorResolverTests(unittest.TestCase):
    def setUp(self):
        clear_temperature_topology_cache()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.hwmon_root = self.root / "sys" / "class" / "hwmon"
        self.block_root = self.root / "sys" / "block"
        self.devices_root = self.root / "sys" / "devices"
        self.hwmon_root.mkdir(parents=True)
        self.block_root.mkdir(parents=True)
        self.devices_root.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def _add_sensor(self, hwmon_index, kind, device_path, values):
        hwmon_path = self.hwmon_root / f"hwmon{hwmon_index}"
        hwmon_path.mkdir()
        (hwmon_path / "name").write_text(kind, encoding="utf-8")
        (hwmon_path / "device").symlink_to(device_path)
        for filename, value in values.items():
            (hwmon_path / filename).write_text(str(value), encoding="utf-8")

    def _add_block_device(self, name, device_path, rotational, model, serial):
        block_path = self.block_root / name
        (block_path / "queue").mkdir(parents=True)
        (block_path / "queue" / "rotational").write_text(str(rotational), encoding="utf-8")
        (block_path / "device").symlink_to(device_path)
        (device_path / "model").write_text(model, encoding="utf-8")
        (device_path / "serial").write_text(serial, encoding="utf-8")

    def test_nvme_sensor_resolves_to_its_exact_namespace(self):
        controller = self.devices_root / "pci0000:00" / "0000:01:00.0" / "nvme" / "nvme0"
        controller.mkdir(parents=True)
        self._add_block_device("nvme0n1", controller, 0, "WD Red SN700", "NVME-SERIAL")
        self._add_sensor(0, "nvme", controller, {
            "temp1_label": "Composite",
            "temp1_input": 17900,
            "temp1_max": 64800,
            "temp1_crit": 79800,
            "temp2_label": "Sensor 1",
            "temp2_input": 22000,
        })

        temperatures, covered = get_storage_temperatures(
            self.hwmon_root,
            self.block_root,
            cache_ttl=0,
        )

        self.assertEqual(len(temperatures), 1)
        self.assertEqual(temperatures[0]["type"], "nvme")
        self.assertEqual(temperatures[0]["device"], "nvme0n1")
        self.assertEqual(temperatures[0]["model"], "WD Red SN700")
        self.assertEqual(temperatures[0]["serial"], "NVME-SERIAL")
        self.assertEqual(temperatures[0]["current"], 17.9)
        self.assertEqual(temperatures[0]["high"], 64.8)
        self.assertEqual(temperatures[0]["critical"], 79.8)
        self.assertEqual(covered, {"nvme"})

    def test_multiple_nvme_controllers_keep_their_own_device_identity(self):
        first = self.devices_root / "pci0000:00" / "0000:01:00.0" / "nvme" / "nvme0"
        second = self.devices_root / "pci0000:00" / "0000:04:00.0" / "nvme" / "nvme1"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        self._add_block_device("nvme0n1", first, 0, "NVMe One", "SERIAL-ONE")
        self._add_block_device("nvme1n1", second, 0, "NVMe Two", "SERIAL-TWO")
        self._add_sensor(0, "nvme", second, {
            "temp1_label": "Composite",
            "temp1_input": 42000,
        })
        self._add_sensor(1, "nvme", first, {
            "temp1_label": "Composite",
            "temp1_input": 37000,
        })

        temperatures, _ = get_storage_temperatures(
            self.hwmon_root,
            self.block_root,
            cache_ttl=0,
        )

        by_device = {item["device"]: item for item in temperatures}
        self.assertEqual(by_device["nvme0n1"]["model"], "NVMe One")
        self.assertEqual(by_device["nvme0n1"]["current"], 37.0)
        self.assertEqual(by_device["nvme1n1"]["model"], "NVMe Two")
        self.assertEqual(by_device["nvme1n1"]["current"], 42.0)

    def test_drivetemp_uses_rotational_flag_to_identify_hdd(self):
        drive = self.devices_root / "pci0000:00" / "ata4" / "host3" / "target3:0:0" / "3:0:0:0"
        drive.mkdir(parents=True)
        self._add_block_device("sda", drive, 1, "ST4000VN006", "HDD-SERIAL")
        self._add_sensor(1, "drivetemp", drive, {
            "temp1_input": 35000,
            "temp1_max": 60000,
            "temp1_crit": 85000,
        })

        temperatures, covered = get_storage_temperatures(
            self.hwmon_root,
            self.block_root,
            cache_ttl=0,
        )

        self.assertEqual(temperatures[0]["name"], "HDD")
        self.assertEqual(temperatures[0]["type"], "hdd")
        self.assertEqual(temperatures[0]["device"], "sda")
        self.assertEqual(temperatures[0]["original_name"], "temp1")
        self.assertEqual(covered, {"drivetemp"})

    def test_drivetemp_does_not_assume_every_drive_is_rotational(self):
        drive = self.devices_root / "pci0000:00" / "ata5" / "host4" / "target4:0:0" / "4:0:0:0"
        drive.mkdir(parents=True)
        self._add_block_device("sdb", drive, 0, "SATA SSD", "SSD-SERIAL")
        self._add_sensor(2, "drivetemp", drive, {"temp1_input": 31000})

        temperatures, _ = get_storage_temperatures(
            self.hwmon_root,
            self.block_root,
            cache_ttl=0,
        )

        self.assertEqual(temperatures[0]["type"], "ssd")
        self.assertEqual(temperatures[0]["device"], "sdb")

    def test_topology_cache_does_not_cache_temperature_values(self):
        controller = self.devices_root / "pci0000:00" / "0000:01:00.0" / "nvme" / "nvme0"
        controller.mkdir(parents=True)
        self._add_block_device("nvme0n1", controller, 0, "NVMe Live", "SERIAL-LIVE")
        self._add_sensor(0, "nvme", controller, {
            "temp1_label": "Composite",
            "temp1_input": 25000,
        })

        first, _ = get_storage_temperatures(self.hwmon_root, self.block_root, cache_ttl=60)
        (self.hwmon_root / "hwmon0" / "temp1_input").write_text("29000", encoding="utf-8")
        second, _ = get_storage_temperatures(self.hwmon_root, self.block_root, cache_ttl=60)

        self.assertEqual(first[0]["current"], 25.0)
        self.assertEqual(second[0]["current"], 29.0)


if __name__ == "__main__":
    unittest.main()
