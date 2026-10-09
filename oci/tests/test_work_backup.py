"""Where the backup taken before changing an application is written."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_work_backup as work

GIB = 1024 ** 3


class Location(unittest.TestCase):
    def locate(self, free, needed=10 * GIB, record=None, storage_free=None, storage_dir=None):
        def available(path):
            return storage_free if storage_dir is not None and Path(path) == storage_dir else free
        with patch.object(work, "required", return_value=needed), patch.object(work, "available", side_effect=available), \
                patch.object(work, "storage_path", return_value=storage_dir):
            return work.locate(Path("/registry/104/transactions/abc"), [104], record or {}, 104)

    def test_a_backup_that_fits_stays_next_to_the_record(self):
        self.assertEqual(self.locate(free=11 * GIB), Path("/registry/104/transactions/abc"))

    def test_without_room_and_without_a_chosen_storage_it_says_what_is_needed(self):
        with self.assertRaises(ValueError) as failure:
            self.locate(free=2 * GIB)
        text = str(failure.exception)
        for expected in ("does not fit on the system disk", "10.0 GB", "2.0 GB", "The application was not modified."):
            self.assertIn(expected, text)
        self.assertNotIn("/registry", text)

    def test_the_chosen_storage_is_used_when_the_system_disk_has_no_room(self):
        with tempfile.TemporaryDirectory() as folder:
            base = self.locate(free=2 * GIB, record={"deployment": {"work_storage": "nas"}},
                               storage_free=50 * GIB, storage_dir=Path(folder))
            self.assertEqual(base, Path(folder) / "proxmenux-oci-work" / "104" / "abc")
            self.assertFalse((Path(folder) / "proxmenux-oci-work").exists())

    def test_a_chosen_storage_without_room_is_named(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError) as failure:
            self.locate(free=2 * GIB, record={"deployment": {"work_storage": "nas"}},
                        storage_free=3 * GIB, storage_dir=Path(folder))
        self.assertIn("nas", str(failure.exception))
        self.assertIn("3.0 GB", str(failure.exception))

    def test_free_space_is_read_where_the_folder_will_be_created(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertGreater(work.available(Path(folder) / "not" / "yet" / "there"), 0)


class Remembering(unittest.TestCase):
    def test_the_folder_of_the_operation_says_where_its_backups_are(self):
        with tempfile.TemporaryDirectory() as folder:
            operation = Path(folder) / "registry" / "abc"
            operation.mkdir(parents=True)
            self.assertEqual(work.recall(operation), operation)
            work.remember(operation, operation)
            self.assertFalse((operation / work.MARK).exists())
            outside = Path(folder) / "nas" / work.FOLDER / "104" / "abc"
            work.remember(operation, outside)
            self.assertEqual(work.recall(operation), outside)

    def test_a_location_that_is_not_one_of_ours_is_never_followed(self):
        with tempfile.TemporaryDirectory() as folder:
            operation = Path(folder)
            (operation / work.MARK).write_text("/etc\n")
            self.assertEqual(work.recall(operation), operation)
            (operation / work.MARK).write_text("relative/proxmenux-oci-work/1/x\n")
            self.assertEqual(work.recall(operation), operation)


class Cleaning(unittest.TestCase):
    def test_the_backups_next_to_the_record_are_deleted_and_the_journal_stays(self):
        with tempfile.TemporaryDirectory() as folder:
            operation = Path(folder)
            (operation / "backup").mkdir()
            (operation / "backup-105").mkdir()
            for name in ("backup/vzdump-lxc-104-x.tar.zst", "backup-105/vzdump-lxc-105-x.tar.zst", "transaction.json"):
                (operation / name).write_text("x")
            work.clear(operation)
            self.assertEqual(sorted(path.name for path in operation.rglob("*") if path.is_file()), ["transaction.json"])

    def test_the_folder_on_another_storage_goes_away_and_the_storage_is_left_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            operation = Path(folder) / "registry" / "abc"
            operation.mkdir(parents=True)
            storage = Path(folder) / "nas"
            base = storage / work.FOLDER / "104" / "abc"
            (base / "backup").mkdir(parents=True)
            (base / "backup" / "vzdump-lxc-104-x.tar.zst").write_text("x")
            (storage / "dump").mkdir()
            (storage / "dump" / "vzdump-lxc-104-kept.tar.zst").write_text("a backup of the user")
            other = storage / work.FOLDER / "200" / "zzz"
            other.mkdir(parents=True)
            work.remember(operation, base)
            work.clear(operation)
            self.assertFalse((storage / work.FOLDER / "104").exists())
            self.assertTrue(other.is_dir())
            self.assertTrue((storage / "dump" / "vzdump-lxc-104-kept.tar.zst").is_file())

    def test_removing_an_application_removes_what_its_operations_left_on_another_storage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "registry"
            operation = root / "104" / "transactions" / "abc"
            operation.mkdir(parents=True)
            base = Path(folder) / "nas" / work.FOLDER / "104" / "abc"
            (base / "backup").mkdir(parents=True)
            (base / "backup" / "vzdump-lxc-104-x.tar.zst").write_text("x")
            work.remember(operation, base)
            work.forget(root, 104)
            self.assertFalse(base.exists())
            self.assertTrue((Path(folder) / "nas").is_dir())


class Choice(unittest.TestCase):
    def test_the_choice_is_kept_in_every_container_of_the_application(self):
        import oci_carried_record
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ids = {104: "11111111-1111-4111-8111-111111111111", 105: "22222222-2222-4222-8222-222222222222"}
            for vmid, extra in ((104, {"stack": {"members": [{"vmid": 104}, {"vmid": 105}]}, "stack_member": {"primary_vmid": 104}}),
                                (105, {"stack_member": {"primary_vmid": 104}})):
                (root / str(vmid)).mkdir()
                (root / str(vmid) / "oci-compose.json").write_text(json.dumps({
                    "schema_version": 1, "vmid": vmid, "installation_id": ids[vmid], "status": "installed",
                    "deployment": {"onboot": True}, **extra}))
            saved = lambda vmid: json.loads((root / str(vmid) / "oci-compose.json").read_text())["deployment"]
            with patch.object(work, "storage_path", return_value=Path(folder)), \
                    patch.object(oci_carried_record, "carry", return_value="carried"):
                self.assertEqual(work.choose(root, 105, "nas"), [104, 105])
                self.assertEqual((saved(104)["work_storage"], saved(105)["work_storage"]), ("nas", "nas"))
                work.choose(root, 104, None)
            self.assertNotIn("work_storage", saved(104))
            self.assertEqual(saved(105), {"onboot": True})

    def test_a_storage_that_does_not_take_backups_is_not_accepted(self):
        with patch.object(work, "storage_path", return_value=None), self.assertRaises(ValueError):
            work.choose(Path("/registry"), 104, "isos")


class Engines(unittest.TestCase):
    def test_a_modification_keeps_what_the_user_chose_for_the_application(self):
        import oci_instance_transaction as transaction
        record = {"status": "installed", "vmid": 109, "installation_id": "x", "template": {"id": "adguard"},
                  "observed": {"config_sha256": "c"},
                  "deployment": {"vmid": 109, "cores": 1, "watchdog": True, "work_storage": "nas"}}
        edited = {"vmid": 109, "installation_id": "x", "template": {"id": "adguard"},
                  "deployment": {"vmid": 109, "cores": 4, "watchdog": False}}
        with patch.object(transaction, "with_default_healthcheck", side_effect=lambda value: value):
            result = transaction.candidate_contract(record, "recreate", {"operation": "recreate", "candidate": edited})
            self.assertEqual(result["deployment"], {"vmid": 109, "cores": 4, "watchdog": True, "work_storage": "nas"})
            record["deployment"] = {"vmid": 109, "cores": 1}
            edited["deployment"]["work_storage"] = "stale"
            result = transaction.candidate_contract(record, "recreate", {"operation": "recreate", "candidate": edited})
        self.assertEqual(result["deployment"], {"vmid": 109, "cores": 4})

    def test_a_stack_asks_for_room_only_until_its_first_backup_exists(self):
        import oci_stack_native as native
        with tempfile.TemporaryDirectory() as folder:
            operation = Path(folder) / "abc"
            operation.mkdir()
            adapter = native.NativeAdapter.__new__(native.NativeAdapter)
            adapter.journal = operation / "transaction.json"
            adapter.plan = {"primary_vmid": 104}
            adapter.records = {104: {"deployment": {}}, 105: {"deployment": {}}}
            with patch.object(native.work_backup, "locate", return_value=operation) as locate:
                self.assertEqual(adapter.work_base(), operation)
                (operation / "backup-105").mkdir()
                self.assertEqual(adapter.work_base(), operation)
            self.assertEqual(locate.call_count, 1)
            self.assertEqual(locate.call_args.args[1:], ([104, 105], {"deployment": {}}, 104))

    def test_an_image_that_does_not_fit_is_refused_before_it_is_downloaded(self):
        import oci_update_current as update
        desired = {"template": {"container_contract": {"image": {"reference": "docker.io/library/app:latest"}}},
                   "deployment": {"template_storage": "local"}}
        candidate = {"manifest_digest": "sha256:" + "a" * 64, "registry_digest": None, "version": "1", "size": 3 * GIB}
        called = []

        def quiet(command, failure, capture=False):
            called.append(command[0])
            return json.dumps(candidate)
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(update, "run_quiet", side_effect=quiet), \
                patch.object(update.transaction, "parse_config", return_value={"arch": "amd64"}), \
                patch.object(update.instances, "command", return_value=(folder + "/image.tar").encode()), \
                patch.object(update.work_backup, "available", return_value=GIB), \
                patch.object(update, "msg_info"), patch.object(update, "msg_ok"), patch.object(update.transaction, "log"):
            with self.assertRaises(ValueError) as failure:
                update.resolve_archive(desired, b"arch: amd64")
        text = str(failure.exception)
        for expected in ("does not fit on the storage where images are downloaded", "local", "1.0 GB", "The application was not modified."):
            self.assertIn(expected, text)
        self.assertNotIn("skopeo", called)


class Menu(unittest.TestCase):
    def ready(self, state, pick=None, unattended=False):
        sys.path.insert(0, str(ROOT / "src"))
        from proxmenux_oci import management
        shown = []

        class UI:
            def message(self, text, title=None):
                shown.append(text)

            def choose(self, title, options, default=None):
                shown.append(options)
                return pick
        ui = UI()
        if unattended:
            ui.unattended = True
        with patch.object(work, "status", return_value=state) as status, patch.object(work, "choose") as choose, \
                patch.object(management, "translate", side_effect=lambda text: text):
            result = management._work_backup_ready(ROOT, ui, 109)
        return result, shown, status, choose

    STATE = {"needed": 10 * GIB, "free": 2 * GIB, "fits": False, "saved": None, "saved_fits": False,
             "candidates": [{"storage": "small", "free": 12 * GIB}, {"storage": "nas", "free": 900 * GIB}]}

    def test_nothing_is_asked_when_the_backup_fits_or_a_storage_with_room_was_chosen(self):
        for state in ({**self.STATE, "fits": True}, {**self.STATE, "saved": "nas", "saved_fits": True}):
            result, shown, _, choose = self.ready(state)
            self.assertTrue(result)
            self.assertEqual(shown, [])
            choose.assert_not_called()

    def test_the_storages_with_room_are_offered_with_the_roomiest_first_and_the_choice_is_saved(self):
        result, shown, _, choose = self.ready(self.STATE, pick="nas")
        self.assertTrue(result)
        self.assertIn("10.0 GB", shown[0])
        self.assertIn("2.0 GB", shown[0])
        self.assertEqual([tag for tag, _ in shown[1]], ["nas", "small"])
        self.assertEqual(choose.call_args.args[1:], (109, "nas"))

    def test_leaving_the_list_or_having_no_storage_with_room_does_not_start_the_operation(self):
        result, _, _, choose = self.ready(self.STATE, pick=None)
        self.assertFalse(result)
        choose.assert_not_called()
        result, shown, _, _ = self.ready({**self.STATE, "candidates": []})
        self.assertFalse(result)
        self.assertEqual(len(shown), 1)
        self.assertIn("No other storage", shown[0])

    def test_a_space_that_cannot_be_measured_leaves_the_answer_to_the_engine(self):
        sys.path.insert(0, str(ROOT / "src"))
        from proxmenux_oci import management
        ui = type("UI", (), {"message": lambda *a, **k: self.fail("nothing is shown"),
                              "choose": lambda *a, **k: self.fail("nothing is asked")})()
        for failure in (RuntimeError("pct failed with exit code 255"), ValueError("a host directory is not available")):
            with patch.object(work, "status", side_effect=failure):
                self.assertTrue(management._work_backup_ready(ROOT, ui, 109))

    def test_a_scheduled_run_asks_nothing_and_lets_the_engine_decide(self):
        result, shown, status, _ = self.ready(self.STATE, unattended=True)
        self.assertTrue(result)
        self.assertEqual(shown, [])
        status.assert_not_called()



class MissingHostDirectory(unittest.TestCase):
    """The disk a shared directory is on is not connected: the container is
    not mounted to be measured, which would leave it locked."""

    def test_the_size_is_not_measured_and_the_directory_is_named(self):
        import oci_instance_transaction as transaction
        with tempfile.TemporaryDirectory() as directory:
            present, missing = Path(directory) / "here", Path(directory) / "gone"
            present.mkdir()
            config = (f"rootfs: local-lvm:vm-111-disk-0,size=4G\nmp0: local-lvm:vm-111-disk-1,mp=/config,backup=1,size=1G\n"
                      f"mp1: {present},mp=/shares/a,backup=0\nmp2: {missing},mp=/shares/b,backup=0\n").encode()
            calls = []

            def run(*args):
                calls.append(args[:2])
                return config if args[1] == "config" else b"MP VOLUME SIZE USED AVAIL USE% PATH\nrootfs x 4G 1G 3G 25% /\n"
            with patch.object(transaction, "run", side_effect=run):
                with self.assertRaisesRegex(ValueError, f"host directory is not available: {missing}"):
                    transaction.backup_size(111)
                self.assertEqual(calls, [("pct", "config")])
                missing.mkdir()
                self.assertEqual(transaction.backup_size(111), 1024 ** 3)


if __name__ == "__main__":
    unittest.main()
