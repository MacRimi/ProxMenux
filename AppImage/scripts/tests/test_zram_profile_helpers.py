"""Contract tests for the opt-in ZRAM profile's pure Bash helpers."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


HELPERS = Path(__file__).resolve().parents[3] / "scripts/post_install/zram_profile_helpers.sh"
SWAPS_HEADER = "Filename\tType\tSize\tUsed\tPriority\n"


class HelperAvailabilityTests(unittest.TestCase):
    def test_helper_file_is_available(self):
        self.assertTrue(HELPERS.is_file(), f"ZRAM helper is missing: {HELPERS}")

    def test_helper_can_be_sourced_twice(self):
        result = subprocess.run(
            ["bash", "-c", 'source "$1" && source "$1"', "bash", str(HELPERS)],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


def call_helper(function, *arguments):
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1" || exit; shift; "$@"',
            "bash",
            str(HELPERS),
            function,
            *(str(argument) for argument in arguments),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


class ZramGeneratorConfigTests(unittest.TestCase):
    def assert_config(self, supports_algorithm_params, expected_algorithm):
        result = call_helper("zram_render_generator_config", supports_algorithm_params)
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = {
            key.strip(): value.strip()
            for line in result.stdout.splitlines()
            if "=" in line
            for key, value in [line.split("=", 1)]
        }
        self.assertIn("[zram0]", result.stdout.splitlines())
        self.assertEqual(settings.get("zram-size", "").strip(), "ram / 10")
        self.assertEqual(settings.get("swap-priority", "").strip(), "32767")
        self.assertEqual(settings.get("compression-algorithm", "").strip(), expected_algorithm)
        self.assertNotIn("writeback", result.stdout.lower())

    def test_generator_1_1_2_2_uses_plain_zstd(self):
        self.assert_config("false", "zstd")

    def test_generator_1_2_1_2_uses_zstd_level_nine(self):
        self.assert_config("true", "zstd(level=9)")


class ForeignActiveZramSwapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        directory = Path(self.temporary.name)
        self.root = directory
        self.swaps_file = directory / "swaps"

    def detect(self, swaps, owned_device=""):
        self.swaps_file.write_text(swaps, encoding="utf-8")
        return call_helper(
            "zram_list_foreign_active_zram_swap", self.swaps_file, owned_device
        )

    def test_active_disk_swap_is_allowed(self):
        result = self.detect(
            SWAPS_HEADER + "/dev/nvme0n1p3\tpartition\t1048576\t0\t-2\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_active_unowned_zram0_is_detected(self):
        result = self.detect(SWAPS_HEADER + "/dev/zram0\tpartition\t1048576\t0\t100\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "active zram: /dev/zram0\n")

    def test_active_owned_zram0_is_allowed_alongside_disk_swap(self):
        result = self.detect(
            SWAPS_HEADER
            + "/dev/nvme0n1p3\tpartition\t1048576\t0\t-2\n"
            + "/dev/zram0\tpartition\t1048576\t0\t100\n",
            "/dev/zram0",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_another_active_zram_device_is_rejected(self):
        result = self.detect(
            SWAPS_HEADER
            + "/dev/zram0\tpartition\t1048576\t0\t100\n"
            + "/dev/zram1\tpartition\t1048576\t0\t90\n",
            "/dev/zram0",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "active zram: /dev/zram1\n")

    def test_swap_table_read_failure_is_reported(self):
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        fake_awk = fake_bin / "awk"
        fake_awk.write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
        fake_awk.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"

        result = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1" || exit; shift; "$@"',
                "bash",
                str(HELPERS),
                "zram_list_foreign_active_zram_swap",
                str(self.swaps_file),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

        self.assertEqual(result.returncode, 2, result.stderr)


class ForeignFstabZramSwapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fstab_file = Path(self.temporary.name) / "fstab"

    def detect(self, text):
        self.fstab_file.write_text(text, encoding="utf-8")
        return call_helper("zram_list_foreign_fstab_zram_swap", self.fstab_file)

    def test_disk_swap_entries_are_allowed(self):
        result = self.detect(
            "UUID=swap-partition none swap defaults 0 0\n"
            "/swapfile none swap sw 0 0\n"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_zram_swap_entry_is_reported(self):
        result = self.detect(
            "UUID=swap-partition none swap defaults 0 0\n"
            "/dev/zram1 none swap pri=100 0 0\n"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "fstab zram: /dev/zram1\n")


class ForeignZramConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.etc = self.root / "etc/systemd"
        (self.etc / "zram-generator.conf.d").mkdir(parents=True)
        self.owned = self.etc / "zram-generator.conf.d/90-proxmenux.conf"

    def foreign_configs(self):
        return call_helper(
            "zram_foreign_generator_config", self.owned, self.root
        ).stdout.splitlines()

    def test_empty_packaged_default_does_not_block_profile(self):
        (self.etc / "zram-generator.conf").write_text(
            "# package default\n[zram0]\n; no active directives\n",
            encoding="utf-8",
        )

        self.assertEqual(self.foreign_configs(), [])

    def test_active_foreign_directive_is_reported(self):
        foreign = self.etc / "zram-generator.conf"
        foreign.write_text("[zram1]\nzram-size = ram / 4\n", encoding="utf-8")

        self.assertEqual(self.foreign_configs(), [str(foreign)])

    def test_owned_drop_in_is_not_reported(self):
        self.owned.write_text(
            "# ProxMenux ZRAM profile\n[zram0]\nzram-size = ram / 10\n",
            encoding="utf-8",
        )

        self.assertEqual(self.foreign_configs(), [])


class ForeignSystemdZramUnitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.system_dir = self.root / "etc/systemd/system"
        self.system_dir.mkdir(parents=True)

    def test_disk_swap_unit_is_allowed_and_zram_units_are_reported(self):
        (self.system_dir / "pve-swap.swap").write_text(
            "[Swap]\nWhat=/dev/mapper/pve-swap\n", encoding="utf-8"
        )
        (self.system_dir / "dev-zram0.swap").write_text(
            "[Swap]\nWhat=/dev/zram0\n", encoding="utf-8"
        )
        external = self.system_dir / "external.swap"
        external.write_text("[Swap]\nWhat=/dev/zram1\n", encoding="utf-8")
        vendor_dir = self.root / "usr/lib/systemd/system"
        vendor_dir.mkdir(parents=True)
        vendor = vendor_dir / "vendor-zram.swap"
        vendor.write_text("[Swap]\nWhat=/dev/zram2\n", encoding="utf-8")

        result = call_helper("zram_list_foreign_systemd_zram_units", self.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            set(result.stdout.splitlines()),
            {
                f"systemd zram unit: {self.system_dir / 'dev-zram0.swap'}",
                f"systemd zram unit: {external}",
                f"systemd zram unit: {vendor}",
            },
        )

    def test_unrelated_custom_swap_unit_is_allowed(self):
        (self.system_dir / "custom.swap").write_text(
            "[Swap]\nWhat=/swapfile\n", encoding="utf-8"
        )

        result = call_helper("zram_list_foreign_systemd_zram_units", self.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_reserved_zram0_unit_masked_with_dev_null_is_reported(self):
        (self.system_dir / "dev-zram0.swap").symlink_to("/dev/null")

        result = call_helper("zram_list_foreign_systemd_zram_units", self.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            f"systemd zram unit masked: {self.system_dir / 'dev-zram0.swap'}\n",
        )

    def test_zram_swap_drop_in_is_reported(self):
        dropins = self.system_dir / "custom.swap.d"
        dropins.mkdir()
        dropin = dropins / "10-zram.conf"
        dropin.write_text("[Swap]\nWhat=/dev/zram1\n", encoding="utf-8")

        result = call_helper("zram_list_foreign_systemd_zram_units", self.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"systemd zram unit: {dropin}\n")

    def test_generator_wants_symlink_is_not_a_foreign_unit_file(self):
        generator = self.root / "run/systemd/generator"
        generator.mkdir(parents=True)
        (generator / "dev-zram0.swap").write_text(
            "[Swap]\nWhat=/dev/zram0\n", encoding="utf-8"
        )
        wants = self.root / "run/systemd/system/swap.target.wants"
        wants.mkdir(parents=True)
        (wants / "dev-zram0.swap").symlink_to("../../generator/dev-zram0.swap")

        result = call_helper("zram_list_foreign_systemd_zram_units", self.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")


class ZramProfileActivationVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.block_root = self.root / "sys/block"
        zram0 = self.block_root / "zram0"
        zram0.mkdir(parents=True)
        (zram0 / "disksize").write_text("3435973836\n", encoding="utf-8")
        (zram0 / "comp_algorithm").write_text(
            "lzo [zstd] lz4\n", encoding="utf-8"
        )
        self.meminfo = self.root / "proc/meminfo"
        self.meminfo.parent.mkdir(parents=True)
        self.meminfo.write_text("MemTotal:       33554432 kB\n", encoding="utf-8")
        self.swaps = self.root / "proc/swaps"
        self.swaps.write_text(SWAPS_HEADER, encoding="utf-8")

    def verify(self):
        return call_helper(
            "zram_profile_verify_active",
            "zstd",
            "32767",
            self.block_root,
            self.meminfo,
            self.swaps,
        )

    def test_profile_is_valid_with_lower_priority_disk_swap_active(self):
        self.swaps.write_text(
            SWAPS_HEADER
            + "/dev/zram0\tpartition\t3355443\t0\t32767\n"
            + "/dev/nvme0n1p3\tpartition\t1048576\t32\t-2\n",
            encoding="utf-8",
        )

        result = self.verify()

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_profile_rejects_a_second_active_zram_device(self):
        self.swaps.write_text(
            SWAPS_HEADER
            + "/dev/zram0\tpartition\t3355443\t0\t32767\n"
            + "/dev/zram1\tpartition\t1048576\t0\t90\n",
            encoding="utf-8",
        )

        result = self.verify()

        self.assertEqual(result.returncode, 1, result.stderr)

    def test_profile_rejects_zram_device_without_requested_priority(self):
        self.swaps.write_text(
            SWAPS_HEADER
            + "/dev/zram0\tpartition\t3355443\t0\t100\n",
            encoding="utf-8",
        )

        result = self.verify()

        self.assertEqual(result.returncode, 1, result.stderr)


if __name__ == "__main__":
    unittest.main()
