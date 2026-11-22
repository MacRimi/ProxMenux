"""Modify changes the paths of an installed application: the host directory of
any path mounted from the host, the read-only mode and the removal of its extra
paths. Its own data is never removed, and a removed container volume is deleted
once the change is saved."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "remote"))

import oci_instance_transaction as transaction
import oci_native_modify as native
from proxmenux_oci import recreation
from proxmenux_oci.custom_mounts import edit_paths
from proxmenux_oci.ui import UserCancelled
from test_modify_image_reuse import record, CONFIG

MEDIA = {"type": "host-bind", "container_path": "/media", "source": "/mnt/media", "backup": False,
         "read_only": False, "size_gb": None}
CONFIG_VOLUME = {"type": "managed-volume", "container_path": "/config", "source": "local-zfs", "size_gb": 4,
                 "backup": True, "read_only": False}
EXTRA = {"type": "managed-volume", "container_path": "/extra", "source": "local-zfs", "size_gb": 1,
         "backup": True, "read_only": False, "custom": True}
SHARE = {"type": "host-bind", "container_path": "/share", "source": "/mnt/share", "backup": False,
         "read_only": False, "custom": True, "create_if_missing": True}


class ScriptedUI:
    def __init__(self, choices, answers=(), delete=True):
        self.choices, self.answers, self.delete = list(choices), list(answers), delete
        self.offered, self.messages = [], []

    def choose(self, text, options, default=None, **_):
        self.offered.append([tag for tag, _label in options])
        return self.choices.pop(0)

    def ask(self, text, default=None, **_):
        return self.answers.pop(0)

    def confirm(self, text, default=False, **_):
        return self.delete

    def message(self, text, title=None):
        self.messages.append(text)


def view(mount):
    return {"container_path": mount["container_path"], "type": mount["type"], "source": mount["source"],
            "size": None, "read_only": mount["read_only"], "extra": bool(mount.get("custom"))}


@patch("proxmenux_oci.i18n.language", return_value="en")
class EditorTests(unittest.TestCase):
    def paths(self):
        return [view(m) for m in (CONFIG_VOLUME, MEDIA, EXTRA, SHARE)]

    def test_the_own_paths_of_the_application_are_never_removed(self, _):
        ui = ScriptedUI(["/config", "/media", "back", "done"])
        self.assertEqual(edit_paths(ui, self.paths(), "local-zfs"), {"remove": [], "change": {}, "add": []})
        self.assertEqual(len(ui.messages), 1)
        self.assertEqual(ui.offered[2], ["source", "back"])

    def test_a_host_directory_of_the_application_can_change(self, _):
        ui = ScriptedUI(["/media", "source", "done"], answers=["/mnt/nas/media"])
        self.assertEqual(edit_paths(ui, self.paths(), "local-zfs")["change"], {"/media": {"source": "/mnt/nas/media"}})

    def test_an_invalid_directory_is_refused(self, _):
        ui = ScriptedUI(["/media", "source"], answers=["relative/path"])
        with self.assertRaises(ValueError):
            edit_paths(ui, self.paths(), "local-zfs")

    def test_extra_paths_change_their_mode_or_are_removed(self, _):
        ui = ScriptedUI(["/share", "read_only", "/extra", "remove", "done"])
        result = edit_paths(ui, self.paths(), "local-zfs")
        self.assertEqual(result, {"remove": ["/extra"], "change": {"/share": {"read_only": True}}, "add": []})

    def test_a_volume_stays_when_its_deletion_is_not_confirmed(self, _):
        ui = ScriptedUI(["/extra", "remove", "done"], delete=False)
        self.assertEqual(edit_paths(ui, self.paths(), "local-zfs")["remove"], [])

    def test_a_removed_path_drops_its_earlier_change(self, _):
        ui = ScriptedUI(["/share", "source", "/share", "remove", "done"], answers=["/mnt/other"])
        self.assertEqual(edit_paths(ui, self.paths(), "local-zfs"), {"remove": ["/share"], "change": {}, "add": []})

    def test_a_new_path_is_added_and_can_be_edited_before_saving(self, _):
        ui = ScriptedUI(["add", "host-bind", "/scans", "read_only", "done"],
                        answers=["/scans", "/mnt/scans"], delete=False)
        result = edit_paths(ui, self.paths(), "local-zfs")
        self.assertEqual([m["container_path"] for m in result["add"]], ["/scans"])
        self.assertTrue(result["add"][0]["read_only"])
        self.assertEqual(result["change"], {})

    def test_cancelling_discards_the_edit(self, _):
        with self.assertRaises(UserCancelled):
            edit_paths(ScriptedUI(["/extra", "remove", None]), self.paths(), "local-zfs")


class RecordTests(unittest.TestCase):
    def test_changes_reach_the_deployment(self):
        deployment = {"mounts": copy.deepcopy([CONFIG_VOLUME, MEDIA, EXTRA, SHARE])}
        recreation.apply_path_changes(deployment, {"remove": ["/extra"], "add": [],
                                                   "change": {"/media": {"source": "/mnt/nas"},
                                                              "/share": {"read_only": True}}})
        mounts = {m["container_path"]: m for m in deployment["mounts"]}
        self.assertEqual(sorted(mounts), ["/config", "/media", "/share"])
        self.assertEqual((mounts["/media"]["source"], mounts["/media"]["create_if_missing"]), ("/mnt/nas", True))
        self.assertTrue(mounts["/share"]["read_only"])

    def test_system_paths_and_files_are_not_offered(self):
        deployment = {"mounts": [MEDIA, {"type": "host-bind", "container_path": "/host/proc", "source": "/proc/"},
                                 {"type": "host-bind", "container_path": "/etc/app.conf", "source": __file__}]}
        self.assertEqual([m["container_path"] for m in recreation.editable_paths(deployment)], ["/media"])


class NativeModifyTests(unittest.TestCase):
    def setUp(self):
        self.record = record()
        self.record["deployment"]["mounts"] = [copy.deepcopy(MEDIA), copy.deepcopy(EXTRA)]
        self.config = (CONFIG + b"mp0: /mnt/media,mp=/media,backup=0\n"
                       b"mp1: local-zfs:subvol-115-disk-1,mp=/extra,backup=1,size=1G\n")
        self.candidate = copy.deepcopy(self.record)
        patcher = patch.object(native.transaction, "preflight")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_host_directory_of_an_own_path_changes_in_place(self):
        self.candidate["deployment"]["mounts"][0].update(source="/mnt/nas", create_if_missing=True)
        self.assertEqual(native.changes(self.record, self.candidate, self.config), {"mounts"})
        values = native.plan(self.record, self.candidate, self.config)["values"]
        self.assertEqual(values["mp0"], "/mnt/nas,mp=/media,backup=0,ro=0")

    def test_the_volume_of_a_removed_path_is_named_for_deletion(self):
        self.candidate["deployment"]["mounts"] = [copy.deepcopy(MEDIA)]
        self.assertEqual(native.removed_volumes(self.candidate, self.config), ["local-zfs:subvol-115-disk-1"])
        self.assertEqual(native.plan(self.record, self.candidate, self.config)["delete"], ["mp1"])

    def test_the_detached_volume_is_deleted_and_the_record_observes_it(self):
        detached = CONFIG + b"mp0: /mnt/media,mp=/media,backup=0\nunused0: local-zfs:subvol-115-disk-1\n"
        saved, written, commands = copy.deepcopy(self.record), {}, []
        with patch.object(native.instances, "command", return_value=detached), \
                patch.object(native.transaction, "run", side_effect=lambda *args: commands.append(args)), \
                patch.object(native.instances, "read", return_value=saved), \
                patch.object(native.instances, "observe", return_value={"config": "fresh"}), \
                patch.object(native.instances, "location", return_value=Path("/nowhere")), \
                patch.object(native.instances, "write", side_effect=written.__setitem__):
            native.delete_removed_volumes(Path("/nowhere"), 115, ["local-zfs:subvol-115-disk-1"])
        self.assertEqual(commands, [("pct", "set", "115", "--delete", "unused0")])
        self.assertEqual(written[Path("/nowhere")]["observed"], {"config": "fresh"})


class RecreatedContainerTests(unittest.TestCase):
    def test_only_the_removed_volumes_leave_the_data_holder(self):
        state = {"stage": 900, "id": "abc",
                 "record": {"deployment": {"mounts": [CONFIG_VOLUME, EXTRA, SHARE]}}}
        candidate = {"deployment": {"mounts": [CONFIG_VOLUME]}}
        holder = [b"description: proxmenux-transaction=abc\n"
                  b"mp0: local-zfs:subvol-900-disk-1,mp=/extra,backup=1\n"
                  b"mp1: local-zfs:subvol-900-disk-2,mp=/kept,backup=1\n",
                  b"description: proxmenux-transaction=abc\nunused0: local-zfs:subvol-900-disk-1\n"]
        commands = []
        with patch.object(transaction, "owned", side_effect=lambda vmid, marker: holder.pop(0) if len(holder) > 1 else holder[0]), \
                patch.object(transaction, "run", side_effect=lambda *args: commands.append(args)), \
                patch.object(transaction, "log"):
            transaction.delete_removed_volumes(state, candidate)
        self.assertEqual(commands, [("pct", "set", "900", "--delete", "mp0"),
                                    ("pct", "set", "900", "--delete", "unused0")])


if __name__ == "__main__":
    unittest.main()
