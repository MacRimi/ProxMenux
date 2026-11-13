"""Modify on a multi-container application edits the paths and devices of its
application container, and never removes its own data."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "remote"))

from proxmenux_oci import stack_recreation

MEMBER = {"vmid": 129, "stack_member": {"name": "application"},
          "deployment": {"replay_profile": {"adapter": "install_tandoor_stack.sh", "role": "application"}}}
DATABASE = {"vmid": 130, "stack_member": {"name": "database"},
            "deployment": {"replay_profile": {"adapter": "install_tandoor_stack.sh", "role": "database"}}}
CONFIG = {
    "rootfs": "local-lvm:vm-129-disk-0,size=8G",
    "mp0": "local-lvm:vm-129-disk-1,mp=/opt/recipes/staticfiles,backup=1,size=2G",
    "mp1": "local-lvm:vm-129-disk-2,mp=/opt/recipes/mediafiles,backup=1,size=16G",
    "mp2": "local-lvm:vm-129-disk-3,mp=/media-extra,backup=1,size=2G",
    "mp3": "/mnt/share,mp=/host-extra,backup=0",
    "dev0": "path=/dev/ttyACM1,mode=0660,deny-write=0,gid=20",
}


class ScriptedUI:
    """Answers the editor of paths in order: menu choices, then the devices to keep."""

    def __init__(self, choices, kept_devices, delete=True, answers=()):
        self.choices = list(choices)
        self.answers = list(answers)
        self.kept_devices = kept_devices
        self.delete = delete
        self.offered = []
        self.messages = []

    def choose(self, text, options, default=None, **_):
        self.offered.append([tag for tag, _label in options])
        return self.choices.pop(0)

    def ask(self, text, default=None, **_):
        return self.answers.pop(0)

    def message(self, text, title=None):
        self.messages.append(text)

    def checklist(self, text, options, default=None):
        return self.kept_devices

    def confirm(self, text, default=False):
        return self.delete if "deletes its container volume" in text else False


@patch("proxmenux_oci.i18n.language", return_value="en")
@patch.object(stack_recreation, "_config", return_value=CONFIG)
class StackRecreationTests(unittest.TestCase):
    def test_only_the_application_container_is_edited(self, *_):
        primary = {"stack": {"members": [DATABASE, MEMBER]}}
        self.assertEqual([m["vmid"] for m in stack_recreation.application_members(primary)], [129])

    def test_the_data_of_the_recipe_is_never_offered_for_removal(self, *_):
        ui = ScriptedUI(["/opt/recipes/mediafiles", "/media-extra", "back", "done"], ["/dev/ttyACM1"])
        self.assertIsNone(stack_recreation.plan_changes(ui, MEMBER))
        self.assertEqual(ui.offered[0], ["/opt/recipes/staticfiles", "/opt/recipes/mediafiles", "/media-extra",
                                         "/host-extra", "add", "done"])
        self.assertEqual(len(ui.messages), 1)
        self.assertEqual(ui.offered[2], ["read_only", "remove", "back"])

    def test_removed_paths_and_devices(self, *_):
        ui = ScriptedUI(["/media-extra", "remove", "/host-extra", "remove", "done"], [])
        changes = stack_recreation.plan_changes(ui, MEMBER)
        self.assertEqual(changes["remove_mounts"], ["/media-extra", "/host-extra"])
        self.assertEqual(changes["remove_devices"], ["/dev/ttyACM1"])
        self.assertEqual((changes["add_mounts"], changes["add_devices"], changes["change_mounts"]), ([], [], {}))

    def test_a_volume_is_kept_when_its_deletion_is_not_confirmed(self, *_):
        ui = ScriptedUI(["/media-extra", "remove", "/host-extra", "remove", "done"], ["/dev/ttyACM1"], delete=False)
        changes = stack_recreation.plan_changes(ui, MEMBER)
        self.assertEqual(changes["remove_mounts"], ["/host-extra"])

    def test_a_path_from_the_host_changes_its_directory_and_its_read_only_mode(self, *_):
        ui = ScriptedUI(["/host-extra", "source", "/host-extra", "read_only", "done"], ["/dev/ttyACM1"],
                        answers=["/mnt/nas/share"])
        changes = stack_recreation.plan_changes(ui, MEMBER)
        self.assertEqual(changes["change_mounts"], {"/host-extra": {"source": "/mnt/nas/share", "read_only": True}})
        self.assertEqual(changes["remove_mounts"], [])

    def test_the_summary_lists_what_changes(self, *_):
        changes = {"remove_mounts": ["/media-extra"], "remove_devices": [], "add_devices": [
            {"host_path": "/dev/ttyACM0"}], "add_mounts": [
            {"type": "host-bind", "container_path": "/scans", "source": "/mnt/scans"}]}
        text = stack_recreation.summary(MEMBER, changes)
        changes["change_mounts"] = {"/host-extra": {"source": "/mnt/nas"}}
        text = stack_recreation.summary(MEMBER, changes)
        for expected in ("CT 129", "+ /scans", "- /media-extra", "+ /dev/ttyACM0", "~ /host-extra",
                         "/mnt/nas", "are not changed"):
            self.assertIn(expected, text)


class StackModifyValidationTests(unittest.TestCase):
    def setUp(self):
        import oci_stack_modify
        self.modify = oci_stack_modify
        lines = "\n".join(f"{key}: {value}" for key, value in CONFIG.items()) + "\n"
        patcher = patch.object(oci_stack_modify, "run", return_value=lines)
        patcher.start()
        self.addCleanup(patcher.stop)

    def changes(self, **values):
        return {"remove_mounts": [], "add_mounts": [], "change_mounts": {}, "remove_devices": [],
                "add_devices": [], **values}

    def test_only_a_mounted_path_from_the_host_changes_its_directory(self):
        with patch.object(self.modify.host_mounts, "validate_source"):
            self.modify.validate(129, self.changes(change_mounts={"/host-extra": {"source": "/mnt/nas"}}))
            self.modify.validate(129, self.changes(change_mounts={"/media-extra": {"read_only": True}}))
            for change in ({"/nope": {"source": "/mnt/nas"}}, {"/media-extra": {"source": "/mnt/nas"}},
                           {"/host-extra": {"size": 4}}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    self.modify.validate(129, self.changes(change_mounts=change))

    def test_a_changed_path_keeps_its_key_and_options(self):
        calls = []
        self.modify.run.side_effect = lambda *args: calls.append(args) or "\n".join(
            f"{key}: {value}" for key, value in CONFIG.items()) + "\n"
        with patch.object(self.modify, "host_directory", side_effect=lambda path: path), \
                patch.object(self.modify.oci_nested_mounts, "follow"):
            self.modify.apply(129, self.changes(change_mounts={"/host-extra": {"source": "/mnt/nas",
                                                                               "read_only": True}}))
        self.assertIn(("pct", "set", "129", "--mp3", "/mnt/nas,mp=/host-extra,backup=0,ro=1"), calls)

    def test_a_path_that_overlaps_the_data_is_refused(self):
        mount = {"type": "managed-volume", "container_path": "/opt/recipes/mediafiles/sub", "source": "local-lvm",
                 "size_gb": 2}
        with self.assertRaises(ValueError):
            self.modify.validate(129, self.changes(add_mounts=[mount]))

    def test_removing_something_that_is_not_there_is_refused(self):
        with self.assertRaises(ValueError):
            self.modify.validate(129, self.changes(remove_mounts=["/nope"]))
        with self.assertRaises(ValueError):
            self.modify.validate(129, self.changes(remove_devices=["/dev/ttyACM0"]))

    def test_an_unsupported_device_is_refused(self):
        device = {"kind": "character-device", "host_path": "/dev/sda"}
        with self.assertRaises(ValueError):
            self.modify.validate(129, self.changes(add_devices=[device]))

    def test_valid_removals_pass(self):
        self.modify.validate(129, self.changes(remove_mounts=["/media-extra"], remove_devices=["/dev/ttyACM1"]))

    def test_an_updated_application_stops_requiring_a_removed_path(self):
        kept = [{"container_path": "/opt/recipes/mediafiles", "required": True}]
        record = {"installation_id": "id", "stack_member": {"primary_vmid": 129},
                  "observed": {"archive_path": "a", "resolved_registry_digest": "d", "image": {}},
                  "template": {"container_contract": {"volumes": kept + [
                      {"container_path": "/media-extra", "required": True}]}},
                  "deployment": {"replay_profile": {"adapter": "install_tandoor_stack.sh"}, "mounts": []}}
        converted = {"deployment": {"mounts": [{"container_path": "/opt/recipes/mediafiles"}], "devices": []},
                     "template": {"container_contract": {"volumes": kept}}}
        written = {}
        with patch.object(self.modify.instances, "read", return_value=record), \
                patch.object(self.modify.instances, "observe", return_value={"config": {}}), \
                patch.object(self.modify.instances, "location", side_effect=lambda root, vmid: vmid), \
                patch.object(self.modify.instances, "write", side_effect=written.__setitem__), \
                patch.dict(self.modify.CONVERTERS, {"install_tandoor_stack.sh": lambda record: converted}):
            self.modify.register(Path("/nowhere"), 129)
        self.assertEqual(written[129]["template"]["container_contract"]["volumes"], kept)


if __name__ == "__main__":
    unittest.main()
