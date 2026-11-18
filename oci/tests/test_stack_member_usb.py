"""The containers of a stack keep their USB devices by what they are: an update
carries them over, and Modify lists, removes and adds them that way too."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "remote"))

import oci_stack_modify as stack_modify
import oci_stack_replay
import oci_usb_passthrough as usb
from proxmenux_oci import stack_recreation

UPS = {"id": "manual-bus-usb-003-004", "kind": "usb", "container_path": "/dev/bus/usb",
       "usb": {"vendor": "0463", "product": "ffff", "port": "3-3"}}
STICK = {"id": "manual-ttyACM0", "kind": "usb", "container_path": "/dev/ttyACM0", "major": 166,
         "serial_link": "/dev/serial/by-id/usb-Z-Stick", "usb": {"vendor": "0658", "product": "0200", "port": "3-8"}}
CHANGES = {"remove_mounts": [], "add_mounts": [], "change_mounts": {}, "remove_devices": [], "add_devices": []}


def member_record(*devices, extra_config=""):
    config = "arch: amd64\n" + "\n".join(usb.lines({"devices": list(devices)})) + "\n" + extra_config
    return {"vmid": 140, "stack_member": {"name": "server"},
            "deployment": {"devices": [copy.deepcopy(device) for device in devices], "mounts": []},
            "observed": {"config": config}}


def changes(**values):
    result = copy.deepcopy(CHANGES)
    result.update(values)
    return result


class ReplayTests(unittest.TestCase):
    def test_an_update_keeps_the_usb_devices_of_the_record(self):
        record = member_record(UPS, STICK)
        with patch.object(oci_stack_replay, "normalize", return_value={}), \
                patch.object(oci_stack_replay, "translated_devices", return_value=[{"id": "native-renderD128"}]):
            result = oci_stack_replay.with_devices(record, {"deployment": {}})
        self.assertEqual(result["deployment"]["devices"], [{"id": "native-renderD128"}, UPS, STICK])

    def test_lines_that_do_not_match_the_record_stop_the_update(self):
        record = member_record(UPS)
        record["deployment"]["devices"].append(copy.deepcopy(STICK))
        with self.assertRaises(ValueError):
            oci_stack_replay.recorded_usb(record)


@patch.object(stack_modify, "entries", return_value={})
class ModifyValidationTests(unittest.TestCase):
    def test_a_recorded_usb_device_is_removed_by_its_id(self, _):
        stack_modify.validate(140, changes(remove_devices=["usb:manual-ttyACM0"]), member_record(UPS, STICK))

    def test_an_unknown_usb_id_is_refused(self, _):
        with self.assertRaises(ValueError):
            stack_modify.validate(140, changes(remove_devices=["usb:other"]), member_record(UPS))

    def test_the_same_device_twice_is_refused(self, _):
        with self.assertRaises(ValueError):
            stack_modify.validate(140, changes(add_devices=[dict(UPS, id="new")]), member_record(UPS))

    def test_a_device_removed_and_added_again_is_accepted(self, _):
        stack_modify.validate(140, changes(remove_devices=["usb:manual-bus-usb-003-004"],
                                           add_devices=[dict(UPS, id="new")]), member_record(UPS))

    def test_an_invalid_usb_record_is_refused(self, _):
        with self.assertRaises(ValueError):
            stack_modify.validate(140, changes(add_devices=[dict(UPS, usb={"vendor": "x"})]), member_record())


class ModifyApplyTests(unittest.TestCase):
    def setUp(self):
        self.record = member_record(UPS)
        self.written, self.applied = [], []
        patches = [patch.object(stack_modify.instances, "read", side_effect=lambda *_: self.record),
                   patch.object(stack_modify.instances, "location", return_value=Path("/registry/140.json")),
                   patch.object(stack_modify.instances, "write",
                                side_effect=lambda _, record: self.written.append(copy.deepcopy(record))),
                   patch.object(stack_modify.usb_passthrough, "apply",
                                side_effect=lambda vmid, plan: self.applied.append(copy.deepcopy(plan))),
                   patch.object(stack_modify, "msg_ok")]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_added_and_removed_devices_reach_the_record_and_the_container(self):
        stack_modify.apply_usb(Path("/registry"), 140, changes(remove_devices=["usb:manual-bus-usb-003-004"],
                                                               add_devices=[copy.deepcopy(STICK)]))
        self.assertEqual(self.applied[0]["devices"], [STICK])
        self.assertEqual(self.written[0]["deployment"]["devices"], [STICK])

    def test_an_id_already_taken_gets_another(self):
        stack_modify.apply_usb(Path("/registry"), 140, changes(add_devices=[dict(STICK, id=UPS["id"])]))
        self.assertEqual([d["id"] for d in self.written[0]["deployment"]["devices"]],
                         [UPS["id"], UPS["id"] + "-2"])

    def test_other_changes_leave_the_usb_devices_alone(self):
        stack_modify.apply_usb(Path("/registry"), 140, changes(remove_devices=["/dev/dri/renderD128"]))
        self.assertEqual((self.applied, self.written), ([], []))


class RecipeInstallTests(unittest.TestCase):
    def test_the_main_member_of_a_recipe_stack_records_the_usb_devices(self):
        import json
        import tempfile
        import oci_native_stack
        prepared = {}
        deployment = {"extra_devices": [UPS, {"id": "gpu", "kind": "character-device", "host_path": "/dev/dri/renderD128"}]}
        with tempfile.TemporaryDirectory() as directory:
            adapter = Path(directory) / "install_immich_stack.sh"
            adapter.write_text("#!/bin/bash\n")
            with patch.object(oci_native_stack, "command", return_value=json.dumps([]).encode()), \
                    patch.object(oci_native_stack, "image_from_archive", return_value={}), \
                    patch.object(oci_native_stack.instances, "release_orphan", return_value=True), \
                    patch.object(oci_native_stack.instances, "prepare",
                                 side_effect=lambda root, vmid, child, plan: prepared.update({vmid: plan})), \
                    patch.object(oci_native_stack.instances, "read", return_value={}), \
                    patch.object(oci_native_stack.instances, "location", return_value=Path("/registry/150.json")), \
                    patch.object(oci_native_stack.instances, "write"):
                oci_native_stack.begin(Path("/registry"), 150, {"id": "immich"}, deployment,
                                       [("server", "150", "img", "/a.tar"), ("database", "151", "img", "/b.tar")],
                                       str(adapter))
        self.assertEqual(prepared[150]["devices"], [UPS])
        self.assertNotIn("devices", prepared[151])


class ConsoleTests(unittest.TestCase):
    def test_recorded_usb_devices_are_listed_by_name_and_removable(self):
        with patch.object(stack_recreation, "_config", return_value={}), \
                patch.object(stack_recreation, "recipe_paths", return_value=set()):
            _, devices, _, _ = stack_recreation.current_state(member_record(UPS))
        self.assertEqual([(d["host_path"], d["label"], d["removable"]) for d in devices],
                         [("usb:manual-bus-usb-003-004", "USB 0463:ffff · 3-3", True)])

    def test_the_summary_names_usb_devices(self):
        text = stack_recreation.summary(member_record(UPS), changes(remove_devices=["usb:manual-bus-usb-003-004"],
                                                                   add_devices=[STICK]))
        self.assertIn("- USB 0463:ffff · 3-3", text)
        self.assertIn("+ /dev/ttyACM0 (USB 0658:0200 · 3-8)", text)


if __name__ == "__main__":
    unittest.main()
