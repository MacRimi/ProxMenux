"""VM/CT backup jobs API: what reaches pvesh, with pvesh itself replaced."""
import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from flask import Flask
except ImportError:
    Flask = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "AppImage/scripts"))

JOB = {"id": "backup-nightly", "all": 0, "vmid": "100,101", "storage": "local", "schedule": "02:00",
       "mode": "snapshot", "compress": "zstd", "enabled": 1, "prune-backups": {"keep-last": 3, "keep-weekly": 2},
       "notes-template": "{{guestname}}", "next-run": 1790000000, "type": "vzdump"}
NODES = [{"node": "pve1", "status": "online"}, {"node": "pve2", "status": "online"}, {"node": "pve3", "status": "offline"}]
GUESTS = [{"vmid": 100, "name": "web", "type": "qemu", "node": "pve1"},
          {"vmid": 101, "name": "db", "type": "lxc", "node": "pve1"},
          {"vmid": 200, "name": "other", "type": "qemu", "node": "pve2"}]


@unittest.skipIf(Flask is None, "Flask runtime required")
class VmBackupJobsApiTests(unittest.TestCase):
    def setUp(self):
        middleware = types.ModuleType("jwt_middleware")
        self.guards = []

        def guard(name):
            def decorator(function):
                self.guards.append((name, function.__name__))
                return function
            return decorator
        middleware.require_auth = guard("auth")
        middleware.require_admin_scope = guard("admin")
        with patch.dict(sys.modules, jwt_middleware=middleware):
            sys.modules.pop("flask_vm_backup_routes", None)
            self.routes = importlib.import_module("flask_vm_backup_routes")
        self.addCleanup(lambda: sys.modules.pop("flask_vm_backup_routes", None))
        app = Flask(__name__)
        app.register_blueprint(self.routes.vm_backup_bp)
        self.client = app.test_client()
        self.calls = []
        self.job = json.loads(json.dumps(JOB))

    def pvesh(self, failing=()):
        def run(args, timeout=25):
            self.calls.append(list(args))
            if args[:2] == ["get", "/cluster/backup"]:
                return True, json.dumps([self.job])
            if args[0] == "get" and args[1].startswith("/cluster/backup/"):
                return True, json.dumps(self.job)
            if args[:2] == ["get", "/nodes"]:
                return True, json.dumps(NODES)
            if args[:2] == ["get", "/cluster/resources"]:
                return True, json.dumps(GUESTS)
            if args[:2] == ["get", "/storage"]:
                return True, json.dumps([{"storage": "local", "type": "dir", "content": "iso,backup"},
                                         {"storage": "isos", "type": "dir", "content": "iso,vztmpl"}])
            if args[0] == "create" and args[1].endswith("/vzdump"):
                node = args[1].split("/")[2]
                if node in failing:
                    return False, "storage is not online"
                return True, f'"UPID:{node}:0001:0002:0003:vzdump::root@pam:"\n'
            return True, ""
        return patch.object(self.routes, "_pvesh", side_effect=run)

    def changes(self):
        return [call for call in self.calls if call[0] in ("create", "set", "delete")]

    def test_reading_needs_a_session_and_changing_needs_an_administrator(self):
        guards = dict((name, kind) for kind, name in self.guards)
        self.assertEqual({name for name, kind in guards.items() if kind == "auth"}, {"list_jobs", "options", "get_job"})
        self.assertEqual({name for name, kind in guards.items() if kind == "admin"},
                         {"create_job", "update_job", "delete_job", "toggle_job", "run_job"})

    def test_the_list_gives_text_properties_and_the_host_backups_that_hang_from_a_job(self):
        with self.pvesh(), patch.object(self.routes, "_host_backups_attached",
                                        return_value={"backup-nightly": ["hostcfg-attached-local"]}):
            answer = self.client.get("/api/vm-backup-jobs").get_json()
        job = answer["jobs"][0]
        self.assertEqual(job["prune-backups"], "keep-last=3,keep-weekly=2")
        self.assertEqual(job["host_backups"], ["hostcfg-attached-local"])

    def test_only_storages_that_take_backups_are_offered(self):
        with self.pvesh():
            answer = self.client.get("/api/vm-backup-jobs/options").get_json()
        self.assertEqual([storage["id"] for storage in answer["storages"]], ["local"])
        self.assertEqual([guest["vmid"] for guest in answer["guests"]], [100, 101, 200])

    def test_a_new_job_reaches_proxmox_with_its_fields(self):
        with self.pvesh():
            answer = self.client.post("/api/vm-backup-jobs", json={
                "id": "nightly", "all": 0, "vmid": "100, 101", "storage": "local", "schedule": "mon..fri 01:30",
                "mode": "stop", "compress": "zstd", "prune_backups": "keep-last=3", "notes_template": "{{guestname}}"})
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(self.changes(), [[
            "create", "/cluster/backup", "--vmid", "100,101", "--all", "0", "--storage", "local",
            "--schedule", "mon..fri 01:30", "--mode", "stop", "--compress", "zstd", "--prune-backups", "keep-last=3",
            "--notes-template", "{{guestname}}", "--id", "nightly", "--enabled", "1"]])

    def test_what_is_not_a_valid_value_never_reaches_proxmox(self):
        good = {"all": 1, "storage": "local", "schedule": "02:00"}
        bad = [{"storage": "local; rm -rf /"}, {"storage": "--delete"}, {"schedule": "--all 1"}, {"schedule": "02:00\n--storage x"},
               {"mode": "fast"}, {"compress": "xz"}, {"prune_backups": "keep-last=3 --all 1"}, {"prune_backups": "forever"},
               {"notes_template": "-x"}, {"all": 0, "vmid": "100;200"}, {"all": 0, "vmid": ""}, {"id": "../etc"}, {"id": "-x"}]
        with self.pvesh():
            for change in bad:
                answer = self.client.post("/api/vm-backup-jobs", json={**good, **change})
                self.assertEqual(answer.status_code, 400, change)
            for name in ("..", "a b", "x;y", "-x"):
                self.assertIn(self.client.delete(f"/api/vm-backup-jobs/{name}").status_code, (400, 404), name)
        self.assertEqual(self.changes(), [])

    def test_a_change_only_sends_what_changed_and_clears_what_was_emptied(self):
        with self.pvesh():
            answer = self.client.put("/api/vm-backup-jobs/backup-nightly", json={
                "all": 1, "storage": "pbs", "prune_backups": "", "notes_template": ""})
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(self.changes(), [[
            "set", "/cluster/backup/backup-nightly", "--all", "1", "--storage", "pbs",
            "--delete", "vmid", "--delete", "prune-backups", "--delete", "notes-template"]])

    def test_toggling_flips_what_the_job_has_now(self):
        with self.pvesh():
            self.assertEqual(self.client.post("/api/vm-backup-jobs/backup-nightly/toggle").get_json()["enabled"], False)
            self.job["enabled"] = 0
            self.assertEqual(self.client.post("/api/vm-backup-jobs/backup-nightly/toggle").get_json()["enabled"], True)
        self.assertEqual([call[-1] for call in self.changes()], ["0", "1"])

    def test_running_starts_a_task_on_each_node_that_hosts_a_guest_of_the_job(self):
        with self.pvesh():
            answer = self.client.post("/api/vm-backup-jobs/backup-nightly/run").get_json()
        self.assertEqual([task["node"] for task in answer["tasks"]], ["pve1"])
        self.assertTrue(answer["tasks"][0]["upid"].startswith("UPID:pve1:"))
        started = self.changes()
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0][:2], ["create", "/nodes/pve1/vzdump"])
        options = dict(zip(started[0][2::2], started[0][3::2]))
        self.assertEqual(options, {"--all": "0", "--compress": "zstd", "--mode": "snapshot", "--notes-template": "{{guestname}}",
                                   "--prune-backups": "keep-last=3,keep-weekly=2", "--storage": "local", "--vmid": "100,101"})

    def test_a_job_of_every_guest_runs_on_every_online_node_and_reports_the_ones_that_fail(self):
        self.job.update(all=1, vmid=None)
        with self.pvesh(failing=("pve2",)):
            answer = self.client.post("/api/vm-backup-jobs/backup-nightly/run").get_json()
        self.assertEqual([task["node"] for task in answer["tasks"]], ["pve1"])
        self.assertEqual([failure["node"] for failure in answer["failures"]], ["pve2"])
        self.assertNotIn("/nodes/pve3/vzdump", [call[1] for call in self.calls])

    def test_a_job_whose_guests_are_on_no_online_node_starts_nothing(self):
        self.job["vmid"] = "999"
        with self.pvesh():
            answer = self.client.post("/api/vm-backup-jobs/backup-nightly/run")
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(self.changes(), [])

    def test_host_backups_are_matched_by_the_job_they_name(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "hostcfg-a.env").write_text("JOB_ID=hostcfg-a\nPVE_STORAGE=local\nPVE_PARENT_JOB=backup-nightly\n")
            Path(folder, "hostcfg-b.env").write_text("JOB_ID=hostcfg-b\nON_CALENDAR=daily\n")
            Path(folder, "notes.txt").write_text("PVE_PARENT_JOB=backup-nightly\n")
            with patch.object(self.routes, "HOST_BACKUP_JOBS", folder):
                self.assertEqual(self.routes._host_backups_attached(), {"backup-nightly": ["hostcfg-a"]})
        with patch.object(self.routes, "HOST_BACKUP_JOBS", "/nonexistent"):
            self.assertEqual(self.routes._host_backups_attached(), {})


if __name__ == "__main__":
    unittest.main()
