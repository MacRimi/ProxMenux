"""Monitor adapter for the installed plain LXC console engine."""

from datetime import datetime, timezone
from functools import wraps
from hashlib import sha256
import json
import subprocess
from uuid import uuid4

from flask import Blueprint, g, jsonify, request
from itsdangerous import BadData, URLSafeTimedSerializer

from auth_manager import _get_jwt_secret
from jwt_middleware import require_admin_scope
from pbs_manager import is_pbs_host


plain_lxc_bp = Blueprint("plain_lxc", __name__, url_prefix="/api/plain-lxc/v1")
ENGINE = "/usr/local/share/proxmenux/scripts/lxc/plain_lxc.py"
PLAN_AGE = 300
CREATE_TIMEOUT = 240
RECEIPT_AGE = 7 * 24 * 3600
SPEC_FIELDS = {
    "node", "vmid", "hostname", "template", "access", "rootfs", "cpu", "memory",
    "network", "dns", "nesting", "onboot", "start_after_create", "prepare_system",
}
REJECTED = {
    "architecture_unsupported", "bridge_unavailable", "catalog_unavailable",
    "disk_space_insufficient", "invalid_field", "invalid_ssh_key", "node_capacity_exceeded",
    "node_not_local", "plan_changed", "request_conflict", "storage_unavailable",
    "target_operation_pending", "template_architecture_mismatch", "template_checksum_mismatch",
    "template_already_present", "template_unverified", "vmid_in_use", "warnings_unaccepted",
}


class EngineError(Exception):
    def __init__(self, code, field=None):
        super().__init__(code)
        self.field = field if isinstance(field, str) else None


def _error(code, status, field=None):
    return jsonify(error=code, field=field), status


def _admin(view):
    # Tickets and receipts belong to the account that asked for them; an
    # open Monitor has no account, so its requests share one owner.
    @wraps(view)
    def protected(*args, **kwargs):
        identity = getattr(g, "identity", None)
        if not identity or "admin" not in identity["permissions"]:
            return _error("admin_required", 403)
        if is_pbs_host():
            return _error("pve_required", 404)
        return view(identity["username"], *args, **kwargs)
    return protected


def _ticket(kind):
    return URLSafeTimedSerializer(_get_jwt_secret(), salt="proxmenux-plain-lxc-" + kind,
                                  signer_kwargs={"digest_method": sha256})


def _decode(kind, token, actor, max_age, *, timestamp=False):
    if not isinstance(token, str) or not token or len(token) > 131072:
        raise BadData("Invalid ticket")
    payload, issued = _ticket(kind).loads(token, max_age=max_age, return_timestamp=True)
    if payload["actor"] != actor:
        raise BadData("Invalid ticket owner")
    return (payload, issued) if timestamp else payload


def _engine(action, **body):
    try:
        output = subprocess.run(
            ["/usr/bin/python3", "-I", "-B", ENGINE],
            input=json.dumps({"schema_version": 2, "action": action, **body}).encode(),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=CREATE_TIMEOUT if action in ("create", "download_template") else 60,
        )
        response = json.loads(output.stdout)
        if type(response) is not dict:
            raise ValueError("Invalid engine envelope")
        if response.get("ok") is False and isinstance(response.get("error"), str):
            raise EngineError(response["error"], response.get("field"))
        if output.returncode or response.get("ok") is not True or type(response.get("data")) is not dict:
            raise ValueError("Invalid engine response")
        return response["data"]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise EngineError("engine_unavailable") from None


def _engine_failure(error):
    code = str(error)
    return _error(code, 422, error.field) if code in REJECTED else _error("engine_unavailable", 503)


def _is_system_template(template, architecture):
    return template.get("origin") == "system" and template.get("architecture") == architecture


def _download_target(inventory, node, name, storage):
    if node != inventory["node"]:
        raise EngineError("node_not_local", "node")
    if not _is_system_template(inventory["catalog"].get(name, {}), inventory["architecture"]):
        code = "catalog_unavailable" if inventory["catalog_state"] == "unavailable" else "template_unverified"
        raise EngineError(code, "catalog_id")
    if "vztmpl" not in inventory["storages"].get(storage, {}).get("content", []):
        raise EngineError("storage_unavailable", "template_storage")


@plain_lxc_bp.after_request
def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@plain_lxc_bp.get("/context")
@require_admin_scope
@_admin
def context(_actor):
    try:
        data = _engine("context")
        architecture = data["architecture"]
        return jsonify(
            node=data["node"], architecture=architecture, next_vmid=data["next_vmid"],
            defaults=data["defaults"], limits=data["limits"],
            templates=sorted(volume for volume, template in data["templates"].items()
                             if _is_system_template(template, architecture)),
            catalog=sorted(name for name, template in data["catalog"].items()
                           if _is_system_template(template, architecture)),
            catalog_state=data["catalog_state"],
            template_storages=sorted(name for name, storage in data["storages"].items()
                                     if "vztmpl" in storage["content"]),
            storages=sorted(name for name, storage in data["storages"].items() if "rootdir" in storage["content"]),
            bridges=data["bridges"],
        )
    except EngineError as error:
        return _engine_failure(error)
    except (KeyError, TypeError, AttributeError):
        return _error("engine_unavailable", 503)


@plain_lxc_bp.post("/plan")
@require_admin_scope
@_admin
def plan(actor):
    body = request.get_json(silent=True)
    spec = body.get("spec") if type(body) is dict and set(body) == {"spec"} else None
    if type(spec) is not dict or not spec.keys() <= SPEC_FIELDS:
        return _error("invalid_field", 422)
    template = spec.get("template")
    if (type(template) is not dict or set(template) != {"volume_id"}
            or not isinstance(template["volume_id"], str)):
        return _error("template_unverified", 422, "template.volume_id")
    try:
        inventory = _engine("context")
        if spec.get("node") != inventory["node"]:
            return _error("node_not_local", 422, "node")
        selected = inventory["templates"].get(template["volume_id"], {})
        if not _is_system_template(selected, inventory["architecture"]):
            return _error("template_unverified", 422, "template.volume_id")
        checked = _engine("plan", spec=spec)
        canonical = checked["plan"]
        if not _is_system_template(canonical["resources"]["template"], inventory["architecture"]):
            return _error("template_unverified", 422, "template.volume_id")
        normalized = canonical["spec"]
        operation = {"actor": actor, "node": normalized["node"], "vmid": normalized["vmid"],
                     "id": uuid4().hex}
        summary = {**normalized, "access": {"mode": normalized["access"]["mode"]}}
        return jsonify(
            summary=summary, warnings=canonical["warnings"],
            check=_ticket("plan").dumps({**operation, "plan": canonical, "hash": checked["plan_hash"]}),
            receipt=_ticket("operation").dumps(operation),
        )
    except EngineError as error:
        return _engine_failure(error)
    except (KeyError, TypeError, AttributeError):
        return _error("engine_unavailable", 503)


def _operation_target(operation):
    if operation.get("action") == "download_template":
        return {"action": "download_template", "volume_id": operation["volume_id"]}
    return {"action": "create", "vmid": operation["vmid"]}


def _operation_status(result, operation):
    state, phase = result.get("status"), result.get("phase")
    target = _operation_target(operation)
    phases = ("download",) if target["action"] == "download_template" else ("create", "prepare", "start")
    if (result.get("request_id") != operation["id"] or result.get("node") != operation["node"]
            or any(result.get(field) != value for field, value in target.items())
            or state not in ("running", "unknown", "succeeded", "failed", "partial")
            or phase not in phases):
        return _error("engine_unavailable", 503)
    return jsonify(
        **target, status=state, phase=phase,
        reason=result.get("reason"), task_warnings=result.get("task_warnings", False),
    )


@plain_lxc_bp.post("/download/plan")
@require_admin_scope
@_admin
def plan_download(actor):
    body = request.get_json(silent=True)
    fields = ("node", "catalog_id", "template_storage")
    if (type(body) is not dict or set(body) != set(fields)
            or any(not isinstance(body[field], str) for field in fields)):
        return _error("invalid_field", 422)
    try:
        _download_target(_engine("context"), body["node"], body["catalog_id"], body["template_storage"])
        operation = {
            "id": uuid4().hex, "actor": actor, "action": "download_template", "node": body["node"],
            "volume_id": f"{body['template_storage']}:vztmpl/{body['catalog_id']}",
        }
        return jsonify(check=_ticket("download").dumps({**operation, **body}),
                       receipt=_ticket("operation").dumps(operation))
    except EngineError as error:
        return _engine_failure(error)
    except (KeyError, TypeError, AttributeError):
        return _error("engine_unavailable", 503)


@plain_lxc_bp.post("/download")
@require_admin_scope
@_admin
def download(actor):
    body = request.get_json(silent=True)
    if type(body) is not dict or set(body) != {"check", "confirmed"} or body["confirmed"] is not True:
        return _error("confirmation_required", 422)
    try:
        operation = _decode("download", body["check"], actor, PLAN_AGE)
    except BadData:
        return _error("plan_changed", 409)
    try:
        try:
            result = _engine("status", request_id=operation["id"])
        except EngineError as error:
            if str(error) != "request_not_found":
                raise
            node, name, storage = (operation[field] for field in ("node", "catalog_id", "template_storage"))
            _download_target(_engine("context"), node, name, storage)
            result = _engine("download_template", request_id=operation["id"], node=node,
                             catalog_id=name, template_storage=storage, confirmed=True)
        return _operation_status(result, operation)
    except EngineError as error:
        return _engine_failure(error)
    except (KeyError, TypeError, AttributeError):
        return _error("engine_unavailable", 503)


@plain_lxc_bp.post("/create")
@require_admin_scope
@_admin
def create(actor):
    body = request.get_json(silent=True)
    if (type(body) is not dict or set(body) - {"check", "confirmed", "accepted_warnings", "password"}
            or body.get("confirmed") is not True):
        return _error("confirmation_required", 422)
    try:
        operation = _decode("plan", body.get("check"), actor, PLAN_AGE)
    except BadData:
        return _error("plan_changed", 409)
    canonical = operation["plan"]
    if body.get("accepted_warnings") != canonical["warnings"]:
        return _error("warnings_unaccepted", 422)
    arguments = {}
    if canonical["spec"]["access"]["mode"] in ("password", "both"):
        password = body.get("password")
        if not isinstance(password, str):
            return _error("invalid_field", 422, "secret.password")
        arguments["secret"] = {"password": password}
    elif "password" in body:
        return _error("invalid_field", 422, "secret.password")
    try:
        result = _engine(
            "create", request_id=operation["id"], plan=canonical, plan_hash=operation["hash"],
            confirmed=True, accepted_warnings=canonical["warnings"], **arguments,
        )
        return _operation_status(result, operation)
    except EngineError as error:
        return _engine_failure(error)


@plain_lxc_bp.get("/status")
@require_admin_scope
@_admin
def status(actor):
    try:
        operation, issued = _decode("operation", request.headers.get("X-ProxMenux-LXC-Receipt"),
                                    actor, RECEIPT_AGE, timestamp=True)
    except BadData:
        return _error("receipt_invalid", 403)
    try:
        return _operation_status(_engine("status", request_id=operation["id"]), operation)
    except EngineError as error:
        if str(error) == "request_not_found":
            # An admitted operation is journalled by the engine. Allow the
            # entire confirmation and command window before treating absence
            # as definite, including after an interrupted browser request.
            age = datetime.now(timezone.utc) - issued
            state = "awaiting" if age.total_seconds() <= PLAN_AGE + CREATE_TIMEOUT else "not_submitted"
            target = _operation_target(operation)
            phase = "download" if target["action"] == "download_template" else "create"
            return jsonify(**target, status=state, phase=phase, task_warnings=False)
        return _engine_failure(error)
