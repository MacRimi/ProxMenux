#!/usr/bin/env python3

# ==========================================================
# ProxMenux - Plain LXC console creation
# ==========================================================
# Author      : Vaso73
# GitHub      : github.com/Vaso73
# Maintainer  : MacRimi
# Copyright   : (c) 2026 MacRimi & contributors
# License     : (GPL-3.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 15/11/2026
# ==========================================================
# Description:
# Privileged JSON entry point for plain LXC creation. Validates local
# plans and observes native tasks without replaying uncertain operations.
# ==========================================================
"""Privileged local JSON entry point for plain LXC creation."""

from contextlib import closing, contextmanager, nullcontext
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import time

# The installed caller uses Python's isolated mode.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from plain_lxc_pve import Proxmox, checked_plan, current_inventory, inventory, local_node, next_id, occupied_ids, storage_for
from plain_lxc_spec import ARCHIVE, DEFAULTS, LxcError, MAX_BODY, NODE, REQUEST_ID, STORAGE
from plain_lxc_spec import digest, fields, integer, normalize, pve_params, strict_json, string
from plain_lxc_state import STATE, installed_directory, private_directory, lock_file, migrate_state, check_uninstall, remove_legacy_alias, runtime_lock


TASK_WAIT_SECONDS = 90
SUBMIT_SECONDS = 15
RECOVERY_GRACE_SECONDS = 300
PENDING = ("running", "unknown")
TASK_LOG_PAGE_SIZE = 50
TASK_LOG_MAX_OFFSET = 1000000


class Operations:
    """Atomically record intent before contacting PVE, with one pending write per target."""

    def __init__(self, directory, actor):
        self.directory = directory
        self.path = directory / "operations.sqlite3"
        self.actor = actor

    def connect(self, write=False):
        if write:
            self.directory.mkdir(mode=0o700, exist_ok=True, parents=True)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise LxcError("operation_store_unavailable")
        if self.path.is_symlink():
            raise LxcError('operation_store_unavailable')
        if write:
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            try:
                db_info = os.fstat(fd)
            finally:
                os.close(fd)
        else:
            db_info = self.path.lstat()
        if not stat.S_ISREG(db_info.st_mode) or db_info.st_uid != os.geteuid() or db_info.st_nlink != 1:
            raise LxcError('operation_store_unavailable')
        if write:
            db = sqlite3.connect(self.path, timeout=5)
            db.execute("""CREATE TABLE IF NOT EXISTS operations (
                id TEXT PRIMARY KEY, actor INTEGER NOT NULL, target TEXT NOT NULL,
                pending INTEGER NOT NULL, data TEXT NOT NULL)""")
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS pending_target ON operations(target) WHERE pending = 1""")
            return db
        return sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=5)

    @contextmanager
    def controller(self, request_id):
        self.directory.mkdir(mode=0o700, exist_ok=True, parents=True)
        private_directory(self.directory)
        with lock_file(self.directory / '.controllers.lock', exclusive=False):
            with lock_file(self.directory / (request_id + '.lock')):
                yield

    def pending(self):
        if not self.path.exists():
            return []
        with closing(self.connect()) as db:
            try:
                return [json.loads(row[0]) for row in db.execute(
                    'SELECT data FROM operations WHERE pending=1 AND actor=? ORDER BY id', (self.actor,))]
            except sqlite3.OperationalError as error:
                if str(error) == 'no such table: operations':
                    return []
                raise

    def get(self, request_id):
        if not self.path.exists():
            return None
        with closing(self.connect()) as db:
            try:
                row = db.execute("SELECT actor, data FROM operations WHERE id = ?", (request_id,)).fetchone()
            except sqlite3.OperationalError as error:
                # A concurrent first writer may have just created the file.
                if str(error) == "no such table: operations":
                    return None
                raise
        if row is None:
            return None
        if row[0] != self.actor:
            raise LxcError("request_conflict")
        return json.loads(row[1])

    def admit(self, operation, target):
        with closing(self.connect(write=True)) as db, db:
            try:
                db.execute("INSERT INTO operations VALUES (?, ?, ?, 1, ?)",
                           (operation["request_id"], self.actor, target, json.dumps(operation)))
                return True
            except sqlite3.IntegrityError:
                return False

    def save(self, operation):
        with closing(self.connect(write=True)) as db, db:
            db.execute("UPDATE operations SET pending = ?, data = ? WHERE id = ? AND actor = ?",
                       (int(operation["status"] in PENDING), json.dumps(operation),
                        operation["request_id"], self.actor))

    def resolve_observed(self, original, result):
        # Do not overwrite a phase advanced by the original controller while
        # a status caller was reading the external task. Keep its reservation.
        updated = {**original, **result}
        with closing(self.connect(write=True)) as db, db:
            changed = db.execute("""UPDATE operations SET pending = 0, data = ?
                WHERE id = ? AND actor = ? AND pending = 1 AND data = ?""",
                (json.dumps(updated), original["request_id"], self.actor, json.dumps(original)))
            return changed.rowcount == 1


def task_id(raw, node, kind, identity):
    # The pstart field can exceed eight hex digits after a long node uptime.
    if type(raw) is str and re.fullmatch(
        rf"UPID:{re.escape(node)}:[0-9A-Fa-f]{{8}}:[0-9A-Fa-f]{{8,9}}:[0-9A-Fa-f]{{8}}:"
        rf"{kind}:{re.escape(str(identity))}:root@pam:", raw
    ):
        return raw
    raise LxcError("task_identity_unknown")


def reply(operation, **changes):
    private = {"fingerprint", "sha512", "deadline", "start_after_create", "prepare_expected", "start_expected",
               "submission", "admitted_at", "recovery_checked_at"}
    return {key: value for key, value in {**operation, **changes}.items() if key not in private}


def task_log(api, operation, phase, offset):
    if operation["action"] != "create":
        raise LxcError("task_log_unavailable")
    node = string(operation["node"], NODE, 63, "node")
    upid = operation.get("upid") if phase == operation["phase"] else None
    if phase == "create" and operation["phase"] in ("start", "prepare"):
        upid = operation.get("create_upid")
    kind = {"create": "vzcreate", "start": "vzstart", "prepare": "vzprepare"}[phase]
    try:
        upid = task_id(upid, node, kind, operation["vmid"])
        # Ask for one extra line so a full last page is not mistaken for more output.
        rows = api.read(f"/nodes/{node}/tasks/{upid}/log", start=offset, limit=TASK_LOG_PAGE_SIZE + 1)
        if type(rows) is not list or len(rows) > TASK_LOG_PAGE_SIZE + 1:
            raise LxcError("task_log_unavailable")
        for index, row in enumerate(rows, offset + 1):
            if (type(row) is not dict or type(row.get("n")) is not int or row["n"] != index
                    or type(row.get("t")) is not str or row["t"].startswith("unable to open file - ")):
                raise LxcError("task_log_unavailable")
    except LxcError:
        raise LxcError("task_log_unavailable") from None
    lines = ["".join(char if char.isprintable() else " " for char in row["t"][:2048])
             for row in rows[:TASK_LOG_PAGE_SIZE]]
    next_offset = offset + TASK_LOG_PAGE_SIZE
    return {"upid": upid, "phase": phase, "lines": lines,
            "next_offset": next_offset if len(rows) > TASK_LOG_PAGE_SIZE and next_offset <= TASK_LOG_MAX_OFFSET else None}


def marker_matches(api, operation):
    config = api.read(f'/nodes/{operation["node"]}/lxc/{operation["vmid"]}/config')
    marker = "ProxMenux request " + operation["request_id"]
    # PVE serializes descriptions as comments and reads a final newline back.
    # Accept exactly that representation, not arbitrary stripped whitespace.
    return (type(config) is dict and not config.get("lock")
            and config.get("description") in (marker, marker + "\n"))


def observe(api, operation):
    if operation["status"] not in PENDING:
        return reply(operation)
    upid = operation.get("upid")
    if upid is None:
        if operation["status"] == "running" and time.time() < operation["deadline"]:
            return reply(operation)
        if operation["phase"] == "create":
            try:
                if marker_matches(api, operation):
                    return reply(operation, status="unknown", container_observed=True)
            except LxcError:
                pass
        return reply(operation, status="unknown")

    node, phase = operation["node"], operation["phase"]
    try:
        task = api.read(f"/nodes/{node}/tasks/{upid}/status")
        if type(task) is not dict or task.get("upid") != upid:
            raise LxcError("task_status_unavailable")
        if task.get("status") == "running":
            return reply(operation, status="running")
        exit_status = task.get("exitstatus")
        if (task.get("status") != "stopped" or type(exit_status) is not str or not exit_status
                or exit_status == "unexpected status" or exit_status.startswith("unable to get last line")):
            raise LxcError("task_status_unavailable")
        warnings = re.fullmatch(r"WARNINGS: [0-9]+", exit_status) is not None
        # Keep each native task's warning independently across the create/start
        # transition, including a failed or uncertain start. This is not OS health.
        warning_phases = {**operation.get("task_warning_phases", {}), phase: warnings}
        operation = {**operation, "task_warning_phases": warning_phases,
                     "task_warnings": any(warning_phases.values())}
        if exit_status != "OK" and not warnings:
            if phase == "create":
                existing = operation["vmid"] in occupied_ids(api.read("/cluster/resources", type="vm"))
                return reply(operation, status="partial" if existing else "failed", reason="create_failed")
            if phase in ("start", "prepare"):
                reason = ("preparation_failed" if phase == "prepare"
                          or exit_status.startswith("ProxMenux preparation failed:") else "start_failed")
                return reply(operation, status="partial", created=True, reason=reason)
            return reply(operation, status="failed", reason="download_failed")
        if phase == "download":
            if api.archive_checksum(operation["volume_id"]) != operation["sha512"]:
                return reply(operation, status="partial", reason="template_checksum_mismatch")
        elif phase == "create":
            if not marker_matches(api, operation):
                return reply(operation, status="unknown", reason="container_identity_unknown")
            if operation["start_after_create"] or operation.get("prepare_expected"):
                if operation["status"] == "running" and time.time() < operation["deadline"]:
                    return reply(operation, status="running", created=True,
                                 reason="awaiting_start" if operation["start_after_create"] else "awaiting_preparation")
                return reply(operation, status="partial", created=True,
                             reason="preparation_not_submitted" if operation.get("prepare_expected") else "start_not_submitted")
        completed = {"created": True} if phase != "download" else {}
        if phase in ("prepare", "start") and operation.get("prepare_expected"):
            completed["prepared"] = True
        return reply(operation, status="succeeded", **completed)
    except LxcError:
        return reply(operation, status="unknown", reason="task_status_unavailable")


def submit(api, store, operation, action, params, kind, identity, on_phase):
    if on_phase is not None:
        on_phase(operation["phase"])
    operation['submission'] = 'started'
    store.save(operation)
    try:
        operation["upid"] = task_id(api.dispatch(action, operation["node"], params), operation["node"], kind, identity)
    except LxcError:
        operation.update(status="unknown", reason="submission_unknown")
    store.save(operation)


def run_operation(api, store, operation, action, params, kind, identity, wait_seconds, on_phase):
    submit(api, store, operation, action, params, kind, identity, on_phase)
    if operation["status"] == "unknown":
        return observe(api, operation)
    deadline = time.monotonic() + wait_seconds
    while True:
        result = observe(api, operation)
        if result.get("reason") in ("awaiting_start", "awaiting_preparation"):
            operation.update(task_warning_phases=result["task_warning_phases"],
                             task_warnings=result["task_warnings"])
            phase = "start" if operation["start_after_create"] else "prepare"
            operation.update(phase=phase, create_upid=operation["upid"], created=True, upid=None,
                             deadline=time.time() + SUBMIT_SECONDS, submission='not_started')
            store.save(operation)
            submit(api, store, operation, phase,
                   {"vmid": identity, "description": params["description"],
                    "expected": operation.get("start_expected", operation.get("prepare_expected"))},
                   "vzstart" if phase == "start" else "vzprepare", identity, on_phase)
            if operation["status"] == "unknown":
                return observe(api, operation)
            deadline = time.monotonic() + wait_seconds
            continue
        if result["status"] not in PENDING:
            operation.update(result)
            store.save(operation)
            return result
        if time.monotonic() >= deadline:
            # Give later status calls a chance to observe the original task.
            # They must never submit a missed start or create again.
            operation["deadline"] = 0
            result = observe(api, operation)
            if result["status"] not in PENDING:
                operation.update(result)
            store.save(operation)
            return result
        time.sleep(1)


def existing_request(api, store, request_id, fingerprint):
    operation = store.get(request_id)
    if operation is None:
        return None
    if operation["fingerprint"] != fingerprint:
        raise LxcError("request_conflict", "request_id")
    return observed_request(api, store, operation)


def observed_request(api, store, operation):
    result = observe(api, operation)
    if operation['status'] not in PENDING or result['status'] in PENDING:
        return result
    try:
        # A live controller may be about to submit the next phase. A task's
        # terminal status alone cannot end that controller's reservation.
        with store.controller(operation['request_id']):
            if not store.resolve_observed(operation, result):
                return observe(api, store.get(operation['request_id']))
    except LxcError as error:
        if error.code != 'operation_controller_active':
            raise
        return reply(operation, status='running', reason='controller_active')
    return result


def recover(api, store, request_id):
    # Recovery is a separate confirmed action. It never sends a missed phase,
    # stops a task, or deletes any guest, template or volume.
    with store.controller(request_id):
        original = store.get(request_id)
        if original is None:
            raise LxcError('request_not_found')
        result = reply(original) if original.get('submission') == 'not_started' else observe(api, original)
        if result['status'] not in PENDING:
            store.resolve_observed(original, result)
            return result
        if original.get('upid') and result['status'] == 'running':
            return result
        if original.get('submission') == 'not_started' and not original.get('upid'):
            result = reply(original, status='partial' if original.get('created') else 'failed',
                           reason='recovered_not_submitted')
        else:
            # An older interrupted controller may have set deadline=0. Start
            # a fresh persisted grace period instead of treating it as expired.
            boundary = max(original.get('admitted_at', 0), original.get('deadline', 0),
                           original.get('recovery_checked_at', 0))
            if not boundary:
                original['recovery_checked_at'] = time.time()
                store.save(original)
                return reply(original, status='unknown', reason='recovery_wait')
            if time.time() < boundary + RECOVERY_GRACE_SECONDS:
                return reply(original, status='unknown', reason='recovery_wait')
            node = local_node(api)
            if node != original['node']:
                raise LxcError('node_not_local', 'node')
            params = {'description': 'ProxMenux request ' + request_id}
            if original['action'] == 'create':
                params['vmid'] = original['vmid']
            else:
                params['volume_id'] = original['volume_id']
            try:
                proof = api.dispatch('recovery_check', node, params)
                if (type(proof) is not dict or type(proof.get('safe')) is not int or proof['safe'] != 1
                        or type(proof.get('present')) is not int or proof['present'] not in (0, 1)):
                    raise LxcError('recovery_unavailable')
                if original['action'] == 'create':
                    result = reply(original, status='partial' if proof['present'] else 'failed',
                                   created=bool(proof['present']), reason='recovered_requires_review')
                elif proof['present']:
                    valid = api.archive_checksum(original['volume_id']) == original['sha512']
                    result = reply(original, status='succeeded' if valid else 'partial',
                                   reason='recovered_download' if valid else 'template_checksum_mismatch')
                else:
                    result = reply(original, status='failed', reason='recovered_not_submitted')
            except LxcError:
                return reply(original, status='unknown', reason='recovery_unavailable')
        if not store.resolve_observed(original, result):
            return observe(api, store.get(request_id))
        return result


def execute(request, api, store, wait_seconds=TASK_WAIT_SECONDS, on_phase=None):
    fields(request, "schema_version action", "spec plan plan_hash accepted_warnings secret request_id "
           "node catalog_id template_storage confirmed phase offset")
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise LxcError("unsupported_schema")
    action = request["action"]
    common = "schema_version action"
    if action == 'operations':
        fields(request, common)
        return {'operations': [reply(operation) for operation in store.pending()]}
    if action == 'recover':
        fields(request, common + ' request_id confirmed')
        if request['confirmed'] is not True:
            raise LxcError('confirmation_required')
        request_id = string(request['request_id'], REQUEST_ID, 32, 'request_id')
        return recover(api, store, request_id)
    if action in ("status", "task_log"):
        if action == "task_log":
            fields(request, common + " request_id phase", "offset")
            phase = string(request["phase"], r"create|start|prepare", 7, "phase")
            offset = integer(request.get("offset", 0), 0, TASK_LOG_MAX_OFFSET, "offset")
        else:
            fields(request, common + " request_id")
        request_id = string(request["request_id"], REQUEST_ID, 32, "request_id")
        operation = store.get(request_id)
        if operation is None:
            raise LxcError("request_not_found")
        if action == "task_log":
            return task_log(api, operation, phase, offset)
        return observed_request(api, store, operation)
    if action == "context":
        fields(request, common)
        data = current_inventory(api)
        data.pop("volumes")
        data.update(defaults=DEFAULTS, operations=[reply(operation) for operation in store.pending()])
        return data
    if action == "plan":
        fields(request, common + " spec")
        spec = normalize(request["spec"])
    elif action == "create":
        fields(request, common + " request_id plan plan_hash accepted_warnings confirmed", "secret")
        fields(request["plan"], "spec resources warnings unprivileged nesting", field="plan")
        spec = normalize(request["plan"]["spec"])
        string(request["plan_hash"], r"[a-f0-9]{64}", 64, "plan_hash")
        if digest(request["plan"]) != request["plan_hash"]:
            raise LxcError("plan_changed")
        if request["accepted_warnings"] != request["plan"]["warnings"]:
            raise LxcError("warnings_unaccepted")
        password = None
        if spec["access"]["mode"] in ("password", "both"):
            secret = request.get("secret")
            fields(secret, "password", field="secret")
            password = string(secret["password"], r"[^\x00-\x1f\x7f]{5,256}", 256, "secret.password")
            if any(0xD800 <= ord(char) <= 0xDFFF for char in password):
                raise LxcError("invalid_field", "secret.password")
        elif "secret" in request:
            raise LxcError("invalid_field", "secret")
        fingerprint = digest([action, request["plan_hash"]])
        target = f'vmid:{spec["vmid"]}'
    elif action == "download_template":
        fields(request, common + " request_id node catalog_id template_storage confirmed")
        string(request["node"], NODE, 63, "node")
        name = string(request["catalog_id"], ARCHIVE, 180, "catalog_id")
        storage = string(request["template_storage"], STORAGE, 64, "template_storage")
        fingerprint = digest([action, request["node"], storage, name])
        volume = f"{storage}:vztmpl/{name}"
        target = f"download:{volume}"
    else:
        raise LxcError("invalid_action")

    if action != "plan":
        if request["confirmed"] is not True:
            raise LxcError("confirmation_required")
        request_id = string(request["request_id"], REQUEST_ID, 32, "request_id")
        previous = existing_request(api, store, request_id, fingerprint)
        if previous is not None:
            return previous

    if action in ("plan", "create"):
        try:
            context = current_inventory(api, spec["node"], spec["vmid"])
            node = context["node"]
            plan = checked_plan(api, spec, context)
        except LxcError:
            if action == "create":
                previous = existing_request(api, store, request_id, fingerprint)
                if previous is not None:
                    return previous
            raise
        plan_hash = digest(plan)
        if action == "plan":
            return {"plan": plan, "plan_hash": plan_hash}
        if plan_hash != request["plan_hash"]:
            raise LxcError("plan_changed")
        phase, kind, identity = "create", "vzcreate", spec["vmid"]
        details = {"vmid": identity, "start_after_create": spec["start_after_create"]}
        params = pve_params(spec, password, request_id)
        params['arch'] = plan['resources']['template']['architecture']
        attachments = plan['resources']['attachments']
        if any(attachments.values()):
            params['resource_identity'] = attachments
        expected = {key: params[key] for key in
                    ("hostname", "features", "cores", "memory", "swap", "onboot", "storage")}
        expected.update(net0=params.get("net0"), storage_type=plan["resources"]["rootfs_type"],
                        prepare_system=spec["prepare_system"])
        if any(attachments.values()):
            expected['resources'] = attachments
        expected['arch'] = params['arch']
        details["start_expected"] = expected
        if spec["prepare_system"]:
            details["prepare_expected"] = expected
    else:
        node = local_node(api)
        if node != request["node"]:
            raise LxcError("node_not_local", "node")
        context = inventory(api, node)
        storage_for(context, storage, "vztmpl")
        if volume in context["volumes"]:
            previous = existing_request(api, store, request_id, fingerprint)
            if previous is not None:
                return previous
            raise LxcError("template_already_present")
        entry = context["catalog"].get(name)
        if entry is None:
            raise LxcError("catalog_unavailable" if context["catalog_state"] == "unavailable" else "template_unverified")
        phase, kind, identity = "download", "download", name
        details = {"volume_id": volume, "sha512": entry["sha512"]}
        params = {"storage": storage, "template": name, "sha512": entry["sha512"],
                  "architecture": entry["architecture"]}

    operation = {"request_id": request_id, "node": node, "action": action, "fingerprint": fingerprint,
                 "phase": phase, "status": "running", "deadline": time.time() + SUBMIT_SECONDS + wait_seconds,
                 "submission": "not_started", "admitted_at": time.time(),
                 **details}
    with store.controller(request_id):
        if not store.admit(operation, target):
            previous = existing_request(api, store, request_id, fingerprint)
            if previous is not None:
                return previous
            previous = next((item for item in store.pending() if
                             (f"vmid:{item['vmid']}" if item['action'] == 'create' else f"download:{item['volume_id']}") == target), None)
            raise LxcError("target_operation_pending", previous['request_id'] if previous else None)
        return run_operation(api, store, operation, action, params, kind, identity, wait_seconds, on_phase)


def emit_phase(phase):
    try:
        print(json.dumps({"schema_version": 1, "event": "phase", "phase": phase}), flush=True)
    except OSError:
        # The console can close while Proxmox owns an admitted operation.
        pass


def main():
    os.umask(0o077)
    try:
        if os.geteuid() != 0:
            raise LxcError("root_required")
        options = sys.argv[1:]
        if options in (["--migrate-state"], ["--rollback-state"], ["--check-uninstall"], ['--remove-legacy-alias']):
            if options == ['--check-uninstall']:
                result = check_uninstall()
            elif options == ['--remove-legacy-alias']:
                result = remove_legacy_alias()
            else:
                with runtime_lock(exclusive=True):
                    result = migrate_state(rollback=options == ["--rollback-state"])
            print(json.dumps({"schema_version": 1, "ok": True, "data": result}))
            return 0
        if options not in ([], ["--progress"], ["--legacy-state"]):
            raise LxcError('invalid_request')
        raw = sys.stdin.buffer.read(MAX_BODY + 1)
        if len(raw) > MAX_BODY:
            raise LxcError("body_too_large")
        request = strict_json(raw)
        if type(request) is not dict:
            raise LxcError('invalid_request')
        if options == ['--legacy-state'] and request.get('action') not in ('operations', 'status', 'task_log', 'recover'):
            raise LxcError('state_migration_required')
        mutating = request.get('action') in ('create', 'download_template', 'recover', 'status')
        with runtime_lock() if mutating else nullcontext():
            result = execute(request, Proxmox(), Operations(installed_directory(legacy=options == ['--legacy-state']), os.getuid()),
                             on_phase=emit_phase if sys.argv[1:] == ["--progress"] else None)
        print(json.dumps({"schema_version": 1, "ok": True, "data": result}, allow_nan=False))
    except LxcError as error:
        print(json.dumps({"schema_version": 1, "ok": False, "error": error.code, "field": error.field}))
        return 1
    except (OSError, sqlite3.Error, ValueError, RecursionError):
        print(json.dumps({"schema_version": 1, "ok": False, "error": "local_operation_error"}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
