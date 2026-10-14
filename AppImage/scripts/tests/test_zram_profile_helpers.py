"""Contract tests for the opt-in ZRAM profile's pure Bash helpers."""

import subprocess
import tempfile
import unittest
from pathlib import Path


HELPERS = Path(__file__).resolve().parents[3] / "scripts/post_install/zram_profile_helpers.sh"
SWAPS_HEADER = "Filename\tType\tSize\tUsed\tPriority\n"


class HelperAvailabilityTests(unittest.TestCase):
    def test_helper_file_is_available(self):
        self.assertTrue(HELPERS.is_file(), f"ZRAM helper is missing: {HELPERS}")


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
        self.assertEqual(settings.get("swap-priority", "").strip(), "100")
        self.assertEqual(settings.get("compression-algorithm", "").strip(), expected_algorithm)
        self.assertNotIn("writeback", result.stdout.lower())

    def test_generator_1_1_2_2_uses_plain_zstd(self):
        self.assert_config("false", "zstd")

    def test_generator_1_2_1_2_uses_zstd_level_nine(self):
        self.assert_config("true", "zstd(level=9)")


class NonZramSwapDetectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        directory = Path(self.temporary.name)
        self.swaps_file = directory / "swaps"
        self.fstab_file = directory / "fstab"

    def detect(self, swaps, fstab):
        self.swaps_file.write_text(swaps, encoding="utf-8")
        self.fstab_file.write_text(fstab, encoding="utf-8")
        return call_helper("zram_has_non_zram_swap", self.swaps_file, self.fstab_file)

    def test_active_disk_swap_is_detected(self):
        result = self.detect(
            SWAPS_HEADER + "/dev/nvme0n1p3\tpartition\t1048576\t0\t-2\n",
            "",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_persistent_swapfile_is_detected(self):
        result = self.detect(SWAPS_HEADER, "/swapfile none swap sw 0 0\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_commented_disk_swap_is_ignored(self):
        result = self.detect(SWAPS_HEADER, "  # /swapfile none swap sw 0 0\n")
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_active_and_persistent_zram_are_ignored(self):
        result = self.detect(
            SWAPS_HEADER + "/dev/zram0\tpartition\t1048576\t0\t100\n",
            "/dev/zram0 none swap defaults 0 0\n",
        )
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_regular_fstab_entry_does_not_count_as_swap(self):
        result = self.detect(SWAPS_HEADER, "/dev/nvme0n1p2 / ext4 defaults 0 1\n")
        self.assertEqual(result.returncode, 1, result.stderr)


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


class SystemdSwapDetectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.system_dir = self.root / "etc/systemd/system"
        self.system_dir.mkdir(parents=True)

    def test_administrator_defined_zram_and_other_swap_units_are_reported(self):
        (self.system_dir / "dev-zram0.swap").write_text("", encoding="utf-8")
        (self.system_dir / "custom.swap").write_text("", encoding="utf-8")

        result = call_helper("zram_list_defined_systemd_swap_units", self.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            set(result.stdout.splitlines()),
            {
                f"systemd: {self.system_dir / 'dev-zram0.swap'}",
                f"systemd: {self.system_dir / 'custom.swap'}",
            },
        )

    def test_no_non_zram_systemd_swap_has_empty_output(self):
        result = call_helper("zram_list_defined_systemd_swap_units", self.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
