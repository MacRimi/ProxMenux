"""Audit regression fixtures. No host probes, daemon or production database."""
import json
import copy
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "AppImage/scripts"))
import audit_checks as engine
import audit_checks_pve as checks
import audit_store as store
import audit_policy


def evaluate(fn, ctx):
    result = fn(ctx)
    if result is not None:
        check = next(c for c in engine.registered_checks() if c.evaluate == fn)
        result = {**result, "classification": engine._classification_of(result, check)}
    return result


HEADER = "Volid Format Type Size VMID\n"


class Context:
    node = "fixture"
    lxc_configs = {101: "hostname: one\nunprivileged: 1\n", 102: "hostname: two\nunprivileged: 1\n"}
    qemu_configs = {}
    cluster_configs = {}
    vzdump_jobs = "vzdump: daily\n all 1\n schedule daily\n storage backups\n"
    pve_user_cfg = ""
    storages = [{"id": "backups", "type": "dir", "content": "backup"}]
    apt_sources = {}
    monitor_snapshot = {}
    storage_snapshot = {"rows": [], "source": "fixture", "collected_at": 123, "units": "bytes"}

    def __init__(self, **values):
        for key, value in type(self).__dict__.items():
            if not key.startswith("_") and not callable(value):
                setattr(self, key, copy.deepcopy(value))
        self.policy = audit_policy.Policy()
        self.responses = {}
        self.files = {}
        self.__dict__.update(values)

    def run(self, argv, **kwargs):
        if tuple(argv) in self.responses:
            return self.responses[tuple(argv)]
        if argv[:2] == ["pvesm", "list"]:
            return (0, HEADER)
        if argv == ["pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json"]:
            return (0, "[]")
        raise AssertionError(f"Unmocked probe: {argv}")

    def read(self, path, **kwargs):
        return self.files.get(str(path), "")


class CheckTests(unittest.TestCase):
    def backup(self, vmid=101, age=0):
        stamp = time.strftime("%Y_%m_%d-%H_%M_%S", time.localtime(time.time() - age))
        return f"backups:backup/vzdump-lxc-{vmid}-{stamp}.tar.zst zst backup 1024 {vmid}\n"

    def test_missing_second_backup_is_not_pass(self):
        ctx = Context(responses={("pvesm", "list", "backups"): (0, HEADER + self.backup())})
        result = evaluate(checks._last_backup_age, ctx)
        self.assertEqual(result["classification"], "warning")
        self.assertEqual(result["affected"][0]["vmid"], 102)

    def test_no_backups_is_not_not_applicable(self):
        self.assertEqual(evaluate(checks._last_backup_age, Context())["classification"], "warning")

    def test_no_storage_is_missing_backup(self):
        self.assertEqual(evaluate(checks._last_backup_age, Context(storages=[]))["classification"], "warning")

    def test_unreadable_destination_is_unknown_not_missing(self):
        ctx = Context(responses={("pvesm", "list", "backups"): (1, "offline")})
        result = evaluate(checks._last_backup_age, ctx)
        self.assertEqual(result["classification"], "unverified")
        self.assertEqual(result.get("affected", []), [])

    def test_bad_inventory_is_unknown(self):
        ctx = Context(responses={("pvesm", "list", "backups"): (0, "unexpected")})
        self.assertEqual(evaluate(checks._last_backup_age, ctx)["classification"], "unverified")

    def test_mixed_storage_host_archives_and_isos_not_guest_copies(self):
        ctx = Context(lxc_configs={101: ""}, responses={
            ("pvesm", "list", "backups"): (0, HEADER + self.backup() +
                "backups:iso/install.iso iso iso 100\n" +
                "backups:backup/hostcfg-daily-20260905_000000.tar.zst tar.zst backup 200\n")})
        result = evaluate(checks._last_backup_age, ctx)
        self.assertEqual(result["classification"], "conformant")
        self.assertFalse(result["incomplete"])
        self.assertIn("not counted", result["evidence"])

    def test_backup_without_vmid_column_can_use_vzdump_identity(self):
        ctx = Context(lxc_configs={101: ""}, responses={
            ("pvesm", "list", "backups"): (0, HEADER + self.backup().rsplit(" ", 1)[0] + "\n")})
        self.assertEqual(evaluate(checks._last_backup_age, ctx)["classification"], "conformant")

    def test_daily_job_older_than_two_days_is_stale(self):
        ctx = Context(lxc_configs={101: ""}, responses={
            ("pvesm", "list", "backups"): (0, HEADER + self.backup(age=2 * 86400))})
        self.assertEqual(evaluate(checks._last_backup_age, ctx)["classification"], "warning")

    def test_unsupported_schedule_is_explicit(self):
        self.assertIsNone(checks._schedule_age_limit("mon..fri */2:00"))
        self.assertIsNone(checks._schedule_age_limit("99:99"))

    def test_job_on_other_node_does_not_cover_local_guest(self):
        ctx = Context(vzdump_jobs="vzdump: remote\n all 1\n node other\n")
        self.assertEqual(evaluate(checks._guest_coverage, ctx)["classification"], "observation")

    def test_disabled_destination_is_not_probed(self):
        ctx = Context(storages=[{"id": "disabled", "type": "dir", "content": "backup", "disable": "1"}])
        self.assertIsNone(evaluate(checks._destination_reachable, ctx))

    def test_all_storage_types_and_dependencies(self):
        storages = [{"id": t, "type": t, "content": "images"} for t in
                    ("dir", "zfspool", "lvmthin", "nfs", "cifs", "iscsi", "pbs")]
        ctx = Context(storages=storages, lxc_configs={101: "rootfs: nfs:101/disk.raw\n"},
                      qemu_configs={200: "scsi0: iscsi:volume\n[old]\nscsi1: cifs:old\n"},
                      storage_snapshot={"rows": [{"name": s["id"], "node": "fixture",
                          "status": "available", "total": 100, "used": 20} for s in storages]})
        ctx.run = lambda argv, **kw: (0, "[]") if argv == ["pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json"] else self.fail("storage check must not probe remote storage")
        result = evaluate(checks._destination_reachable, ctx)
        self.assertEqual(result["classification"], "conformant")
        self.assertEqual(result["summary_params"]["total"], 7)
        rows = {r["storage"]: r for r in result["observations"]}
        self.assertEqual(rows["nfs"]["dependencies"][0]["vmid"], 101)
        self.assertEqual(rows["iscsi"]["dependencies"][0]["vmid"], 200)
        self.assertEqual(rows["cifs"]["dependencies"], [])

    def test_storage_missing_metadata_is_unknown(self):
        self.assertEqual(evaluate(checks._destination_reachable, Context())["classification"], "unverified")

    def test_cached_missing_resource_is_not_confirmed_outage(self):
        ctx = Context(storage_snapshot={"rows": [{"name": "backups", "node": "fixture",
                       "status": "error", "status_detail": "not_found"}]})
        self.assertEqual(evaluate(checks._destination_reachable, ctx)["classification"], "unverified")

    def test_pbs_unknown_capacity_not_full_or_failed(self):
        ctx = Context(storage_snapshot={"rows": [{"name": "backups", "node": "fixture",
                       "status": "namespace_restricted", "total": 0, "used": 0}]})
        result = evaluate(checks._destination_reachable, ctx)
        self.assertEqual(result["classification"], "conformant")
        self.assertFalse(result["observations"][0]["capacity_known"])

    def test_unavailable_and_full_network_storage(self):
        ctx = Context(storages=[{"id": "nas", "type": "nfs", "content": "images"}],
                      storage_snapshot={"rows": [{"name": "nas", "node": "fixture",
                           "status": "available", "total": 100, "used": 95}]})
        self.assertEqual(evaluate(checks._destination_reachable, ctx)["classification"], "warning")
        ctx.storage_snapshot["rows"][0]["status"] = "unavailable"
        self.assertEqual(evaluate(checks._destination_reachable, ctx)["classification"], "warning")

    def test_storage_credentials_not_in_evidence(self):
        ctx = Context(storages=[{"id": "nas", "type": "cifs", "password": "SECRET",
                                "username": "PRIVATE", "content": "images"}])
        result = evaluate(checks._destination_reachable, ctx)
        self.assertNotIn("SECRET", result["evidence"])
        self.assertNotIn("PRIVATE", result["evidence"])

    def test_other_node_storage_never_assessed(self):
        ctx = Context(storages=[{"id": "remote", "type": "pbs", "nodes": "other"}])
        self.assertIsNone(evaluate(checks._destination_reachable, ctx))

    def two_destinations(self):
        return Context(lxc_configs={101: ""}, storages=[
            {"id": name, "type": "pbs", "content": "backup"} for name in ("backups", "second")],
            vzdump_jobs="vzdump: first\n all 1\n storage backups\n schedule daily\nvzdump: second\n all 1\n storage second\n schedule weekly\n",
            responses={("pvesm", "list", "backups"): (0, HEADER + self.backup())})

    def test_recent_pbs_cannot_mask_missing_second_destination(self):
        result = evaluate(checks._last_backup_age, self.two_destinations())
        self.assertEqual(result["classification"], "warning")
        self.assertEqual(result["affected"][0]["storage"], "second")
        self.assertEqual(result["summary_params"]["total"], 2)

    def test_second_pbs_failure_does_not_claim_missing_copy(self):
        ctx = self.two_destinations()
        ctx.responses[("pvesm", "list", "second")] = (1, "offline")
        result = evaluate(checks._last_backup_age, ctx)
        self.assertEqual(result["classification"], "unverified")
        self.assertEqual(result.get("affected", []), [])

    def test_each_destination_has_own_schedule(self):
        ctx = self.two_destinations()
        ctx.responses[("pvesm", "list", "second")] = (0, HEADER + self.backup(age=3 * 86400))
        self.assertEqual(evaluate(checks._last_backup_age, ctx)["classification"], "conformant")
        ctx.responses[("pvesm", "list", "second")] = (0, HEADER + self.backup(age=11 * 86400))
        self.assertEqual(evaluate(checks._last_backup_age, ctx)["affected"][0]["storage"], "second")

    def test_missing_target_configuration_is_reported(self):
        ctx = self.two_destinations()
        ctx.storages = ctx.storages[:1]
        self.assertEqual(evaluate(checks._last_backup_age, ctx)["affected"][0]["storage"], "second")

    def test_failure_elsewhere_does_not_hide_missing_expected_copy(self):
        ctx = self.two_destinations()
        ctx.responses[("pvesm", "list", "backups")] = (1, "offline")
        result = evaluate(checks._last_backup_age, ctx)
        self.assertEqual(result["classification"], "warning")
        self.assertTrue(result["incomplete"])
        self.assertEqual(result["affected"][0]["storage"], "second")

    def test_templates_are_not_missing_backups(self):
        ctx = Context(lxc_configs={101: "template: 1\n"})
        self.assertIsNone(evaluate(checks._guest_coverage, ctx))
        self.assertIsNone(evaluate(checks._last_backup_age, ctx))

    def test_bind_mount_and_backup_zero_are_reported(self):
        ctx = Context(lxc_configs={101: "rootfs: local:vm-101-disk-0\nmp0: /data,mp=/data,backup=1\nmp1: local:vm-101-disk-1,mp=/x,backup=0\n"})
        result = evaluate(checks._guest_coverage, ctx)
        self.assertEqual(result["summary_key"], "excludedData")
        self.assertEqual(len(result["affected"]), 2)

    def test_old_snapshot_cannot_override_current_privileged_state(self):
        ctx = Context(lxc_configs={101: "unprivileged: 0\n[old]\nunprivileged: 1\n"})
        self.assertEqual(evaluate(checks._privileged_containers, ctx)["classification"], "observation")

    def test_agent_options_order(self):
        ctx = Context(qemu_configs={101: "agent: fstrim_cloned_disks=1,enabled=1\n"})
        self.assertEqual(evaluate(checks._qemu_without_agent, ctx)["classification"], "conformant")

    def test_disabled_deb822_is_not_enterprise_enabled(self):
        ctx = Context(apt_sources={"pve.sources": "Types: deb\nURIs: https://enterprise.proxmox.com/debian/pve\nEnabled: no\n"})
        self.assertEqual(evaluate(checks._enterprise_repo, ctx)["classification"], "observation")

    def test_orphan_inventory_failure_cannot_pass(self):
        ctx = Context(storages=[{"id": "local", "type": "dir", "content": "images"}],
                      responses={("pvesm", "list", "local"): (1, "offline")})
        self.assertEqual(evaluate(checks._orphaned_volumes, ctx)["classification"], "unverified")

    def test_unreferenced_volume_with_existing_vmid_is_candidate(self):
        ctx = Context(storages=[{"id": "local", "type": "dir", "content": "images"}],
                      responses={("pvesm", "list", "local"): (0, HEADER + "local:101/vm-101-disk-9.raw raw images 1 101\n")})
        self.assertEqual(evaluate(checks._orphaned_volumes, ctx)["classification"], "observation")

    def test_unused_snapshot_and_template_base_are_protected(self):
        ctx = Context(lxc_configs={}, qemu_configs={101: "unused0: local:vm-101-disk-0\n[old]\nscsi0: local:vm-101-disk-1\n"},
                      storages=[{"id": "local", "type": "lvmthin", "content": "images"}], responses={
                          ("pvesm", "list", "local"): (0, HEADER +
                              "local:vm-101-disk-0 raw images 1 101\nlocal:vm-101-disk-1 raw images 1 101\nlocal:base-999-disk-0 raw images 1 999\n")})
        self.assertEqual(evaluate(checks._orphaned_volumes, ctx)["classification"], "conformant")

    def test_orphan_on_guestless_host(self):
        ctx = Context(lxc_configs={}, storages=[{"id": "local", "type": "dir", "content": "images"}],
                      responses={("pvesm", "list", "local"): (0, HEADER + "local:101/vm-101-disk-0.raw raw images 1 101\n")})
        self.assertEqual(evaluate(checks._orphaned_volumes, ctx)["classification"], "observation")

    def scrub_context(self, scan):
        ctx = Context(responses={("zpool", "list", "-H", "-o", "name"): (0, "tank\n"),
                                  ("zpool", "status", "tank"): (0, "  scan: " + scan)})
        return ctx

    @patch.object(Path, "exists", return_value=True)
    def test_resilver_is_not_scrub(self, _):
        ctx = self.scrub_context("resilvered 1G in 1h on " + time.ctime())
        self.assertEqual(evaluate(checks._zfs_scrub_age, ctx)["classification"], "unverified")

    @patch.object(Path, "exists", return_value=True)
    def test_one_never_scrubbed_pool_is_not_hidden(self, _):
        ctx = self.scrub_context("scrub repaired 0B in 1h with 0 errors on " + time.ctime())
        ctx.responses[("zpool", "list", "-H", "-o", "name")] = (0, "tank\nother\n")
        ctx.responses[("zpool", "status", "other")] = (0, "scan: none requested")
        self.assertEqual(evaluate(checks._zfs_scrub_age, ctx)["classification"], "warning")

    def test_storage_inherited_retention(self):
        ctx = Context(storages=[{"id": "backups", "type": "dir", "content": "backup", "prune-backups": "keep-last=7"}])
        self.assertEqual(evaluate(checks._retention_defined, ctx)["classification"], "conformant")

    def test_pbs_remote_retention_is_not_declared_absent(self):
        ctx = Context(storages=[{"id": "backups", "type": "pbs", "content": "backup"}])
        self.assertEqual(evaluate(checks._retention_defined, ctx)["classification"], "observation")

    def test_firewall_default_host_enable(self):
        ctx = Context(files={"/etc/pve/firewall/cluster.fw": "[OPTIONS]\nenable: 1\n"})
        self.assertEqual(evaluate(checks._host_firewall, ctx)["classification"], "conformant")

    def test_firewall_other_section_not_an_enable_option(self):
        ctx = Context(files={"/etc/pve/firewall/cluster.fw": "[RULES]\nenable: 1\n"})
        self.assertEqual(evaluate(checks._host_firewall, ctx)["classification"], "observation")

    def test_no_smart_cache_does_not_start_smartctl(self):
        ctx = Context()
        ctx.run = lambda *a, **kw: self.fail("must not run any disk command")
        self.assertEqual(evaluate(checks._disk_service_life, ctx)["classification"], "unverified")

    def test_ha_managed_guest_does_not_need_onboot(self):
        ctx = Context(lxc_configs={101: "onboot: 0\n"}, files={"/etc/pve/ha/resources.cfg": "ct: 101\n state started\n"})
        self.assertEqual(evaluate(checks._autostart, ctx)["classification"], "conformant")

    def test_legacy_jobs_parse_without_execution(self):
        jobs = checks._parse_vzdump_jobs("0 2 * * * root /usr/sbin/vzdump 101 102 --storage backups --all 0\n")
        self.assertEqual(jobs[0]["vmid"], "101 102")
        self.assertEqual(jobs[0]["storage"], "backups")

    def test_another_job_type_ends_vzdump_section(self):
        jobs = checks._parse_vzdump_jobs("vzdump: a\n all 1\nother: b\n enabled 0\n")
        self.assertNotIn("enabled", jobs[0])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(store, "DB_PATH", Path(self.temp.name) / "audit.db")
        self.db_patch.start()
        store._schema_ready = False
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.db_patch.stop)
        self.addCleanup(lambda: setattr(store, "_schema_ready", False))

    def finding(self, objects=None, state="warn"):
        f = {"check_id": "guests.test", "area": "guests", "severity": "WARNING", "state": state,
             "raw_state": state, "classification": store.classification_of(state, "WARNING"),
             "raw_classification": store.classification_of(state, "WARNING"), "affected": objects or [{"vmid": 101}], "check_version": 2, "host": "fixture"}
        f["scope"] = store.finding_scope(f)
        return f

    def recorded(self, f):
        run = store.start_run("full")
        store.record_findings(run, [f])
        store.finish_run(run, checks_total=1)
        return run

    def test_accept_and_revoke_immediate_without_mutating_history(self):
        f = self.finding()
        run = self.recorded(f)
        store.accept_risk(f["check_id"], "lab", "operator", scope=f["scope"])
        self.assertEqual(store.effective_findings(run)[0]["state"], "accepted")
        self.assertEqual(store.get_findings(run)[0]["state"], "warn")
        store.revoke_risk(f["check_id"], "operator")
        self.assertEqual(store.effective_findings(run)[0]["state"], "warn")
        self.assertEqual(len(store.exception_history()), 2)

    def test_acceptance_does_not_extend_to_new_guest(self):
        f = self.finding()
        self.recorded(f)
        store.accept_risk(f["check_id"], "lab", "operator", scope=f["scope"])
        newer = self.recorded(self.finding([{"vmid": 101}, {"vmid": 102}]))
        self.assertEqual(store.effective_findings(newer)[0]["state"], "warn")

    def test_expiry_is_effective_without_new_scan(self):
        f = self.finding()
        run = self.recorded(f)
        expiry = int(time.time()) + 60
        store.accept_risk(f["check_id"], "lab", "operator", expiry, scope=f["scope"])
        with patch.object(store.time, "time", return_value=expiry + 1):
            self.assertEqual(store.effective_findings(run)[0]["state"], "warn")

    def test_accepted_snapshot_survives_revocation(self):
        f = self.finding()
        store.accept_risk(f["check_id"], "lab", "operator", scope=f["scope"])
        f.update(decision=store.DECISION_ACCEPTED, exception=store.active_exceptions()[f["check_id"]])
        run = self.recorded(f)
        store.revoke_risk(f["check_id"])
        self.assertEqual(store.get_findings(run)[0]["exception"]["reason"], "lab")
        self.assertEqual(store.effective_findings(run)[0]["state"], "warn")

    def test_scope_ignores_age_but_not_rule_or_severity(self):
        a = self.finding([{"vmid": 101, "days": 40}])
        b = self.finding([{"vmid": 101, "days": 41}])
        self.assertEqual(a["scope"], b["scope"])
        b["check_version"] = 3
        self.assertNotEqual(a["scope"], store.finding_scope(b))

    def test_new_failure_visible_instead_of_old_complete_run(self):
        self.recorded(self.finding())
        run = store.start_run("full")
        store.finish_run(run, checks_total=0, error="interrupted")
        self.assertEqual(store.latest_run()["run_id"], run)

    def test_no_false_resolved_when_collection_failed(self):
        before = self.recorded(self.finding())
        after = self.recorded(self.finding(state="unknown"))
        result = engine.compare_runs(before, after)
        self.assertEqual(result["resolved"], [])
        self.assertEqual(len(result["unverified"]), 1)

    def test_acceptance_is_not_resolution_and_class_changes_are_visible(self):
        before = self.recorded(self.finding())
        accepted = self.finding()
        accepted['decision'] = store.DECISION_ACCEPTED
        after = self.recorded(accepted)
        result = engine.compare_runs(before, after)
        self.assertEqual(len(result['accepted']), 1)
        self.assertFalse(result['resolved'])
        critical = self.finding()
        critical.update(classification='critical', raw_classification='critical')
        changed = self.recorded(critical)
        self.assertEqual(len(engine.compare_runs(before, changed)['new']), 1)
        self.assertEqual(len(engine.compare_runs(changed, before)['new']), 1)

    def test_malformed_result_does_not_abort_remaining_checks(self):
        for bad in (False, [], {'affected': [None]}, {'affected': 'invalid'}):
            with self.subTest(result=bad), patch.object(engine.AuditContext, 'metadata', return_value={}), patch.object(
                    engine, 'registered_checks', return_value=[
                        engine.Check('guests.bad', 'guests', 'WARNING', lambda ctx: bad),
                        engine.Check('guests.good', 'guests', 'WARNING', lambda ctx: {'classification':'conformant'})]):
                run = engine.run_assessment()
                results = {f['check_id']: f['classification'] for f in store.get_findings(run)}
                self.assertEqual(results, {'guests.bad':'unverified', 'guests.good':'conformant'})
                self.assertEqual(store.get_run(run)['status'], 'partial')

    def test_interrupted_run_marked_failed(self):
        run = store.start_run("full")
        store.recover_interrupted_runs()
        self.assertEqual(store.get_run(run)["status"], "failed")

    def test_secrets_are_redacted_before_persistence(self):
        f = self.finding()
        f["evidence"] = "https://alice:secret@example.com/x?token=abc\nAuthorization: Bearer xyz"
        run = self.recorded(f)
        evidence = store.get_findings(run)[0]["evidence"]
        self.assertNotIn("alice", evidence)
        self.assertNotIn("abc", evidence)
        self.assertNotIn("xyz", evidence)

    def test_raising_check_is_unknown_and_run_partial(self):
        def bad(ctx):
            raise OSError("fixture source offline")
        with patch.object(engine.AuditContext, "metadata", return_value={}), patch.object(engine, "registered_checks", return_value=[
            engine.Check("guests.test", "guests", "WARNING", bad)]):
            run = engine.run_assessment()
        self.assertEqual(store.get_findings(run)[0]["state"], "unknown")
        self.assertEqual(store.get_run(run)["status"], "partial")

    def test_failed_command_cannot_become_pass(self):
        def bad(ctx):
            ctx.run(["fixture-command"])
            return {"state": "pass"}
        with patch.object(engine.AuditContext, "metadata", return_value={}), patch.object(engine.subprocess, "run", return_value=SimpleNamespace(
                returncode=1, stdout="", stderr="failed")), patch.object(engine, "registered_checks", return_value=[
            engine.Check("guests.test", "guests", "WARNING", bad)]):
            run = engine.run_assessment()
        self.assertEqual(store.get_findings(run)[0]["state"], "unknown")

    def test_v1_migration_preserves_legacy_decisions_without_reusing_scope(self):
        connection = sqlite3.connect(store.DB_PATH)
        connection.executescript("""
            CREATE TABLE audit_runs (run_id TEXT PRIMARY KEY, profile TEXT, started_at INTEGER,
                finished_at INTEGER, status TEXT, error TEXT, is_baseline INTEGER DEFAULT 0,
                checks_total INTEGER DEFAULT 0, schema_version INTEGER DEFAULT 1);
            CREATE TABLE audit_findings (id INTEGER PRIMARY KEY, run_id TEXT, check_id TEXT,
                area TEXT, severity TEXT, state TEXT, summary_key TEXT, summary_params TEXT,
                affected TEXT, evidence TEXT, remediable_by TEXT);
            CREATE TABLE audit_exceptions (check_id TEXT PRIMARY KEY, reason TEXT,
                accepted_by TEXT, accepted_at INTEGER, expires_at INTEGER);
            INSERT INTO audit_runs (run_id, profile, started_at, status) VALUES ('old', 'full', 1, 'complete');
            INSERT INTO audit_findings (run_id, check_id, area, severity, state)
                VALUES ('old', 'guests.test', 'guests', 'WARNING', 'accepted');
            INSERT INTO audit_exceptions VALUES ('guests.test', 'original reason', 'original author', 1, NULL);
        """)
        connection.commit()
        connection.close()
        store.init_db()
        self.assertEqual(store.get_findings("old")[0]["state"], "accepted")
        self.assertEqual(store.effective_findings("old")[0]["state"], "unknown")
        event = store.exception_history()[0]
        self.assertEqual(json.loads(event["decision"])["reason"], "original reason")
        self.assertEqual(event["action"], "legacy-unscoped")

    def test_baseline_and_running_run_survive_retention(self):
        baseline = self.recorded(self.finding())
        store.set_baseline(baseline)
        running = store.start_run("full")
        store.prune_runs(keep=0)
        self.assertIsNotNone(store.get_run(baseline))
        self.assertIsNotNone(store.get_run(running))

    def test_incomplete_warning_cannot_be_accepted(self):
        f = self.finding()
        f["incomplete"] = True
        run = self.recorded(f)
        store.accept_risk(f["check_id"], "lab", "operator", scope=f["scope"])
        self.assertEqual(store.effective_findings(run)[0]["state"], "warn")


class EngineTests(unittest.TestCase):
    def test_incomplete_and_invalid_classification_never_become_conformant(self):
        check = engine.Check('guests.test', 'guests', 'WARNING', lambda ctx: None)
        for result, expected in [
                ({'classification':'conformant', 'incomplete':True}, 'unverified'),
                ({'classification':'observation', 'affected':[{'classification':'unverified'}]}, 'unverified'),
                ({'classification':'invented'}, 'unverified'),
                ({'incomplete':True, 'affected':[{'classification':'warning'}]}, 'warning'),
                ({'classification':'unverified', 'affected':[{'classification':'critical'}]}, 'critical')]:
            self.assertEqual(engine._classification_of(result, check), expected)

    def test_cached_derived_source_keeps_transitive_failures(self):
        ctx = engine.AuditContext()
        with patch.object(engine.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='', stderr='offline')) as probe:
            def collect():
                ctx.run(['fixture'])
                return {}
            ctx.begin_check()
            ctx._once('derived', lambda: ctx._once('inner', collect))
            ctx.begin_check()
            ctx._once('derived', lambda: self.fail('source must be reused'))
            self.assertIn('inner', ctx._sources_used)
            self.assertTrue(ctx._sources_used & ctx._errors.keys())
            self.assertEqual(probe.call_count, 1)

    def test_storage_snapshot_reuses_cache_without_probe(self):
        server = SimpleNamespace(_proxmox_storage_cache={"time": time.time(),
                                 "data": {"storage": [{"name": "nas"}]}})
        with patch.dict(sys.modules, {"flask_server": server}), patch.object(engine.subprocess, "run") as probe:
            ctx = engine.AuditContext()
            self.assertEqual(ctx.storage_snapshot["source"], "Monitor storage cache")
            ctx.storage_snapshot["rows"][0]["name"] = "modified copy"
            self.assertEqual(server._proxmox_storage_cache["data"]["storage"][0]["name"], "nas")
            probe.assert_not_called()

    def test_expired_storage_snapshot_reads_metadata_once(self):
        server = SimpleNamespace(_proxmox_storage_cache={"time": 1, "data": {"storage": []}})
        ctx = engine.AuditContext()
        rows = [{"node": ctx.node, "storage": "nas", "status": "available"},
                {"node": "another", "storage": "hidden", "status": "available"}]
        with patch.dict(sys.modules, {"flask_server": server}), patch.object(engine.subprocess, "run",
                return_value=SimpleNamespace(returncode=0, stdout=json.dumps(rows), stderr="")) as probe:
            self.assertEqual(len(ctx.storage_snapshot["rows"]), 1)
            self.assertEqual(ctx.storage_snapshot["rows"][0]["name"], "nas")
            self.assertEqual(probe.call_count, 1)
            self.assertIn("/cluster/resources", probe.call_args[0][0])

    def test_failed_storage_metadata_records_unknown_source(self):
        with patch.dict(sys.modules, {"flask_server": SimpleNamespace()}), patch.object(
                engine.subprocess, "run", return_value=SimpleNamespace(returncode=1, stdout="", stderr="offline")):
            ctx = engine.AuditContext()
            self.assertEqual(ctx.storage_snapshot, {})
            self.assertIn("storage_snapshot", ctx._errors)

    def test_shared_failed_source_remains_unknown_for_each_consumer(self):
        ctx = engine.AuditContext()
        with patch.object(engine.subprocess, "run", return_value=SimpleNamespace(
                returncode=1, stdout="", stderr="offline")) as command:
            ctx.begin_check()
            ctx.run(["fixture"])
            ctx.begin_check()
            ctx.run(["fixture"])
            self.assertTrue(ctx._sources_used & ctx._errors.keys())
            self.assertEqual(command.call_count, 1)

    def test_command_deadline_prevents_next_probe(self):
        ctx = engine.AuditContext()
        ctx._check_deadline = time.monotonic() - 1
        with patch.object(engine.subprocess, "run") as command:
            rc, _ = ctx.run(["fixture-probe"])
        command.assert_not_called()
        self.assertEqual(rc, -1)

    def test_invalid_scope_rejected_before_collection(self):
        with self.assertRaises(ValueError):
            engine.run_assessment(only_areas={"invented"})

    def test_catalog_has_43_distinct_checks(self):
        registered = engine.registered_checks()
        self.assertEqual(len(registered), 43)
        self.assertEqual(len({c.check_id for c in registered}), 43)
        for c in registered:
            self.assertTrue(c.check_id.startswith(c.area + "."))

    def test_locales_have_new_states_and_matching_placeholders(self):
        root = Path(__file__).resolve().parents[1] / "AppImage/messages"
        for locale in ("en", "es", "de", "fr", "it", "pt", "sk", "sv"):
            audit = json.loads((root / locale / "common.json").read_text())["audit"]
            self.assertEqual({area+'.'+name for area, names in audit['checks'].items() for name in names},
                             {check.check_id for check in engine.registered_checks()})
            self.assertIn("unknown", audit["states"])
            self.assertIn("{completed}", audit["progress"])
            self.assertEqual(set(audit["areas"]), set(engine.AREAS) | {"all"})
            connected = audit["checks"]["storage"]["connected_storage"]
            self.assertIn("{total}", connected["summary"]["available"])
            self.assertIn("{count}", connected["summary"]["attention"])


if __name__ == "__main__":
    unittest.main()
