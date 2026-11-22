"""Guarded removal of one stopped, ordinary LXC through the native PVE task.

This deliberately does not try to be a generic ``pct destroy`` wrapper.  The
route accepts only a locally hosted, stopped LXC with a single ordinary rootfs
volume and no extra mounts, OCI identity, HA, replication, lock, pending
change, active backup or unreadable safety input.  The same preflight runs
before the preview and again while holding the shared LXC-operation lock.
"""

from __future__ import annotations

from functools import wraps
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import socket
import subprocess

from flask import Blueprint, g, jsonify, request
from itsdangerous import BadData, URLSafeTimedSerializer

from auth_manager import _get_jwt_secret
from jwt_middleware import require_admin_scope
from pbs_manager import is_pbs_host


lxc_removal_bp = Blueprint("lxc_removal", __name__)

CONF_DIR = Path("/etc/pve/lxc")
OCI_INSTANCE_ROOT = Path("/usr/local/share/proxmenux/oci/instances")
CHECK_AGE = 180
NODE_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$")
DESTROY_UPID_RE = re.compile(
    r"^UPID:(?P<node>[\w.-]+):[0-9A-Fa-f]+:[0-9A-Fa-f]+:[0-9A-Fa-f]+:"
    r"vzdestroy:(?P<vmid>[0-9]+):[\w.@!-]+:$"
)


class RemovalError(Exception):
    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code = code
        self.status = status


def _admin(view):
    @wraps(view)
    def protected(*args, **kwargs):
        identity = getattr(g, "identity", None)
        if not identity or "admin" not in identity.get("permissions", ()):
            return jsonify(error="admin_required"), 403
        if is_pbs_host():
            return jsonify(error="pve_required"), 404
        return view(identity["username"], *args, **kwargs)
    return protected


def _ticket() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_get_jwt_secret(), salt="proxmenux-lxc-remove")


def _pvesh_json(args: list[str], timeout: int = 10):
    """Return PVE JSON without a shell.  Every failed read fails closed."""
    try:
        result = subprocess.run(
            ["pvesh", *args, "--output-format", "json"],
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RemovalError("proxmox_read_unavailable", 503) from exc
    if result.returncode != 0:
        raise RemovalError("proxmox_read_unavailable", 503)
    try:
        return json.loads(result.stdout)
    except (TypeError, ValueError) as exc:
        raise RemovalError("proxmox_read_unavailable", 503) from exc


def _local_node() -> str:
    try:
        name = os.path.basename(os.readlink("/etc/pve/local"))
    except OSError:
        name = socket.gethostname().split(".", 1)[0].lower()
    if not NODE_RE.fullmatch(name):
        raise RemovalError("node_identity_unavailable", 503)
    return name


def _plain_config(vmid: int):
    path = CONF_DIR / f"{int(vmid)}.conf"
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RemovalError("configuration_unavailable", 409) from exc
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RemovalError("configuration_unavailable", 409) from exc
    values: dict[str, str] = {}
    lxc: list[tuple[str, str]] = []
    for line in text.splitlines():
        if line.startswith("[") and line.endswith("]"):
            break
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        if key.startswith("lxc."):
            lxc.append((key, value))
        else:
            values[key] = value
    return raw, values, lxc


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _rootfs(value: str):
    volume, _, options = value.partition(",")
    storage, sep, name = volume.partition(":")
    if not (sep and storage and name and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", storage)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+:/@-]*", name)):
        raise RemovalError("rootfs_ambiguous")
    parsed = {}
    for option in options.split(",") if options else ():
        key, eq, option_value = option.partition("=")
        if not (eq and key and option_value):
            raise RemovalError("rootfs_ambiguous")
        parsed[key] = option_value
    return {"storage": storage, "volume": volume, "size": parsed.get("size", "")}


def _contains_oci(vmid: int, config_text: str) -> bool:
    # Both an on-disk OCI record and a surviving restoration marker forbid
    # this path.  An unreadable record is not interpreted as an ordinary CT.
    record = OCI_INSTANCE_ROOT / str(vmid) / "oci-compose.json"
    if record.exists():
        try:
            value = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise RemovalError("oci_identity_unavailable") from None
        if not isinstance(value, dict):
            raise RemovalError("oci_identity_unavailable")
        return True
    return bool(re.search(
        r"^#.*proxmenux-instance=|^\s*lxc\.(?:environment\.runtime|init\.cwd|signal\.halt):",
        config_text, re.MULTILINE,
    ))


def _backup_inventory(node: str, vmid: int):
    storages = _pvesh_json(["get", "/storage"])
    if not isinstance(storages, list):
        raise RemovalError("backup_state_unavailable", 503)
    backups = []
    for storage in storages:
        if not isinstance(storage, dict):
            raise RemovalError("backup_state_unavailable", 503)
        name = storage.get("storage")
        content = str(storage.get("content") or "")
        if not isinstance(name, str) or not name:
            continue
        if "backup" not in content.split(",") and storage.get("type") != "pbs":
            continue
        items = _pvesh_json([
            "get", f"/nodes/{node}/storage/{name}/content", "--vmid", str(vmid),
        ], timeout=20)
        if not isinstance(items, list):
            raise RemovalError("backup_state_unavailable", 503)
        for item in items:
            if not isinstance(item, dict) or item.get("content") != "backup":
                continue
            volid = str(item.get("volid") or "")
            subtype = str(item.get("subtype") or "")
            if subtype not in ("", "lxc"):
                continue
            if subtype != "lxc" and f"vzdump-lxc-{vmid}-" not in volid:
                continue
            backups.append({
                "storage": name, "volid": volid, "size": item.get("size", 0),
                "timestamp": item.get("ctime", 0), "protected": bool(item.get("protected")),
            })
    backups.sort(key=lambda item: item["timestamp"] if isinstance(item["timestamp"], int) else 0,
                 reverse=True)
    # The Monitor has archive presence, not a fresh isolated restore proof.
    return {"state": "unverified" if backups else "none", "archives": backups}


def _active_backup_tasks(node: str, vmid: int):
    tasks = _pvesh_json([
        "get", f"/nodes/{node}/tasks", "--source", "active", "--typefilter", "vzdump",
    ])
    if not isinstance(tasks, list):
        raise RemovalError("backup_task_state_unavailable", 503)
    selected = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        upid = str(task.get("upid") or "")
        target = str(task.get("id") or "")
        upid_target = re.search(r":vzdump:(?P<target>[^:]*):", upid)
        # A node-wide `all` job can include this LXC.  If PVE returned an
        # active vzdump task without a usable target at all, fail closed
        # rather than treating another backup as unrelated.
        if target != str(vmid):
            if upid_target and upid_target["target"] not in {str(vmid), "", "all"}:
                continue
            if not upid_target and target:
                continue
        selected.append({
            "upid": upid, "status": str(task.get("status") or ""),
            "starttime": task.get("starttime"),
        })
    return selected


def _preflight(vmid: int):
    """Collect all independent safety facts; uncertainty is a blocker."""
    resources = _pvesh_json(["get", "/cluster/resources", "--type", "vm"])
    if not isinstance(resources, list):
        raise RemovalError("target_state_unavailable", 503)
    resource = next((row for row in resources
                     if isinstance(row, dict) and str(row.get("vmid")) == str(vmid)), None)
    if resource is None:
        raise RemovalError("target_not_found", 404)
    if resource.get("type") != "lxc":
        raise RemovalError("target_not_lxc")
    node = resource.get("node")
    if not isinstance(node, str) or not NODE_RE.fullmatch(node) or node != _local_node():
        raise RemovalError("target_not_local")

    raw, config, lxc_lines = _plain_config(vmid)
    reasons: list[str] = []
    if resource.get("status") != "stopped":
        reasons.append("container_running")
    if _truthy(config.get("protection")):
        reasons.append("container_protected")
    if config.get("lock"):
        reasons.append("container_locked")
    if any(re.fullmatch(r"(?:mp|unused)\d+", key) for key in config):
        reasons.append("attached_or_unassigned_disk")
    if any(key.startswith("lxc.mount") or key.startswith("lxc.hook") for key, _ in lxc_lines):
        reasons.append("bound_directory")
    if lxc_lines:
        reasons.append("custom_lxc_configuration")
    if _contains_oci(vmid, raw.decode("utf-8", errors="replace")):
        reasons.append("oci_managed")
    try:
        disk = _rootfs(config.get("rootfs", ""))
    except RemovalError:
        reasons.append("rootfs_ambiguous")
        disk = {"storage": "", "volume": "", "size": ""}

    ha = _pvesh_json(["get", "/cluster/ha/resources"])
    if not isinstance(ha, list):
        raise RemovalError("ha_state_unavailable", 503)
    if any(isinstance(row, dict) and row.get("sid") == f"ct:{vmid}" for row in ha):
        reasons.append("ha_managed")

    replication = _pvesh_json(["get", "/cluster/replication"])
    # Proxmox's native destroy checks all configured jobs for the guest,
    # including disabled jobs and jobs still marked for removal.
    if not isinstance(replication, list) or any(
        not isinstance(job, dict) or type(job.get("guest")) is not int
        or not 100 <= job["guest"] <= 999999999
        for job in replication
    ):
        raise RemovalError("replication_state_unavailable", 503)
    if any(job["guest"] == vmid for job in replication):
        reasons.append("replication_configured")

    pending = _pvesh_json(["get", f"/nodes/{node}/lxc/{vmid}/pending"])
    if not isinstance(pending, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("key"), str) or not row["key"]
        or not (row.keys() & {"value", "pending", "delete"})
        or type(row.get("delete", 0)) is not int or row.get("delete", 0) not in (0, 1, 2)
        for row in pending
    ):
        raise RemovalError("pending_state_unavailable", 503)
    # The endpoint includes current values too. A pending value can be empty.
    if any("pending" in row or row.get("delete", 0) for row in pending):
        reasons.append("pending_changes")

    backup = _backup_inventory(node, vmid)
    tasks = _active_backup_tasks(node, vmid)
    if tasks:
        reasons.append("backup_running")

    identity = sha256(json.dumps({
        "vmid": vmid, "node": node, "name": resource.get("name"), "type": resource.get("type"),
        "config": sha256(raw).hexdigest(), "rootfs": disk["volume"],
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "identity": identity,
        "target": {
            "vmid": vmid, "name": str(resource.get("name") or f"CT {vmid}"), "node": node,
            "status": str(resource.get("status") or "unknown"),
        },
        "disk": disk,
        "backup": backup,
        "backup_tasks": tasks,
    }


def _task_from_output(output: str, vmid: int, node: str):
    lines = [line.strip().strip('"') for line in (output or "").splitlines() if line.strip()]
    task = lines[-1] if lines else ""
    parsed = DESTROY_UPID_RE.fullmatch(task)
    if not parsed or parsed["vmid"] != str(vmid) or parsed["node"] != node:
        return None
    return task


def _invalidate(vmid: int):
    # Import only after Flask has fully initialized; this module deliberately
    # owns no second cache.  A missing server module is harmless in unit tests.
    try:
        import flask_server
        flask_server._pvesh_cache["cluster_resources_vm_time"] = 0
        flask_server._vm_cache_invalidate(vmid)
    except Exception:
        pass


def _status(vmid: int, task: str):
    parsed = DESTROY_UPID_RE.fullmatch(task)
    if not parsed or parsed["vmid"] != str(vmid):
        raise RemovalError("invalid_task", 400)
    node = parsed["node"]
    try:
        status = _pvesh_json(["get", f"/nodes/{node}/tasks/{task}/status"])
    except RemovalError:
        return {"state": "unknown", "task": task, "reason": "task_status_unavailable"}
    if not isinstance(status, dict) or status.get("status") not in {"running", "stopped"}:
        return {"state": "unknown", "task": task, "reason": "task_status_unavailable"}
    if status["status"] == "running":
        return {"state": "running", "task": task}
    exitstatus = status.get("exitstatus")
    if not isinstance(exitstatus, str) or not exitstatus:
        return {"state": "unknown", "task": task, "reason": "task_status_unavailable"}
    if exitstatus != "OK":
        return {"state": "failed", "task": task, "exitstatus": exitstatus}
    try:
        resources = _pvesh_json(["get", "/cluster/resources", "--type", "vm"])
    except RemovalError:
        return {"state": "unknown", "task": task, "reason": "result_verification_unavailable"}
    if not isinstance(resources, list):
        return {"state": "unknown", "task": task, "reason": "result_verification_unavailable"}
    if any(isinstance(row, dict) and str(row.get("vmid")) == str(vmid) for row in resources):
        return {"state": "warning", "task": task, "reason": "vmid_still_present"}
    if (CONF_DIR / f"{vmid}.conf").exists():
        return {"state": "warning", "task": task, "reason": "configuration_still_present"}
    _invalidate(vmid)
    return {"state": "succeeded", "task": task}


@lxc_removal_bp.get("/api/vms/<int:vmid>/remove-preview")
@require_admin_scope
@_admin
def preview(actor: str, vmid: int):
    try:
        preflight = _preflight(vmid)
        check = _ticket().dumps({"actor": actor, "vmid": vmid, "identity": preflight["identity"]})
        return jsonify(**preflight, check=check)
    except RemovalError as error:
        return jsonify(error=error.code), error.status


@lxc_removal_bp.post("/api/vms/<int:vmid>/remove")
@require_admin_scope
@_admin
def remove(actor: str, vmid: int):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) - {"check", "confirm_vmid", "confirm_no_backup"}:
        return jsonify(error="invalid_request"), 400
    if body.get("confirm_vmid") != str(vmid):
        return jsonify(error="confirmation_required"), 422
    try:
        check = _ticket().loads(body.get("check"), max_age=CHECK_AGE)
    except BadData:
        return jsonify(error="check_expired"), 409
    if not isinstance(check, dict) or check.get("actor") != actor or check.get("vmid") != vmid:
        return jsonify(error="check_mismatch"), 409

    import lxc_check_job
    reservation = None
    retained = False
    try:
        try:
            reservation = lxc_check_job.acquire(vmid)
        except BlockingIOError:
            return jsonify(error="operation_pending"), 409
        preflight = _preflight(vmid)
        if check.get("identity") != preflight["identity"]:
            return jsonify(error="target_changed", preview=preflight), 409
        if not preflight["eligible"]:
            return jsonify(error="removal_blocked", preview=preflight), 409
        if preflight["backup"]["state"] == "none" and body.get("confirm_no_backup") is not True:
            return jsonify(error="no_backup_confirmation_required"), 422

        # Store an uncertainty marker before the native call.  If the process
        # times out or returns no attributable UPID, the marker stays and a
        # second request is forbidden instead of gambling with a reused VMID.
        lxc_check_job.begin_control(reservation, preflight["target"]["node"])
        try:
            result = subprocess.run(
                ["pvesh", "delete", f"/nodes/{preflight['target']['node']}/lxc/{vmid}"],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            reservation = None
            return jsonify(state="unknown", task=None, reason="submission_unconfirmed"), 202
        task = _task_from_output(result.stdout, vmid, preflight["target"]["node"])
        if result.returncode != 0 or not task:
            reservation = None
            return jsonify(state="unknown", task=None, reason="submission_unconfirmed"), 202
        lxc_check_job.retain_control(vmid, task, reservation)
        retained = True
        reservation = None
        return jsonify(state="running", task=task, node=preflight["target"]["node"]), 202
    except RemovalError as error:
        return jsonify(error=error.code), error.status
    finally:
        if reservation is not None and not retained:
            reservation.close()


@lxc_removal_bp.get("/api/vms/<int:vmid>/remove-task/<path:task>")
@require_admin_scope
@_admin
def task_status(actor: str, vmid: int, task: str):
    try:
        return jsonify(_status(vmid, task))
    except RemovalError as error:
        return jsonify(error=error.code), error.status
