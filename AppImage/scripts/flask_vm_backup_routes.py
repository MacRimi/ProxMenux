"""
ProxMenux Monitor - VM/CT backup jobs (Datacenter > Backup)

Thin wrapper around `pvesh` on /cluster/backup. The jobs are the ones of
Proxmox itself: whatever is created or changed here is what the Proxmox
web interface shows, and the other way round.

Based on the contribution of MattiaC46 (PR #421).

Endpoints, all under /api/vm-backup-jobs:
  GET    /                 list of jobs
  POST   /                 create a job
  GET    /options          storages that accept backups + VMs and CTs
  GET    /<id>             one job
  PUT    /<id>             change a job
  DELETE /<id>             delete a job (its backups are kept)
  POST   /<id>/toggle      enable / disable
  POST   /<id>/run         run it now, as a Proxmox task on each node
"""

import json
import os
import re
import subprocess

from flask import Blueprint, jsonify, request

from jwt_middleware import require_admin_scope, require_auth

vm_backup_bp = Blueprint("vm_backup", __name__)

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
STORAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
VMID_RE = re.compile(r"^\d{1,9}(,\d{1,9})*$")
PRUNE_RE = re.compile(r"^keep-(?:last|hourly|daily|weekly|monthly|yearly|all)=\d{1,5}"
                      r"(?:,keep-(?:last|hourly|daily|weekly|monthly|yearly|all)=\d{1,5})*$")
SCHEDULE_RE = re.compile(r"^[A-Za-z0-9*.,:/ -]{1,80}$")
NODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")
MODES = {"snapshot", "suspend", "stop"}
COMPRESS = {"0", "gzip", "lzo", "zstd"}

# What a job stores about itself and its schedule; everything else is a
# vzdump option and is passed on when the job is run by hand.
JOB_ONLY = {"id", "type", "schedule", "enabled", "next-run", "comment", "repeat-missed", "digest", "node",
            "starttime", "dow"}

HOST_BACKUP_JOBS = "/var/lib/proxmenux/backup-jobs"


def _pvesh(args, timeout=25):
    """Run pvesh without a shell. Returns (ok, output)."""
    try:
        done = subprocess.run(["pvesh", *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "pvesh timed out"
    except FileNotFoundError:
        return False, "pvesh not found (a Proxmox VE node is required)"
    if done.returncode != 0:
        return False, (done.stderr or done.stdout).strip()
    return True, done.stdout


def _pvesh_json(args):
    ok, out = _pvesh([*args, "--output-format", "json"])
    if not ok:
        return False, out
    try:
        return True, json.loads(out or "null")
    except json.JSONDecodeError:
        return False, "pvesh returned an invalid answer"


def _flat(value):
    """pvesh answers some property strings as objects; a job stores them as text."""
    if isinstance(value, dict):
        return ",".join(f"{key}={val}" for key, val in value.items())
    if isinstance(value, bool):
        return 1 if value else 0
    return value


def _normalize_job(job):
    if isinstance(job, dict):
        for key in list(job):
            job[key] = _flat(job[key])
    return job


def _enabled(job):
    return job.get("enabled", 1) in (1, True, "1")


def _host_backups_attached():
    """Host backups of ProxMenux that run with a Proxmox job: {job id: [host backup ids]}."""
    attached = {}
    try:
        names = sorted(os.listdir(HOST_BACKUP_JOBS))
    except OSError:
        return attached
    for name in names:
        if not name.endswith(".env"):
            continue
        parent = ""
        try:
            with open(os.path.join(HOST_BACKUP_JOBS, name)) as file:
                for line in file:
                    if line.startswith("PVE_PARENT_JOB="):
                        parent = line.split("=", 1)[1].strip().strip("'\"")
        except OSError:
            continue
        if parent:
            attached.setdefault(parent, []).append(name[:-4])
    return attached


def _err(message, code=400):
    return jsonify({"success": False, "error": message}), code


def _validate(data, partial=False):
    """Check the payload and turn it into pvesh arguments. Returns ((args, deletes), error)."""
    args = []
    deletes = []

    def has(key):
        return key in data and data[key] not in (None, "")

    if "all" in data or "vmid" in data:
        if data.get("all") in (1, True, "1", "true"):
            args += ["--all", "1"]
            deletes.append("vmid")
        else:
            vmid = str(data.get("vmid", "")).replace(" ", "")
            if not VMID_RE.match(vmid):
                return None, "Select at least one VM or CT"
            args += ["--vmid", vmid, "--all", "0"]
    elif not partial:
        return None, "Either all the guests or a list of them is required"

    if has("storage"):
        if not STORAGE_RE.match(str(data["storage"])):
            return None, "Invalid storage"
        args += ["--storage", str(data["storage"])]
    elif not partial:
        return None, "A storage is required"

    if has("schedule"):
        schedule = str(data["schedule"]).strip()
        if not SCHEDULE_RE.match(schedule) or schedule.startswith("-"):
            return None, "Invalid schedule"
        args += ["--schedule", schedule]
    elif not partial:
        return None, "A schedule is required"

    if has("mode"):
        if data["mode"] not in MODES:
            return None, "Invalid mode"
        args += ["--mode", data["mode"]]

    if has("compress"):
        if str(data["compress"]) not in COMPRESS:
            return None, "Invalid compression"
        args += ["--compress", str(data["compress"])]

    if "prune_backups" in data:
        prune = str(data.get("prune_backups") or "").replace(" ", "")
        if prune:
            if not PRUNE_RE.match(prune):
                return None, "Invalid retention (for example keep-last=3,keep-weekly=2)"
            args += ["--prune-backups", prune]
        else:
            deletes.append("prune-backups")

    if "notes_template" in data:
        notes = str(data.get("notes_template") or "").strip()
        if notes:
            if len(notes) > 512 or notes.startswith("-") or "\n" in notes:
                return None, "Invalid notes"
            args += ["--notes-template", notes]
        else:
            deletes.append("notes-template")

    if "enabled" in data:
        args += ["--enabled", "1" if data["enabled"] in (1, True, "1", "true") else "0"]

    return (args, deletes), None


@vm_backup_bp.route("/api/vm-backup-jobs", methods=["GET"])
@require_auth
def list_jobs():
    ok, res = _pvesh_json(["get", "/cluster/backup"])
    if not ok:
        return _err(res, 500)
    attached = _host_backups_attached()
    jobs = []
    for job in res or []:
        job = _normalize_job(job)
        job["host_backups"] = attached.get(str(job.get("id")), [])
        jobs.append(job)
    return jsonify({"success": True, "jobs": jobs})


@vm_backup_bp.route("/api/vm-backup-jobs/options", methods=["GET"])
@require_auth
def options():
    ok, storages = _pvesh_json(["get", "/storage"])
    if not ok:
        return _err(storages, 500)
    ok, guests = _pvesh_json(["get", "/cluster/resources", "--type", "vm"])
    if not ok:
        return _err(guests, 500)
    return jsonify({
        "success": True,
        "storages": [
            {"id": storage["storage"], "type": storage.get("type", "")}
            for storage in storages
            if "backup" in (storage.get("content") or "").split(",")
        ],
        "guests": sorted(
            [
                {"vmid": guest["vmid"], "name": guest.get("name", "-"), "type": guest["type"],
                 "node": guest.get("node", "")}
                for guest in guests
                if guest.get("type") in ("qemu", "lxc")
            ],
            key=lambda guest: guest["vmid"],
        ),
    })


@vm_backup_bp.route("/api/vm-backup-jobs", methods=["POST"])
@require_admin_scope
def create_job():
    data = request.get_json(silent=True) or {}
    parsed, error = _validate(data)
    if error:
        return _err(error)
    args, _deletes = parsed
    job_id = str(data.get("id") or "").strip()
    if job_id:
        if not ID_RE.match(job_id):
            return _err("Invalid job name")
        args += ["--id", job_id]
    if "enabled" not in data:
        args += ["--enabled", "1"]
    ok, out = _pvesh(["create", "/cluster/backup", *args])
    if not ok:
        return _err(out, 500)
    return jsonify({"success": True})


@vm_backup_bp.route("/api/vm-backup-jobs/<job_id>", methods=["GET"])
@require_auth
def get_job(job_id):
    if not ID_RE.match(job_id):
        return _err("Invalid job")
    ok, res = _pvesh_json(["get", f"/cluster/backup/{job_id}"])
    if not ok:
        return _err(res, 404)
    job = _normalize_job(res)
    job["host_backups"] = _host_backups_attached().get(job_id, [])
    return jsonify({"success": True, "job": job})


@vm_backup_bp.route("/api/vm-backup-jobs/<job_id>", methods=["PUT"])
@require_admin_scope
def update_job(job_id):
    if not ID_RE.match(job_id):
        return _err("Invalid job")
    parsed, error = _validate(request.get_json(silent=True) or {}, partial=True)
    if error:
        return _err(error)
    args, deletes = parsed
    for key in dict.fromkeys(deletes):
        args += ["--delete", key]
    if not args:
        return _err("Nothing to change")
    ok, out = _pvesh(["set", f"/cluster/backup/{job_id}", *args])
    if not ok:
        return _err(out, 500)
    return jsonify({"success": True})


@vm_backup_bp.route("/api/vm-backup-jobs/<job_id>", methods=["DELETE"])
@require_admin_scope
def delete_job(job_id):
    if not ID_RE.match(job_id):
        return _err("Invalid job")
    ok, out = _pvesh(["delete", f"/cluster/backup/{job_id}"])
    if not ok:
        return _err(out, 500)
    return jsonify({"success": True})


@vm_backup_bp.route("/api/vm-backup-jobs/<job_id>/toggle", methods=["POST"])
@require_admin_scope
def toggle_job(job_id):
    if not ID_RE.match(job_id):
        return _err("Invalid job")
    ok, job = _pvesh_json(["get", f"/cluster/backup/{job_id}"])
    if not ok:
        return _err(job, 404)
    state = "0" if _enabled(job) else "1"
    ok, out = _pvesh(["set", f"/cluster/backup/{job_id}", "--enabled", state])
    if not ok:
        return _err(out, 500)
    return jsonify({"success": True, "enabled": state == "1"})


def _run_nodes(job):
    """The nodes a job has something to back up on. Returns (nodes, error)."""
    ok, nodes = _pvesh_json(["get", "/nodes"])
    if not ok:
        return None, nodes
    online = [node["node"] for node in nodes or [] if node.get("status") == "online"]
    wanted = str(job.get("node") or "")
    if wanted:
        return ([wanted] if wanted in online else []), None
    if job.get("all") in (1, True, "1") or job.get("pool"):
        return online, None
    selected = {vmid for vmid in str(job.get("vmid", "")).replace(" ", "").split(",") if vmid}
    ok, guests = _pvesh_json(["get", "/cluster/resources", "--type", "vm"])
    if not ok:
        return None, guests
    hosting = {guest.get("node") for guest in guests or [] if str(guest.get("vmid")) in selected}
    return [node for node in online if node in hosting], None


def _run_arguments(job):
    """The vzdump options of a job, as pvesh arguments."""
    args = []
    for key, value in sorted(job.items()):
        if key in JOB_ONLY or key == "host_backups" or value in (None, ""):
            continue
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,40}", key):
            continue
        for item in value if isinstance(value, list) else [value]:
            args += [f"--{key}", str(_flat(item))]
    return args


@vm_backup_bp.route("/api/vm-backup-jobs/<job_id>/run", methods=["POST"])
@require_admin_scope
def run_job(job_id):
    """Start the backup of a job now. Each node runs its part as a Proxmox
    task, so it is listed and logged like a scheduled run."""
    if not ID_RE.match(job_id):
        return _err("Invalid job")
    ok, job = _pvesh_json(["get", f"/cluster/backup/{job_id}"])
    if not ok:
        return _err(job, 404)
    job = _normalize_job(job)
    if not job.get("storage") or not STORAGE_RE.match(str(job["storage"])):
        return _err("The job has no storage")
    nodes, error = _run_nodes(job)
    if error:
        return _err(error, 500)
    if not nodes:
        return _err("No online node has a guest of this job")
    arguments = _run_arguments(job)
    tasks, failures = [], []
    for node in nodes:
        if not NODE_RE.match(node):
            continue
        ok, out = _pvesh(["create", f"/nodes/{node}/vzdump", *arguments])
        if ok:
            found = re.search(r"UPID:[^\s\"']+", out)
            tasks.append({"node": node, "upid": found.group(0) if found else ""})
        else:
            failures.append({"node": node, "error": out})
    if not tasks:
        return _err(failures[0]["error"] if failures else "The backup could not be started", 500)
    return jsonify({"success": True, "tasks": tasks, "failures": failures})
