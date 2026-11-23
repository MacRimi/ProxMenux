"""Guarded removal of one stopped, ordinary LXC through the native PVE task.

This deliberately does not try to be a generic ``pct destroy`` wrapper.  The
route accepts only a locally hosted, stopped ordinary LXC with an owned rootfs
and no extra configured volumes, OCI identity, lock or pending changes.
Archive browsing is independent of removal. The preview binds the target
and checks whether protection is the only blocker before offering to disable it.
Confirmation checks dependencies under the shared LXC lock.
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
import time
from uuid import uuid4

from flask import Blueprint, g, jsonify, request
from itsdangerous import BadData, URLSafeTimedSerializer

from auth_manager import _get_jwt_secret
from jwt_middleware import require_admin_scope
from pbs_manager import is_pbs_host
import custom_links
import lxc_removal_receipts as receipts
from oci_instance_info import OciStateError, check_plain_lxc


lxc_removal_bp = Blueprint("lxc_removal", __name__)

CONF_DIR = Path("/etc/pve/lxc")
CFS_DIR = Path("/etc/pve")
OCI_INSTANCE_ROOT = Path("/usr/local/share/proxmenux/oci/instances")
NATIVE_BRIDGE = str(Path(__file__).with_name("plain_lxc_pve.pl"))
CHECK_AGE = 180
NODE_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$")


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
        with path.open("rb") as source:
            info = os.fstat(source.fileno())
            raw = source.read()
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
    return raw, values, lxc, [info.st_dev, info.st_ino, info.st_mtime_ns // 10**9, info.st_ctime_ns // 10**9]


def _generation(vmid, node):
    try:
        start = json.loads((CFS_DIR / ".version").read_bytes())["starttime"]
        guest = json.loads((CFS_DIR / ".vmlist").read_bytes())["ids"][str(vmid)]
        version = guest["version"]
        if (guest["node"] != node or guest["type"] != "lxc"
                or type(start) is not int or start < 1 or type(version) is not int or version < 1):
            raise ValueError
        return [start, version]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RemovalError("node_identity_unavailable", 503) from exc


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
    try:
        check_plain_lxc(config_text.split("\n[", 1)[0], OCI_INSTANCE_ROOT / str(vmid),
                        time.monotonic() + 3)
    except OciStateError as error:
        if str(error) == "managed_oci":
            return True
        raise RemovalError("oci_identity_unavailable") from None
    return False


def _root_volume_exists(node, vmid, volume):
    exists = _native_request("remove-disk-status", node, {"vmid": vmid, "volume": volume})
    if type(exists) is not int or exists not in (0, 1):
        raise RemovalError("rootfs_state_unavailable", 503)
    return bool(exists)


def _preflight(vmid: int):
    """Read the identity, state and configured disk without probing storage."""
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

    generation = _generation(vmid, node)
    raw, config, lxc_lines, file_identity = _plain_config(vmid)
    if generation != _generation(vmid, node):
        raise RemovalError("target_changed")
    reasons: list[str] = []
    if resource.get("status") != "stopped":
        reasons.append("container_running")
    if _truthy(config.get("protection")):
        reasons.append("container_protected")
    if config.get("lock"):
        reasons.append("container_locked")
    if _truthy(config.get("template")) or _truthy(resource.get("template")):
        reasons.append("container_template")
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
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "guard": {"file": file_identity, "generation": generation, "digest": sha256(raw).hexdigest()},
        "target": {
            "vmid": vmid, "name": str(resource.get("name") or f"CT {vmid}"), "node": node,
            "status": str(resource.get("status") or "unknown"),
        },
        "disk": disk,
    }


def _check_jobs(node, vmid, reasons):
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


def _check_dependencies(preflight, *, include_jobs):
    target, disk = preflight["target"], preflight["disk"]
    node, vmid = target["node"], target["vmid"]
    reasons = preflight["reasons"]
    if not _root_volume_exists(node, vmid, disk["volume"]):
        reasons.append("rootfs_ambiguous")
    if include_jobs:
        _check_jobs(node, vmid, reasons)
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

    preflight["eligible"] = not reasons


def _invalidate(vmid: int):
    # Import only after Flask has fully initialized; this module deliberately
    # owns no second cache.  A missing server module is harmless in unit tests.
    try:
        import flask_server
        flask_server._pvesh_cache["cluster_resources_vm_time"] = 0
        flask_server._vm_cache_invalidate(vmid)
    except Exception:
        pass


def _task_status(node, task):
    try:
        status = _pvesh_json(["get", f"/nodes/{node}/tasks/{task}/status"])
    except RemovalError:
        status = None
    if not isinstance(status, dict) or status.get("status") not in ("running", "stopped"):
        return {"state": "unknown", "task": task, "reason": "task_status_unavailable"}
    if status["status"] == "running":
        return {"state": "running", "task": task}
    exitstatus = status.get("exitstatus")
    if (not isinstance(exitstatus, str) or not exitstatus or exitstatus == "unexpected status"
            or exitstatus.startswith("unable to get last line from task log")):
        return {"state": "unknown", "task": task, "reason": "task_status_unavailable"}
    if re.fullmatch(r"WARNINGS: [0-9]+", exitstatus):
        return {"state": "warning", "task": task, "exitstatus": exitstatus}
    if exitstatus != "OK":
        return {"state": "failed", "task": task, "exitstatus": exitstatus}
    return {"state": "ok", "task": task}


def _settle_link_detachment(operation, status):
    state = status["state"]
    if state not in {"ok", "failed", "warning"}:
        return
    try:
        pending = receipts.link_detachment(operation)
        if pending is None:
            return
        if state == "warning" and _guest_removal_evidence(pending["vmid"], status["task"]):
            return
        if state in {"ok", "warning"}:
            custom_links.detach_lxc_bindings(pending["vmid"], pending["bindings"])
        receipts.finish_link_detachment(operation)
    except (OSError, ValueError, TypeError, KeyError) as error:
        # Preserve the pending record for a retry. The native outcome is independent.
        print(f"[ProxMenux] Could not finish LXC link detachment: {error}", flush=True)


def reconcile_link_detachments(vmid=None):
    """Recover pending link work after a browser disconnect or Monitor restart."""
    try:
        operations = list(receipts.pending_link_detachments())
    except OSError as error:
        print(f"[ProxMenux] Could not list pending LXC link detachments: {error}", flush=True)
        return
    for operation in operations:
        try:
            pending = receipts.link_detachment(operation)
            if pending is None or (vmid is not None and pending["vmid"] != vmid):
                continue
            started, value = receipts.outcome(operation)
            if value == receipts.REJECTED or started is None or time.time() - started >= receipts.RECEIPT_AGE:
                receipts.finish_link_detachment(operation)
                continue
            task = receipts.task_for(value, pending["node"], pending["vmid"])
            if task:
                _settle_link_detachment(operation, _task_status(pending["node"], task))
        except (OSError, ValueError, TypeError, KeyError) as error:
            print(f"[ProxMenux] Could not recover LXC link detachment: {error}", flush=True)


def _guest_removal_evidence(vmid, task):
    try:
        resources = _pvesh_json(["get", "/cluster/resources", "--type", "vm"])
    except RemovalError:
        return {"state": "unknown", "task": task, "reason": "result_verification_unavailable"}
    if not isinstance(resources, list) or any(
        not isinstance(row, dict) or type(row.get("vmid")) is not int or row["vmid"] < 100
        for row in resources
    ):
        return {"state": "unknown", "task": task, "reason": "result_verification_unavailable"}
    if any(row["vmid"] == vmid for row in resources):
        return {"state": "warning", "task": task, "reason": "vmid_still_present"}
    try:
        (CONF_DIR / f"{vmid}.conf").stat()
    except FileNotFoundError:
        pass
    except OSError:
        return {"state": "unknown", "task": task, "reason": "result_verification_unavailable"}
    else:
        return {"state": "warning", "task": task, "reason": "configuration_still_present"}
    return None


def _status(vmid, node, volume, task, operation):
    status = _task_status(node, task)
    # The original task identifies the removal even if the VMID or disk name
    # has already been reused. Only the saved bindings may be detached here.
    _settle_link_detachment(operation, status)
    if status["state"] != "ok":
        return status
    evidence = _guest_removal_evidence(vmid, task)
    if evidence:
        return evidence
    try:
        if _root_volume_exists(node, vmid, volume):
            return {"state": "warning", "task": task, "reason": "root_volume_still_present"}
    except RemovalError:
        return {"state": "unknown", "task": task, "reason": "result_verification_unavailable"}
    _invalidate(vmid)
    return {"state": "succeeded", "task": task}


@lxc_removal_bp.get("/api/vms/<int:vmid>/remove-preview")
@require_admin_scope
@_admin
def preview(actor: str, vmid: int):
    try:
        preflight = _preflight(vmid)
        guard = preflight.pop("guard")
        if preflight["reasons"] == ["container_protected"]:
            _check_dependencies(preflight, include_jobs=False)
        review = {
            "actor": actor, "vmid": vmid, "guard": guard, "node": preflight["target"]["node"],
            "volume": preflight["disk"]["volume"], "operation": uuid4().hex, "expires": time.time() + CHECK_AGE,
        }
        if preflight["eligible"]:
            return jsonify(**preflight, check=_ticket().dumps(review))
        if preflight["reasons"] == ["container_protected"]:
            return jsonify(**preflight, check=None,
                           protection_check=_ticket().dumps({**review, "purpose": "disable_protection"}))
        return jsonify(**preflight, check=None)
    except RemovalError as error:
        return jsonify(error=error.code), error.status


@lxc_removal_bp.post("/api/vms/<int:vmid>/disable-removal-protection")
@require_admin_scope
@_admin
def disable_removal_protection(actor: str, vmid: int):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {"check"}:
        return jsonify(error="invalid_request"), 400
    import lxc_check_job
    try:
        check = _load_check(body["check"], actor, vmid, CHECK_AGE, purpose="disable_protection")
        try:
            reservation = lxc_check_job.acquire(vmid)
        except BlockingIOError:
            raise RemovalError("operation_pending") from None
        with reservation:
            current = _preflight(vmid)
            if (current["guard"] != check["guard"] or current["target"]["node"] != check["node"]
                    or current["reasons"] != ["container_protected"]):
                raise RemovalError("target_changed")
            _check_dependencies(current, include_jobs=False)
            if current["reasons"] != ["container_protected"]:
                raise RemovalError("target_changed")
            if time.time() >= check["expires"]:
                raise RemovalError("check_expired")
            result = _native_request("disable-protection", check["node"], {
                "vmid": vmid, "guard": check["guard"],
            })
        _invalidate(vmid)
        if type(result) is not int or result != 1:
            raise RemovalError("protection_change_unconfirmed", 503)
        return jsonify(protection=False)
    except RemovalError as error:
        return jsonify(error=error.code), error.status
    except (OSError, UnicodeError):
        return jsonify(error="protection_change_unconfirmed"), 503


@lxc_removal_bp.post("/api/vms/<int:vmid>/remove")
@require_admin_scope
@_admin
def remove(actor: str, vmid: int):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) - {"check", "confirm_vmid", "purge", "destroy_unreferenced_disks"}:
        return jsonify(error="invalid_request"), 400
    purge = body.get("purge", False)
    destroy_unreferenced = body.get("destroy_unreferenced_disks", False)
    if type(purge) is not bool or type(destroy_unreferenced) is not bool:
        return jsonify(error="invalid_request"), 400
    if body.get("confirm_vmid") != str(vmid):
        return jsonify(error="confirmation_required"), 422
    import lxc_check_job
    try:
        check = _load_check(body.get("check"), actor, vmid, CHECK_AGE)
        operation = check["operation"]
        if receipts.outcome(operation)[0] is not None:
            return jsonify(_operation_status(check)), 202
        try:
            reservation = lxc_check_job.acquire(vmid)
        except BlockingIOError:
            return jsonify(error="operation_pending"), 409
        try:
            if receipts.outcome(operation)[0] is not None:
                return jsonify(_operation_status(check)), 202
            preflight = _preflight(vmid)
            guard = preflight.pop("guard")
            if (check["guard"] != guard or check["node"] != preflight["target"]["node"]
                    or check["volume"] != preflight["disk"]["volume"]):
                return jsonify(error="target_changed", preview=preflight), 409
            if preflight["eligible"]:
                _check_dependencies(preflight, include_jobs=not purge)
            if not preflight["eligible"]:
                return jsonify(error="removal_blocked", preview=preflight), 409

            if time.time() >= check["expires"]:
                raise RemovalError("check_expired")
            try:
                receipts.begin(operation)
            except FileExistsError:
                return jsonify(_operation_status(check)), 202
            receipts.stage_link_detachment(operation, check["node"], vmid,
                                           custom_links.snapshot_lxc_bindings(vmid))
            if time.time() >= check["expires"]:
                receipts.seal_unstarted(operation)
                receipts.finish_link_detachment(operation)
                raise RemovalError("check_expired")
            lxc_check_job.begin_removal(reservation, check["node"], operation)
            if not _dispatch(check, purge, destroy_unreferenced):
                if receipts.seal_unstarted(operation) == receipts.REJECTED:
                    receipts.finish_link_detachment(operation)
        finally:
            reservation.close()
        return jsonify(_operation_status(check)), 202
    except RemovalError as error:
        return jsonify(error=error.code), error.status
    except (OSError, UnicodeError):
        return jsonify(state="unknown", task=None, reason="submission_unconfirmed"), 202


def _load_check(token, actor, vmid, max_age, purpose="remove"):
    if not isinstance(token, str) or len(token) > 4096:
        raise RemovalError("invalid_request", 400)
    try:
        check = _ticket().loads(token, max_age=max_age)
    except BadData:
        raise RemovalError("check_expired") from None
    if (not isinstance(check, dict) or check.get("actor") != actor or check.get("vmid") != vmid
            or check.get("purpose", "remove") != purpose):
        raise RemovalError("check_mismatch")
    if not receipts.OPERATION.fullmatch(check.get("operation", "")):
        raise RemovalError("check_expired")
    return check


def _dispatch(check, purge, destroy_unreferenced):
    params = {key: check[key] for key in ("vmid", "operation", "guard", "volume")}
    params.update(purge=int(purge), destroy_unreferenced_disks=int(destroy_unreferenced))
    task = _native_request("remove", check["node"], params)
    return receipts.task_for(task, check["node"], check["vmid"])


def _native_request(action, node, params):
    try:
        result = subprocess.run(
            ["/usr/bin/perl", NATIVE_BRIDGE], capture_output=True, text=True, timeout=12,
            input=json.dumps({"action": action, "node": node, "params": params}),
        )
        return json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _operation_status(check):
    operation, vmid, node = (check[key] for key in ("operation", "vmid", "node"))
    started, value = receipts.outcome(operation)
    if started is None:
        if time.time() < check["expires"]:
            return {"state": "unknown", "task": None, "reason": "submission_unconfirmed"}
        # Reserve the expired operation before reporting a definite rejection.
        # A confirmation already in progress may win this reservation instead.
        try:
            receipts.begin(operation)
        except FileExistsError:
            started, value = receipts.outcome(operation)
        else:
            value = receipts.seal_unstarted(operation)
    if value is None:
        if time.time() - started < receipts.DISPATCH_WINDOW:
            return {"state": "running", "task": None, "reason": "dispatch_pending"}
        value = receipts.seal_unstarted(operation)
    if value == receipts.REJECTED:
        return {"state": "failed", "task": None, "reason": "not_started"}
    task = receipts.task_for(value, node, vmid)
    if not task:
        return {"state": "unknown", "task": None, "reason": "submission_unconfirmed"}
    return _status(vmid, node, check["volume"], task, operation)


@lxc_removal_bp.get("/api/vms/<int:vmid>/remove-operation")
@require_admin_scope
@_admin
def task_status(actor: str, vmid: int):
    try:
        check = _load_check(request.headers.get("X-LXC-Removal-Check"), actor, vmid, receipts.RECEIPT_AGE)
        return jsonify(_operation_status(check))
    except RemovalError as error:
        return jsonify(error=error.code), error.status
    except (OSError, UnicodeError):
        return jsonify(state="unknown", task=None, reason="submission_unconfirmed")
