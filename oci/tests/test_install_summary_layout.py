"""The final summary of an installation reads in groups: the container, its
data, its network, its variables and its start, each path with its target and
the variables in aligned columns."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "remote"), str(ROOT / "tests")]

from proxmenux_oci.catalog import Catalog  # noqa: E402
from proxmenux_oci.cli import SUMMARY_TEXT_WIDTH, _columns, _deployment_summary_text  # noqa: E402
from proxmenux_oci.installer import DEFAULT_MODE, build_deployment  # noqa: E402
from test_advanced_flow_order import RecordingUI, addresses, storages  # noqa: E402


@patch("proxmenux_oci.i18n.language", return_value="en")
@patch("proxmenux_oci.installer.host.storages", side_effect=storages)
@patch("proxmenux_oci.installer.host.bridges", return_value=[{"iface": "vmbr0", "cidr": "192.0.2.10/24"}])
@patch("proxmenux_oci.installer.host.timezone", return_value="Europe/Madrid")
@patch("proxmenux_oci.installer.access.ask_ipv4", return_value=("dhcp", None))
@patch("proxmenux_oci.installer.access.ask_addresses", side_effect=addresses)
class InstallSummaryLayoutTests(unittest.TestCase):
    def summary(self, app):
        template = Catalog(ROOT).compose(app)
        plan = build_deployment(template, RecordingUI(), DEFAULT_MODE)
        plan["watchdog"] = True
        return _deployment_summary_text(template, plan).splitlines()

    def test_groups_are_apart_and_labels_are_aligned(self, *_):
        lines = self.summary("omada-controller")
        self.assertEqual(lines[1], "TP-Link Omada Controller")
        self.assertTrue(set(lines[0]) == set(lines[2]) == {"─"})
        for label in ("Data:", "Network:", "Variables:", "Start:"):
            index = next(i for i, line in enumerate(lines) if line.startswith(label))
            self.assertEqual(lines[index - 1], "", label)
        values = {line.index(":") + 1 + len(line[line.index(":") + 1:]) - len(line[line.index(":") + 1:].lstrip())
                  for line in lines if line[:1].isalpha() and ": " in line and not line.endswith(":")}
        self.assertEqual(len(values), 1, values)

    def test_paths_read_alike_and_variables_sit_in_two_columns(self, *_):
        lines = self.summary("omada-controller")
        data = lines.index("Data:")
        self.assertTrue(lines[data + 1].strip().startswith("/opt/tplink/EAPController/data"))
        self.assertTrue(lines[data + 2].strip().startswith("→ "))
        variables = lines[lines.index("Variables:") + 1:]
        self.assertIn("PUID=1000", variables[0])
        self.assertIn("PGID=1000", variables[0])
        self.assertTrue(all(len(line) <= SUMMARY_TEXT_WIDTH for line in lines))
        self.assertNotIn(",", " ".join(variables[:3]))

    def test_columns_fall_back_to_one_per_line_when_a_pair_does_not_fit(self, *_):
        self.assertEqual(_columns(["A=1", "B=2", "C=3"]), ["  A=1   B=2", "  C=3"])
        long = "X=" + "y" * 40
        self.assertEqual(_columns([long, "B=2"]), [f"  {long}", "  B=2"])


if __name__ == "__main__":
    unittest.main()
