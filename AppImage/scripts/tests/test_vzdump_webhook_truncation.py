import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from notification_templates import _format_vzdump_body, _parse_vzdump_message


def _vzdump_table_row(vmid, name, status="OK", time_value="00:00:12", size="1.23 GiB"):
    filename = (
        f"/mnt/pve/fast-zfs-backup/dump/"
        f"vzdump-lxc-{vmid}-2026_08_09-04_00_00.tar.zst"
    )
    return "{:<8}{:<22}{:<10}{:<10}{:<14}{}".format(
        str(vmid),
        name,
        status,
        time_value,
        size,
        filename,
    )


def _make_long_vzdump_report():
    header = "{:<8}{:<22}{:<10}{:<10}{:<14}{}".format(
        "VMID",
        "Name",
        "Status",
        "Time",
        "Size",
        "Filename",
    )
    rows = [_vzdump_table_row(100 + i, f"ct-{100 + i:03d}") for i in range(28)]
    dockflare_row = _vzdump_table_row(129, "dockflare")

    message_prefix = (
        "Proxmox vzdump report\n\n"
        + header
        + "\n"
        + "\n".join(rows)
        + "\n"
    )

    # Place the 4096-character cut right after the dockflare VMID + name
    # columns, before the Status/Time/Size/Filename columns. This reproduces
    # the production symptom: CT 129 appears as a failed backup with no detail.
    cut_at = len(message_prefix) + 8 + 22
    filler = "X" * max(0, 4096 - cut_at) + "\n"

    return (
        filler
        + message_prefix
        + dockflare_row
        + "\nTotal running time: 00:12:34\nTotal size: 42.0 GiB\n"
    )


class VzdumpWebhookTruncationTests(unittest.TestCase):
    def test_truncating_vzdump_report_at_4096_can_create_false_failed_backup(self):
        full_message = _make_long_vzdump_report()
        truncated_message = full_message[:4096]

        full_parsed = _parse_vzdump_message(full_message)
        full_body = _format_vzdump_body(full_parsed, True)
        truncated_parsed = _parse_vzdump_message(truncated_message)
        truncated_body = _format_vzdump_body(truncated_parsed, True)

        full_dockflare = [
            vm for vm in full_parsed["vms"] if vm.get("vmid") == "129"
        ][0]
        truncated_dockflare = [
            vm for vm in truncated_parsed["vms"] if vm.get("vmid") == "129"
        ][0]

        self.assertEqual(full_dockflare["status"], "OK")
        self.assertIn("✅ CT dockflare (129)", full_body)
        self.assertNotIn("failed", full_body)

        self.assertEqual(truncated_dockflare["name"], "dockflare")
        self.assertEqual(truncated_dockflare["status"], "")
        self.assertIn("❌ dockflare (129)", truncated_body)
        self.assertIn("❌ 1 failed", truncated_body)

    def test_webhook_handler_does_not_truncate_message_before_parsing(self):
        source = (SCRIPTS_DIR / "flask_notification_routes.py").read_text()

        self.assertNotIn("payload['message'] = message[:4096]", source)
        self.assertNotIn('payload["message"] = message[:4096]', source)
        self.assertIn("Keep the full webhook body for downstream parsers", source)


if __name__ == "__main__":
    unittest.main()
