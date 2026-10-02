"""An update or a recreation marks its containers for the Monitor and reports
its result once, whether it works or fails."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_operation_notice as notice


class OperationNoticeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.markers = Path(tmp.name)
        patcher = patch.object(notice, "MARKERS", self.markers)
        patcher.start()
        self.addCleanup(patcher.stop)

    def mark(self, vmid):
        return json.loads((self.markers / str(vmid)).read_text())

    def test_the_containers_are_marked_while_it_runs_and_the_result_is_sent(self):
        with patch.object(notice, "notify") as notify:
            with notice.operation([115, 116], "update", "Immich", 115):
                self.assertIsNone(self.mark(115)["ended"])
                self.assertIsNone(self.mark(116)["ended"])
                notify.assert_not_called()
            self.assertIsNotNone(self.mark(115)["ended"])
        notify.assert_called_once_with("oci_update_completed",
                                       {"app_name": "Immich", "vmid": 115, "containers": "CT 115, CT 116"})

    def test_a_failure_is_reported_with_its_reason_and_raised(self):
        with patch.object(notice, "notify") as notify:
            with self.assertRaises(RuntimeError):
                with notice.operation([120], "recreate", "Jellyfin"):
                    raise RuntimeError("the new image did not answer")
        event, data = notify.call_args.args
        self.assertEqual(event, "oci_recreate_failed")
        self.assertEqual(data["reason"], "the new image did not answer")
        self.assertIsNotNone(self.mark(120)["ended"])

    def test_a_monitor_that_does_not_answer_never_stops_the_operation(self):
        with patch.object(notice.urllib.request, "urlopen", side_effect=OSError("refused")):
            self.assertFalse(notice.notify("oci_update_completed", {"app_name": "x"}))
            with notice.operation([120], "update", "Jellyfin"):
                pass

    def test_both_engines_report_through_it(self):
        self.assertIn("oci_operation_notice.operation", (ROOT / "remote/oci_update_current.py").read_text())
        self.assertIn("oci_operation_notice.operation", (ROOT / "remote/oci_stack_native.py").read_text())
        self.assertIn("oci_operation_notice.operation", (ROOT / "remote/oci_stack_modify.py").read_text())


if __name__ == "__main__":
    unittest.main()
