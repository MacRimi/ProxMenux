import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "security_manager.py"
SPEC = importlib.util.spec_from_file_location("security_manager_under_test", MODULE_PATH)
security_manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(security_manager)


class Fail2BanTrustedNetworksTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.managed_file = root / "jail.d" / "99-proxmenux-ignore.local"
        self.legacy_file = root / "jail.local"
        self.paths_patch = mock.patch.multiple(
            security_manager,
            FAIL2BAN_TRUSTED_NETWORKS_FILE=str(self.managed_file),
            FAIL2BAN_LEGACY_GLOBAL_FILE=str(self.legacy_file),
        )
        self.paths_patch.start()
        self.addCleanup(self.paths_patch.stop)
        self.command_patch = mock.patch.object(
            security_manager, "_run_cmd", return_value=(0, "OK", "")
        )
        self.run_command = self.command_patch.start()
        self.addCleanup(self.command_patch.stop)

    def write_legacy(self, content):
        self.legacy_file.write_text(content)

    def test_reads_and_normalises_existing_global_entries(self):
        self.write_legacy(
            "[DEFAULT]\nignoreip = 127.0.0.1/8, ::1 192.168.10.15 10.1.2.9/24\n"
            "\n[sshd]\nenabled = true\n"
        )

        entries = security_manager.get_fail2ban_trusted_networks()

        self.assertEqual(
            [entry["value"] for entry in entries],
            ["127.0.0.0/8", "::1", "192.168.10.15", "10.1.2.0/24"],
        )
        self.assertTrue(entries[0]["protected"])
        self.assertTrue(entries[1]["protected"])
        self.assertFalse(entries[2]["protected"])

    def test_adds_ipv4_network_and_reloads_fail2ban(self):
        success, message, value = security_manager.add_fail2ban_trusted_network(
            "192.168.50.123/24"
        )

        self.assertTrue(success, message)
        self.assertEqual(value, "192.168.50.0/24")
        content = self.managed_file.read_text()
        self.assertIn("ignoreip = 127.0.0.0/8 ::1 192.168.50.0/24", content)
        self.run_command.assert_called_once_with(["fail2ban-client", "reload"])

    def test_adds_ipv6_network(self):
        success, message, value = security_manager.add_fail2ban_trusted_network(
            "fd12:3456:789a::42/64"
        )

        self.assertTrue(success, message)
        self.assertEqual(value, "fd12:3456:789a::/64")

    def test_rejects_invalid_or_multiple_values_without_writing(self):
        for value in ("not-an-ip", "10.0.0.1 10.0.0.2", "10.0.0.0/99"):
            with self.subTest(value=value):
                success, _, normalised = security_manager.add_fail2ban_trusted_network(value)
                self.assertFalse(success)
                self.assertIsNone(normalised)

        self.assertFalse(self.managed_file.exists())
        self.run_command.assert_not_called()

    def test_duplicate_is_rejected(self):
        self.write_legacy("[DEFAULT]\nignoreip = 10.0.0.0/24\n")

        success, message, value = security_manager.add_fail2ban_trusted_network("10.0.0.9/24")

        self.assertFalse(success)
        self.assertIn("already trusted", message)
        self.assertEqual(value, "10.0.0.0/24")
        self.run_command.assert_not_called()

    def test_address_already_covered_by_network_is_rejected(self):
        self.write_legacy("[DEFAULT]\nignoreip = 10.0.0.0/24\n")

        success, message, value = security_manager.add_fail2ban_trusted_network("10.0.0.42")

        self.assertFalse(success)
        self.assertIn("already trusted", message)
        self.assertEqual(value, "10.0.0.42")

    def test_rejects_network_that_would_disable_all_bans(self):
        for value in ("0.0.0.0/0", "::/0"):
            with self.subTest(value=value):
                success, _, normalised = security_manager.add_fail2ban_trusted_network(value)
                self.assertFalse(success)
                self.assertIsNone(normalised)

    def test_protected_network_cannot_be_removed(self):
        success, message = security_manager.remove_fail2ban_trusted_network("127.0.0.1/8")

        self.assertFalse(success)
        self.assertIn("cannot be removed", message)
        self.run_command.assert_not_called()

    def test_removes_user_network_and_keeps_other_entries(self):
        self.managed_file.parent.mkdir(parents=True)
        self.managed_file.write_text(
            "[DEFAULT]\nignoreip = 127.0.0.0/8 ::1 10.0.0.0/24 192.168.1.5\n"
        )

        success, message = security_manager.remove_fail2ban_trusted_network("10.0.0.0/24")

        self.assertTrue(success, message)
        content = self.managed_file.read_text()
        self.assertNotIn("10.0.0.0/24", content)
        self.assertIn("192.168.1.5", content)

    def test_updates_user_network_in_place(self):
        self.managed_file.parent.mkdir(parents=True)
        self.managed_file.write_text(
            "[DEFAULT]\nignoreip = 127.0.0.0/8 ::1 10.0.0.0/24 192.168.1.5\n"
        )

        success, message, value = security_manager.update_fail2ban_trusted_network(
            "10.0.0.0/24", "10.20.30.99/24"
        )

        self.assertTrue(success, message)
        self.assertEqual(value, "10.20.30.0/24")
        content = self.managed_file.read_text()
        self.assertNotIn("10.0.0.0/24", content)
        self.assertIn("10.20.30.0/24", content)
        self.assertIn("192.168.1.5", content)

    def test_protected_network_cannot_be_updated(self):
        success, message, value = security_manager.update_fail2ban_trusted_network(
            "::1", "::2"
        )

        self.assertFalse(success)
        self.assertIn("cannot be changed", message)
        self.assertIsNone(value)

    def test_reload_failure_restores_previous_file(self):
        self.managed_file.parent.mkdir(parents=True)
        original = "[DEFAULT]\nignoreip = 127.0.0.0/8 ::1 10.0.0.0/24\n"
        self.managed_file.write_text(original)
        self.run_command.side_effect = [
            (1, "", "configuration error"),
            (0, "OK", ""),
        ]

        success, message, _ = security_manager.add_fail2ban_trusted_network("192.168.1.0/24")

        self.assertFalse(success)
        self.assertIn("configuration error", message)
        self.assertEqual(self.managed_file.read_text(), original)
        self.assertEqual(self.run_command.call_count, 2)


if __name__ == "__main__":
    unittest.main()
