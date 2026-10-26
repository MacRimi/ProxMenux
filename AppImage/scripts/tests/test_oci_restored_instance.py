"""A container restored from a backup carries the mark of its installation and
has no record on this host: the modal says so instead of treating it as an
ordinary container."""
import json
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import oci_instance_info

APP = "83e373f2-5ccc-4548-9b89-22d0956d1c77"
OTHER = "488ed3cb-1145-477a-b90f-c46777d69fb2"


class RestoredInstanceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for target, value in (("ROOT", str(self.root)),):
            patcher = patch.object(oci_instance_info, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(oci_instance_info.oci_console_logs, "configured_log", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def record(self, vmid, identity):
        folder = self.root / str(vmid)
        folder.mkdir()
        (folder / "oci-compose.json").write_text(json.dumps(
            {"vmid": vmid, "installation_id": identity, "status": "installed", "deployment": {}}))

    def info(self, vmid, installation):
        with patch.object(oci_instance_info, "_installation", return_value=installation):
            return oci_instance_info.info(vmid)

    def test_a_marked_container_without_record_was_restored(self):
        result = self.info(119, APP)
        self.assertTrue(result["restored"])
        self.assertFalse(result["oci_instance"])

    def test_the_record_of_another_installation_does_not_register_it(self):
        self.record(119, OTHER)
        result = self.info(119, APP)
        self.assertTrue(result["restored"])
        self.assertFalse(result["oci_instance"])

    def test_a_container_the_menu_could_not_recover_is_an_ordinary_one(self):
        (self.root / ".unrecoverable.json").write_text(json.dumps({"119": APP}))
        self.assertFalse(self.info(119, APP)["restored"])
        self.assertTrue(self.info(119, OTHER)["restored"])

    def test_a_registered_container_is_an_oci_instance(self):
        self.record(119, APP)
        result = self.info(119, APP)
        self.assertFalse(result["restored"])
        self.assertTrue(result["oci_instance"])

    def test_an_ordinary_container_is_neither(self):
        result = self.info(100, None)
        self.assertFalse(result["restored"])
        self.assertFalse(result["oci_instance"])

    def test_the_mark_is_read_from_the_notes_of_the_container(self):
        text = f"#<div>Tandoor</div>\n#<!-- proxmenux-instance={APP} -->\narch: amd64\n[snap]\n#proxmenux-instance={OTHER}\n"
        with patch("builtins.open", unittest.mock.mock_open(read_data=text)):
            self.assertEqual(oci_instance_info._installation(119), APP)


if __name__ == "__main__":
    unittest.main()
